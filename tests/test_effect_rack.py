import tempfile
import unittest
from pathlib import Path
from audio_processing import validate_audio_settings, audio_filter_graph, DEFAULT_AUDIO_SETTINGS, NOISE_COLORS
from audio_presets import AudioPresetStore
from profiles import ProfileStore
from server import Controller
from test_server import FakePlayer


class EffectRackTests(unittest.TestCase):
    def test_order_changes_processing_not_just_display(self):
        s={'gain_db':3,'compressor_enabled':True,'echo_enabled':True,
           'rack_order':['compressor','echo','gain']}
        graph=audio_filter_graph(s)
        self.assertLess(graph.index('acompressor='),graph.index('aecho='))
        self.assertLess(graph.index('aecho='),graph.index('volume='))
        self.assertNotIn('alimiter=',graph)
        graph=audio_filter_graph({**s,'rack_order':['compressor']})
        self.assertNotIn('volume=',graph)
        self.assertNotIn('aecho=',graph)

    def test_migration_and_mutation_isolation(self):
        migrated=validate_audio_settings({'gain_db':2})
        self.assertEqual(migrated['rack_order'],['gain','eq','compressor','limiter'])
        migrated['rack_order'].clear()
        self.assertTrue(DEFAULT_AUDIO_SETTINGS['rack_order'])
        self.assertEqual(audio_filter_graph({'gain_db':4,'gain_enabled':False}),'')

    def test_rejects_unsafe_order_colors_and_layer_levels(self):
        for order in (['gain','gain'],['amovie=/secret'],True,{},['gain',3]):
            with self.assertRaises(ValueError):validate_audio_settings({'rack_order':order})
        for patch in ({'noise1_color':'pink;amovie=/secret'},{'noise1_db':0},{'noise2_db':True}):
            with self.assertRaises(ValueError):validate_audio_settings(patch)

    def test_two_layers_follow_track_duration_and_bypass(self):
        for color in NOISE_COLORS:
            s={'noise1_enabled':True,'noise2_enabled':True,'noise1_color':color,'noise2_db':-40}
            graph=audio_filter_graph(s,source_sample_rate=96000)
            self.assertEqual(graph.count('anoisesrc='),2)
            self.assertIn('r=96000',graph)
            self.assertIn('duration=first',graph)
            self.assertIn('normalize=0',graph)
            self.assertIn('alimiter=',graph)
            self.assertEqual(audio_filter_graph({**s,'bypass':True}),'')
        self.assertNotIn('anoisesrc=',audio_filter_graph({}))

    def test_presets_roundtrip_chain_and_layers(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'presets.json'
            store=AudioPresetStore(path)
            settings={'rack_order':['echo','gain'],'echo_enabled':True,'noise1_enabled':True,'noise1_color':'blue'}
            store.change({'action':'create','id':'1'*32,'name':'My scene','settings':settings,'expected_revision':0})
            reread=AudioPresetStore(path).snapshot()['custom'][0]['settings']
            self.assertEqual(reread['rack_order'],['echo','gain'])
            self.assertTrue(reread['noise1_enabled'])
            self.assertEqual(reread['noise1_color'],'blue')

    def test_noise_edit_does_not_turn_off_normalization(self):
        with tempfile.TemporaryDirectory() as root:
            c=Controller(Path(root),FakePlayer())
            c.set_normalization(True)
            c.set_audio_processing({'noise1_enabled':True,'noise1_color':'violet'})
            self.assertTrue(c.normalization)

    def test_fullscreen_is_profile_specific_and_preserves_future_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'profiles.json';store=ProfileStore(path)
            store.change('enabled',enabled=True)
            pid=store.change('add',name='Listener')['profiles'][1]['id']
            store.update_preferences(pid,{'fullscreen_layout':True,'future_setting':{'x':1}})
            store.update_preferences('none',{'fullscreen_layout':False})
            restored=ProfileStore(path)
            self.assertTrue(restored.data(pid)['preferences']['fullscreen_layout'])
            self.assertFalse(restored.data('none')['preferences']['fullscreen_layout'])
            self.assertEqual(restored.data(pid)['preferences']['future_setting'],{'x':1})
