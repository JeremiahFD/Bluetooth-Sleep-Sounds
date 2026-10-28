"""Offline tests only: temporary files, fake player, loopback HTTP server."""
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from library_discovery import DiscoveryStore
from server import Controller, Server
from test_server import FakePlayer


class NextBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.player = FakePlayer()
        self.c = Controller(self.data, self.player)
        for name in ('Rain.wav', 'Thunder.wav'):
            (self.c.tracks / name).write_bytes(b'audio fixture')
        self.server = Server(('127.0.0.1', 0), self.c, ['127.0.0.1'])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, body=None, *, token=True, origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Sleep-Token'] = self.c.token
        if origin:
            headers['Origin'] = origin
        connection.request('GET' if body is None else 'POST', path,
                           None if body is None else json.dumps(body), headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_deletion_requires_setting_confirmation_token_and_same_origin(self):
        payload = {'track': 'Rain.wav', 'confirm': True}
        self.assertFalse(self.request('/api/config')[1]['allow_track_deletion'])
        self.assertEqual(self.request('/api/track-delete', payload)[0], 400)
        self.assertEqual(self.request('/api/settings', {'allow_track_deletion': True})[0], 200)
        self.assertTrue(self.request('/api/config')[1]['allow_track_deletion'])
        self.assertTrue(Controller(self.data, FakePlayer()).allow_track_deletion)
        self.assertEqual(self.request('/api/track-delete', payload, token=False)[0], 403)
        self.assertEqual(self.request('/api/track-delete', payload, origin='http://other.example')[0], 403)
        for confirm in (None, False, 'true', 1):
            self.assertEqual(self.request('/api/track-delete', {**payload, 'confirm': confirm})[0], 400)
        self.assertTrue((self.c.tracks / 'Rain.wav').exists())
        self.request('/api/settings', {'allow_track_deletion': False})
        self.assertEqual(self.request('/api/track-delete', payload)[0], 400)

    def test_delete_removes_only_selected_file_artwork_and_retains_history(self):
        key = hashlib.sha256(b'Rain.wav').hexdigest()
        image = self.c.artwork_dir / (key + '.png')
        image.write_bytes(b'image fixture')
        unrelated = self.c.artwork_dir / 'unrelated.png'
        unrelated.write_bytes(b'keep')
        self.c.discovery.rating('Rain.wav', 'none', 4)
        self.c.discovery.post('none', 'Keep this note', track='Rain.wav')
        self.c.profiles.set_favorite('none', 'Rain.wav', True)
        self.c.allow_track_deletion = True
        response, result = self.request('/api/track-delete', {'track': 'Rain.wav', 'confirm': True})
        self.assertEqual(response, 200)
        self.assertTrue(result['history_retained'])
        self.assertFalse((self.c.tracks / 'Rain.wav').exists())
        self.assertFalse(image.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue((self.c.tracks / 'Thunder.wav').exists())
        self.assertEqual(self.c.discovery.state['ratings']['none']['Rain.wav'], 4)
        self.assertIn('Rain.wav', self.c.profiles.favorites('none'))
        self.assertEqual(self.player.calls, [])

    def test_delete_protects_playing_paused_referenced_and_external_files(self):
        self.c.allow_track_deletion = True
        self.c.selected = 'Rain.wav'
        self.player.properties['idle-active'] = False
        for paused in (False, True):
            self.player.properties['pause'] = paused
            self.assertEqual(self.request('/api/track-delete', {'track': 'Rain.wav', 'confirm': True})[0], 400)
        self.player.properties['idle-active'] = True
        self.c.alarm.state['config']['track'] = 'Rain.wav'
        self.assertEqual(self.request('/api/track-delete', {'track': 'Rain.wav', 'confirm': True})[0], 400)
        self.c.alarm.state['config']['track'] = None
        self.c.remote_store.state['remotes'].append({'default_track': 'Rain.wav'})
        self.assertEqual(self.request('/api/track-delete', {'track': 'Rain.wav', 'confirm': True})[0], 400)
        for name in ('../Rain.wav', '..\\Rain.wav', '/tmp/other.wav', None):
            self.assertEqual(self.request('/api/track-delete', {'track': name, 'confirm': True})[0], 400)
        self.assertTrue((self.c.tracks / 'Rain.wav').exists())

    def test_unlink_failure_does_not_remove_annotations_or_claim_success(self):
        self.c.allow_track_deletion = True
        self.c.discovery.rating('Rain.wav', 'none', 3)
        with patch.object(Path, 'unlink', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                self.c.delete_track('Rain.wav', True)
        self.assertTrue((self.c.tracks / 'Rain.wav').exists())
        self.assertEqual(self.c.discovery.state['ratings']['none']['Rain.wav'], 3)
        self.assertEqual(self.c.library_revision, 0)

    def test_toggle_invalid_payload_is_not_applied(self):
        for value in (1, 'true', None):
            self.assertEqual(self.request('/api/settings', {'allow_track_deletion': value})[0], 400)
        self.assertEqual(self.request('/api/settings', {'allow_track_deletion': True, 'volume': 999})[0], 400)
        self.assertFalse(self.c.allow_track_deletion)

    def test_failed_settings_save_cannot_enable_deletion(self):
        with patch.object(self.c, 'save', side_effect=OSError('read only')):
            self.assertEqual(self.request('/api/settings', {'allow_track_deletion': True})[0], 503)
        self.assertFalse(self.c.allow_track_deletion)
        self.assertTrue((self.c.tracks / 'Rain.wav').exists())

    def test_delete_does_not_invert_alarm_transition_lock_order(self):
        self.c.allow_track_deletion = True
        failures = []
        def remove():
            try:
                self.c.delete_track('Thunder.wav', True)
            except Exception as error:
                failures.append(error)
        worker = threading.Thread(target=remove)
        self.c.alarm.lock.acquire()
        try:
            worker.start()
            deadline = time.monotonic() + 2
            while not self.c.upload_lock.locked() and time.monotonic() < deadline:
                threading.Event().wait(.005)
            self.assertTrue(self.c.upload_lock.locked())
            acquired = self.c.transition_lock.acquire(timeout=.5)
            try:
                self.assertTrue(acquired, 'Alarm callback would deadlock on the player transition')
            finally:
                if acquired:
                    self.c.transition_lock.release()
        finally:
            self.c.alarm.lock.release()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])

    def test_comments_are_scoped_and_do_not_change_audio(self):
        self.assertEqual(self.request('/api/feedback', {'body': 'General feedback'})[0], 200)
        status, result = self.request('/api/track-comments', {'track': 'Rain.wav', 'body': 'Lovely rain'})
        self.assertEqual(status, 200)
        parent = result['posts'][0]['id']
        self.assertEqual(self.request('/api/feedback')[1]['posts'][0]['body'], 'General feedback')
        self.assertEqual(self.request('/api/track-comments?track=Thunder.wav')[1]['posts'], [])
        self.assertEqual(self.request('/api/track-comments', {'track': 'Thunder.wav', 'body': 'Wrong track', 'parent': parent})[0], 400)
        self.assertEqual(self.request('/api/feedback', {'body': 'Wrong scope', 'parent': parent})[0], 400)
        self.assertEqual(self.request('/api/track-comments', {'track': 'Rain.wav', 'body': 'Agreed', 'parent': parent})[0], 200)
        self.c.discovery.edit('Rain.wav', {'title': 'Renamed rain'}, self.c.discovery.state['revision'])
        stored = DiscoveryStore(self.c.discovery.path)
        self.assertEqual(stored.feedback(self.c.profiles.catalog()['profiles'], track='Rain.wav')['posts'][0]['replies'][0]['body'], 'Agreed')
        self.assertEqual(self.player.calls, [])

    def test_comments_enforce_profile_and_mutation_boundaries(self):
        payload = {'track': 'Rain.wav', 'body': 'Hello'}
        self.assertEqual(self.request('/api/track-comments', payload, token=False)[0], 403)
        self.assertEqual(self.request('/api/track-comments', payload, origin='http://other.example')[0], 403)
        self.assertEqual(self.request('/api/track-comments', {**payload, 'track': '../other.wav'})[0], 400)
        pid = self.c.profiles.change('add', name='Another')['profiles'][-1]['id']
        self.c.profiles.change('enabled', enabled=True)
        result = self.request('/api/track-comments', {**payload, 'profile': pid})[1]
        self.assertEqual(result['posts'][0]['name'], 'Another')
        self.c.profiles.change('rename', profile=pid, name='New name')
        self.assertEqual(self.request('/api/track-comments?track=Rain.wav')[1]['posts'][0]['name'], 'New name')
        self.assertEqual(self.c.active_profile_id, 'none')
