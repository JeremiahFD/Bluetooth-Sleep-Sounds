import tempfile
import unittest
from pathlib import Path

from track_details import ListeningStats, TrackCatalog, parse_probe


class TrackDetailsTests(unittest.TestCase):
    def test_probe_fields_and_missing_bit_depth(self):
        facts = parse_probe({"streams": [{"codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100", "channels": 2,
                                            "bits_per_sample": 0, "bit_rate": "192000"}],
                             "format": {"format_name": "mp3", "duration": "36000.5"}}, 12345, ".mp3")
        self.assertEqual(facts["duration_seconds"], 36000.5)
        self.assertEqual(facts["bitrate_kbps"], 192.0)
        self.assertEqual(facts["sample_rate_hz"], 44100)
        self.assertIsNone(facts["bit_depth_bits"])

    def test_catalog_reuses_cache_and_invalidates_changed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            audio = folder / "rain.mp3"
            audio.write_bytes(b"first")
            calls = []
            def probe(path):
                calls.append(path)
                return {"streams": [{"codec_type": "audio", "codec_name": "mp3"}], "format": {"duration": "5"}}
            cache = folder / "catalog.json"
            catalog = TrackCatalog(cache, {".mp3": "mp3"}, probe=probe)
            self.assertEqual(catalog.details(audio)["duration_seconds"], 5)
            self.assertEqual(TrackCatalog(cache, {".mp3": "mp3"}, probe=probe).details(audio)["duration_seconds"], 5)
            self.assertEqual(len(calls), 1)
            audio.write_bytes(b"changed bytes")
            self.assertEqual(catalog.details(audio)["size_bytes"], 13)
            self.assertEqual(len(calls), 2)
            self.assertEqual(catalog.summary([audio]), {"track_count": 1, "duration_seconds": 5.0, "duration_known_count": 1})

    def test_listening_counts_only_started_play_and_unpaused_time(self):
        with tempfile.TemporaryDirectory() as directory:
            instant = [0.0]
            stats = ListeningStats(Path(directory) / "stats.json", clock=lambda: instant[0])
            def observe(session, playing, paused=False):
                stats.observe(session=session, profile="none", track="rain.mp3", playing=playing, paused=paused)
            observe(1, False)
            observe(1, True)
            instant[0] = 1.5
            observe(1, True)
            instant[0] = 2.0
            observe(1, True, paused=True)
            instant[0] = 8.0
            observe(1, True)
            instant[0] = 9.0
            observe(1, True)
            observe(2, False)
            actual = stats.details("rain.mp3", "none")
            self.assertEqual(actual["play_count"], 1)
            self.assertEqual(actual["play_time_seconds"], 3.0)
            reread = ListeningStats(Path(directory) / "stats.json", clock=lambda: instant[0])
            self.assertEqual(reread.details("rain.mp3", "none"), actual)

    def test_long_tick_gap_is_bounded_and_profiles_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            stats = ListeningStats(Path(directory) / "stats.json", clock=lambda: 0)
            stats.observe(session=1, profile="p1", track="storm.flac", playing=True, now=0)
            stats.observe(session=1, profile="p1", track="storm.flac", playing=True, now=3600)
            stats.observe(session=2, profile="p2", track="storm.flac", playing=True, now=3601)
            self.assertEqual(stats.details("storm.flac", "p1")["play_time_seconds"], 3)
            self.assertEqual(stats.details("storm.flac", "p2")["play_count"], 2)
            self.assertEqual(stats.details("storm.flac", "p2")["profile_play_count"], 1)
            self.assertEqual(stats.summary(profile="p1", tracks=["storm.flac"])["play_time_seconds"], 3)
            stats.remove_profile("p1")
            self.assertEqual(stats.details("storm.flac", "p2")["play_count"], 1)
            with self.assertRaises(ValueError):
                stats.remove_profile("none")


if __name__ == "__main__":
    unittest.main()
