import os
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.git('init','-q');self.git('config','user.name','Test');self.git('config','user.email','test@example.invalid')
        self.shas=[]
        for i in range(3):
            self.commit_date=['2023-09-05T12:00:00+00:00','2026-08-03T12:00:00+00:00','2026-09-24T12:00:00+00:00'][i]
            (self.repo/'code.txt').write_text(str(i));self.git('add','.');self.git('commit','-qm',f'Change {i}');self.shas.append(self.git('rev-parse','HEAD'))
        self.git('tag','v1',self.shas[0]);self.git('tag','-a','v2','-m','version two',self.shas[1])
        self.assertIsNotNone(importlib.util.find_spec('revisions'),'Revision picker and summary backend must exist')
        self.module=importlib.import_module('revisions')
    def tearDown(self):self.t.cleanup()
    def git(self,*args):return subprocess.check_output(['git','-C',str(self.repo),*args],text=True,env=dict(os.environ,GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1',GIT_AUTHOR_DATE=getattr(self,'commit_date','2026-09-24T12:00:00+00:00'),GIT_COMMITTER_DATE=getattr(self,'commit_date','2026-09-24T12:00:00+00:00'))).strip()
    def test_versions_include_tags_branches_and_immutable_shas(self):
        data=self.module.versions(str(self.repo),0,2)
        self.assertEqual(data['default_base'],self.shas[1]);self.assertTrue(data['has_more']);self.assertEqual(len(data['commits']),2)
        tags={r['name']:r['sha'] for r in data['refs']}
        self.assertEqual(tags['v1'],self.shas[0]);self.assertEqual(tags['v2'],self.shas[1])
    def test_range_excludes_baseline_includes_candidate_and_handles_identical(self):
        data=self.module.commit_range(str(self.repo),'v1','HEAD')
        self.assertEqual([r['sha'] for r in data['commits']],self.shas[1:])
        self.assertEqual(data['relationship'],'forward')
        self.assertEqual(self.module.commit_range(str(self.repo),'HEAD','HEAD')['commits'],[])
        reverse=self.module.commit_range(str(self.repo),'HEAD','v1')
        self.assertEqual(reverse['relationship'],'reverse')
        self.assertEqual([c['sha'] for c in reverse['commits']],self.shas[1:])
        self.assertEqual(reverse['direction'],'removed')
        with self.assertRaises(ValueError):self.module.commit_range(str(self.repo),'bad-ref','HEAD')
    def test_diverged_range_is_explicit(self):
        self.git('checkout','-qb','side',self.shas[0]);(self.repo/'other').write_text('side');self.git('add','.');self.git('commit','-qm','Side change')
        data=self.module.commit_range(str(self.repo),self.shas[2],'HEAD')
        self.assertEqual(data['relationship'],'diverged');self.assertEqual(len(data['commits']),1)
    def test_shallow_disconnected_history_never_becomes_whole_history(self):
        # Hide the edge between the current tip and the still-present older history.
        (self.repo/'.git/shallow').write_text(self.shas[2]+'\n')
        data=self.module.commit_range(str(self.repo),self.shas[2],self.shas[0])
        self.assertEqual(data['relationship'],'unavailable')
        self.assertEqual(data['commits'],[])
        self.assertIn('shallow',data['message'].lower())
        from engine import Manager
        manager=Manager(self.root/'runs')
        with self.assertRaisesRegex(ValueError,'[Hh]istory|shallow'):
            manager.summaries.start({'repo':str(self.repo),'base':self.shas[2],'candidate':self.shas[0]})
        self.assertIsNone(manager.summaries.active)

    def test_demo_month_window_is_explicit_and_excludes_old_history(self):
        (self.repo/'.git/shallow').write_text(self.shas[2]+'\n')
        data=self.module.commit_range(str(self.repo),self.shas[2],self.shas[0],demo=True)
        self.assertEqual(data['relationship'],'date_window')
        self.assertTrue(data['demo'])
        self.assertTrue(data['commits'])
        self.assertNotIn(self.shas[0],[c['sha'] for c in data['commits']])
        self.assertTrue(all('2026-08-01'<=c['date']<'2026-10-01' for c in data['commits']))
        self.assertIn('not a verified',data['message'])
        versions=self.module.versions(str(self.repo),demo=True)
        self.assertTrue(all('2026-08-01'<=c['date']<'2026-10-01' for c in versions['commits']))

    def test_summary_validation_requires_exact_commit_set_and_one_line(self):
        data=[{'sha':s,'summary':'One concise explanation.'} for s in self.shas]
        self.module.validate_summaries(data,self.shas)
        for bad in [data[:-1],data+[data[0]],[{'sha':s,'summary':'two\nlines'} for s in self.shas]]:
            with self.assertRaises(ValueError):self.module.validate_summaries(bad,self.shas)
    def test_real_worker_contract_cache_and_busy_guard(self):
        from engine import Manager
        manager=Manager(self.root/'runs');worker=manager.summaries
        request={'repo':str(self.repo),'base':'v1','candidate':'HEAD'}
        with patch('revisions.shutil.which',return_value='/bin/codex'),patch('threading.Thread.start'):
            state=worker.start(request)
        with self.assertRaises(ValueError):manager.start({})
        def fake(command,cwd,prompt,events,stderr,cancel,deadline):
            output={'commits':[{'sha':s,'summary':'Changes the test input.'} for s in self.shas[1:]]}
            Path(command[command.index('-o')+1]).write_text(json.dumps(output))
        with patch('revisions.execute',side_effect=fake):worker.worker(state['id'])
        saved=worker.get(state['id']);self.assertEqual(saved['status'],'complete');self.assertEqual(len(saved['summaries']),2)
        with patch('revisions.shutil.which',return_value=None):self.assertEqual(worker.start(request)['status'],'complete')
        self.assertIsNone(worker.active)
