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


class GraphContextTests(unittest.TestCase):
    def node(self,id=42,serial=101,name='output.sleep_sounds_example_wired',media='Audio/Sink'):
        return {'id':id,'type':'PipeWire:Interface:Node','info':{'state':'running','props':{'object.serial':serial,'node.name':name,'media.class':media,'clock.name':'private-clock','node.group':'private-group','node.latency':'2048/48000','audio.rate':48000}}}
    def test_error_can_be_assigned_to_branch_and_lifetime_without_names(self):
        serials,details=health.graph_snapshot(json.dumps([self.node()]))
        self.assertEqual(serials,{'42':'101'});self.assertEqual(details['42']['role'],'wired_member')
        self.assertEqual(details['42']['serial'],'101');self.assertEqual(details['42']['node.latency'],'2048/48000')
        self.assertNotIn('private',json.dumps(details));self.assertNotIn('sleep_sounds_example',json.dumps(details))
    def test_bluetooth_address_is_hashed_and_never_persisted(self):
        row=self.node(name='bluez_output.00_11_22_33_44_55.1')
        _,details=health.graph_snapshot(json.dumps([row]));self.assertEqual(details['42']['role'],'bluetooth_sink')
        self.assertNotIn('00_11_22',json.dumps(details));self.assertEqual(len(details['42']['name_fingerprint']),16)
    def test_node_id_reuse_has_new_identity_and_role(self):
        _,a=health.graph_snapshot(json.dumps([self.node()]))
        _,b=health.graph_snapshot(json.dumps([self.node(serial=202,name='bluez_output.example')]))
        self.assertNotEqual(a['42']['serial'],b['42']['serial']);self.assertNotEqual(a['42']['role'],b['42']['role'])
    def test_profiler_timing_keeps_metrics_and_ignores_name(self):
        text='R 42 2048 48000 12us 0.4ms 0.2 0.01 9 F32LE private device\nC 42 0 0 --- --- --- --- 0 name\n'
        result=health.graph_timing(text);self.assertEqual(result['42']['errors'],9);self.assertEqual(result['42']['quantum_frames'],2048)
        self.assertEqual(result['42']['busy'],'0.4ms');self.assertNotIn('private',json.dumps(result))
    def test_partial_and_malformed_graphs_do_not_create_context(self):
        for raw in ['{','{}',json.dumps([{'id':42,'type':'PipeWire:Interface:Node','info':None}]),json.dumps([{'type':'PipeWire:Interface:Node','info':7}])]:self.assertEqual(health.graph_snapshot(raw),({},{}))
    def test_non_audio_names_are_not_saved_and_rows_are_bounded(self):
        rows=[self.node(id=n,media='Video/Source',name='private-camera')for n in range(300)]
        serials,details=health.graph_snapshot(json.dumps(rows));self.assertEqual(len(serials),256);self.assertEqual(details,{})
