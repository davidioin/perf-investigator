import http.client
import json
import tempfile
import threading
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demo import Server
from engine import Manager

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.manager = Manager(Path(self.folder.name))
        self.server = Server(('127.0.0.1', 0), self.manager)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.folder.cleanup()
    def call(self, method, path, data=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        client.request(method, path, json.dumps(data) if data is not None else None, headers or {})
        response=client.getresponse(); body=response.read(); status=response.status; client.close()
        return status,body
    def test_setup_and_history_are_available(self):
        status,body=self.call('GET','/api/config')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['token'],self.server.token)
        self.assertEqual(self.call('GET','/api/runs'),(200,b'[]'))
    def test_cross_origin_and_missing_token_are_rejected(self):
        self.assertEqual(self.call('POST','/api/runs',{})[0],403)
        self.assertEqual(self.call('GET','/api/config',headers={'Origin':'http://evil.example'})[0],403)
        self.assertEqual(self.call('GET','/api/config',headers={'Host':'evil.example'})[0],403)
    def test_non_ascii_token_is_rejected(self):
        self.assertEqual(self.call('POST','/api/runs',{}, {'X-Launch-Token':'é'})[0],403)

    def test_invalid_preflight_is_actionable(self):
        status,body=self.call('POST','/api/preflight',{'repo':'/no/such/path'}, {'X-Launch-Token':self.server.token})
        self.assertEqual(status,200)
        self.assertFalse(json.loads(body)['ok'])
    def test_no_arbitrary_download(self):
        self.assertEqual(self.call('GET','/api/runs/../download/config')[0],404)
    def test_report_download_and_history(self):
        folder=Path(self.folder.name)/'example';folder.mkdir()
        (folder/'state.json').write_text(json.dumps({'id':'example','status':'complete','started':1}))
        (folder/'report.md').write_text('# Real report')
        self.assertEqual(self.call('GET','/api/runs/example/download/report.md'),(200,b'# Real report'))
        self.assertEqual(json.loads(self.call('GET','/api/runs')[1])[0]['id'],'example')

if __name__=='__main__':unittest.main()

class AnalysisApiTests(ApiTests):
    def seed(self):
        run=Path(self.folder.name)/'completed';run.mkdir()
        (run/'state.json').write_text(json.dumps({'id':'completed','status':'complete','started':1,'results':[]}))
        (run/'changes.diff').write_text('real diff\n')
        return run
    def test_analysis_status_and_source_preview(self):
        self.seed()
        status,body=self.call('GET','/api/runs/completed/analysis')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['status'],'not_started')
        status,body=self.call('GET','/api/runs/completed/analysis/evidence?file=changes.diff&start=1&end=1')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['text'],'real diff')
        self.assertEqual(self.call('GET','/api/runs/completed/analysis/evidence?file=../outside&start=1&end=1')[0],404)
    def test_analysis_requires_token_and_complete_evidence(self):
        self.seed()
        self.assertEqual(self.call('POST','/api/runs/completed/analysis',{})[0],403)
        self.assertEqual(self.call('POST','/api/runs/completed/analysis',{}, {'X-Launch-Token':self.server.token})[0],400)
    def test_page_has_agent_action_and_evidence_panel(self):
        status,body=self.call('GET','/')
        self.assertEqual(status,200)
        self.assertIn(b'Run agent investigation',body)
        self.assertIn(b'id="analysis-evidence"',body)

class AnalysisDownloadTests(ApiTests):
    def test_completed_analysis_reopens_and_downloads(self):
        run=Path(self.folder.name)/'finished';attempt=run/'analysis'/'attempt-1';attempt.mkdir(parents=True)
        (run/'state.json').write_text(json.dumps({'id':'finished','status':'complete','started':1}))
        (attempt/'state.json').write_text(json.dumps({'id':'attempt-1','status':'complete','started':2,'result':{'summary':'No slowdown'}}))
        (attempt/'report.md').write_text('# Read-only analysis\nNo slowdown\n')
        status,body=self.call('GET','/api/runs/finished/analysis')
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['result']['summary'],'No slowdown')
        self.assertEqual(self.call('GET','/api/runs/finished/analysis/report?attempt=attempt-1'),(200,b'# Read-only analysis\nNo slowdown\n'))
        self.assertEqual(self.call('GET','/api/runs/finished/analysis/report?attempt=../state')[0],404)

class RevisionUiTests(ApiTests):
    def test_revision_dropdowns_and_commit_summaries_are_exposed(self):
        _,body=self.call('GET','/')
        self.assertIn(b'<select id="base"',body)
        self.assertIn(b'<select id="candidate"',body)
        self.assertIn(b'id="commit-range-list"',body)
        self.assertEqual(self.call('POST','/api/revisions',{})[0],403)
