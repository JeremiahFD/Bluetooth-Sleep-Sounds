"""Cached audio facts and bounded, Pi-local listening counters.

ffprobe reads container headers; it never decodes an entire recording.  These
helpers deliberately know nothing about HTTP or the currently selected UI.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import threading
import time

from persistence import atomic_json


PROBE_FIELDS = (
    "stream=codec_type,codec_name,sample_rate,channels,bits_per_raw_sample,"
    "bits_per_sample,bit_rate:format=duration,bit_rate,format_name"
)


def _number(value, *, positive=False):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or (result <= 0 if positive else result < 0):
        return None
    return result


def parse_probe(result, size_bytes, extension):
    """Return serializable audio facts, leaving unavailable fields as None."""
    streams = result.get("streams") or []
    audio = next((s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"), None)
    if audio is None:
        raise ValueError("This file does not contain an audio stream.")
    container = result.get("format") or {}
    duration = _number(container.get("duration"), positive=True)
    sample_rate = _number(audio.get("sample_rate"), positive=True)
    channels = _number(audio.get("channels"), positive=True)
    bits = _number(audio.get("bits_per_raw_sample"), positive=True) or _number(audio.get("bits_per_sample"), positive=True)
    bitrate = _number(audio.get("bit_rate"), positive=True) or _number(container.get("bit_rate"), positive=True)
    # A bitrate inferred from file size includes headers and artwork, and is
    # misleading for variable-bitrate files. Report it only when ffprobe knows.
    return {
        "duration_seconds": round(duration, 3) if duration is not None else None,
        "format": extension.lstrip(".").upper(),
        "container": str(container.get("format_name") or "").split(",")[0] or None,
        "codec": audio.get("codec_name") or None,
        "bitrate_kbps": round(bitrate / 1000, 1) if bitrate is not None else None,
        "bit_depth_bits": int(bits) if bits is not None else None,
        "sample_rate_hz": int(sample_rate) if sample_rate is not None else None,
        "channels": int(channels) if channels is not None else None,
        "size_bytes": size_bytes,
    }


class TrackCatalog:
    """Use stat identity to invalidate saved header information after replacement."""

    def __init__(self, path, formats, probe=None):
        self.path = Path(path)
        self.formats = formats
        self.lock = threading.RLock()
        self.probe = probe or self._probe
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            self.records = document.get("tracks", {}) if isinstance(document, dict) else {}
            if not isinstance(self.records, dict):
                self.records = {}
        except (OSError, ValueError):
            self.records = {}

    def _probe(self, path):
        suffix = path.suffix.lower()
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file",
             "-f", self.formats[suffix], "-show_entries", PROBE_FIELDS,
             "-of", "json", str(path)], capture_output=True, text=True, timeout=15,
            check=False,
        )
        if result.returncode:
            raise ValueError("Could not read audio details.")
        try:
            return json.loads(result.stdout)
        except ValueError as error:
            raise ValueError("Could not read audio details.") from error

    @staticmethod
    def _identity(path):
        stat = path.stat()
        return {"bytes": stat.st_size, "modified_ns": stat.st_mtime_ns}

    def cached(self, path):
        path = Path(path)
        identity = self._identity(path)
        with self.lock:
            record = self.records.get(path.name)
            if isinstance(record, dict) and record.get("identity") == identity and isinstance(record.get("details"), dict):
                return dict(record["details"])
        return None

    def details(self, path):
        path = Path(path)
        known = self.cached(path)
        if known is not None:
            return known
        identity = self._identity(path)
        return self.remember(path, self.probe(path), identity=identity)

    def remember(self, path, probe_result, *, identity=None):
        """Reuse the validation probe during upload after the file is published."""
        path = Path(path)
        identity = identity or self._identity(path)
        facts = parse_probe(probe_result, identity["bytes"], path.suffix)
        # A file changed during probing: leave it uncached for the next read.
        if self._identity(path) != identity:
            raise ValueError("The audio file changed while reading its details.")
        with self.lock:
            self.records[path.name] = {"identity": identity, "details": facts}
            atomic_json(self.path, {"version": 1, "tracks": self.records})
        return dict(facts)

    def warm(self, paths):
        """Populate old uploads one at a time, off the HTTP request thread."""
        for path in paths:
            try:
                self.details(path)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                continue

    def summary(self, paths):
        duration = 0.0
        known = 0
        count = 0
        for path in paths:
            count += 1
            try:
                facts = self.cached(path)
            except OSError:
                continue
            if facts and facts.get("duration_seconds") is not None:
                duration += facts["duration_seconds"]
                known += 1
        return {"track_count": count, "duration_seconds": round(duration, 3),
                "duration_known_count": known}


class ListeningStats:
    """Count a started play once and accumulate actual unpaused wall time.

    The caller must pass the profile that owned playback at start.  `observe`
    is safe to call every second; writes are limited to one every 30 seconds,
    plus pause/stop.  Sleep gaps are capped to avoid counting hours of silence.
    """

    def __init__(self, path, *, clock=None):
        self.path = Path(path)
        self.clock = clock or time.monotonic
        self.lock = threading.RLock()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            self.records = loaded.get("profiles", {}) if isinstance(loaded, dict) else {}
            if not isinstance(self.records, dict):
                self.records = {}
        except (OSError, ValueError):
            self.records = {}
        self.session = None
        self.active = False
        self.previous = None
        self.dirty = False
        self.last_saved = self.clock()

    def _save(self, now):
        if self.dirty:
            atomic_json(self.path, {"version": 1, "profiles": self.records})
            self.dirty = False
        self.last_saved = now

    def observe(self, *, session, profile, track, playing, paused=False, now=None):
        now = self.clock() if now is None else now
        with self.lock:
            if session != self.session:
                self._save(now)
                self.session = session
                self.active = False
                self.previous = None
            if not playing or paused or not track:
                if self.previous is not None:
                    bucket = self.records[profile][track]
                    bucket["play_time_seconds"] = round(
                        bucket["play_time_seconds"] + max(0.0, min(3.0, now - self.previous)), 3)
                    self.dirty = True
                    self._save(now)
                self.previous = None
                return
            if not self.active:
                bucket = self.records.setdefault(profile, {}).setdefault(track, {"play_count": 0, "play_time_seconds": 0.0})
                bucket["play_count"] += 1
                bucket["last_played_at"] = time.time()
                self.active = True
                self.dirty = True
            if self.previous is not None:
                elapsed = max(0.0, min(3.0, now - self.previous))
                bucket = self.records[profile][track]
                bucket["play_time_seconds"] = round(bucket["play_time_seconds"] + elapsed, 3)
                self.dirty = True
            self.previous = now
            if now - self.last_saved >= 30:
                self._save(now)

    def flush(self):
        with self.lock:
            self._save(self.clock())

    def details(self, track, profile):
        with self.lock:
            own = self.records.get(profile, {}).get(track, {})
            all_records = [items.get(track, {}) for items in self.records.values() if isinstance(items, dict)]
            return {
                "play_count": sum(int(item.get("play_count", 0)) for item in all_records),
                "play_time_seconds": round(sum(float(item.get("play_time_seconds", 0)) for item in all_records), 3),
                "last_played_at": max((float(item.get("last_played_at", 0)) for item in all_records), default=0) or None,
                "profile_play_count": int(own.get("play_count", 0)),
                "profile_play_time_seconds": round(float(own.get("play_time_seconds", 0)), 3),
            }

    def summary(self, profile=None, tracks=None):
        """Aggregate lifetime listens, optionally for one profile/library subset."""
        track_set = set(tracks) if tracks is not None else None
        with self.lock:
            profiles = [self.records.get(profile, {})] if profile is not None else self.records.values()
            plays = 0
            seconds = 0.0
            for items in profiles:
                if not isinstance(items, dict):
                    continue
                for name, item in items.items():
                    if track_set is not None and name not in track_set:
                        continue
                    plays += int(item.get("play_count", 0))
                    seconds += float(item.get("play_time_seconds", 0))
            return {"play_count": plays, "play_time_seconds": round(seconds, 3)}

    def remove_profile(self, profile):
        if profile == "none":
            raise ValueError("The None profile cannot be removed.")
        with self.lock:
            if profile in self.records:
                del self.records[profile]
                self.dirty = True
                self._save(self.clock())
