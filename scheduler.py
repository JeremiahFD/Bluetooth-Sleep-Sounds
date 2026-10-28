"""One recurring alarm, local calendar scheduling, and atomic occurrence claims."""
from copy import deepcopy
from datetime import datetime, time as wall_time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import threading
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
DEFAULT = {"enabled": False, "time": "07:00", "timezone": "America/Chicago",
           "weekdays": list(range(7)), "track": None, "volume": 50,
           "output": None, "ring_minutes": 10, "loop": True}


class Alarm:
    """Occurrence is claimed on disk before playback; interrupted claims never replay."""
    def __init__(self, path: Path, play, validate, clock_ready, observe=None):
        self.path, self.play, self.validate, self.clock_ready = path, play, validate, clock_ready
        self.lock = threading.RLock()
        self.observe, self.pending = observe, None
        self.state = {"config": deepcopy(DEFAULT), "revision": uuid.uuid4().hex,
                      "configured_at": datetime.now(UTC).isoformat(), "occurrence": None, "result": None, "scheduled_high_water": None}
        if path.exists():
            self.state = json.loads(path.read_text())
            self.state.setdefault("scheduled_high_water", (self.state.get("result") or {}).get("scheduled_utc"))
            if (self.state.get("result") or {}).get("status") in {"claimed", "starting"}:
                self.state["result"]["status"] = "interrupted"
                self._commit(self.state)

    def _commit(self, state):
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w") as stream:
            stream.write(json.dumps(state))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)
        if os.name == "posix":
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        self.state = state

    def configure(self, changes, now=None):
        now = now or datetime.now(UTC)
        with self.lock:
            if not isinstance(changes, dict) or set(changes) - set(DEFAULT):
                raise ValueError("Unknown alarm setting.")
            config = {**self.state["config"], **changes}
            if not isinstance(config["enabled"], bool) or not isinstance(config["loop"], bool):
                raise ValueError("Alarm enabled and loop must be on or off.")
            if not isinstance(config["time"], str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", config["time"]):
                raise ValueError("Alarm time must use HH:MM, for example 07:00.")
            try:
                ZoneInfo(config["timezone"])
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                raise ValueError("Choose a valid timezone, for example America/Chicago.") from None
            days = config["weekdays"]
            if not isinstance(days, list) or not days or len(days) > 7 or any(type(d) is not int or not 0 <= d <= 6 for d in days) or len(set(days)) != len(days):
                raise ValueError("Choose weekdays 0–6 (Monday–Sunday), without duplicates.")
            if type(config["volume"]) is not int or not 1 <= config["volume"] <= 100:
                raise ValueError("Alarm volume must be 1–100.")
            if type(config["ring_minutes"]) is not int or not 1 <= config["ring_minutes"] <= 180:
                raise ValueError("Alarm duration must be 1–180 minutes.")
            if config["enabled"]:
                if not isinstance(config["track"], str):
                    raise ValueError("Choose an alarm audio file.")
                self.validate(config)
            elif config["track"] is not None and not isinstance(config["track"], str):
                raise ValueError("Invalid alarm track.")
            new_state = {"config": config, "revision": uuid.uuid4().hex, "configured_at": now.isoformat(), "occurrence": None, "result": None, "scheduled_high_water": None}
            self._commit(new_state)
            self.pending = None

    def candidates(self, now):
        config = self.state["config"]
        zone = ZoneInfo(config["timezone"])
        local = now.astimezone(zone)
        hour, minute = map(int, config["time"].split(":"))
        configured = datetime.fromisoformat(self.state["configured_at"])
        results = []
        for offset in range(-7, 9):
            date = local.date() + timedelta(days=offset)
            if date.weekday() not in config["weekdays"]:
                continue
            candidate = datetime.combine(date, wall_time(hour, minute), zone).replace(fold=0)
            utc = candidate.astimezone(UTC)
            # Skip nonexistent spring-forward times; fall-back uses the first occurrence.
            if utc.astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
                continue
            high_water = self.state.get("scheduled_high_water")
            if utc >= configured and (not high_water or utc > datetime.fromisoformat(high_water)):
                results.append((utc, f"{self.state['revision']}:{date.isoformat()}"))
        return results

    def status(self, now=None):
        now = now or datetime.now(UTC)
        with self.lock:
            upcoming = []
            if self.state["config"]["enabled"]:
                upcoming = [(instant, identity) for instant, identity in self.candidates(now)
                            if instant > now and identity != self.state["occurrence"]]
            return {**deepcopy(self.state), "next_utc": min(upcoming)[0].isoformat() if upcoming else None,
                    "clock_ready": bool(self.clock_ready()), "late_grace_seconds": 300,
                    "dst_policy": "Skip nonexistent times; first occurrence only for repeated times."}

    def tick(self, now=None):
        now = now or datetime.now(UTC)
        with self.lock:
            if self.pending and self.observe:
                revision, occurrence, receipt = self.pending
                result = self.observe(receipt)
                if revision == self.state["revision"] and occurrence == self.state["occurrence"]:
                    status = result["status"]
                    if status == "loaded":
                        status = "starting"
                    if status != self.state["result"]["status"]:
                        update = deepcopy(self.state)
                        update["result"].update(result, status=status)
                        self._commit(update)
                    if status in {"failed", "completed", "stopped", "superseded"}:
                        self.pending = None
            if not self.state["config"]["enabled"] or not self.clock_ready():
                return
            due = [(instant, identity) for instant, identity in self.candidates(now) if instant <= now]
            if not due:
                return
            instant, identity = max(due)
            if identity == self.state["occurrence"]:
                return
            state = deepcopy(self.state)
            state["occurrence"] = identity
            state["scheduled_high_water"] = instant.isoformat()
            late = (now - instant).total_seconds() > 300
            state["result"] = {"status": "missed" if late else "claimed", "scheduled_utc": instant.isoformat(), "checked_utc": now.isoformat()}
            self._commit(state)
            if late:
                return
            try:
                receipt = self.play(deepcopy(state["config"]))
                state["result"]["status"] = "starting" if self.observe else "started"
                if self.observe:
                    self.pending = (state["revision"], identity, receipt)
            except Exception as error:
                state["result"].update(status="failed", message=str(error)[-300:])
            self._commit(state)
