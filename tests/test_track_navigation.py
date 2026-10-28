"""Paused track navigation regression tests (temporary FakePlayer; no hardware)."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from server import Controller
from test_server import FakePlayer

class TrackNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.player=FakePlayer()
        self.c=Controller(Path(self.tmp.name), self.player)
        self.c.output="auto"
        for name in ("A.wav","B.wav","C.wav"):
            (self.c.tracks/name).write_bytes(b"fixture")
    def tearDown(self):self.tmp.cleanup()
    def test_idle_select_is_silent(self):
        self.c.select_library_track("B.wav")
        self.assertEqual(self.c.selected,"B.wav")
        self.assertIsNone(self.c.last_played_track)
        self.assertNotIn("loadfile",[x[0] for x in self.player.calls])
    def test_playing_select_starts_new_track(self):
        self.c.play("A.wav")
        self.c.select_library_track("B.wav")
        self.assertEqual(self.c.selected,"B.wav")
        self.assertFalse(self.player.get("pause"))
    def test_paused_select_remains_paused_and_keeps_sleep_timer(self):
        self.c.play("A.wav",mode="sleep")
        self.c.set_timer(20)
        deadline=self.c.deadline
        self.c.set_paused(True)
        self.player.calls.clear()
        self.c.select_library_track("B.wav")
        self.assertTrue(self.player.get("pause"))
        self.assertEqual(self.c.deadline,deadline)
        self.assertEqual(self.c.mode,"sleep")
        self.assertLess(self.player.calls.index(("set_property","pause",True)),next(i for i,x in enumerate(self.player.calls) if x[0]=="loadfile"))
        self.assertNotIn(("set_property","pause",False),self.player.calls)
        self.assertEqual(self.c.playback_status(self.c.receipt)["status"],"paused")
        self.c.set_paused(False)
        self.assertFalse(self.player.get("pause"))
    def test_next_previous_remain_paused(self):
        self.c.play("A.wav")
        self.c.set_paused(True)
        self.player.calls.clear()
        self.c.skip()
        self.assertEqual(self.c.selected,"B.wav")
        self.assertTrue(self.player.get("pause"))
        self.assertNotIn(("set_property","pause",False),self.player.calls)
        self.player.calls.clear()
        self.c.previous()
        self.assertEqual(self.c.selected,"A.wav")
        self.assertTrue(self.player.get("pause"))
        self.assertNotIn(("set_property","pause",False),self.player.calls)
    def test_playing_next_plays_and_explicit_play_resumes(self):
        self.c.play("A.wav")
        self.c.skip()
        self.assertFalse(self.player.get("pause"))
        self.c.set_paused(True)
        self.c.play("C.wav")
        self.assertFalse(self.player.get("pause"))
    def test_alarm_cannot_replace_and_invalid_path_rejected(self):
        with self.assertRaises(ValueError):self.c.select_library_track("../bad.wav")
        self.c.play("A.wav",mode="alarm")
        with self.assertRaisesRegex(ValueError,"alarm"):self.c.select_library_track("B.wav")
    def test_idle_paused_preparation_is_silent_and_can_seek_after_load(self):
        self.c.select_library_track("B.wav", start_paused=True)
        self.assertFalse(self.player.get("idle-active"))
        self.assertTrue(self.player.get("pause"))
        self.assertLess(self.player.calls.index(("set_property", "pause", True)),
                        next(i for i,x in enumerate(self.player.calls) if x[0]=="loadfile"))
        self.assertEqual(self.c.playback_status(self.c.receipt)["status"], "paused")
        self.player.properties["duration"]=120.0
        self.c.seek(31)
        self.assertIn(("seek",31,"absolute"),self.player.calls)
    def test_paused_preparation_requires_boolean(self):
        with self.assertRaisesRegex(ValueError,"on or off"):
            self.c.select_library_track("B.wav",start_paused="yes")
    def test_loaded_paused_never_times_out_as_failed(self):
        self.c.play("A.wav")
        self.c.set_paused(True)
        self.c.skip()
        with patch.object(self.player,"playback_status",return_value={"status":"loaded"}):
            with patch("server.time.monotonic",return_value=self.c.receipt["deadline"]+30):
                self.assertEqual(self.c.playback_status(self.c.receipt)["status"],"paused")

if __name__=="__main__":unittest.main()
