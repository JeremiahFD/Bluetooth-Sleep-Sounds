import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('health', Path(__file__).parents[1] / 'scripts/sleep-sounds-health.py')
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class HealthTests(unittest.TestCase):
    def test_graph_parse_ignores_names_and_non_rows(self):
        text = 'S ID QUANT RATE WAIT BUSY W/Q B/Q ERR FORMAT NAME\nR 42 1024 48000 1us 2us 0.1 0.2 7 F32LE private device\n'
        self.assertEqual(health.graph_errors(text), {'42': 7})

    def test_creating_frame_is_not_zero_error_evidence(self):
        initial = 'C 42 0 0 --- --- --- --- 0 private device\n'
        self.assertEqual(health.graph_errors(initial), {})
        # A later profiler frame supplies the real count; a newly creating row
        # must not overwrite an already observed value with a placeholder zero.
        updated = 'R 42 1024 48000 1us 2us 0.1 0.2 7 F32LE private device\n'
        self.assertEqual(health.graph_errors(initial + updated + initial), {'42': 7})

    def test_api_allowlist_excludes_sensitive_data(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _):
                return json.dumps({'csrf': 'secret', 'selected': '/private/recording.mp3',
                                   'playback_error': 'private path', 'session_id': 42,
                                   'bluetooth': {'busy': False, 'devices': ['private']}}).encode()
        with patch.object(health.urllib.request, 'urlopen', return_value=Response()):
            result = health.api_state()
        encoded = json.dumps(result)
        self.assertNotIn('secret', encoded)
        self.assertNotIn('private', encoded)
        self.assertTrue(result['playback_error_present'])
        self.assertEqual(result['session_id'], 42)

    def test_timeout_returns_unavailable(self):
        with patch.object(health.subprocess, 'run', side_effect=health.subprocess.TimeoutExpired('probe', 2)):
            self.assertIsNone(health.command(['probe']))

    def test_process_fallback_handles_exited_process(self):
        values = {'/group/cgroup.procs': '12\n13', '/proc/12/status': 'VmRSS: 100 kB',
                  '/proc/12/io': 'read_bytes: 4\nwrite_bytes: 8'}
        with patch.object(health, 'read', side_effect=lambda p: values.get(str(p).replace('\\', '/'))):
            value = health.process_usage(Path('/group'))
        self.assertEqual(value, {'process_count': 1, 'rss_kib_sum': 100,
                                 'read_bytes': 4, 'write_bytes': 8})


if __name__ == '__main__':
    unittest.main()


class HealthCounterIdentityTests(unittest.TestCase):
    def test_placeholder_zero_and_recovery_do_not_repeat_errors(self):
        baseline={};changes=[]
        for value in [1,0,1,2,0,2,3]:
            increments,baseline=health.graph_increments(baseline,{'42':value},{'42':'serial-one'})
            changes.append(increments)
        self.assertEqual(changes,[{},{},{},{'42':1},{},{},{'42':1}])
    def test_reused_node_id_starts_new_baseline(self):
        _,baseline=health.graph_increments({}, {'42':34},{'42':'old'})
        increments,baseline=health.graph_increments(baseline,{'42':2},{'42':'new'})
        self.assertEqual(increments,{})
        increments,_=health.graph_increments(baseline,{'42':3},{'42':'new'})
        self.assertEqual(increments,{'42':1})
    def test_unknown_identity_cannot_be_correlated(self):
        increments,baseline=health.graph_increments({}, {'42':100},{})
        self.assertEqual((increments,baseline),({},{}))
    def test_timeline_has_no_raw_filename_or_output_address(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,_):return json.dumps({'selected':'private.wav','active_output':'secret address','position':18001.25,'duration':43200}).encode()
        with patch.object(health.urllib.request,'urlopen',return_value=Response()):result=health.api_state()
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('secret',json.dumps(result));self.assertEqual(result['position_seconds'],18001.25)
