import json
import tempfile
import unittest
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import compare, Manager, run_command, preflight, RunStopped


def sample(mean, low=None, high=None):
    return {'mean': mean, 'lower': low if low is not None else mean * .99,
            'upper': high if high is not None else mean * 1.01}

class ComparisonTests(unittest.TestCase):
    def verdict(self, bases, candidates, valid=True):
        return compare('redact', bases, candidates, valid)['verdict']

    def test_same_revision_timings_are_stable(self):
        self.assertEqual(self.verdict([sample(100)] * 3, [sample(100)] * 3), 'no_detected_change')

    def test_repeatable_slowdown(self):
        self.assertEqual(self.verdict([sample(100)] * 3, [sample(125)] * 3), 'regression')

    def test_repeatable_improvement(self):
        self.assertEqual(self.verdict([sample(100)] * 3, [sample(75)] * 3), 'improvement')

    def test_contradictory_pairs_are_inconclusive(self):
        self.assertEqual(self.verdict([sample(100)] * 3, [sample(125), sample(90), sample(125)]), 'inconclusive')

    def test_overlapping_intervals_are_not_proof(self):
        self.assertEqual(self.verdict([sample(100, 80, 120)] * 3, [sample(115, 90, 130)] * 3), 'inconclusive')

    def test_bad_redaction_prevents_verdict(self):
        self.assertEqual(self.verdict([sample(100)] * 3, [sample(125)] * 3, False), 'invalid_correctness')

    def test_missing_and_malformed_measurements(self):
        for values in ([], [sample(100)], [sample(float('nan'))] * 3):
            with self.assertRaises(ValueError):
                compare('bad', [sample(100)] * 3, values)

class LifecycleTests(unittest.TestCase):
    def test_interrupted_run_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'abc'
            directory.mkdir()
            (directory / 'state.json').write_text(json.dumps({'id': 'abc', 'status': 'running', 'stage': 'building'}))
            manager = Manager(Path(folder))
            self.assertEqual(manager.get('abc')['status'], 'interrupted')

    def test_invalid_repository_is_preflight_error(self):
        with tempfile.TemporaryDirectory() as folder:
            result = preflight({'repo': folder, 'base': 'HEAD', 'candidate': 'HEAD'})
            self.assertFalse(result['ok'])
            self.assertTrue(result['errors'])

    def test_timeout_terminates_command(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RunStopped):
                run_command([sys.executable, '-c', 'import time; time.sleep(30)'], Path(folder), Path(folder)/'log', threading.Event(), time.monotonic()+.1)

    def test_cancel_terminates_command(self):
        with tempfile.TemporaryDirectory() as folder:
            cancel = threading.Event()
            threading.Timer(.15, cancel.set).start()
            with self.assertRaises(RunStopped):
                run_command([sys.executable, '-c', 'import time; time.sleep(30)'], Path(folder), Path(folder)/'log', cancel, time.monotonic()+10)

if __name__ == '__main__':
    unittest.main()

class DiagnosticsTests(unittest.TestCase):
    def test_structured_compiler_error_is_in_visible_log(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            command=[sys.executable,'-c','import json; print(json.dumps({"reason":"compiler-message","message":{"rendered":"error: incompatible scanner API"}})); raise SystemExit(1)']
            with self.assertRaises(ValueError):
                run_command(command,folder,folder/'log',threading.Event(),time.monotonic()+10,stdout_path=folder/'build.jsonl')
            self.assertIn('error: incompatible scanner API',(folder/'log').read_text().split('\n$ ')[-1].split('\n',1)[-1])

class ReportTests(unittest.TestCase):
    def test_same_commit_report_labels_control_run(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=Manager(Path(folder)); run=Path(folder)/'control';run.mkdir()
            state={'id':'control','revisions':{side:{'sha':'abc','summary':'same commit'} for side in ('baseline','candidate')},'environment':{},'harness_hash':'hash','results':[],'correctness':True,'profiling':'Not requested','repo':'/test'}
            (run/'state.json').write_text(json.dumps(state))
            manager.write_reports('control')
            self.assertIn('Same-commit control',(run/'report.md').read_text())

class WorkerFailureTests(unittest.TestCase):
    def test_failed_build_remains_in_history(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            manager=Manager(Path(folder)); run=Path(folder)/'broken';run.mkdir()
            state={'id':'broken','status':'running','stage':'preparing','started':1,'toolchain':'stable','repo':folder,'revisions':{side:{'sha':'abc','package':'sds'} for side in ('baseline','candidate')}}
            (run/'state.json').write_text(json.dumps(state))
            with patch('engine.run_command',side_effect=ValueError('incompatible build')):
                manager.worker('broken',threading.Event())
            self.assertEqual(manager.get('broken')['status'],'failed')
            self.assertIn('incompatible',manager.get('broken')['message'])
            self.assertEqual(len(manager.history()),1)
            self.assertIsNone(manager.active)

    def test_single_run_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=Manager(Path(folder));manager.active='running'
            with self.assertRaisesRegex(ValueError,'already running'):
                manager.start({})

    def test_invalid_revision(self):
        repo=Path(__file__).resolve().parents[2]/'dd-sds-sdsp-568'
        if not repo.exists():
            self.skipTest('Optional local SDS checkout is absent')
        result=preflight({'repo':str(repo),'base':'this-revision-does-not-exist','candidate':'HEAD'})
        self.assertFalse(result['ok'])
        self.assertTrue(result['errors'])

class PreflightDependencyTests(unittest.TestCase):
    def test_shared_library_requires_protoc(self):
        from unittest.mock import patch
        import shutil
        repo=Path(__file__).resolve().parents[2]/'sds-shared-library-sdsp-568'
        if not repo.exists():
            self.skipTest('Optional local SDS checkout is absent')
        original=shutil.which
        with patch('engine.shutil.which', side_effect=lambda name: None if name=='protoc' else original(name)):
            result=preflight({'repo':str(repo),'base':'HEAD','candidate':'HEAD'})
        self.assertFalse(result['ok'])
        self.assertTrue(any('protoc' in error for error in result['errors']))
