import json
import http.client
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from audio_processing import METER_INPUT_LABEL, METER_OUTPUT_LABEL
from profiles import ProfileStore
from server import Controller, Server
from test_server import FakePlayer


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'profiles.json'
        self.store = ProfileStore(self.path, ['Rain.wav'])

    def tearDown(self):
        self.temp.cleanup()

    def test_none_is_permanent_and_disabled_always_resolves_to_none(self):
        self.assertEqual(self.store.favorites(), {'Rain.wav'})
        self.assertEqual(self.store.resolve('invalid'), 'none')
        with self.assertRaisesRegex(ValueError, 'None profile'):
            self.store.change('delete', profile='none')
        with self.assertRaisesRegex(ValueError, 'None profile'):
            self.store.change('rename', profile='none', name='Changed')
        added = self.store.change('add', name='Listener B')['profiles'][1]['id']
        self.store.change('enabled', enabled=True)
        self.assertEqual(self.store.resolve(added), added)
        self.store.change('enabled', enabled=False)
        self.assertEqual(self.store.resolve(added), 'none')
        self.assertEqual(len(self.store.catalog()['profiles']), 2)

    def test_named_favorites_settings_and_unknown_fields_survive_restart(self):
        added = self.store.change('add', name='Listener A')['profiles'][1]['id']
        self.store.change('enabled', enabled=True)
        self.store.set_favorite(added, 'Storm.flac', True)
        self.store.update_preferences(added, {'theme':'cloudstorm','future_setting':{'a':1}})
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        saved['future_top'] = {'version': 7}
        saved['profiles'][1]['future_profile'] = {'notes': ['kept']}
        self.path.write_text(json.dumps(saved), encoding='utf-8')
        reloaded = ProfileStore(self.path)
        reloaded.change('rename', profile=added, name='J')
        stored = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(stored['future_top'], {'version': 7})
        self.assertEqual(stored['profiles'][1]['future_profile'], {'notes': ['kept']})
        self.assertEqual(reloaded.favorites(added), {'Storm.flac'})
        self.assertEqual(reloaded.data(added)['preferences']['theme'], 'cloudstorm')
        self.assertEqual(reloaded.favorites('none'), {'Rain.wav'})

    def test_invalid_names_and_unknown_profile_rejected_when_enabled(self):
        for value in ['', 'None', 'none', 'bad\nname', 'x'*33]:
            with self.assertRaises(ValueError):
                self.store.change('add', name=value)
        self.store.change('enabled', enabled=True)
        with self.assertRaisesRegex(ValueError, 'no longer available'):
            self.store.resolve('deleted')

    def test_corrupt_profile_file_is_not_overwritten(self):
        self.path.write_text('{broken', encoding='utf-8')
        reloaded = ProfileStore(self.path, ['Rain.wav'])
        self.assertTrue(reloaded.read_error)
        self.assertEqual(reloaded.favorites('none'), {'Rain.wav'})
        with self.assertRaisesRegex(ValueError, 'needs repair'):
            reloaded.change('add', name='New')
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{broken')


class ProfileControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.player = FakePlayer()
        self.controller = Controller(self.data, self.player)
        (self.controller.tracks / 'Rain.wav').write_bytes(b'fake audio')

    def tearDown(self):
        self.temp.cleanup()

    def test_per_profile_favorites_and_favorited_by(self):
        c = self.controller
        c.set_favorite('Rain.wav', True)
        other = c.profiles.change('add', name='Other')['profiles'][1]['id']
        c.profiles.change('enabled', enabled=True)
        self.assertFalse(c.library(other)[0]['favorite'])
        c.set_favorite('Rain.wav', True, other)
        self.assertEqual(c.favorited_by('Rain.wav'), ['None','Other'])
        c.profiles.change('enabled', enabled=False)
        self.assertTrue(c.library(other)[0]['favorite'])
        self.assertEqual(Controller(self.data, FakePlayer()).favorites, {'Rain.wav'})

    def test_profile_choice_does_not_change_player_until_explicit_play(self):
        c = self.controller
        pid = c.profiles.change('add', name='Quiet')['profiles'][1]['id']
        c.profiles.change('enabled', enabled=True)
        c.profiles.update_preferences(pid, {'volume': 18, 'play_mode': 'loop'})
        self.assertEqual(c.volume, 35)
        self.assertFalse(c.loop)
        c.output = 'lineout'
        self.player.properties['audio-device-list'].append({'name':'lineout','description':'Headphones'})
        c.play('Rain.wav', profile=pid)
        self.assertEqual((c.volume,c.play_mode,c.active_profile_id),(18,'loop',pid))
        self.assertIn(('set_property','volume',18),self.player.calls)

    def test_normalization_and_manual_dsp_are_exclusive_and_rollback(self):
        c = self.controller
        c.set_normalization(True)
        self.assertTrue(c.normalization)
        self.assertTrue(c.audio_processing['bypass'])
        settings = dict(c.audio_processing)
        settings['bypass'] = False
        c.set_audio_processing(settings)
        self.assertFalse(c.normalization)
        self.assertFalse(c.audio_processing['bypass'])
        previous = (dict(c.audio_processing),c.audio_processing_revision,c.normalization)
        with patch('server.apply_normalization', side_effect=RuntimeError('broken')):
            with self.assertRaisesRegex(RuntimeError,'broken'):
                c.set_normalization(True)
        self.assertEqual((c.audio_processing,c.audio_processing_revision,c.normalization), previous)


class ProfileHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.player = FakePlayer()
        self.controller = Controller(Path(self.temp.name), self.player)
        (self.controller.tracks / 'Rain.wav').write_bytes(b'fake audio')
        self.server = Server(('127.0.0.1', 0), self.controller, ['127.0.0.1'])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        if self.controller.gain_meter._timer:
            self.controller.gain_meter._timer.cancel()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'X-Sleep-Token': self.controller.token} if body is not None else {}
        client.request('POST' if body is not None else 'GET', path,
                       body=json.dumps(body).encode() if body is not None else None, headers=headers)
        response = client.getresponse()
        result = response.status, json.loads(response.read())
        client.close()
        return result

    def test_profile_routes_scope_favorites_and_none_when_disabled(self):
        status, catalog = self.request('/api/profiles')
        self.assertEqual(status, 200)
        self.assertEqual(catalog['profiles'], [{'id':'none','name':'None'}])
        self.assertEqual(self.request('/api/profiles', {'action':'add','name':'Second'})[0], 200)
        pid = self.controller.profiles.catalog()['profiles'][1]['id']
        self.assertEqual(self.request('/api/profiles', {'action':'enabled','enabled':True})[0], 200)
        self.assertEqual(self.request('/api/favorite', {'track':'Rain.wav','favorite':True,'profile':pid})[0], 200)
        self.assertFalse(self.request('/api/tracks?profile=none')[1][0]['favorite'])
        self.assertTrue(self.request('/api/tracks?profile='+pid)[1][0]['favorite'])
        self.assertEqual(self.request('/api/profile-data', {'profile':pid,'preferences':{'theme':'forest'}})[1]['preferences']['theme'], 'forest')
        self.assertEqual(self.request('/api/profiles', {'action':'enabled','enabled':False})[0], 200)
        self.assertFalse(self.request('/api/tracks?profile='+pid)[1][0]['favorite'])

    def test_meter_lease_requires_post_token(self):
        self.assertEqual(self.request('/api/audio-meter')[0], 404)
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        client.request('POST', '/api/audio-meter', body=b'{}')
        self.assertEqual(client.getresponse().status, 403)
        client.close()
        self.assertFalse(self.controller.gain_meter.active)
        self.controller.mode = 'normal'
        self.player.properties['idle-active'] = False
        self.player.properties['af-metadata/' + METER_INPUT_LABEL] = {'lavfi.astats.Overall.Peak_level':'-6.0'}
        self.player.properties['af-metadata/' + METER_OUTPUT_LABEL] = {'lavfi.astats.Overall.Peak_level':'-5.0'}
        status, result = self.request('/api/audio-meter', {})
        self.assertEqual(status, 200)
        self.assertTrue(result['available'])
        self.assertEqual(result['input_peak_dbfs'], -6.0)
        self.assertTrue(self.controller.gain_meter.active)

    def test_other_profile_can_edit_shared_volume_and_effects_without_owning_playback(self):
        c=self.controller
        c.output='lineout'
        self.player.properties['audio-device-list'].append({'name':'lineout','description':'Headphones'})
        self.assertEqual(self.request('/api/play', {'track':'Rain.wav','profile':'none'})[0],200)
        pid=self.request('/api/profiles', {'action':'add','name':'Other'})[1]['profiles'][1]['id']
        self.request('/api/profiles', {'action':'enabled','enabled':True})
        prior_calls=len(self.player.calls)
        self.assertEqual(self.request('/api/settings', {'profile':pid,'volume':18,'sleep_minutes':90})[0],200)
        self.assertEqual(self.request('/api/play_mode', {'profile':pid,'mode':'loop'})[0],200)
        self.assertEqual(self.request('/api/audio-processing',
            {'profile':pid,'settings':{'gain_db':5,'bypass':False},'expected_revision':0})[0],200)
        self.assertEqual(c.volume,18)
        self.assertEqual(c.audio_processing['gain_db'],5)
        self.assertEqual(len(self.player.calls),prior_calls + 2)
        status,config=self.request('/api/config?profile='+pid)
        self.assertEqual(status,200)
        self.assertEqual((config['volume'],config['sleep_minutes'],config['audio_processing']['gain_db']),(18,90,5))
        self.assertEqual(config['play_mode'],'loop')
        self.assertEqual(config['active_profile_id'],'none')


if __name__ == '__main__':
    unittest.main()
