import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from audio_processing import DEFAULT_AUDIO_SETTINGS, validate_audio_settings, audio_filter_graph
from audio_presets import AudioPresetStore, BUILTIN_PRESETS, preset_name
from server import Controller, Server
from test_server import FakePlayer

class FiveBandTests(unittest.TestCase):
    def test_older_saved_settings_receive_new_defaults(self):
        s=validate_audio_settings({'gain_db':3,'eq_bass_db':2})
        self.assertEqual(s['eq_bands'],3);self.assertEqual(s['eq_lowmid_db'],0);self.assertEqual(s['gain_db'],3)
    def test_mode_rejects_booleans_floats_strings_and_other_integers(self):
        for bad in (True,False,3.0,'5',None,4,6):
            with self.subTest(value=bad),self.assertRaises(ValueError):validate_audio_settings({'eq_bands':bad})
    def test_three_band_remembers_but_never_applies_hidden_bands(self):
        s=validate_audio_settings({'eq_enabled':True,'eq_lowmid_db':4,'eq_presence_db':-2})
        self.assertNotIn('f=500',audio_filter_graph(s));self.assertNotIn('f=4000',audio_filter_graph(s))
        five=validate_audio_settings({'eq_bands':5},s)
        self.assertIn('f=500',audio_filter_graph(five));self.assertIn('f=4000',audio_filter_graph(five))
        back=validate_audio_settings({'eq_bands':3},five);self.assertEqual(back['eq_lowmid_db'],4)
    def test_five_band_uses_exact_centers_once_and_safe_rate(self):
        s=validate_audio_settings({'eq_enabled':True,'eq_bands':5,**{k:1 for k in ('eq_bass_db','eq_lowmid_db','eq_mid_db','eq_presence_db','eq_treble_db')}})
        graph=audio_filter_graph(s);self.assertEqual(graph.count('equalizer='),5)
        for hz in (125,500,1000,4000,8000):self.assertIn(f'equalizer=f={hz}:',graph)
        self.assertNotIn('aresample=',graph)  # Unknown/high source rates are never forced downward.
        low_rate=audio_filter_graph(s,source_sample_rate=8000)
        self.assertLess(low_rate.index('aresample=32000'),low_rate.index('equalizer='))
        self.assertNotIn('aresample=',audio_filter_graph(s,source_sample_rate=192000))
    def test_bypass_and_disabled_eq_are_neutral(self):
        self.assertEqual(audio_filter_graph({'eq_bands':5,'eq_presence_db':12}), '')
        self.assertEqual(audio_filter_graph({'bypass':True,'eq_enabled':True,'eq_bands':5,'eq_presence_db':12}), '')
    def test_builtin_presets_are_complete_valid_independent_and_sourced(self):
        self.assertEqual(len({p['id'] for p in BUILTIN_PRESETS}),len(BUILTIN_PRESETS))
        for p in BUILTIN_PRESETS:
            self.assertEqual(validate_audio_settings(p['settings']),p['settings']);self.assertTrue(p['source']['note']);audio_filter_graph(p['settings'])
        self.assertEqual(BUILTIN_PRESETS[0]['settings'],DEFAULT_AUDIO_SETTINGS)
        glue=next(p for p in BUILTIN_PRESETS if p['id']=='master-glue')['settings']
        self.assertEqual((glue['compressor_ratio'],glue['compressor_attack_ms'],glue['compressor_release_ms']),(4,30,100))

class PresetStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'audio-presets.json';self.store=AudioPresetStore(self.path)
    def tearDown(self):self.tmp.cleanup()
    def create(self,name='Night rain',identifier='a'*32,settings=None,revision=None):
        return self.store.change({'action':'create','id':identifier,'name':name,'settings':settings or {},'expected_revision':self.store.revision if revision is None else revision})
    def test_create_and_restart_preserves_full_settings_and_name(self):
        self.create('Rain – bedtime',settings={'eq_bands':5,'eq_presence_db':2,'limiter_enabled':True})
        other=AudioPresetStore(self.path);self.assertEqual(other.revision,1);self.assertEqual(other.records,self.store.records)
    def test_rename_update_delete_are_atomic_revisioned_operations(self):
        self.create();self.store.change({'action':'rename','id':'a'*32,'name':'New name','expected_revision':1})
        self.store.change({'action':'update','id':'a'*32,'settings':{'gain_db':2},'expected_revision':2})
        self.assertEqual(self.store.records[0]['name'],'New name');self.assertEqual(self.store.records[0]['settings']['gain_db'],2)
        self.store.change({'action':'delete','id':'a'*32,'expected_revision':3});self.assertEqual(self.store.records,[]);self.assertEqual(self.store.revision,4)
    def test_case_insensitive_duplicate_names_are_not_silently_overwritten(self):
        self.create()
        with self.assertRaisesRegex(ValueError,'name already'):self.create('  NIGHT RAIN  ','b'*32)
        self.assertEqual(len(self.store.records),1)
    def test_name_validation_and_unicode_normalization(self):
        self.assertEqual(preset_name('  Cafe\u0301  '),'Café')
        for name in ('', ' ', 'x'*65,'bad\nname','a\x00b',None):
            with self.subTest(name=name),self.assertRaises(ValueError):preset_name(name)
    def test_names_are_not_paths_or_executable_html(self):
        self.create('../<script>alert(1)</script>');self.assertEqual(len(list(Path(self.tmp.name).iterdir())),1)
    def test_identity_rejects_path_traversal_and_builtin_replacement(self):
        for identifier in ('../settings.json','flat','A'*32,'a'*31):
            with self.assertRaises(ValueError):self.create(identifier=identifier)
    def test_repeat_create_after_lost_response_is_idempotent(self):
        self.create();r=self.create(revision=0);self.assertEqual(r['revision'],1);self.assertEqual(len(r['custom']),1)
        with self.assertRaises(ValueError):self.create('Different',revision=0)
    def test_concurrent_revision_rejects_change_without_losing_data(self):
        self.create()
        with self.assertRaisesRegex(ValueError,'another device'):
            self.store.change({'action':'delete','id':'a'*32,'expected_revision':0})
        self.assertEqual(len(self.store.records),1)
    def test_missing_revision_is_rejected(self):
        with self.assertRaises(ValueError):self.store.change({'action':'create','id':'a'*32,'name':'X','settings':{}})
    def test_failure_to_write_does_not_publish_new_state(self):
        with patch('audio_presets.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.create()
        self.assertEqual(self.store.records,[]);self.assertEqual(self.store.revision,0)
    def test_corrupt_or_future_file_preserved_and_writes_disabled(self):
        for raw in ('not json', '{"version":2,"revision":1,"presets":[]}', '{"version":1,"revision":true,"presets":[]}'):
            self.path.write_text(raw);s=AudioPresetStore(self.path);self.assertIsNotNone(s.error)
            with self.assertRaises(ValueError):s.change({'action':'create','id':'a'*32,'name':'X','settings':{},'expected_revision':0})
            self.assertEqual(self.path.read_text(),raw)
    def test_maximum_presets_enforced(self):
        for i in range(64):self.create(str(i),f'{i:032x}')
        with self.assertRaisesRegex(ValueError,'64'):self.create('overflow','f'*32)
    def test_snapshot_is_not_mutable_store_state(self):
        self.create();snapshot=self.store.snapshot();snapshot['custom'][0]['name']='Hacked';snapshot['builtin'][0]['settings']['gain_db']=99
        self.assertEqual(self.store.records[0]['name'],'Night rain');self.assertEqual(BUILTIN_PRESETS[0]['settings']['gain_db'],0)
    def test_arbitrary_filters_are_rejected(self):
        with self.assertRaises(ValueError):self.create(settings={'filter':'amovie=secret'})
    def test_presets_do_not_call_player_or_change_active_audio(self):
        player=FakePlayer();c=Controller(Path(self.tmp.name),player);c.output='auto';(c.tracks/'Rain.wav').write_bytes(b'audio');c.play('Rain.wav');c.set_timer(15)
        state=(c.deadline,c.session,dict(c.audio_processing));player.calls.clear()
        c.audio_presets.change({'action':'create','id':'a'*32,'name':'Saved only','settings':{'gain_db':18},'expected_revision':0})
        self.assertEqual(state,(c.deadline,c.session,c.audio_processing));self.assertEqual(player.calls,[])

class PresetHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=Controller(Path(self.tmp.name),FakePlayer());self.server=Server(('127.0.0.1',0),self.c,['127.0.0.1']);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,body=None,token=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5);headers={'Content-Type':'application/json'}
        if token:headers['X-Sleep-Token']=self.c.token
        conn.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=headers)
        r=conn.getresponse();result=r.status,json.loads(r.read());conn.close();return result
    def test_catalog_modes_and_custom_round_trip(self):
        config=self.request('/api/config')[1];self.assertEqual(config['audio_processing_eq_modes'],[3,5]);self.assertTrue(config['audio_presets_supported'])
        code,data=self.request('/api/audio-presets',{'action':'create','id':'a'*32,'name':'Test','settings':{'eq_bands':5},'expected_revision':0})
        self.assertEqual(code,200);self.assertEqual(data['custom'][0]['settings']['eq_bands'],5)
        self.assertEqual(self.request('/api/audio-presets')[1]['custom'],data['custom']);self.assertEqual(self.c.audio_processing_revision,0)
    def test_csrf_and_invalid_settings_rejected(self):
        payload={'action':'create','id':'a'*32,'name':'Test','settings':{},'expected_revision':0}
        self.assertEqual(self.request('/api/audio-presets',payload,False)[0],403)
        payload['settings']={'gain_db':99};self.assertEqual(self.request('/api/audio-presets',payload)[0],400);self.assertEqual(self.c.audio_presets.records,[])
    def test_five_band_actual_processing_round_trip(self):
        code,data=self.request('/api/audio-processing',{'settings':{'eq_bands':5,'eq_enabled':True,'eq_lowmid_db':2,'eq_presence_db':-3},'expected_revision':0})
        self.assertEqual(code,200);self.assertEqual(data['settings']['eq_bands'],5)
        self.assertIn('equalizer=f=500',self.c.player.calls[-1][2]);self.assertIn('equalizer=f=4000',self.c.player.calls[-1][2])
