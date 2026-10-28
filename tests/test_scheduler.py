from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from scheduler import Alarm

UTC = timezone.utc


def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def chicago(key):
    if key != "America/Chicago":
        raise ValueError("Unavailable test timezone")
    with (Path(__file__).parent / "Chicago.tzif").open("rb") as source:
        return ZoneInfo.from_file(source, key)


class AlarmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "alarm.json"
        self.play = Mock()
        self.ready = True
        self.alarm = Alarm(self.path, self.play, lambda config: None, lambda: self.ready)
        self.zone_patch = patch("scheduler.ZoneInfo", side_effect=chicago)
        self.zone_patch.start()

    def tearDown(self):
        self.zone_patch.stop()
        self.temp.cleanup()

    def configure(self, **changes):
        self.alarm.configure({"enabled": True, "time": "07:00", "track": "Rain.webm", "output": "pulse/explicit-speaker", **changes}, now=stamp("2026-10-15T00:00:00"))

    def test_due_alarm_runs_once_across_restart(self):
        self.configure()
        now = stamp("2026-10-16T12:00:05")
        self.alarm.tick(now)
        self.alarm.tick(now)
        restarted = Alarm(self.path, self.play, lambda config: None, lambda: True)
        restarted.tick(now)
        self.assertEqual(self.play.call_count, 1)
        self.assertEqual(restarted.state["result"]["status"], "started")

    def test_clock_gate_and_missed_alarm(self):
        self.configure()
        self.ready = False
        self.alarm.tick(stamp("2026-10-16T12:00:01"))
        self.play.assert_not_called()
        self.ready = True
        self.alarm.tick(stamp("2026-10-16T12:10:00"))
        self.play.assert_not_called()
        self.assertEqual(self.alarm.state["result"]["status"], "missed")

    def test_playback_confirmation_then_error_is_persisted_without_ntp(self):
        observed = {"status": "starting"}
        self.alarm.observe = lambda receipt: dict(observed)
        self.configure()
        now = stamp("2026-10-16T12:00:00")
        self.alarm.tick(now)
        self.assertEqual(self.alarm.state["result"]["status"], "starting")
        self.ready = False
        observed["status"] = "started"
        self.alarm.tick(now)
        self.assertEqual(self.alarm.state["result"]["status"], "started")
        observed.update(status="failed", message="Decode failed")
        self.alarm.tick(now)
        self.assertEqual(self.alarm.state["result"]["message"], "Decode failed")
        self.assertIsNone(self.alarm.pending)

    def test_reconfigure_does_not_receive_stale_playback_result(self):
        self.alarm.observe = lambda receipt: {"status": "failed", "message": "old"}
        self.configure()
        now = stamp("2026-10-16T12:00:00")
        self.alarm.tick(now)
        self.alarm.configure({"enabled": False}, now=now)
        self.alarm.tick(now)
        self.assertIsNone(self.alarm.state["result"])

    def test_clock_rollback_does_not_replace_claim_or_repeat_alarm(self):
        self.configure()
        self.alarm.tick(stamp("2026-10-16T12:00:00"))
        identity = self.alarm.state["occurrence"]
        self.alarm.tick(stamp("2026-10-16T11:59:59"))
        self.assertEqual(self.alarm.state["occurrence"], identity)
        restarted = Alarm(self.path, self.play, lambda config: None, lambda: True)
        restarted.tick(stamp("2026-10-16T12:00:00"))
        self.assertEqual(self.play.call_count, 1)

    def test_missing_output_failure_is_recorded_without_retry(self):
        self.configure()
        self.play.side_effect = ValueError("Output unavailable")
        now = stamp("2026-10-16T12:00:00")
        self.alarm.tick(now)
        self.alarm.tick(now)
        self.assertEqual(self.play.call_count, 1)
        self.assertEqual(self.alarm.state["result"]["status"], "failed")

    def test_spring_gap_skips_nonexistent_time(self):
        self.alarm.configure({"enabled": True, "time": "02:30", "track": "Rain.wav", "output": "pulse/speaker"}, now=stamp("2026-03-07T00:00:00"))
        self.assertEqual(self.alarm.status(stamp("2026-03-08T06:00:00"))["next_utc"], "2026-03-09T07:30:00+00:00")

    def test_fall_repeat_rings_only_first_occurrence(self):
        self.alarm.configure({"enabled": True, "time": "01:30", "track": "Rain.wav", "output": "pulse/speaker"}, now=stamp("2026-10-31T00:00:00"))
        self.alarm.tick(stamp("2026-11-01T06:30:00"))
        self.alarm.tick(stamp("2026-11-01T07:30:00"))
        self.assertEqual(self.play.call_count, 1)

    def test_weekday_and_new_year(self):
        self.alarm.configure({"enabled": True, "time": "07:00", "weekdays": [4], "track": "Rain.wav", "output": "pulse/speaker"}, now=stamp("2026-12-31T00:00:00"))
        self.assertEqual(self.alarm.status(stamp("2026-12-31T23:00:00"))["next_utc"], "2027-01-01T13:00:00+00:00")

    def test_validation_is_atomic_and_output_is_chosen_at_ring_time(self):
        self.configure()
        original = self.path.read_bytes()
        for invalid in [{"volume": 101}, {"time": "25:00"}, {"weekdays": [True]}, {"timezone": "Invalid/Zone"}, {"ring_minutes": 0}]:
            with self.assertRaises(ValueError):
                self.alarm.configure(invalid)
            self.assertEqual(self.path.read_bytes(), original)

    def test_failed_persistence_never_triggers_audio(self):
        self.configure()
        with patch.object(Path, "replace", side_effect=OSError("disk failed")):
            with self.assertRaises(OSError):
                self.alarm.tick(stamp("2026-10-16T12:00:01"))
        self.play.assert_not_called()
        self.assertIsNone(self.alarm.state["occurrence"])

    def test_interrupted_claim_is_not_replayed(self):
        self.configure()
        with patch.object(self.play, "side_effect", KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.alarm.tick(stamp("2026-10-16T12:00:00"))
        restarted = Alarm(self.path, self.play, lambda config: None, lambda: True)
        self.assertEqual(restarted.state["result"]["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
