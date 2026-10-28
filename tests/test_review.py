import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_server import FakePlayer
from server import Controller
from audio_processing import NORMALIZATION_GRAPH

class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.player=FakePlayer();self.c=Controller(Path(self.tmp.name),self.player);self.c.output='auto'
  for name in ('Rain.wav','Thunder.wav'):(self.c.tracks/name).write_bytes(b'audio')
 def tearDown(self):self.tmp.cleanup()
 def test_favorites_survive_restart_and_are_per_file(self):
  self.c.set_favorite('Rain.wav',True);self.c.set_favorite('Rain.wav',True)
  reloaded=Controller(self.c.data,FakePlayer())
  self.assertEqual(reloaded.favorites,{'Rain.wav'})
  self.assertTrue(next(t for t in reloaded.library() if t['id']=='Rain.wav')['favorite'])
  self.c.set_favorite('Rain.wav',False);self.assertFalse(Controller(self.c.data,FakePlayer()).favorites)
 def test_favorites_reject_nonfiles_and_nonboolean(self):
  for name in ('../settings.json','Missing.wav'):
   with self.assertRaises(ValueError):self.c.set_favorite(name,True)
  with self.assertRaises(ValueError):self.c.set_favorite('Rain.wav','yes')
 def test_failed_favorite_write_does_not_lie_to_ui(self):
  with patch('server.atomic_json',side_effect=OSError('disk failure')):
   with self.assertRaises(OSError):self.c.set_favorite('Rain.wav',True)
  self.assertFalse(self.c.favorites)
 def test_normalization_is_off_by_default_and_is_persisted(self):
  self.assertFalse(self.c.normalization);self.c.set_normalization(True)
  self.assertTrue(Controller(self.c.data,FakePlayer()).normalization)
  self.assertIn(('af','set','@sleep_normalization:lavfi=['+NORMALIZATION_GRAPH+']'),self.player.calls)
  self.c.set_normalization(False);self.assertIn(('af','set',''),self.player.calls)
 def test_normalization_failure_keeps_prior_setting(self):
  with patch('server.apply_normalization',side_effect=RuntimeError('filter unavailable')):
   with self.assertRaises(RuntimeError):self.c.set_normalization(True)
  self.assertFalse(self.c.normalization)
 def test_alarm_processing_stays_separate(self):
  self.c.mode='alarm'
  with self.assertRaises(ValueError):self.c.set_normalization(True)
  with self.assertRaises(ValueError):self.c.set_play_mode('shuffle')
 def test_pause_clears_checkpoint_immediately(self):
  self.c.resume_after_restart=True;self.c.play('Rain.wav');self.c.resume_last_saved=-60;self.c.persist_resume()
  self.assertTrue((self.c.data/'resume.json').exists())
  self.c.set_paused(True);self.assertFalse((self.c.data/'resume.json').exists())
 def test_expired_timer_cannot_start_another_file(self):
  self.c.deadline=time.monotonic()-1
  with self.assertRaisesRegex(ValueError,'expired'):self.c.play('Rain.wav')
  self.assertFalse(any(c[0]=='loadfile' for c in self.player.calls))
 def test_previous_preserves_timer_deadline(self):
  self.c.play('Thunder.wav',mode='sleep');self.c.set_timer(15);deadline=self.c.deadline
  self.c.previous();self.assertEqual(self.c.selected,'Rain.wav');self.assertEqual(self.c.deadline,deadline)
 def test_nonfinite_seek_is_rejected(self):
  for value in (float('nan'),float('inf'),-1,True):
   with self.assertRaises(ValueError):self.c.seek(value)
 def test_normalization_has_limiter_without_auto_boost(self):
  self.assertIn('m=2',NORMALIZATION_GRAPH);self.assertIn('level=0',NORMALIZATION_GRAPH);self.assertIn('limit=0.891',NORMALIZATION_GRAPH)
