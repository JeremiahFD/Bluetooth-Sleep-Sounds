"""Small persistent profile catalog. The Pi player and audio output remain shared."""
from __future__ import annotations

import copy
import json
import re
import secrets
import threading
import unicodedata

from persistence import atomic_json
from audio_processing import DEFAULT_AUDIO_SETTINGS


PROFILE_ID = re.compile(r"^[a-f0-9]{16}$")
MAX_PROFILES = 16


def valid_name(value):
    if not isinstance(value, str):
        raise ValueError("Enter a profile name.")
    name = unicodedata.normalize("NFC", value.strip())
    if not name or len(name) > 32 or any(unicodedata.category(char).startswith("C") for char in name):
        raise ValueError("Profile names must have 1–32 printable characters.")
    if name.casefold() == "none":
        raise ValueError("None is reserved for the default profile.")
    return name


class ProfileStore:
    def __init__(self, path, legacy_favorites=()):
        self.path = path
        self.lock = threading.RLock()
        self.state = {"version": 1, "enabled": False, "revision": 0,
                      "profiles": [{"id": "none", "name": "None", "favorites": sorted(set(legacy_favorites)),
                                    "preferences": {}}]}
        self.read_error = False
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self.read_error = True
            return
        # Do not silently replace malformed or newer data with defaults on the next edit.
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("profiles"), list)
                or not isinstance(candidate.get("enabled"), bool)
                or type(candidate.get("revision")) is not int or candidate["revision"] < 0
                or candidate.get("version") != 1):
            self.read_error = True
            return
        ids = set()
        names = set()
        for item in candidate["profiles"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("name"), str):
                self.read_error = True
                return
            pid, name = item["id"], item["name"]
            if pid == "none" and name != "None":
                self.read_error = True
                return
            if (pid != "none" and not PROFILE_ID.fullmatch(pid)) or pid in ids or name.casefold() in names:
                self.read_error = True
                return
            if (not isinstance(item.get("favorites"), list) or not all(isinstance(v, str) for v in item["favorites"])
                    or not isinstance(item.get("preferences"), dict)):
                self.read_error = True
                return
            ids.add(pid)
            names.add(name.casefold())
        if "none" not in ids or len(candidate["profiles"]) > MAX_PROFILES + 1:
            self.read_error = True
            return
        self.state = candidate  # Keep unfamiliar fields for future versions.

    def _commit(self, next_state):
        if self.read_error:
            raise ValueError("Profile data needs repair before it can be changed.")
        next_state["revision"] += 1
        atomic_json(self.path, next_state)
        self.state = next_state

    def resolve(self, requested=None):
        with self.lock:
            if not self.state["enabled"]:
                return "none"
            if requested is None:
                return "none"  # Existing clients continue to use the default profile.
            if not isinstance(requested, str) or not any(item["id"] == requested for item in self.state["profiles"]):
                raise ValueError("That profile is no longer available. Choose another profile.")
            return requested

    def _item(self, profile_id):
        return next(item for item in self.state["profiles"] if item["id"] == profile_id)

    def catalog(self):
        with self.lock:
            return {"enabled": self.state["enabled"], "revision": self.state["revision"],
                    "profiles": [{"id": p["id"], "name": p["name"]} for p in self.state["profiles"]],
                    "read_error": self.read_error}

    def favorites(self, requested=None):
        with self.lock:
            return set(self._item(self.resolve(requested))["favorites"])

    def favorite_names(self, track):
        with self.lock:
            return [p["name"] for p in self.state["profiles"] if track in p["favorites"]]

    def set_favorite(self, requested, track, favorite):
        with self.lock:
            pid = self.resolve(requested)
            next_state = copy.deepcopy(self.state)
            row = next(p for p in next_state["profiles"] if p["id"] == pid)
            values = set(row["favorites"])
            if favorite:
                values.add(track)
            else:
                values.discard(track)
            row["favorites"] = sorted(values)
            self._commit(next_state)
            return pid

    def data(self, requested=None):
        with self.lock:
            row = self._item(self.resolve(requested))
            return {"id": row["id"], "name": row["name"], "preferences": copy.deepcopy(row["preferences"])}

    def update_preferences(self, requested, changes):
        if not isinstance(changes, dict):
            raise ValueError("Profile settings must be an object.")
        if len(json.dumps(changes, ensure_ascii=False)) > 4096:
            raise ValueError("Profile settings are too large.")
        with self.lock:
            pid = self.resolve(requested)
            next_state = copy.deepcopy(self.state)
            row = next(p for p in next_state["profiles"] if p["id"] == pid)
            row["preferences"].update(copy.deepcopy(changes))
            self._commit(next_state)
            return self.data(pid)

    def change(self, action, *, profile=None, name=None, enabled=None):
        with self.lock:
            next_state = copy.deepcopy(self.state)
            rows = next_state["profiles"]
            if action == "enabled":
                if type(enabled) is not bool:
                    raise ValueError("Profiles must be on or off.")
                next_state["enabled"] = enabled
            elif action == "add":
                label = valid_name(name)
                if len(rows) >= MAX_PROFILES + 1:
                    raise ValueError("Maximum 16 named profiles.")
                if any(p["name"].casefold() == label.casefold() for p in rows):
                    raise ValueError("That profile name already exists.")
                pid = secrets.token_hex(8)
                while any(p["id"] == pid for p in rows):
                    pid = secrets.token_hex(8)
                rows.append({"id": pid, "name": label, "favorites": [],
                             "preferences": {"volume": 35, "play_mode": "once", "sleep_minutes": 60,
                                             "normalization": False, "audio_processing": dict(DEFAULT_AUDIO_SETTINGS),
                                             "audio_processing_revision": 0}})
            elif action in {"rename", "delete"}:
                if profile == "none":
                    raise ValueError("The None profile cannot be edited or removed.")
                row = next((p for p in rows if p["id"] == profile), None)
                if row is None:
                    raise ValueError("That profile is no longer available.")
                if action == "delete":
                    rows.remove(row)
                else:
                    label = valid_name(name)
                    if any(p is not row and p["name"].casefold() == label.casefold() for p in rows):
                        raise ValueError("That profile name already exists.")
                    row["name"] = label
            else:
                raise ValueError("Unknown profile action.")
            self._commit(next_state)
            return self.catalog()
