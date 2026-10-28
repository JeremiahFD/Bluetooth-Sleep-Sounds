import unittest
from playback import PlaybackEvents


class PlaybackTests(unittest.TestCase):
    def test_early_error_survives_later_receipt_binding(self):
        events = PlaybackEvents()
        events.event(1, {"event": "start-file", "playlist_entry_id": 7})
        events.event(1, {"event": "end-file", "playlist_entry_id": 7, "reason": "error", "file_error": "bad data"})
        self.assertEqual(events.snapshot({"generation": 1, "entry": 7})["status"], "failed")

    def test_old_entry_and_generation_cannot_contaminate_new_playback(self):
        events = PlaybackEvents()
        for generation, entry in [(1, 1), (1, 2), (2, 1)]:
            events.event(generation, {"event": "start-file", "playlist_entry_id": entry})
            events.event(generation, {"event": "playback-restart"})
        events.event(1, {"event": "end-file", "playlist_entry_id": 1, "reason": "error"})
        self.assertEqual(events.snapshot({"generation": 1, "entry": 2})["status"], "started")
        self.assertEqual(events.snapshot({"generation": 2, "entry": 1})["status"], "started")

    def test_failure_after_start_and_listener_eof_are_visible(self):
        events = PlaybackEvents()
        events.event(1, {"event": "start-file", "playlist_entry_id": 1})
        events.event(1, {"event": "playback-restart"})
        events.event(1, {"event": "end-file", "playlist_entry_id": 1, "reason": "error"})
        self.assertEqual(events.snapshot({"generation": 1, "entry": 1})["status"], "failed")
        events.disconnected(2)
        self.assertEqual(events.snapshot({"generation": 2, "entry": 1})["status"], "failed")

    def test_intentional_stop_and_natural_end_are_not_failures(self):
        events = PlaybackEvents()
        for entry, reason, expected in [(1, "stop", "stopped"), (2, "eof", "completed")]:
            events.event(1, {"event": "end-file", "playlist_entry_id": entry, "reason": reason})
            self.assertEqual(events.snapshot({"generation": 1, "entry": entry})["status"], expected)
