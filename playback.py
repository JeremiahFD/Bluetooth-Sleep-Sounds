"""Bounded mpv event history keyed by process generation and playlist entry ID."""
from collections import OrderedDict
import threading


class PlaybackEvents:
    def __init__(self):
        self.lock = threading.Lock()
        self.records = OrderedDict()
        self.current = {}
        self.failures = {}

    def record(self, generation, entry, status, message=None):
        if entry is None:
            return
        with self.lock:
            key = (generation, entry)
            previous = self.records.get(key, {})
            if previous.get("status") == "failed":
                return
            self.records[key] = {"status": status, **({"message": message} if message else {})}
            self.records.move_to_end(key)
            while len(self.records) > 64:
                self.records.popitem(last=False)

    def event(self, generation, event):
        kind = event.get("event")
        if kind == "start-file":
            self.current[generation] = event.get("playlist_entry_id")
            self.record(generation, self.current[generation], "starting")
        elif kind in {"file-loaded", "playback-restart"}:
            self.record(generation, self.current.get(generation), "loaded" if kind == "file-loaded" else "started")
        elif kind == "end-file":
            entry = event.get("playlist_entry_id")
            reason = event.get("reason")
            self.record(generation, entry, "failed" if reason == "error" else "completed" if reason == "eof" else "stopped",
                        "Audio could not play: " + str(event.get("file_error", "check the recording and output")) if reason == "error" else None)
            if self.current.get(generation) == entry:
                self.current.pop(generation, None)

    def disconnected(self, generation):
        with self.lock:
            self.failures[generation] = "Audio player event connection was lost."
            # Keep only recent process failures.
            for old in sorted(self.failures)[:-4]:
                del self.failures[old]

    def snapshot(self, receipt):
        with self.lock:
            generation, entry = receipt["generation"], receipt["entry"]
            result = dict(self.records.get((generation, entry), {"status": "starting"}))
            if generation in self.failures:
                return {"status": "failed", "message": self.failures[generation]}
            return result
