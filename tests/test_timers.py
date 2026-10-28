from datetime import datetime,timezone
from pathlib import Path
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from timers import seconds_to_end_time

def chicago(key):
    if key!="America/Chicago":raise ValueError("Unknown test zone")
    with (Path(__file__).parent/"Chicago.tzif").open("rb") as source:
        return ZoneInfo.from_file(source,key)

class TimerDeadlineTests(unittest.TestCase):
    def test_end_time_and_midnight_rollover(self):
        with patch("timers.ZoneInfo",side_effect=chicago):
            now=datetime(2026,10,17,3,0,tzinfo=timezone.utc) # Friday 22:00 CDT
            self.assertAlmostEqual(seconds_to_end_time("23:00",now=now),3600,delta=2)
            self.assertAlmostEqual(seconds_to_end_time("00:30",now=now),9000,delta=2)
    def test_invalid_or_too_distant_clock_times(self):
        with patch("timers.ZoneInfo",side_effect=chicago):
            now=datetime(2026,10,17,3,0,tzinfo=timezone.utc)
            for value in ("25:00","2 pm","10:99",""):
                with self.assertRaises(ValueError):seconds_to_end_time(value,now=now)
            with self.assertRaisesRegex(ValueError,"16 hours"):
                seconds_to_end_time("15:00",now=now)
    def test_dst_nonexistent_spring_forward_is_skipped(self):
        with patch("timers.ZoneInfo",side_effect=chicago):
            now=datetime(2027,3,14,7,30,tzinfo=timezone.utc) # Sunday 01:30 CST
            with self.assertRaises(ValueError):
                seconds_to_end_time("02:30",now=now) # Next valid occurrence >16 h away
if __name__=="__main__":unittest.main()
