import http.client
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from audio_processing import ENUM_VALUES, DEFAULT_AUDIO_SETTINGS, NUMERIC_RANGES, NORMALIZATION_GRAPH, GainMeter, audio_filter_graph, gain_meter_snapshot, validate_audio_settings
from server import Controller, Server
from test_server import FakePlayer

class AudioGraphTests(unittest.TestCase):
    def test_default_graph_is_neutral(self):
        self.assertEqual(audio_filter_graph(), '')
        self.assertEqual(DEFAULT_AUDIO_SETTINGS['gain_db'], 0)
        self.assertFalse(any(DEFAULT_AUDIO_SETTINGS[k] for k in ('eq_enabled','limiter_enabled','compressor_enabled')))
    def test_legacy_normalization_is_preserved_exactly(self):
        self.assertEqual(audio_filter_graph(normalization=True), '@sleep_normalization:lavfi=['+NORMALIZATION_GRAPH+']')
    def test_invalid_numbers_never_enter_filter_graph(self):
        for key,(lo,hi) in NUMERIC_RANGES.items():
            for bad in (True,False,None,'3',float('nan'),float('inf'),-float('inf'),lo-1,hi+1):
                with self.subTest(key=key,value=bad),self.assertRaises(ValueError):
                    validate_audio_settings({key:bad})
    def test_boolean_fields_are_strict(self):
        for key in set(DEFAULT_AUDIO_SETTINGS)-set(NUMERIC_RANGES)-set(ENUM_VALUES)-{'normalization_strength'}:
            for bad in (1,0,'true',None):
                with self.subTest(key=key,value=bad),self.assertRaises(ValueError):
                    validate_audio_settings({key:bad})
    def test_unknown_fields_and_filter_injection_rejected(self):
        for bad in ({'filters':'amovie=/secret'}, {'gain_db':'6dB,amovie=secret'}, [], ''):
            with self.subTest(value=bad),self.assertRaises(ValueError):audio_filter_graph(bad)
    def test_bounds_are_accepted(self):
        for key,(lo,hi) in NUMERIC_RANGES.items():
            for v in (lo,hi):self.assertEqual(validate_audio_settings({key:v})[key],v)
    def test_gain_precedes_compressor_and_limiter(self):
        g=audio_filter_graph({'gain_db':6,'eq_enabled':True,'eq_mid_db':2,'compressor_enabled':True,'limiter_enabled':True})
        self.assertLess(g.index('volume='),g.index('equalizer='))
        self.assertLess(g.index('equalizer='),g.index('acompressor='))
        self.assertLess(g.index('acompressor='),g.index('alimiter='))
        self.assertIn('level=0',g)
        self.assertIn('threshold=0.06309573445',g)
        self.assertIn('limit=0.8912509381',g)
    def test_bypass_disables_every_effect_without_mutating_settings(self):
        s=validate_audio_settings({'bypass':True,'gain_db':12,'limiter_enabled':True,'compressor_enabled':True})
        self.assertEqual(audio_filter_graph(s,False),'');self.assertEqual(s['gain_db'],12)
    def test_normalization_excludes_manual_gain_and_retains_ceiling(self):
        g=audio_filter_graph({'gain_db':3},True)
        self.assertIn('dynaudnorm=',g);self.assertNotIn('volume=3dB',g);self.assertEqual(g.count('alimiter='),1)
        self.assertIn('limit=0.891:level=0',g)
    def test_requested_limiter_does_not_replace_normalization_ceiling(self):
        g=audio_filter_graph({'limiter_enabled':True,'limiter_ceiling_db':-6},True)
        self.assertEqual(g.count('alimiter='),1);self.assertIn('limit=0.891',g)
    def test_normalization_presets_and_ceiling_are_bounded(self):
        g=audio_filter_graph({'bypass':True,'normalization_strength':'light','normalization_ceiling_db':-3},True)
        self.assertIn('m=1.5',g);self.assertIn('limit=0.7079457844',g)
        with self.assertRaises(ValueError):audio_filter_graph({'normalization_strength':'danger'},True)
    def test_meter_wraps_chain_only_when_requested(self):
        g=audio_filter_graph({'gain_db':6},meter=True)
        self.assertLess(g.index('@sleep_meter_input'),g.index('volume=6dB'))
        self.assertLess(g.index('volume=6dB'),g.index('@sleep_meter_output'))
        self.assertIn('measure_overall=Peak_level+RMS_level',g)
        self.assertNotIn('sleep_meter_',audio_filter_graph({'gain_db':6}))
    def test_meter_snapshot_omits_nonfinite_and_reports_gain_stage(self):
        class Peaks:
            def get(self,name):
                return {'lavfi.astats.Overall.Peak_level':'-2.5' if name.endswith('input') else '-0.1'}
        snap=gain_meter_snapshot(Peaks(),{'gain_db':4})
        self.assertEqual(snap['gain_stage_peak_dbfs'],1.5);self.assertTrue(snap['gain_clipping'])
        self.assertFalse(snap['output_clipping']);self.assertEqual(snap['output_peak_dbfs'],-0.1)
        class Silence:
            def get(self,name):return {'lavfi.astats.Overall.Peak_level':'-inf'}
        self.assertFalse(gain_meter_snapshot(Silence(),{})['available'])
    def test_eq_never_downsamples_normal_or_high_rate_sources(self):
        for rate in (32000,44100,48000,96000,192000,None):
            with self.subTest(rate=rate):
                graph=audio_filter_graph({'eq_enabled':True,'eq_treble_db':3},source_sample_rate=rate)
                self.assertNotIn('aresample=',graph)
                self.assertIn('equalizer=f=8000',graph)

    def test_eq_only_upsamples_low_rate_sources_for_active_high_bands(self):
        self.assertIn('aresample=32000',audio_filter_graph({'eq_enabled':True,'eq_treble_db':3},source_sample_rate=8000))
        self.assertNotIn('aresample=',audio_filter_graph({'eq_enabled':True,'eq_bass_db':3},source_sample_rate=8000))
        self.assertNotIn('aresample=',audio_filter_graph({'eq_enabled':True},source_sample_rate=8000))

    def test_live_eq_uses_input_sample_rate_without_forcing_output_rate(self):
        from audio_processing import apply_normalization
        for rate in (8000,44100,96000,192000):
            player=FakePlayer()
            player.properties['audio-params']={'samplerate':rate}
            apply_normalization(player,False,{'eq_enabled':True,'eq_treble_db':3})
            graph=player.calls[-1][2]
            self.assertEqual('aresample=32000' in graph,rate==8000)

    def test_low_rate_eq_zeroes_need_no_filters(self):
        g=audio_filter_graph({'eq_enabled':True})
        self.assertNotIn('equalizer=',g)

class AudioControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=FakePlayer();self.c=Controller(Path(self.tmp.name),self.p)
        self.c.output='auto';(self.c.tracks/'Rain.wav').write_bytes(b'audio')
    def tearDown(self):self.tmp.cleanup()
    def test_player_output_rate_and_buffer_survive_player_restart(self):
        from server import Player
        from unittest.mock import Mock
        process=Mock()
        process.poll.return_value=1
        with patch('server.subprocess.Popen',return_value=process) as launch:
            with self.assertRaisesRegex(RuntimeError,'could not start'):
                Player(self.c.data).start()
        argv=launch.call_args.args[0]
        self.assertIn('--audio-buffer=0.5',argv)
        self.assertFalse(any(arg.startswith('--audio-samplerate=') for arg in argv))

    def test_explicit_normalization_off_persists_even_when_live_state_already_off(self):
        self.c.profiles.change('enabled',enabled=True)
        other=self.c.profiles.change('add',name='Other listener')['profiles'][1]['id']
        stale={**DEFAULT_AUDIO_SETTINGS,'bypass':True,'gain_db':5}
        self.c.profiles.update_preferences('none',{'normalization':True,'audio_processing':stale,'future_option':{'keep':True}})
        self.c.profiles.update_preferences(other,{'normalization':True,'audio_processing':stale})
        self.p.calls.clear()
        self.c.set_normalization(False,profile='none')
        self.assertFalse(self.c.profiles.data('none')['preferences']['normalization'])
        self.assertEqual(self.c.profiles.data('none')['preferences']['future_option'],{'keep':True})
        self.assertTrue(self.c.profiles.data(other)['preferences']['normalization'])
        self.assertFalse(self.p.calls)
        self.assertEqual(self.c.audio_processing_revision,0)
        loaded=Controller(self.c.data,FakePlayer());loaded.output='auto'
        loaded.play('Rain.wav',profile='none')
        self.assertFalse(loaded.normalization)
        self.assertEqual(loaded.audio_processing,DEFAULT_AUDIO_SETTINGS)

    def test_noop_effect_patch_synchronizes_only_explicit_profile_without_reapplying(self):
        self.c.profiles.change('enabled',enabled=True)
        pid=self.c.profiles.change('add',name='Other listener')['profiles'][1]['id']
        self.c.profiles.update_preferences(pid,{'normalization':True,'audio_processing':{**DEFAULT_AUDIO_SETTINGS,'eq_enabled':True,'gain_db':6}})
        self.p.calls.clear()
        self.c.set_audio_processing({'gain_db':0,'eq_enabled':False},0,profile=pid)
        prefs=self.c.profiles.data(pid)['preferences']
        self.assertFalse(prefs['normalization'])
        self.assertEqual(prefs['audio_processing'],DEFAULT_AUDIO_SETTINGS)
        self.assertFalse(self.p.calls)
        self.assertEqual(self.c.audio_processing_revision,0)
        with patch.object(self.c.profiles,'update_preferences') as write:
            self.c.set_audio_processing({'gain_db':0,'eq_enabled':False},0,profile=pid)
            write.assert_not_called()
        loaded=Controller(self.c.data,FakePlayer());loaded.output='auto'
        loaded.play('Rain.wav',profile=pid)
        self.assertFalse(loaded.normalization)
        self.assertFalse(loaded.audio_processing['eq_enabled'])
        self.assertEqual(loaded.audio_processing['gain_db'],0)

    def test_settings_persist_after_restart(self):
        self.c.set_audio_processing({'gain_db':3,'limiter_enabled':True},0)
        loaded=Controller(self.c.data,FakePlayer())
        self.assertEqual(loaded.audio_processing['gain_db'],3);self.assertTrue(loaded.audio_processing['limiter_enabled'])
        self.assertEqual(loaded.audio_processing_revision,1)
    def test_legacy_configuration_retains_volume_and_normalization(self):
        self.c.volume=23;self.c.normalization=True;self.c.save()
        settings=json.loads((self.c.data/'settings.json').read_text());settings.pop('audio_processing');settings.pop('audio_processing_revision')
        (self.c.data/'settings.json').write_text(json.dumps(settings))
        loaded=Controller(self.c.data,FakePlayer());self.assertEqual(loaded.volume,23);self.assertTrue(loaded.normalization)
        self.assertEqual(loaded.audio_processing,DEFAULT_AUDIO_SETTINGS)
    def test_corrupt_audio_settings_reset_only_processing(self):
        self.c.volume=41;self.c.save();settings=json.loads((self.c.data/'settings.json').read_text());settings['audio_processing']={'gain_db':'bad'}
        (self.c.data/'settings.json').write_text(json.dumps(settings));loaded=Controller(self.c.data,FakePlayer())
        self.assertEqual(loaded.volume,41);self.assertEqual(loaded.audio_processing,DEFAULT_AUDIO_SETTINGS)
    def test_revision_conflict_rejects_without_applying(self):
        self.c.set_audio_processing({'gain_db':3},0);self.p.calls.clear()
        with self.assertRaisesRegex(ValueError,'another device'):self.c.set_audio_processing({'gain_db':6},0)
        self.assertEqual(self.c.audio_processing['gain_db'],3);self.assertFalse(self.p.calls)
    def test_graph_failure_rolls_back(self):
        with patch('server.apply_normalization',side_effect=[RuntimeError('unavailable'),None]):
            with self.assertRaises(RuntimeError):self.c.set_audio_processing({'gain_db':6},0)
        self.assertEqual(self.c.audio_processing,DEFAULT_AUDIO_SETTINGS);self.assertEqual(self.c.audio_processing_revision,0)
    def test_save_failure_rolls_back_graph_and_configuration(self):
        with patch('server.atomic_json',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.c.set_audio_processing({'gain_db':6},0)
        self.assertEqual(self.c.audio_processing['gain_db'],0);self.assertEqual(self.p.calls[-1],('af','set',''))
    def test_gain_change_does_not_restart_playback_or_timer(self):
        self.c.play('Rain.wav');self.c.set_timer(60);deadline=self.c.deadline;session=self.c.session;self.p.calls.clear()
        self.c.set_audio_processing({'gain_db':3},0)
        self.assertEqual(self.c.deadline,deadline);self.assertEqual(self.c.session,session)
        self.assertEqual(len(self.p.calls),1);self.assertEqual(self.p.calls[0][:2],('af','set'))
    def test_meter_lease_changes_filter_only_at_start_and_expiry(self):
        self.c.play('Rain.wav');self.p.calls.clear()
        self.p.properties['af-metadata/sleep_meter_input']={'lavfi.astats.Overall.Peak_level':'-5'}
        self.p.properties['af-metadata/sleep_meter_output']={'lavfi.astats.Overall.Peak_level':'-5'}
        meter=GainMeter(self.c)
        with patch.object(meter,'_schedule'):
            self.assertTrue(meter.read()['available']);meter.read()
            self.assertEqual(len([x for x in self.p.calls if x[:2]==('af','set')]),1)
            meter.deadline=0;meter._expire()
            self.assertFalse(meter.active)
            self.assertEqual(len([x for x in self.p.calls if x[:2]==('af','set')]),2)
    def test_normalization_toggle_bypasses_manual_processing(self):
        self.c.set_audio_processing({'gain_db':3},0);self.c.set_normalization(True)
        self.assertNotIn('volume=3dB',self.p.calls[-1][2]);self.assertIn('dynaudnorm=',self.p.calls[-1][2])
        self.c.set_normalization(False);self.assertNotIn('dynaudnorm=',self.p.calls[-1][2])
    def test_alarm_bypasses_processing_and_disallows_edits(self):
        self.c.set_audio_processing({'gain_db':6,'limiter_enabled':True},0);self.p.calls.clear()
        self.c.play('Rain.wav',mode='alarm');self.assertIn(('af','set',''),self.p.calls)
        with self.assertRaisesRegex(ValueError,'alarm'):self.c.set_audio_processing({'gain_db':12},1)
    def test_unchanged_settings_do_not_write_or_reapply(self):
        self.c.set_audio_processing({'gain_db':0},0);self.assertFalse(self.p.calls);self.assertEqual(self.c.audio_processing_revision,0)

class AudioHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=Controller(Path(self.tmp.name),FakePlayer())
        self.server=Server(('127.0.0.1',0),self.c,['127.0.0.1']);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,body=None,token=True):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'Content-Type':'application/json'}
        if token:headers['X-Sleep-Token']=self.c.token
        connection.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=headers)
        result=connection.getresponse();data=json.loads(result.read());status=result.status;connection.close();return status,data
    def test_config_exposes_defaults_and_parameter_bounds(self):
        code,data=self.request('/api/config');self.assertEqual(code,200)
        self.assertEqual(data['audio_processing'],DEFAULT_AUDIO_SETTINGS);self.assertEqual(data['audio_processing_ranges']['gain_db'],[-12,18])
    def test_settings_round_trip_and_version(self):
        code,data=self.request('/api/audio-processing',{'settings':{'gain_db':4,'compressor_enabled':True},'expected_revision':0})
        self.assertEqual(code,200);self.assertEqual(data['revision'],1)
        self.assertEqual(self.request('/api/config')[1]['audio_processing']['gain_db'],4)
    def test_two_profiles_share_live_effects_and_sparse_changes_merge(self):
        self.c.profiles.change('enabled', enabled=True)
        pid = self.c.profiles.change('add', name='Test listener')['profiles'][1]['id']
        self.assertEqual(self.request('/api/audio-processing', {'profile':'none', 'settings':{'gain_db':3}})[0],200)
        code, result = self.request('/api/audio-processing', {'profile':pid, 'settings':{'eq_enabled':True}})
        self.assertEqual(code,200)
        self.assertEqual(result['audio_processing']['gain_db'],3)
        self.assertTrue(result['audio_processing']['eq_enabled'])
        first = self.request('/api/config?profile=none')[1]
        second = self.request('/api/config?profile='+pid)[1]
        self.assertEqual(first['audio_processing'], second['audio_processing'])
        self.assertEqual(first['audio_processing_revision'],second['audio_processing_revision'])
        # Stale full-form clients still receive an explicit conflict, not a silent overwrite.
        self.assertEqual(self.request('/api/audio-processing', {'profile':'none','settings':{'gain_db':6},'expected_revision':0})[0],400)
        self.assertEqual(self.c.audio_processing['gain_db'],3)
        self.assertEqual(self.request('/api/audio-processing', {'profile':'none','settings':{'eq_enabled':False}})[0],200)
        self.assertFalse(self.c.audio_processing['eq_enabled'])

    def test_normalization_and_bypass_use_shared_revision_for_both_profiles(self):
        self.c.profiles.change('enabled', enabled=True)
        pid = self.c.profiles.change('add', name='Test listener')['profiles'][1]['id']
        code, result = self.request('/api/normalization', {'profile':pid, 'enabled':True})
        self.assertEqual(code,200)
        self.assertTrue(result['normalization'])
        revision = result['revision']
        code, result = self.request('/api/audio-processing', {'profile':'none','settings':{'bypass':False},'expected_revision':revision})
        self.assertEqual(code,200)
        self.assertFalse(result['normalization'])
        self.assertEqual(result['revision'],revision+1)
        code,result=self.request('/api/normalization',{'profile':pid,'enabled':False})
        self.assertEqual(code,200)
        self.assertEqual(result['revision'],revision+1)

    def test_buffer_live_update_persists_without_playback_restart_and_honors_lock(self):
        self.assertEqual(self.request('/api/config')[1]['audio_buffer_seconds'],0.5)
        self.c.player.calls.clear()
        code,result=self.request('/api/settings',{'audio_buffer_seconds':0.85})
        self.assertEqual(code,200)
        self.assertEqual(self.request('/api/config')[1]['audio_buffer_seconds'],0.85)
        self.assertEqual(self.request('/api/status')[1]['audio_buffer_seconds'],0.85)
        self.assertEqual(self.c.player.calls,[('set_property','audio-buffer',0.85)])
        from server import Player
        loaded_player=Player(self.c.data)
        loaded=Controller(self.c.data,loaded_player)
        self.assertEqual(loaded.audio_buffer_seconds,0.85)
        self.assertEqual(loaded_player.audio_buffer_seconds,0.85)
        from unittest.mock import Mock
        process=Mock();process.poll.return_value=1
        with patch('server.subprocess.Popen',return_value=process) as launch:
            with self.assertRaises(RuntimeError):loaded_player.start()
        self.assertIn('--audio-buffer=0.85',launch.call_args.args[0])
        self.request('/api/audio-edit-lock',{'action':'configure','enabled':True})
        self.request('/api/audio-processing',{'settings':{'gain_db':1},'editor_session':'client-aaa'})
        self.assertEqual(self.request('/api/settings',{'audio_buffer_seconds':0.9,'editor_session':'client-bbb'})[0],400)
        self.assertEqual(self.c.audio_buffer_seconds,0.85)
        self.assertEqual(self.request('/api/settings',{'audio_buffer_seconds':0.9,'editor_session':'client-aaa'})[0],200)

    def test_buffer_rejects_invalid_requests_without_mutating_volume_or_player(self):
        for invalid in (True,False,None,'0.5',0.099,2.001,float('nan'),float('inf'),-float('inf')):
            with self.subTest(value=invalid):
                before=list(self.c.player.calls)
                self.assertEqual(self.request('/api/settings',{'audio_buffer_seconds':invalid,'volume':99})[0],400)
                self.assertEqual(self.c.audio_buffer_seconds,0.5)
                self.assertEqual(self.c.volume,35)
                self.assertEqual(self.c.player.calls,before)

    def test_buffer_player_failure_does_not_persist_candidate(self):
        with patch.object(self.c.player,'command',side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):self.c.set_audio_buffer(1.0)
        self.assertEqual(self.c.audio_buffer_seconds,0.5)
        self.assertEqual(Controller(self.c.data,FakePlayer()).audio_buffer_seconds,0.5)

    def test_edit_lock_defaults_off_and_expires_on_inactivity(self):
        self.assertFalse(self.request('/api/audio-edit-lock')[1]['enabled'])
        self.assertEqual(self.request('/api/audio-processing',{'settings':{'gain_db':1}})[0],200)
        self.assertEqual(self.request('/api/audio-edit-lock',{'action':'configure','enabled':True,'timeout_seconds':30})[0],200)
        self.assertEqual(self.request('/api/audio-processing',{'settings':{'gain_db':2}})[0],400)
        self.assertEqual(self.request('/api/audio-processing',{'settings':{'gain_db':2},'editor_session':'client-aaa'})[0],200)
        self.assertTrue(self.request('/api/audio-edit-lock?editor_session=client-aaa')[1]['owned'])
        # Reads must not renew the lease; a second client cannot change any shared effect/volume.
        deadline=self.c._audio_editor_deadline
        self.assertEqual(self.request('/api/normalization',{'enabled':True,'editor_session':'client-bbb'})[0],400)
        self.assertEqual(self.request('/api/settings',{'volume':80,'editor_session':'client-bbb'})[0],400)
        self.assertEqual(self.c._audio_editor_deadline,deadline)
        self.c._audio_editor_deadline=0
        self.assertEqual(self.request('/api/normalization',{'enabled':True,'editor_session':'client-bbb'})[0],200)
        self.assertEqual(self.c._audio_editor,'client-bbb')
        # Non-owner release is harmless, owner release is immediate.
        self.assertTrue(self.request('/api/audio-edit-lock',{'action':'release','editor_session':'client-aaa'})[1]['locked'])
        self.assertFalse(self.request('/api/audio-edit-lock',{'action':'release','editor_session':'client-bbb'})[1]['locked'])
        self.request('/api/audio-processing',{'settings':{'gain_db':3},'editor_session':'client-aaa'})
        loaded=Controller(self.c.data,FakePlayer())
        self.assertTrue(loaded.audio_edit_lock_enabled)
        self.assertFalse(loaded.audio_edit_lock_status()['locked'])
        self.assertEqual(loaded.audio_edit_lock_timeout,30)
        # Configuration is always reachable, even if the owning browser disappeared.
        self.assertEqual(self.request('/api/audio-edit-lock',{'action':'configure','enabled':False})[0],200)
        self.assertEqual(self.request('/api/audio-processing',{'settings':{'gain_db':4}})[0],200)

    def test_unsafe_or_untrusted_requests_leave_state_unchanged(self):
        self.assertEqual(self.request('/api/audio-processing',{'settings':{'gain_db':4}},False)[0],403)
        self.assertEqual(self.request('/api/audio-processing',{'settings':{'gain_db':19}})[0],400)
        self.assertEqual(self.request('/api/audio-processing',{'settings':{'filter':'volume=100'}})[0],400)
        self.assertEqual(self.c.audio_processing['gain_db'],0)
