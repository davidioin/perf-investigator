"""Behavioral contract for the read-only agent handoff."""
import copy
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import Manager


def answer():
    return {'summary':'No reproducible slowdown established.', 'changed_behavior':'Keyword handling changed.',
            'hypotheses':[{'title':'Measurement variation','explanation':'One inconsistent pair.',
                           'confidence':'low','counterevidence':'Other pairs are stable.',
                           'next_experiment':'Repeat the dense workload on an idle host.',
                           'evidence':[{'file':'changes.diff','start':1,'end':1}]}],
            'limitations':['No profiles available.']}

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.manager=Manager(self.root)
        self.run=self.root/'comparison';self.run.mkdir()
        self.state={'id':'comparison','status':'complete','started':1,'correctness':True,
                    'revisions':{'baseline':{'sha':'a'},'candidate':{'sha':'b'}},
                    'environment':{},'harness_hash':'abc','profiling':'Not requested',
                    'results':[{'name':'dense_matches','verdict':'inconclusive','pair_changes':[1,6,-1]}]}
        (self.run/'state.json').write_text(json.dumps(self.state))
        for filename,data in [('results.json',self.state),('measurements.json',{'baseline':{},'candidate':{}})]:
            (self.run/filename).write_text(json.dumps(data))
        (self.run/'changes.diff').write_text('changed keyword matching\n')
        for side in ['baseline','candidate']:
            source=self.run/side/'sds/benches';source.mkdir(parents=True)
            (source/'investigator.rs').write_text('fixed workload\n')
            (self.run/f'{side}-Cargo.lock').write_text('lockfile\n')
        self.analysis=getattr(self.manager,'analysis',None)
        self.assertIsNotNone(self.analysis,'Manager must expose an agent-analysis worker')
    def tearDown(self):
        if self.manager.thread and self.manager.thread.is_alive():
            self.manager.cancel_event.set();self.manager.thread.join(3)
        self.temp.cleanup()
    def start(self):
        with patch('analysis.shutil.which',return_value='/usr/bin/codex'),patch('analysis.capture',return_value='codex test'),patch('threading.Thread.start'):
            return self.analysis.start('comparison')
    def test_packet_launch_and_measurements_remain_immutable(self):
        before=(self.run/'state.json').read_bytes();state=self.start()
        folder=self.run/'analysis'/state['id']
        prompt=(folder/'prompt.md').read_text()
        for required in ['No reproducible slowdown established','measurements.json','changes.diff','baseline/sds/benches/investigator.rs','read-only']:
            self.assertIn(required,prompt)
        command=json.loads((folder/'invocation.json').read_text())['command']
        for flag in ['--json','--output-schema','--ignore-user-config','--ephemeral','read-only','approval_policy="never"']:
            self.assertIn(flag,command)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',command)
        self.assertEqual(before,(self.run/'state.json').read_bytes())
        self.assertEqual(state['measured_outcome'],'No reproducible slowdown established.')
    def test_inherited_integrations_and_subagents_are_disabled(self):
        state=self.start()
        command=json.loads((self.run/'analysis'/state['id']/'invocation.json').read_text())['command']
        for flag in ['features.apps=false','features.plugins=false','features.multi_agent=false','features.hooks=false']:
            self.assertIn(flag,command)
    def test_benchmark_cancel_cannot_mutate_analysis_source_run(self):
        self.start();before=(self.run/'state.json').read_bytes()
        with self.assertRaises(ValueError):self.manager.cancel('comparison')
        self.assertEqual(before,(self.run/'state.json').read_bytes())
    def test_reproducible_regression_comes_from_measurements(self):
        self.state['results'][0]['verdict']='regression'
        (self.run/'state.json').write_text(json.dumps(self.state))
        self.assertIn('1 reproducible regression',self.start()['measured_outcome'])
    def test_single_job_guard_both_directions(self):
        self.start()
        with self.assertRaises(ValueError):self.analysis.start('comparison')
        with self.assertRaises(ValueError):self.manager.start({})
    def test_missing_cli_and_incomplete_run_are_actionable(self):
        with patch('analysis.shutil.which',return_value=None):
            with self.assertRaisesRegex(ValueError,'Codex'):self.analysis.start('comparison')
        self.state['status']='failed';(self.run/'state.json').write_text(json.dumps(self.state))
        with self.assertRaisesRegex(ValueError,'complete'):self.analysis.start('comparison')
    def test_saved_yaml_rule_citations_are_allowed_but_outside_files_are_not(self):
        rule=self.run/'candidate/sds/data/standard_rules/vin.yaml'
        rule.parent.mkdir(parents=True);rule.write_text('name: VIN\nvalidator: VinChecksum\n')
        ref='candidate/sds/data/standard_rules/vin.yaml'
        self.assertIn('VinChecksum',self.analysis.evidence('comparison',ref,1,2)['text'])
        value=answer();value['hypotheses'][0]['evidence']=[{'file':ref,'start':1,'end':2}]
        self.analysis.validate('comparison',value)
        outside=self.root/'outside.yaml';outside.write_text('outside')
        rule.unlink();rule.symlink_to(outside)
        with self.assertRaises(ValueError):self.analysis.evidence('comparison',ref,1,1)

    def test_new_investigations_request_short_responses_and_have_length_limits(self):
        state=self.start()
        prompt=(self.run/'analysis'/state['id']/'prompt.md').read_text()
        self.assertIn('at most 180 words',prompt)
        value=answer();self.analysis.validate('comparison',value)
        value['summary']='x'*241
        with self.assertRaises(ValueError):self.analysis.validate('comparison',value)
        value=answer();value['hypotheses']*=3
        with self.assertRaises(ValueError):self.analysis.validate('comparison',value)

    def test_schema_and_reference_validation(self):
        state=self.start();self.analysis.validate('comparison',answer())
        for mutation in ['missing','confidence','traversal','symlink','line','unknown']:
            result=copy.deepcopy(answer())
            if mutation=='missing':del result['summary']
            if mutation=='confidence':result['hypotheses'][0]['confidence']='certain'
            if mutation=='traversal':result['hypotheses'][0]['evidence'][0]['file']='../state.json'
            if mutation=='symlink':
                (self.run/'baseline/sds/escape.rs').symlink_to(self.root/'outside')
                (self.root/'outside').write_text('outside')
                result['hypotheses'][0]['evidence'][0]['file']='baseline/sds/escape.rs'
            if mutation=='line':result['hypotheses'][0]['evidence'][0]['end']=999
            if mutation=='unknown':result['results']=[{'verdict':'regression'}]
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.analysis.validate('comparison',result)
    def test_recovery_preserves_attempt_and_benchmark(self):
        state=self.start(); recovered=Manager(self.root)
        self.assertEqual(recovered.analysis.get('comparison')['status'],'interrupted')
        self.assertEqual(recovered.get('comparison')['status'],'complete')
        self.assertTrue((self.run/'analysis'/state['id']/'prompt.md').exists())
    def test_safe_evidence_read_and_no_profiles(self):
        self.assertEqual(self.analysis.evidence('comparison','changes.diff',1,1)['text'],'changed keyword matching')
        for file in ['state.json','../outside','baseline/../../outside','run.log']:
            with self.assertRaises(ValueError):self.analysis.evidence('comparison',file,1,1)
        self.assertIn('No profiles available', (self.run/'analysis'/self.start()['id']/'prompt.md').read_text())
    def test_worker_success_failure_cancel_and_timeout(self):
        from analysis import execute
        from engine import RunStopped
        folder=self.root/'process';folder.mkdir()
        events=folder/'events.jsonl';stderr=folder/'stderr.log'
        cmd=[sys.executable,'-c','import json; print(json.dumps({"type":"turn.started"}),flush=True)']
        execute(cmd,folder,'',events,stderr,threading.Event(),time.monotonic()+3)
        self.assertIn('turn.started',events.read_text())
        with self.assertRaisesRegex(ValueError,'login'):
            execute([sys.executable,'-c','import sys; print("login required",file=sys.stderr); sys.exit(1)'],folder,'',events,stderr,threading.Event(),time.monotonic()+3)
        for cancelled in [False,True]:
            cancel=threading.Event()
            if cancelled:threading.Timer(.1,cancel.set).start()
            with self.assertRaises(RunStopped):execute([sys.executable,'-c','import time; time.sleep(10)'],folder,'',events,stderr,cancel,time.monotonic()+(.2 if not cancelled else 3))
    def test_worker_persists_validated_output_and_retry(self):
        state=self.start()
        def fake(command,cwd,prompt,events,stderr,cancel,deadline):
            Path(command[command.index('-o')+1]).write_text(json.dumps(answer()))
            events.write_text('{"type":"session.started","model":"reported-test-model"}\n')
        with patch('analysis.execute',side_effect=fake):self.analysis.worker('comparison',state['id'],threading.Event())
        result=self.analysis.get('comparison');self.assertEqual(result['status'],'complete')
        self.assertEqual(result['model'],'reported-test-model')
        self.assertIn('No reproducible slowdown established',self.analysis.report('comparison',state['id']))
        retry=self.start();self.assertNotEqual(state['id'],retry['id'])
        self.assertEqual(len(self.analysis.get('comparison')['attempts']),2)
    def test_malformed_output_fails_without_overwriting_result(self):
        state=self.start()
        def fake(command,*args):Path(command[command.index('-o')+1]).write_text('{broken')
        with patch('analysis.execute',side_effect=fake):self.analysis.worker('comparison',state['id'],threading.Event())
        self.assertEqual(self.analysis.get('comparison')['status'],'failed')
        self.assertEqual(self.manager.get('comparison'),self.state)

if __name__=='__main__':unittest.main()

class AnalysisFailureStateTests(AnalysisTests):
    def test_cancel_and_deadline_keep_partial_attempts(self):
        from engine import RunStopped
        for cancelled in (True,False):
            state=self.start();event=threading.Event()
            if cancelled:event.set()
            with patch('analysis.execute',side_effect=RunStopped('Cancelled' if cancelled else '15-minute deadline reached')):
                self.analysis.worker('comparison',state['id'],event)
            saved=self.analysis.get('comparison')
            self.assertEqual(saved['status'],'cancelled' if cancelled else 'failed')
            self.assertTrue((self.run/'analysis'/state['id']/'prompt.md').exists())
            self.assertIsNone(self.manager.active)
            self.assertEqual(self.manager.get('comparison'),self.state)
