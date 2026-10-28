"""Small LAN controller. Audio and timers run on the Raspberry Pi, not the phone."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit
import uuid
from scheduler import Alarm
from audio_processing import apply_normalization, audio_filter_graph, validate_audio_settings, DEFAULT_AUDIO_SETTINGS, NUMERIC_RANGES, GainMeter
from persistence import atomic_json
from profiles import ProfileStore
from library_discovery import DiscoveryStore
from system_status import system_snapshot
from remote_controls import RemoteStore, CURRENT_TRACK
from remote_input import RemoteManager
from audio_presets import AudioPresetStore
from speaker_sync import snapshot as speaker_sync_snapshot, read_sync, save_sync, apply_sync
from audio_output import normalize_selected_bluetooth_volume, COMBINED_OUTPUT, COMBINED_BLUETOOTH_ADDRESS, COMBINED_BT, COMBINED_WIRED, validate_combined_devices
from bluetooth_adapter import execute as selected_bluetooth_command
from bluetooth_adapter import validate_output as validate_selected_bluetooth_output
from track_details import TrackCatalog, ListeningStats, PROBE_FIELDS
from timers import seconds_to_end_time, MAX_SLEEP_MINUTES
import random
from playback import PlaybackEvents

ROOT = Path(__file__).resolve().parent
FORMATS = {".mp3": "mp3", ".wav": "wav", ".flac": "flac", ".ogg": "ogg", ".opus": "ogg", ".m4a": "mov", ".aac": "aac", ".mp4": "mov", ".webm": "matroska", ".mka": "matroska", ".wma": "asf", ".aif": "aiff", ".aiff": "aiff", ".caf": "caf", ".ac3": "ac3"}
AUDIO_EXTENSIONS = set(FORMATS)
GIB = 1024 ** 3
MIB = 1024 ** 2
DEFAULT_MAX_UPLOAD = 5 * GIB
MAX_UPLOAD_CAP = 50 * GIB
DEFAULT_STORAGE_RESERVE_MB = 256
MAX_ARTWORK_BYTES = 8 * MIB
ARTWORK_CODECS = {".jpg": "mjpeg", ".jpeg": "mjpeg", ".png": "png", ".webp": "webp"}
MAC = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")
LOG = logging.getLogger("sleep-sounds")


def run(args, timeout=15):
    adapter = os.environ.get("SLEEP_SOUNDS_BLUETOOTH_ADAPTER", "").strip()
    if args and args[0] == "bluetoothctl" and adapter:
        return selected_bluetooth_command(adapter, args[1:], timeout)
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "Command failed")[-600:].strip())
    return result.stdout


class Player:
    def __init__(self, runtime):
        self.path = runtime / "player.sock"
        self.audio_buffer_seconds = 0.5
        self.process = None
        self.lock = threading.RLock()
        self.error = None
        self.generation = 0
        self.history = PlaybackEvents()
        self.event_ready = threading.Event()

    def start(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                if self.error:
                    raise RuntimeError(self.error)
                else:
                    return
            self.path.unlink(missing_ok=True)
            self.generation += 1
            self.error = None
            self.event_ready.clear()
            self.process = subprocess.Popen([
                "mpv", "--no-config", "--idle=yes", "--no-video", "--no-terminal",
                "--no-input-default-bindings", "--input-terminal=no", "--volume=35",
                "--audio-client-name=Sleep Sounds", "--loop-file=inf",
                f"--audio-buffer={self.audio_buffer_seconds:g}",
                "--load-scripts=no", "--autoload-files=no", "--access-references=no",
                "--demuxer-max-bytes=8MiB", "--demuxer-max-back-bytes=1MiB",
                f"--input-ipc-server={self.path}",
            ], stdin=subprocess.DEVNULL)
            for _ in range(60):
                if self.path.exists():
                    threading.Thread(target=self.events, args=(self.generation,), daemon=True, name="sleep-sounds-player-events").start()
                    if not self.event_ready.wait(3):
                        self.close()
                        raise RuntimeError("Audio player event listener did not become ready.")
                    return
                if self.process.poll() is not None:
                    raise RuntimeError("Audio player could not start. Check the service log.")
                time.sleep(0.05)
            raise RuntimeError("Audio player did not become ready.")

    def events(self, generation):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(str(self.path))
                connection.sendall(b'{"command":["get_property","idle-active"],"request_id":0}\n')
                with connection.makefile("rb") as stream:
                    for line in stream:
                        if generation != self.generation:
                            return
                        event = json.loads(line)
                        if event.get("request_id") == 0 and event.get("error") == "success":
                            self.event_ready.set()
                        self.history.event(generation, event)
        except (OSError, ValueError):
            pass
        finally:
            if generation == self.generation:
                self.history.disconnected(generation)
                self.error = "Audio player disconnected. Select an output and press Play to retry."

    def load(self, path):
        with self.lock:
            result = self.command("loadfile", str(path), "replace")
            if not isinstance(result, dict) or "playlist_entry_id" not in result:
                raise RuntimeError("Audio player did not provide a playback receipt.")
            return {"generation": self.generation, "entry": result["playlist_entry_id"]}

    def prepare(self):
        """Recover only before a whole playback transaction, never midway through controls."""
        with self.lock:
            if self.error or (self.process and self.process.poll() is not None):
                self.close()
            self.start()

    def playback_status(self, receipt):
        return self.history.snapshot(receipt)

    def command(self, *args):
        with self.lock:
            if not self.process or self.process.poll() is not None or self.error:
                raise RuntimeError(self.error or "Audio player is unavailable. Press Play to retry.")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(1)
                connection.connect(str(self.path))
                connection.sendall(json.dumps({"command": args, "request_id": 1}).encode() + b"\n")
                with connection.makefile("rb") as stream:
                    for line in stream:
                        reply = json.loads(line)
                        if reply.get("request_id") == 1:
                            if reply.get("error") != "success":
                                raise RuntimeError(f"Player: {reply.get('error', 'unknown error')}")
                            return reply.get("data")
            raise RuntimeError("Audio player closed the connection.")

    def get(self, name, fallback=None):
        try:
            return self.command("get_property", name)
        except RuntimeError:
            return fallback

    def close(self):
        with self.lock:
            self.generation += 1
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.path.unlink(missing_ok=True)


class Controller:
    def __init__(self, data, player):
        self.data = data
        self.tracks = data / "tracks"
        self.tracks.mkdir(parents=True, exist_ok=True)
        self.artwork_dir = data / "artwork"
        self.artwork_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        for abandoned in self.tracks.glob("*.upload"):
            if re.fullmatch(r"[0-9a-f]{32}\.upload", abandoned.name) and not abandoned.is_symlink() and time.time() - abandoned.stat().st_mtime > 86400:
                abandoned.unlink()
        self.player = player
        self.lock = threading.RLock()
        self.upload_lock = threading.Lock()
        self.timer_lock = threading.Lock()
        self.persistence_lock = threading.RLock()
        self.library_revision = 0
        self.allow_track_deletion = False
        self.normalization = False
        self.audio_buffer_seconds = 0.5
        self.audio_processing = dict(DEFAULT_AUDIO_SETTINGS)
        self.audio_processing_revision = 0
        self.audio_edit_lock_enabled = False
        self.audio_edit_lock_timeout = 120
        self._audio_editor = None
        self._audio_editor_profile = None
        self._audio_editor_deadline = 0
        self.audio_presets = AudioPresetStore(data / "audio-presets.json")
        self.favorites = set()
        try:
            favorites = json.loads((data / "favorites.json").read_text(encoding="utf-8"))
            if isinstance(favorites, list):
                self.favorites = {name for name in favorites if isinstance(name,str)}
        except (OSError, ValueError):
            pass
        self.profiles = ProfileStore(data / "profiles.json", self.favorites)
        try:
            identity = json.loads((data / 'host-identity.json').read_text(encoding='utf-8'))
            value = identity.get('id')
            self.host_id = value if isinstance(value, str) and re.fullmatch('[a-f0-9]{32}', value) else None
        except FileNotFoundError:
            self.host_id = secrets.token_hex(16)
            atomic_json(data / 'host-identity.json', {'version': 1, 'id': self.host_id})
        except (OSError, ValueError, AttributeError):
            self.host_id = None  # Do not overwrite a damaged identity or silently trust another host.
        self.discovery = DiscoveryStore(data / "library.json")
        self.remote_store = RemoteStore(data / "remotes.json")
        self.remote_manager = RemoteManager(self.remote_store, self.remote_action)
        if self.profiles.read_error:
            LOG.warning("Profile data needs repair; existing file was left untouched")
        self.favorites = self.profiles.favorites("none")
        self.active_profile_id = "none"
        self.stats_suppressed_session = None
        self.catalog = TrackCatalog(data / "track-details.json", FORMATS)
        self.listening_stats = ListeningStats(data / "listening-stats.json")
        self._stats_warning_logged = False
        self.transition_lock = threading.RLock()
        self.session = 0
        self.timer_session = 0
        self.deadline = None
        self.selected = None
        self.last_played_track = None
        self.loop = False
        self.play_mode = "once"
        self.volume = 35
        self.output = None
        self.speaker = None
        self.auto_reconnect = True
        self.reconnect_suppressed = False
        self.reconnect_retry_minutes = 10
        self.reconnect_expires_at = None
        self.resume_after_restart = False
        self.resume_pending = None
        self.resume_last_saved = -60.0
        self.reconnect_next = 0.0
        self.reconnect_delay = 8.0
        self.reconnect_message = ""
        self.pairing_target = None
        self.pairing_agent = None
        self.bluetooth_route_lock = threading.Lock()
        self.bluetooth_route_cache = None
        self.playback_error = None
        self.active_output = None
        self.mode = "idle"
        self.receipt = None
        self.finished = {}
        self.sleep_minutes = 60
        self.max_upload_bytes = DEFAULT_MAX_UPLOAD
        self.storage_reserve_mb = DEFAULT_STORAGE_RESERVE_MB
        self._clock = {"ready": False, "checked": -1000}
        self.token = secrets.token_urlsafe(32)
        self.closed = threading.Event()
        self.bt = {"busy": False, "message": "Put your speaker in pairing mode, then search.", "devices": []}
        self.power = {"checked": 0, "undervoltage": None, "throttled": None}
        self.gain_meter = GainMeter(self)
        try:
            settings = json.loads((data / "settings.json").read_text())
            previous_track = settings.get('last_played_track')
            if isinstance(previous_track, str) and Path(previous_track).name == previous_track and '/' not in previous_track and '\\' not in previous_track:
                self.last_played_track = previous_track
            self.loop = bool(settings["loop"])
            saved_mode = settings.get("play_mode", "loop" if self.loop else "once")
            self.play_mode = saved_mode if saved_mode in {"once", "loop", "next", "shuffle"} else "once"
            self.loop = self.play_mode == "loop"
            self.volume = min(100, max(0, int(settings["volume"])))
            self.output = settings.get("output")
            self.speaker = settings.get("speaker")
            self.auto_reconnect = settings.get("auto_reconnect", True) is True
            self.reconnect_suppressed = settings.get("reconnect_suppressed", False) is True
            self.resume_after_restart = settings.get("resume_after_restart", False) is True
            buffer_seconds = settings.get("audio_buffer_seconds", 0.5)
            if type(buffer_seconds) in (int, float) and math.isfinite(buffer_seconds) and 0.1 <= buffer_seconds <= 2.0:
                self.audio_buffer_seconds = float(buffer_seconds)
            self.allow_track_deletion = settings.get("allow_track_deletion", False) is True
            self.audio_edit_lock_enabled = settings.get("audio_edit_lock_enabled", False) is True
            timeout = settings.get("audio_edit_lock_timeout", 120)
            if type(timeout) is int and 15 <= timeout <= 3600:
                self.audio_edit_lock_timeout = timeout
            self.normalization = settings.get("normalization", False) is True
            try:
                self.audio_processing = validate_audio_settings(settings.get("audio_processing", {}))
                revision = settings.get("audio_processing_revision", 0)
                self.audio_processing_revision = revision if type(revision) is int and revision >= 0 else 0
            except (ValueError, TypeError):
                self.audio_processing = dict(DEFAULT_AUDIO_SETTINGS)
            retry = settings.get("reconnect_retry_minutes", 10)
            if type(retry) is int and 1 <= retry <= 1440:
                self.reconnect_retry_minutes = retry
            expiry = settings.get("reconnect_expires_at")
            if type(expiry) in (int, float) and math.isfinite(expiry) and expiry > 0:
                self.reconnect_expires_at = float(expiry)
            self.sleep_minutes = min(MAX_SLEEP_MINUTES, max(1, int(settings.get("sleep_minutes", 60))))
            candidate_limit = settings.get("max_upload_bytes", DEFAULT_MAX_UPLOAD)
            if type(candidate_limit) is int and MIB <= candidate_limit <= MAX_UPLOAD_CAP:
                self.max_upload_bytes = candidate_limit
            candidate_reserve = settings.get("storage_reserve_mb", DEFAULT_STORAGE_RESERVE_MB)
            if type(candidate_reserve) is int and 0 <= candidate_reserve <= 10240:
                self.storage_reserve_mb = candidate_reserve
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.player.audio_buffer_seconds = self.audio_buffer_seconds
        default_preferences = {"volume": self.volume, "play_mode": self.play_mode,
            "sleep_minutes": self.sleep_minutes, "normalization": self.normalization,
            "audio_processing": dict(self.audio_processing),
            "audio_processing_revision": self.audio_processing_revision}
        existing_preferences = self.profiles.data("none")["preferences"]
        missing_preferences = {key: value for key, value in default_preferences.items()
                               if key not in existing_preferences}
        if missing_preferences and not self.profiles.read_error:
            self.profiles.update_preferences("none", missing_preferences)
        if self.resume_after_restart and not self.reconnect_suppressed:
            try:
                candidate = json.loads((self.data / "resume.json").read_text())
                elapsed = time.time() - candidate["updated"]
                expires = candidate.get("timer_end")
                if (type(candidate.get("updated")) in (int,float)
                        and type(candidate.get("position")) in (int,float)
                        and math.isfinite(candidate["updated"]) and math.isfinite(candidate["position"])
                        and candidate["position"] >= 0
                        and 0 <= elapsed <= 300
                        and candidate.get("mode") in ("normal","sleep")
                        and type(candidate.get("paused")) is bool
                        and not candidate["paused"]
                        and (expires is None or (type(expires) in (int,float) and math.isfinite(expires) and expires > time.time()))
                        and self.track(candidate.get("track"))):
                    self.resume_pending = candidate
            except (OSError, ValueError, KeyError, TypeError):
                pass
        self.alarm = Alarm(data / "alarm.json", self.run_alarm, self.validate_alarm, lambda: self._clock["ready"], self.playback_status)

    def save(self):
        with self.persistence_lock:
            fields=("loop","play_mode","volume","output","speaker","auto_reconnect",
                    "reconnect_suppressed","reconnect_retry_minutes","reconnect_expires_at",
                    "resume_after_restart","normalization","audio_processing","audio_processing_revision",
                    "audio_edit_lock_enabled","audio_edit_lock_timeout","audio_buffer_seconds",
                    "sleep_minutes","max_upload_bytes","storage_reserve_mb","allow_track_deletion","last_played_track")
            atomic_json(self.data / "settings.json", {name:getattr(self,name) for name in fields})

    def clear_resume(self):
        self.resume_pending = None
        (self.data / "resume.json").unlink(missing_ok=True)

    def persist_resume(self):
        if not self.resume_after_restart or self.mode not in ("normal","sleep") or not self.selected:
            return
        if self.player.get("idle-active",True):return
        if self.player.get("pause",False):
            self.clear_resume()
            return
        now=time.monotonic()
        if now-self.resume_last_saved<15:return
        with self.transition_lock:
            time_left=self.deadline-now if self.deadline is not None else None
            if time_left is not None and time_left<=0:return
            position=float(self.player.get("time-pos",0) or 0)
            if not math.isfinite(position):return
            state={"track":self.selected,"mode":self.mode,"position":max(0,position),
                   "updated":time.time(),"paused":False,
                   "timer_end":time.time()+time_left if time_left is not None else None,
                   "output":self.active_output}
            atomic_json(self.data/"resume.json",state)
            self.resume_last_saved=now

    def try_resume(self):
        candidate=self.resume_pending
        if not candidate:
            return
        elapsed=time.time()-candidate["updated"]
        until=candidate.get("timer_end")
        if (not self.resume_after_restart or self.reconnect_suppressed or not 0 <= elapsed <= 300
                or (until is not None and until <= time.time())):
            self.clear_resume()
            return
        if candidate.get("output") and candidate["output"] != self.output:
            self.clear_resume()
            return
        # Do not redirect audio or play after the physical speaker is switched off.
        if self.speaker and not any(self.speaker.replace(":","_").lower() in d["name"].lower()
                                    for d in self.player.get("audio-device-list",[])):
            return
        try:
            self.play(candidate["track"],mode=candidate["mode"])
            if until is not None:
                remaining=until-time.time()
                if remaining <= 1:
                    self.stop()
                    return
                self.set_timer(remaining/60)
            position=max(0,float(candidate.get("position",0)))
            if position>0:
                try:
                    self.player.command("seek",position,"absolute")
                except (OSError, RuntimeError, subprocess.TimeoutExpired):
                    LOG.info("Resume seek failed; playback begins at beginning")
            self.resume_pending=None
            self.resume_last_saved=0
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            return

    def upload_result(self, key):
        if not isinstance(key,str) or not re.fullmatch(r"[a-f0-9]{32}",key):
            raise ValueError("Invalid upload receipt.")
        path=self.data/"upload-receipts"/(key+".json")
        try:record=json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:return {"complete":False}
        candidate=self.tracks/record["id"]
        valid=candidate.parent==self.tracks and not candidate.is_symlink() and candidate.is_file()
        return {"complete":bool(valid and candidate.stat().st_size==record["size"]),**record}

    def effective_profile_id(self, requested=None):
        return self.profiles.resolve(requested)

    def profile_edit_is_inactive(self, requested=None):
        return (self.mode in ("normal", "sleep") and not self.player.get("idle-active", True)
                and self.effective_profile_id(requested) != self.active_profile_id)

    def favorited_by(self, track):
        return self.profiles.favorite_names(track)

    def remember_profile_preferences(self, profile, changes):
        if not self.profiles.read_error:
            self.profiles.update_preferences(profile, changes)

    def observe_listening(self, *, playing=False, paused=False):
        # Counters are ancillary; an SD write problem must not stop the player.
        if playing and self.stats_suppressed_session == self.session:
            return
        try:
            self.listening_stats.observe(session=self.session, profile=self.active_profile_id,
                track=self.selected, playing=playing, paused=paused)
            self._stats_warning_logged = False
        except (OSError, ValueError, KeyError):
            if not self._stats_warning_logged:
                LOG.warning("Listening counters could not be saved; playback continues")
                self._stats_warning_logged = True

    def set_favorite(self, track, favorite, profile=None):
        if type(favorite) is not bool:raise ValueError("Favorite must be on or off.")
        if self.profiles.read_error:raise ValueError("Profile data needs repair before favorites can be changed.")
        self.track(track)
        with self.persistence_lock:
            pid = self.effective_profile_id(profile)
            if pid == "none":
                new = set(self.favorites)
                if favorite:new.add(track)
                else:new.discard(track)
                # Keep the previous format as a readable backup of the default profile.
                atomic_json(self.data / "favorites.json", sorted(new))
            self.profiles.set_favorite(pid, track, favorite)
            if pid == "none":
                self.favorites = new
            self.library_revision+=1
        return {"track":track,"favorite":favorite,"profile":pid}

    def set_audio_buffer(self, seconds, editor_session=None, profile=None):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0.1 <= seconds <= 2.0:
            raise ValueError("Playback buffer must be between 0.1 and 2.0 seconds.")
        with self.transition_lock:
            self.check_audio_editor(editor_session, profile)
            previous = self.audio_buffer_seconds
            if seconds == previous:
                return
            try:
                self.player.command('set_property', 'audio-buffer', float(seconds))
                self.audio_buffer_seconds = float(seconds)
                self.player.audio_buffer_seconds = float(seconds)
                self.save()
            except Exception:
                self.audio_buffer_seconds = previous
                self.player.audio_buffer_seconds = previous
                try:
                    self.player.command('set_property', 'audio-buffer', previous)
                except Exception:
                    pass
                raise

    def audio_settings_snapshot(self):
        with self.transition_lock:
            return {"settings": dict(self.audio_processing), "audio_processing": dict(self.audio_processing),
                "revision": self.audio_processing_revision, "audio_processing_revision": self.audio_processing_revision,
                "normalization": self.normalization}

    def audio_edit_lock_status(self, editor_session=None):
        with self.transition_lock:
            remaining = max(0, self._audio_editor_deadline - time.monotonic())
            locked = self.audio_edit_lock_enabled and self._audio_editor is not None and remaining > 0
            return {"enabled": self.audio_edit_lock_enabled,
                "timeout_seconds": self.audio_edit_lock_timeout, "locked": locked,
                "owned": bool(locked and editor_session == self._audio_editor),
                "owner_profile": self._audio_editor_profile if locked else None,
                "remaining_seconds": math.ceil(remaining) if locked else 0}

    def check_audio_editor(self, editor_session=None, profile=None):
        # Caller holds transition_lock. Leases are process-local and never survive a restart.
        if not self.audio_edit_lock_enabled:
            return
        if not isinstance(editor_session, str) or not 8 <= len(editor_session) <= 128:
            raise ValueError("This device needs a fresh editing session. Reload the page.")
        state = self.audio_edit_lock_status(editor_session)
        if state["locked"] and not state["owned"]:
            raise ValueError("Audio controls are being edited on another device. Wait for its inactivity timeout or turn off the edit lock.")
        self._audio_editor = editor_session
        self._audio_editor_profile = self.effective_profile_id(profile)
        self._audio_editor_deadline = time.monotonic() + self.audio_edit_lock_timeout

    def change_audio_edit_lock(self, values):
        with self.transition_lock:
            action = values.get("action")
            if action == "configure":
                enabled = values.get("enabled", self.audio_edit_lock_enabled)
                timeout = values.get("timeout_seconds", self.audio_edit_lock_timeout)
                if type(enabled) is not bool or type(timeout) is not int or not 15 <= timeout <= 3600:
                    raise ValueError("Edit lock needs an on/off setting and a timeout of 15-3600 seconds.")
                previous = self.audio_edit_lock_enabled, self.audio_edit_lock_timeout
                self.audio_edit_lock_enabled, self.audio_edit_lock_timeout = enabled, timeout
                try:
                    self.save()
                except Exception:
                    self.audio_edit_lock_enabled, self.audio_edit_lock_timeout = previous
                    raise
                # Configuration is always accessible so no abandoned client can lock everyone out.
                self._audio_editor = None
                self._audio_editor_profile = None
                self._audio_editor_deadline = 0
            elif action == "release":
                if self.audio_edit_lock_status(values.get("editor_session"))["owned"]:
                    self._audio_editor = None
                    self._audio_editor_profile = None
                    self._audio_editor_deadline = 0
            else:
                raise ValueError("Choose configure or release for the audio edit lock.")
            return self.audio_edit_lock_status(values.get("editor_session"))

    def remember_current_audio_preferences(self, profile):
        # An explicit no-op still saves this listener's choice. Otherwise stale
        # per-profile defaults can revive an effect on the next explicit Play.
        # Do not rewrite other listeners or touch unknown preference fields.
        changes = {"normalization": self.normalization,
            "audio_processing": dict(self.audio_processing),
            "audio_processing_revision": self.audio_processing_revision}
        preferences = self.profiles.data(profile)["preferences"]
        if any(preferences.get(key) != value for key, value in changes.items()):
            self.remember_profile_preferences(profile, changes)

    def set_normalization(self, enabled, profile=None, editor_session=None):
        if type(enabled) is not bool:raise ValueError("Normalization must be on or off.")
        with self.transition_lock:
            if self.mode=="alarm":raise ValueError("Dismiss the alarm before changing normalization.")
            profile = self.effective_profile_id(profile)
            self.check_audio_editor(editor_session, profile)
            previous, previous_audio, previous_revision = self.normalization, dict(self.audio_processing), self.audio_processing_revision
            candidate = {**self.audio_processing, "bypass": True} if enabled else dict(self.audio_processing)
            if enabled == previous and candidate == previous_audio:
                self.remember_current_audio_preferences(profile)
                return
            try:
                apply_normalization(self.player,enabled,candidate, meter=self.gain_meter.active)
                self.normalization=enabled
                self.audio_processing = candidate
                self.audio_processing_revision += 1
                self.save()
                self.remember_profile_preferences(profile, {"normalization": enabled,
                    "audio_processing": dict(self.audio_processing),
                    "audio_processing_revision": self.audio_processing_revision})
            except Exception:
                self.normalization, self.audio_processing, self.audio_processing_revision = previous, previous_audio, previous_revision
                try:apply_normalization(self.player,previous,previous_audio, meter=self.gain_meter.active)
                except Exception:self.stop(failure="Audio processing could not be restored.")
                raise

    def set_audio_processing(self, values, expected_revision=None, profile=None, editor_session=None):
        # Do not restart playback, alter the timer or set hardware/app output volume.
        with self.transition_lock:
            if self.mode == "alarm":
                raise ValueError("Dismiss the alarm before changing audio processing.")
            profile = self.effective_profile_id(profile)
            candidate = validate_audio_settings(values, self.audio_processing)
            self.check_audio_editor(editor_session, profile)
            if expected_revision is not None and (type(expected_revision) is not int or expected_revision != self.audio_processing_revision):
                raise ValueError("Audio settings changed on another device. Reload the settings before applying.")
            mode_fields = set(values) - {k for k in DEFAULT_AUDIO_SETTINGS if k.startswith('noise') or k.startswith('normalization_')}
            normalization = False if mode_fields and not candidate["bypass"] else self.normalization
            if candidate == self.audio_processing and normalization == self.normalization:
                self.remember_current_audio_preferences(profile)
                return
            previous, revision, previous_normalization = dict(self.audio_processing), self.audio_processing_revision, self.normalization
            filter_changed = (audio_filter_graph(previous, previous_normalization, self.gain_meter.active)
                              != audio_filter_graph(candidate, normalization, self.gain_meter.active))
            try:
                if filter_changed:
                    apply_normalization(self.player, normalization, candidate, meter=self.gain_meter.active)
                self.audio_processing = candidate
                self.normalization = normalization
                self.audio_processing_revision += 1
                self.save()
                self.remember_profile_preferences(profile, {"normalization": normalization,
                    "audio_processing": dict(candidate),
                    "audio_processing_revision": self.audio_processing_revision})
            except Exception:
                self.audio_processing, self.audio_processing_revision, self.normalization = previous, revision, previous_normalization
                if filter_changed:
                    try:
                        apply_normalization(self.player, previous_normalization, previous, meter=self.gain_meter.active)
                    except Exception:
                        self.stop(failure="Audio processing could not be restored.")
                raise

    def previous(self):
        with self.transition_lock:
            if self.mode=="alarm":raise ValueError("Previous is disabled during alarms.")
            ids=[f["id"] for f in self.library()]
            if not ids:raise ValueError("Add an audio file first.")
            index=ids.index(self.selected) if self.selected in ids else 0
            mode=self.mode if self.mode in ("normal","sleep") else "normal"
            self.play(ids[(index-1)%len(ids)], mode=mode, preserve_pause=True)

    def select_library_track(self, name, profile=None, start_paused=False):
        """Select without autoplay, or explicitly prime a paused session from idle."""
        if type(start_paused) is not bool:
            raise ValueError("Paused preparation must be on or off.")
        with self.transition_lock:
            self.track(name)
            if self.mode == "alarm":
                raise ValueError("Dismiss the alarm before choosing another track.")
            if self.player.get("idle-active", True):
                if start_paused:
                    self.play(name, profile=profile, start_paused=True)
                else:
                    self.selected = name
                return
            mode = self.mode if self.mode in ("normal", "sleep") else "normal"
            self.play(name, mode=mode, profile=profile, preserve_pause=True)

    def set_paused(self, paused=None):
        with self.transition_lock:
            if self.player.get("idle-active",True):raise ValueError("No audio file is playing.")
            if self.active_output not in [d["name"] for d in self.player.get("audio-device-list",[])]:
                raise ValueError("The playing audio output is unavailable.")
            if paused is None:paused=not self.player.get("pause",False)
            if type(paused) is not bool:raise ValueError("Paused must be on or off.")
            if not paused:
                self.validate_bluetooth_output(self.active_output, force=True)
            if paused:
                self.observe_listening(playing=False)
            self.player.command("set_property","pause",paused)
            if paused:self.clear_resume()
            else:
                self.resume_last_saved=-60
                self.persist_resume()

    def seek(self, seconds):
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0:
            raise ValueError("Choose a valid position.")
        with self.transition_lock:
            if self.mode=="alarm" or self.player.get("idle-active",True):raise ValueError("Seek is unavailable.")
            duration=self.player.get("duration",0) or 0
            if not duration or seconds>duration:raise ValueError("Position is outside the audio file.")
            self.player.command("seek",seconds,"absolute")

    def artwork_path(self, track_name):
        self.track(track_name)  # Must be an existing, validated library recording.
        key = hashlib.sha256(track_name.encode("utf-8")).hexdigest()
        for suffix in (".jpg", ".png", ".webp"):
            path = self.artwork_dir / (key + suffix)
            if path.is_file() and not path.is_symlink():
                return path
        return None

    def artwork_url(self, track_name):
        path = self.artwork_path(track_name)
        return ("/api/artwork?track=" + quote(track_name, safe="") + "&v=" +
                str(path.stat().st_mtime_ns)) if path else None

    def library(self, profile=None):
        pid = self.effective_profile_id(profile)
        favorites = self.profiles.favorites(pid)
        profiles = self.profiles.catalog()['profiles']
        rows = []
        for f in sorted(self.tracks.iterdir(), key=lambda f: f.name.lower()):
            if not f.is_file() or f.is_symlink() or f.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            facts = self.catalog.cached(f) or {}
            info = self.discovery.metadata(f.name)
            stats = self.listening_stats.details(f.name, pid)
            rows.append({"id": f.name, "name": info.get('title') or f.stem.replace("_", " "),
                "bytes": f.stat().st_size, "artwork": self.artwork_url(f.name), "favorite": f.name in favorites,
                "favorited_by": self.favorited_by(f.name), 'metadata': info, **facts,
                **stats, **self.discovery.ratings(f.name, profiles, pid)})
        return rows

    def public_profile(self, profile):
        profiles = self.profiles.catalog()['profiles']
        row = next((p for p in profiles if p['id'] == profile), None)
        if row is None:
            raise ValueError('That profile is no longer available.')
        # Browsing is independent from active/default profile resolution, even when profiles are off.
        with self.profiles.lock:
            favorites = set(self.profiles._item(profile)['favorites'])
        tracks = self.library('none')
        ratings = {t['id']: self.discovery.ratings(t['id'], profiles, profile)['my_rating'] for t in tracks}
        return {**row, 'favorites': [t for t in tracks if t['id'] in favorites],
            'ratings': [{'id': t['id'], 'name': t['name'], 'rating': ratings[t['id']]} for t in tracks if ratings[t['id']]],
            'stats': self.listening_stats.summary(profile, [t['id'] for t in tracks])}

    def track_details(self, track, profile=None):
        path = self.track(track)
        pid = self.effective_profile_id(profile)
        return {"audio": self.catalog.details(path), "stats": self.listening_stats.details(path.name, pid),
                "favorited_by": self.favorited_by(path.name), "metadata": self.discovery.metadata(path.name),
                **self.discovery.ratings(path.name, self.profiles.catalog()["profiles"], pid)}

    def library_summary(self, profile=None):
        pid = self.effective_profile_id(profile)
        paths = [self.tracks / row["id"] for row in self.library(pid)]
        return {**self.catalog.summary(paths),
                **self.listening_stats.summary(profile=pid, tracks=[path.name for path in paths])}

    def track(self, name):
        if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Choose a track from the library.")
        path = self.tracks / name
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError("That track is no longer available.")
        return path

    def delete_track(self, name, confirm=False):
        """Delete only an explicitly selected local recording; preserve historical data."""
        # Alarm callbacks acquire transition_lock while holding alarm.lock.
        with self.upload_lock, self.alarm.lock, self.transition_lock, self.remote_store.lock, self.persistence_lock:
            if not self.allow_track_deletion:
                raise ValueError("Track deletion is disabled in Settings.")
            if confirm is not True:
                raise ValueError("Confirm deleting this recording.")
            path = self.track(name)
            if self.selected == name and not self.player.get('idle-active', True):
                raise ValueError("Stop this track before deleting it.")
            if self.alarm.state['config'].get('track') == name:
                raise ValueError("Choose another alarm track before deleting this recording.")
            if any(r.get('default_track') == name for r in self.remote_store.state['remotes']):
                raise ValueError("Choose another default sound in the controller profiles first.")
            # Resolve the exact associated artwork before deleting the recording.
            artwork = self.artwork_path(name)
            path.unlink()
            warning = None
            if artwork:
                try:
                    artwork.unlink(missing_ok=True)
                except OSError:
                    LOG.warning("Deleted track artwork could not be removed")
                    warning = "Audio deleted; its thumbnail could not be removed."
            if self.selected == name:
                self.selected = None
                try:
                    self.clear_resume()
                except OSError:
                    warning = "Audio deleted; its saved resume information could not be cleared."
            if self.last_played_track == name:
                self.last_played_track = None
                try:
                    self.save()
                except OSError:
                    warning = "Audio deleted; its saved last-played setting could not be cleared."
            self.library_revision += 1
            return {'deleted': name, 'warning': warning, 'history_retained': True}

    def play(self, name, *, volume=None, loop=None, output=None, mode="normal", profile=None, preserve_pause=False, start_paused=False):
        with self.transition_lock, self.player.lock:
            path = self.track(name)
            # Capture pause while holding the transition lock; pause *before* loading.
            keep_paused = bool(start_paused or (preserve_pause and not self.player.get("idle-active", True)
                               and self.player.get("pause", False)))
            previous_processing = dict(self.audio_processing)
            previous_normalization = self.normalization
            if profile is not None and mode != "alarm":
                profile_id = self.effective_profile_id(profile)
                prefs = self.profiles.data(profile_id)["preferences"]
                if "volume" in prefs and type(prefs["volume"]) in (int, float) and 0 <= prefs["volume"] <= 100:
                    self.volume = int(prefs["volume"])
                if prefs.get("play_mode") in {"once", "loop", "next", "shuffle"}:
                    self.play_mode = prefs["play_mode"]
                    self.loop = self.play_mode == "loop"
                if type(prefs.get("sleep_minutes")) is int and 1 <= prefs["sleep_minutes"] <= MAX_SLEEP_MINUTES:
                    self.sleep_minutes = prefs["sleep_minutes"]
                if type(prefs.get("normalization")) is bool:
                    self.normalization = prefs["normalization"]
                if isinstance(prefs.get("audio_processing"), dict):
                    self.audio_processing = validate_audio_settings(prefs["audio_processing"])
                if self.normalization and not self.audio_processing["bypass"]:
                    self.audio_processing = {**self.audio_processing, "bypass": True}
            self.player.prepare()
            # Never resume the previous paused file while preparing its replacement.
            self.observe_listening(playing=False)
            self.player.command("stop")
            if output is None:
                self.configure_output()
                output = self.output
            else:
                if output == "auto" or output not in [d["name"] for d in self.player.get("audio-device-list", [])]:
                    raise ValueError("The selected alarm output is not available.")
                self.validate_bluetooth_output(output, force=True)
                self.player.command("set_property", "audio-device", output)
            self.playback_error = None
            self.resume_pending = None
            # Set all controls before loadfile; avoid a burst at a previous session's volume.
            self.player.command("set_property", "loop-file", "inf" if ((self.play_mode == "loop") if loop is None else loop) else "no")
            self.player.command("set_property", "volume", self.volume if volume is None else volume)
            self.player.command("set_property", "pause", keep_paused)
            apply_normalization(self.player, self.normalization and mode != "alarm",
                                self.audio_processing if mode != "alarm" else None,
                                meter=self.gain_meter.active and mode != "alarm",
                                source_sample_rate=(self.catalog.cached(path) or {}).get('sample_rate_hz', 0))
            if self.deadline is not None and self.deadline <= time.monotonic():
                self.stop()
                raise ValueError("The sleep timer expired before audio could start.")
            receipt = self.player.load(path)
            self.selected = name
            if mode != 'alarm':
                self.last_played_track = name
            if profile is not None and mode != "alarm":
                self.active_profile_id = profile_id
                if self.audio_processing != previous_processing or self.normalization != previous_normalization:
                    self.audio_processing_revision += 1
            if mode != 'alarm':
                self.save()
            self.session += 1
            with self.timer_lock:
                if self.deadline is not None and self.deadline <= time.monotonic():
                    self.deadline = None
                self.timer_session = self.session
            self.active_output = output
            self.mode = mode
            self.receipt = {**receipt, "session": self.session, "deadline": time.monotonic() + 10, "paused_on_load": keep_paused}
            return dict(self.receipt)

    def playback_status(self, receipt):
        with self.transition_lock:
            if receipt["session"] in self.finished:
                return dict(self.finished[receipt["session"]])
            if receipt["session"] != self.session:
                return {"status": "superseded"}
            result = self.player.playback_status(receipt)
            # mpv may signal file-loaded but no playback-restart until unpaused.
            if (receipt.get("paused_on_load") and result["status"] in {"loaded", "started"}
                    and self.player.get("pause", False)
                    and not self.player.get("idle-active", True)):
                return {"status": "paused"}
            if result["status"] in {"starting", "loaded"} and time.monotonic() > receipt["deadline"]:
                result = {"status": "failed", "message": "Audio did not start within 10 seconds."}
            if result["status"] == "failed":
                self.stop(expected_session=receipt["session"], failure=result["message"])
                self.playback_error = result["message"]
            return result

    def remote_action(self, manager, generation, remote, action):
        """Use the same player/timer/profile/DSP paths as the LAN UI; no shell actions."""
        with self.lock:
            if not manager.dispatch_if_current(generation, remote, action):
                return
            if self.mode == "alarm":
                raise ValueError("Dismiss the alarm before using remote playback controls.")
            profile = self.effective_profile_id(remote['profile'])
            idle = self.player.get('idle-active', True)
            if action in ('play_default', 'sleep_default') or (action in ('play_pause', 'play_stop') and idle):
                target = remote.get('default_track')
                if target == CURRENT_TRACK:
                    target = self.selected if not idle else self.last_played_track
                    if not target:
                        raise ValueError("Play a track once before using Last played / current track.")
                if not target:
                    raise ValueError("Choose a default sound for this remote first.")
                if action == 'sleep_default':
                    self.sleep(target, profile=profile)
                else:
                    self.play(target, profile=profile)
            elif action == 'play_pause':
                self.set_paused()
            elif action in ('stop', 'play_stop'):
                self.stop()
            elif action == 'next':
                self.skip()
            elif action == 'previous':
                self.previous()
            elif action == 'cancel_timer':
                self.set_timer(0)
            elif action == 'timer':
                minutes = self.profiles.data(profile)['preferences'].get('sleep_minutes', self.sleep_minutes)
                self.set_timer(minutes)
            elif action in ('loop', 'normalization', 'processing', 'volume_up', 'volume_down'):
                if not idle and profile != self.active_profile_id:
                    raise ValueError("This sound belongs to another profile. Start this remote's default sound first.")
                if action == 'loop':
                    self.set_play_mode('once' if self.loop else 'loop', profile)
                elif action == 'normalization':
                    current = self.profiles.data(profile)['preferences'].get('normalization', self.normalization)
                    self.set_normalization(not current, profile)
                elif action == 'processing':
                    current = self.profiles.data(profile)['preferences'].get('audio_processing', self.audio_processing)
                    self.set_audio_processing({'bypass': not current['bypass']}, profile=profile)
                else:
                    value = min(100, max(0, self.volume + (5 if action == 'volume_up' else -5)))
                    self.player.command('set_property', 'volume', value)
                    self.volume = value
                    self.save()
                    self.remember_profile_preferences(profile, {'volume': value})

    def selected_bluetooth_unity(self):
        """Apply 100% digital output to *only* the selected Bluetooth sink."""
        self.validate_bluetooth_output(self.output, force=True)
        if self.output == COMBINED_OUTPUT:
            if not any(d["name"] == COMBINED_BT for d in self.player.get("audio-device-list", [])):
                return False
            try:
                return normalize_selected_bluetooth_volume(self.speaker, COMBINED_BT, run)
            except RuntimeError:
                return False  # Wired member keeps playing while Bluetooth recovers.
        return normalize_selected_bluetooth_volume(self.speaker, self.output, run)

    def set_play_mode(self, new_mode, profile=None):
        if new_mode not in {"once", "loop", "next", "shuffle"}:
            raise ValueError("Choose Play once, Loop, Next or Shuffle.")
        with self.transition_lock:
            if self.mode == "alarm":
                raise ValueError("Dismiss the alarm before changing playback mode.")
            if self.profile_edit_is_inactive(profile):
                self.remember_profile_preferences(profile, {"play_mode": new_mode})
                return
            self.player.command("set_property", "loop-file", "inf" if new_mode == "loop" else "no")
            self.play_mode = new_mode
            self.loop = new_mode == "loop"
            self.save()
            self.remember_profile_preferences(profile, {"play_mode": new_mode})

    def choose_next_file(self, wrap=False):
        ids = [item["id"] for item in self.library()]
        if not ids:
            return None
        if self.play_mode == "shuffle":
            choices = [name for name in ids if name != self.selected]
            return random.choice(choices) if choices else None
        if self.selected not in ids:
            return ids[0]
        next_index = ids.index(self.selected) + 1
        return ids[next_index] if next_index < len(ids) else (ids[0] if wrap else None)

    def skip(self):
        with self.transition_lock:
            if self.mode == "alarm":
                raise ValueError("Next is disabled during alarms.")
            target = self.choose_next_file(wrap=True)
            if not target:
                raise ValueError("No next audio file available.")
            mode = self.mode if self.mode in ("normal", "sleep") else "normal"
            self.play(target, mode=mode, preserve_pause=True)

    def configure_output(self):
        devices = self.player.get("audio-device-list", [])
        if self.speaker and self.output != COMBINED_OUTPUT:
            needle = self.speaker.replace(":", "_").lower()
            self.output = next((d["name"] for d in devices if needle in d["name"].lower()), None)
        if not self.output or self.output not in [d["name"] for d in devices]:
            raise ValueError("Choose an available audio output before pressing Play.")
        self.validate_bluetooth_output(self.output, force=True)
        self.player.command("set_property", "audio-device", self.output)
        self.selected_bluetooth_unity()

    def stop(self, cancel_timer=True, expected_session=None, failure=None):
        with self.transition_lock:
            if expected_session is not None and expected_session != self.session:
                return False
            self.observe_listening(playing=False)
            if self.receipt and self.receipt["session"] == self.session:
                self.finished[self.session] = {"status": "failed", "message": failure} if failure else {"status": "stopped"}
                for old in sorted(self.finished)[:-64]:
                    del self.finished[old]
            with self.timer_lock:
                if cancel_timer:
                    self.deadline = None
            try:
                self.player.command("stop")
            except Exception:
                self.player.close()
                self.playback_error = "Player stopped after losing its control connection. Press Play to retry."
            self.session += 1
            self.mode = "idle"
            self.clear_resume()
            return True

    def set_timer(self, minutes):
        if isinstance(minutes,bool) or not isinstance(minutes,(int,float)) or not 0<=minutes<=MAX_SLEEP_MINUTES:
            raise ValueError("Timer must be between 0 and 960 minutes (16 hours).")
        with self.transition_lock:
            with self.timer_lock:
                self.deadline=time.monotonic()+minutes*60 if minutes else None
                self.timer_session=self.session
            self.resume_last_saved=-60
            self.persist_resume()

    def set_timer_end(self, clock):
        zone = self.alarm.state["config"].get("timezone", "America/Chicago")
        duration_seconds = seconds_to_end_time(clock, zone)
        self.set_timer(duration_seconds / 60)
        return duration_seconds

    def tick(self):
        with self.transition_lock:
            playback = None
            if self.receipt and self.receipt["session"] == self.session:
                playback = self.playback_status(self.receipt)
            self.observe_listening(playing=bool(playback and playback["status"] == "started"
                and self.mode != "alarm" and not self.player.get("idle-active", True)),
                paused=self.player.get("pause", False))
            with self.timer_lock:
                expired = self.deadline is not None and time.monotonic() >= self.deadline
                owner = self.timer_session
                if expired:
                    self.deadline = None
            if expired:
                self.stop(cancel_timer=False, expected_session=owner)
            elif playback and playback["status"] == "completed" and self.mode in ("normal", "sleep"):
                next_id = self.choose_next_file() if self.play_mode in ("next", "shuffle") else None
                if next_id:
                    current_mode = self.mode
                    try:
                        self.play(next_id, mode=current_mode)
                    except (ValueError, RuntimeError, OSError):
                        LOG.exception("Could not advance to the next audio file")
                        self.stop()
                else:
                    self.stop()
            if self.resume_pending:
                self.try_resume()
            self.persist_resume()

    def sleep(self, name, minutes=None, profile=None):
        if minutes is None and profile is not None:
            candidate = self.profiles.data(profile)["preferences"].get("sleep_minutes")
            if type(candidate) is int and 1 <= candidate <= MAX_SLEEP_MINUTES:
                minutes = candidate
        minutes = self.sleep_minutes if minutes is None else minutes
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 1 <= minutes <= MAX_SLEEP_MINUTES:
            raise ValueError("Sleep duration must be between 1 and 960 minutes.")
        with self.transition_lock:
            self.play(name, mode="sleep", profile=profile)
            self.set_timer(minutes)

    def validate_alarm(self, config):
        # The selected output is chosen at ring time, not when scheduling.
        self.track(config["track"])

    def run_alarm(self, config):
        with self.transition_lock:
            self.stop()  # Alarm preempts sleep audio and cancels its old timer.
            self.validate_alarm(config)
            output=self.output
            devices=[d["name"] for d in self.player.get("audio-device-list",[])]
            if not output or output=="auto" or output not in devices:
                raise ValueError("Alarm cannot play: selected audio output is unavailable.")
            self.selected_bluetooth_unity()
            receipt=self.play(config["track"], volume=config["volume"], loop=config["loop"], output=output, mode="alarm")
            self.set_timer(config["ring_minutes"])
            return receipt

    def alarm_monitor(self):
        while not self.closed.wait(1):
            try:
                if time.monotonic() - self._clock["checked"] > 30:
                    try:
                        self._clock["ready"] = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=2).strip() == "yes"
                    except (OSError, RuntimeError, subprocess.TimeoutExpired):
                        self._clock["ready"] = False
                    self._clock["checked"] = time.monotonic()
                self.alarm.tick()
            except Exception:
                LOG.exception("Alarm scheduler failed; no automatic output fallback")

    def monitor(self):
        while not self.closed.wait(1):
            try:
                self.tick()
            except Exception:
                LOG.exception("Sleep timer could not stop playback; will retry")

    def reconnect_monitor(self):
        # Never creates a pairing: only retry the last explicitly selected, paired output.
        while not self.closed.wait(8):
            try:
                self.reconnect_once()
            except Exception:
                LOG.exception("Bluetooth reconnection check failed")

    def reconnect_once(self):
        with self.lock:
            speaker = self.speaker
            if (not self.auto_reconnect or self.reconnect_suppressed or not speaker
                    or self.bt["busy"] or time.monotonic() < self.reconnect_next):
                return False
            self.reconnect_next = time.monotonic() + self.reconnect_delay
        try:
            info = run(["bluetoothctl", "info", speaker], timeout=5)
            if "Paired: yes" not in info:
                self.forget_stale_speaker(speaker)
                return False
            if "Connected: yes" not in info:
                with self.lock:
                    # A saved deadline survives a service crash or Pi reboot.
                    # Expiration is checked BEFORE issuing any further connect command.
                    if not self.auto_reconnect or self.reconnect_suppressed or self.speaker != speaker:
                        return False
                    if self.reconnect_expires_at is None:
                        self.reconnect_expires_at = time.time() + self.reconnect_retry_minutes * 60
                        self.save()
                    if time.time() >= self.reconnect_expires_at:
                        self.reconnect_message = "Reconnect time limit reached. Tap Connect to try again."
                        return False
                run(["bluetoothctl", "--timeout", "12", "connect", speaker], timeout=17)
                info = run(["bluetoothctl", "info", speaker], timeout=5)
                if "Connected: yes" not in info:
                    raise RuntimeError("Bluetooth connect command returned without a speaker connection.")
                self.reconnect_message = "Speaker reconnected to combined output." if self.output == COMBINED_OUTPUT else "Reconnected to saved speaker. Playback remains stopped."
            # Restore the explicit output without starting playback or selecting another speaker.
            device_name = speaker.replace(":", "_").lower()
            devices = self.player.get("audio-device-list", [])
            matched = next((d["name"] for d in devices if device_name in d["name"].lower()), None)
            if self.output == COMBINED_OUTPUT:
                matched = COMBINED_OUTPUT if any(d["name"] == COMBINED_OUTPUT for d in devices) else None
            with self.lock, self.transition_lock:
                if self.auto_reconnect and self.speaker == speaker and not self.reconnect_suppressed:
                    if matched and self.player.get("idle-active", True) and (self.output != matched or self.reconnect_expires_at is not None):
                        self.validate_bluetooth_output(matched, force=True)
                        self.player.command("set_property", "audio-device", matched)
                        normalize_selected_bluetooth_volume(speaker, COMBINED_BT if matched == COMBINED_OUTPUT else matched, run)
                    changed = self.reconnect_expires_at is not None or bool(matched and self.output != matched)
                    if matched:
                        self.output = matched
                    self.reconnect_expires_at = None
                    if changed:
                        self.save()
                    self.reconnect_delay = 8
            return True
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            if "not available" in str(error).lower():
                try:
                    devices = run(["bluetoothctl", "devices", "Paired"], timeout=5)
                    if not any(speaker.upper() == line.split(" ", 2)[1].upper()
                                for line in devices.splitlines() if len(line.split(" ", 2)) >= 2):
                        self.forget_stale_speaker(speaker)
                        return False
                except (OSError, RuntimeError, subprocess.TimeoutExpired):
                    pass
            with self.lock:
                if self.reconnect_expires_at is None and self.speaker == speaker:
                    self.reconnect_expires_at = time.time() + self.reconnect_retry_minutes * 60
                    self.save()
                expired = self.reconnect_expires_at is not None and time.time() >= self.reconnect_expires_at
                self.reconnect_message = ("Reconnect time limit reached. Tap Connect to try again."
                                          if expired else "Speaker unavailable; retrying within the time limit.")
                self.reconnect_delay = min(180, max(15, self.reconnect_delay * 2))
            LOG.info("Speaker reconnect attempt failed: %s", error)
            return False
    def forget_stale_speaker(self, address):
        with self.lock, self.transition_lock:
            if self.speaker == address:
                self.speaker = None
                self.output = None
                self.reconnect_suppressed = True
                self.reconnect_expires_at = None
                self.reconnect_message = "Speaker removed. Tap Find Bluetooth speakers to connect again."
                self.save()

    def routing_monitor(self):
        while not self.closed.wait(3):
            try:
                if self.check_output():
                    with self.lock:
                        for device in self.bt["devices"]:
                            if device["address"] == self.speaker:
                                device["connected"] = False
            except Exception:
                LOG.exception("Could not check audio routing")

    def validate_bluetooth_output(self, output, force=False):
        if output == COMBINED_OUTPUT:
            devices = self.player.get("audio-device-list", [])
            validate_combined_devices(devices)
            names = {d["name"] for d in devices}
            if COMBINED_BT in names:
                try:
                    self.validate_bluetooth_output(COMBINED_BT, force=force)
                except RuntimeError:
                    if COMBINED_WIRED not in names:
                        raise
            return
        adapter = os.environ.get("SLEEP_SOUNDS_BLUETOOTH_ADAPTER", "").strip()
        if not adapter or "bluez_" not in (output or "").lower():
            return
        with self.bluetooth_route_lock:
            key = (adapter, output)
            cached = self.bluetooth_route_cache
            if not force and cached and cached[0] == key and time.monotonic() - cached[1] < 1:
                if cached[2]:
                    raise RuntimeError(cached[2])
                return
            error = None
            try:
                validate_selected_bluetooth_output(adapter, output, run)
            except RuntimeError as failure:
                error = str(failure)
            self.bluetooth_route_cache = (key, time.monotonic(), error)
            if error:
                raise RuntimeError(error)

    def check_output(self):
        with self.transition_lock:
            owner, output = self.session, self.active_output
        if self.player.get("idle-active", True):
            return False
        devices = self.player.get("audio-device-list", [])
        failure = "Audio output disconnected." if output not in [d["name"] for d in devices] else None
        if not failure:
            try:
                self.validate_bluetooth_output(output)
            except RuntimeError as error:
                failure = str(error)
        with self.transition_lock:
            if owner != self.session or output != self.active_output:
                return False
            if failure and self.stop(expected_session=owner, failure=failure):
                self.playback_error = failure + " Reconnect it and press Play to resume."
                return True
        return False

    def status(self):
        # No controller lock during subprocess/IPC: timer expiry must remain independent.
        if time.monotonic() - self.power["checked"] > 30:
            try:
                flags = int(run(["vcgencmd", "get_throttled"], timeout=2).strip().split("=")[1], 16)
                self.power = {"checked": time.monotonic(), "undervoltage": bool(flags & 1), "throttled": bool(flags & 4)}
            except (OSError, RuntimeError, ValueError, IndexError, subprocess.TimeoutExpired):
                self.power["checked"] = time.monotonic()
        self.check_output()
        playback = self.playback_status(self.receipt) if self.receipt else None
        devices = self.player.get("audio-device-list", [])
        available = self.output in [d["name"] for d in devices]
        routing_error = None
        if available:
            try:
                self.validate_bluetooth_output(self.output)
            except RuntimeError as error:
                available, routing_error = False, str(error)
        idle = self.player.get("idle-active", True)
        deadline = self.deadline
        return {"csrf": self.token, "selected": self.selected, "loop": self.loop,
                "active_profile_id": self.active_profile_id,
                "play_mode": self.play_mode, "volume": self.volume, "audio_buffer_seconds": self.audio_buffer_seconds,
                "normalization": self.normalization, "audio_processing": dict(self.audio_processing),
                "audio_processing_revision": self.audio_processing_revision, "library_revision": self.library_revision,
                "server_time": time.time(), "session_id": self.session,
                "timezone": self.alarm.state["config"].get("timezone","America/Chicago"),
                "idle": idle, "paused": self.player.get("pause", False),
                "output_ready": available, "playback_error": self.playback_error or routing_error or getattr(self.player, "error", None),
                "mode": "idle" if idle else self.mode, "active_output": self.active_output, "playback": playback,
                "clock_ready": self._clock["ready"],
                "position": self.player.get("time-pos", 0) or 0,
                "duration": self.player.get("duration", 0) or 0,
                "timer_seconds": max(0, int(deadline - time.monotonic())) if deadline else None,
                "timer_ends_at": time.time()+max(0,deadline-time.monotonic()) if deadline else None,
                "power": self.power, "bluetooth": dict(self.bt), "auto_reconnect": self.auto_reconnect,
                "reconnect_message": self.reconnect_message,
                "reconnect_suppressed": self.reconnect_suppressed,
                "reconnect_remaining_seconds": (max(0, int(self.reconnect_expires_at - time.time())) if self.reconnect_expires_at is not None else None),
                "resume_after_restart": self.resume_after_restart,
                "pairing": self.pairing_agent.state() if self.pairing_agent else {"available": False, "pending": None}}

    def bluetooth_job(self, action, address=None, confirm=False):
        if action not in {"scan", "connect", "disconnect", "remove", "clear_pairings"}:
            raise ValueError("Unknown Bluetooth action.")
        if action in {"connect", "disconnect", "remove"} and (not isinstance(address, str) or not MAC.fullmatch(address)):
            raise ValueError("Invalid Bluetooth device address.")
        if action == "clear_pairings" and confirm is not True:
            raise ValueError("Confirm clearing all saved Bluetooth pairings.")
        with self.lock:
            if self.bt["busy"]:
                raise ValueError("Bluetooth is busy. Wait for the current action to finish.")
            if action == "disconnect" and address == self.speaker:
                self.reconnect_suppressed = True
                self.reconnect_expires_at = None
                self.reconnect_message = "Disconnected manually. Automatic reconnect paused."
                self.clear_resume()
                self.save()
            if action == "clear_pairings":
                # Stop reconnect attempts before any pair records are removed.
                self.reconnect_suppressed = True
            if action == "connect":
                self.reconnect_suppressed = False
                self.reconnect_expires_at = None
                self.reconnect_next = 0
                self.reconnect_delay = 8
                self.reconnect_message = ""
                self.save()
                self.pairing_target = address
            descriptions = {"scan": "Searching for 12 seconds…", "connect": "Connecting…", "disconnect": "Disconnecting…",
                            "remove": "Unpairing device…", "clear_pairings": "Clearing paired devices…"}
            self.bt.update(busy=True, message=descriptions[action])
        threading.Thread(target=self._bluetooth, args=(action, address), daemon=True, name="sleep-sounds-bluetooth").start()

    def _bluetooth(self, action, address):
        message = ""
        try:
            if action == "scan":
                run(["bluetoothctl", "--timeout", "12", "scan", "on"], timeout=17)
                message = "Search complete. Select your speaker."
            elif action == "connect":
                with self.lock, self.transition_lock:
                    keep_combined = self.output == COMBINED_OUTPUT and address == COMBINED_BLUETOOTH_ADDRESS
                    if not keep_combined:
                        self.stop()
                        self.output = None
                    self.speaker = address
                    self.save()
                info = run(["bluetoothctl", "info", address])
                if "Paired: yes" not in info:
                    if not self.pairing_agent or not self.pairing_agent.state()["available"]:
                        raise RuntimeError("Phone pairing confirmation service is unavailable.")
                    output = run(["bluetoothctl", "--timeout", "65", "pair", address], timeout=70)
                    if "Pairing successful" not in output:
                        raise RuntimeError("Pairing was not confirmed. Put the speaker in pairing mode and try again.")
                run(["bluetoothctl", "trust", address])
                run(["bluetoothctl", "--timeout", "20", "connect", address], timeout=25)
                info = run(["bluetoothctl", "info", address])
                if "Connected: yes" not in info:
                    raise RuntimeError("Speaker did not confirm a connection.")
                # Choose this speaker explicitly; leave playback stopped until owner presses Play.
                needle = address.replace(":", "_").lower()
                for _ in range(10):
                    devices = self.player.get("audio-device-list", [])
                    match = next((d["name"] for d in devices if needle in d["name"].lower()), None)
                    if match:
                        with self.lock, self.transition_lock:
                            self.validate_bluetooth_output(match, force=True)
                            if not (keep_combined and self.output == COMBINED_OUTPUT):
                                self.stop()
                                self.player.command("set_property", "audio-device", match)
                                self.output = match
                            self.speaker = address
                            self.selected_bluetooth_unity()
                            self.reconnect_expires_at = None
                            self.save()
                        message = "Speaker rejoined combined output." if keep_combined and self.output == COMBINED_OUTPUT else "Speaker connected and selected for playback."
                        break
                    time.sleep(0.5)
                else:
                    message = "Bluetooth connected. Choose its audio output below before playback."
            elif action == "disconnect":
                # Combined members are independent; do not interrupt the survivor.
                keep_combined = self.output == COMBINED_OUTPUT
                if not keep_combined:
                    self.stop()
                run(["bluetoothctl", "disconnect", address])
                message = "Disconnected. Other speaker keeps playing." if keep_combined else "Disconnected. Playback stopped."
            elif action == "remove":
                if self.speaker == address:
                    self.stop()
                run(["bluetoothctl", "remove", address])
                if self.speaker == address:
                    with self.lock, self.transition_lock:
                        self.speaker = None
                        self.output = None
                        self.reconnect_suppressed = True
                        self.reconnect_expires_at = None
                        self.save()
                message = "Device unpaired from Pi."
            elif action == "clear_pairings":
                paired = []
                for line in run(["bluetoothctl", "devices", "Paired"]).splitlines():
                    parts = line.split(" ", 2)
                    if len(parts) >= 2 and MAC.fullmatch(parts[1]):
                        paired.append(parts[1])
                if self.speaker:
                    self.stop()
                removed, failures = 0, []
                for device in paired:
                    try:
                        run(["bluetoothctl", "remove", device])
                        removed += 1
                    except (OSError, RuntimeError, subprocess.TimeoutExpired):
                        failures.append(device)
                # Also forget any stale selected speaker that was already removed
                # from BlueZ before this request. Clearing pairings resets app state.
                with self.lock, self.transition_lock:
                    self.speaker = None
                    self.output = None
                    self.reconnect_message = ""
                    self.reconnect_delay = 8
                    self.reconnect_expires_at = None
                    self.save()
                message = f"Removed {removed} paired device(s); saved speaker cleared." + (f" Could not unpair: {', '.join(failures)}." if failures else "")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            message = str(error)[-500:]
        finally:
            devices = []
            try:
                def addresses(text):
                    return {parts[1] for line in text.splitlines() if len(parts := line.split(" ", 2)) >= 2 and MAC.fullmatch(parts[1])}
                connected = addresses(run(["bluetoothctl", "devices", "Connected"], timeout=5))
                paired = addresses(run(["bluetoothctl", "devices", "Paired"], timeout=5))
                for line in run(["bluetoothctl", "devices"]).splitlines()[:40]:
                    parts = line.split(" ", 2)
                    if len(parts) == 3 and MAC.fullmatch(parts[1]):
                        devices.append({"address": parts[1], "name": parts[2],
                                        "connected": parts[1] in connected,
                                        "paired": parts[1] in paired})
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                message += " Device list unavailable: " + str(error)[-150:]
            with self.lock:
                if action == "connect" and self.pairing_target == address:
                    self.pairing_target = None
                self.bt.update(busy=False, message=message, devices=devices)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, controller, hosts):
        self.controller = controller
        self.hosts = {h.lower() for h in hosts}
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "SleepSounds/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(120)

    def reply(self, code, body, kind="application/json"):
        payload = json.dumps(body).encode() if kind == "application/json" else body
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def valid_host(self):
        try:
            return urlsplit("http://" + self.headers.get("Host", "")).hostname in self.server.hosts
        except ValueError:
            return False

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {"error": "Unrecognized server address."})
        controller = self.server.controller
        path = urlsplit(self.path).path
        try:
            if path == "/" and os.environ.get("SLEEP_SOUNDS_SERVE_UI", "false").lower() != "true":
                return self.reply(200, {"service": "Sleep Sounds backend", "status": "ready", "gui": "Awaiting owner's new design", "api": "/api/status"})
            if path == '/api/identity':
                return self.reply(200, {'service': 'sleep-sounds', 'host_id': controller.host_id, 'version': '0.7.0-library'})
            if path == "/api/status":
                return self.reply(200, controller.status())
            if path == "/api/tracks":
                profile = parse_qs(urlsplit(self.path).query).get("profile", [None])[0]
                try:
                    return self.reply(200, controller.library(profile))
                except ValueError as error:
                    return self.reply(400, {"error": str(error)})
            if path == "/api/library-catalog":
                return self.reply(200, controller.discovery.snapshot())
            if path == "/api/feedback":
                return self.reply(200, controller.discovery.feedback(controller.profiles.catalog()['profiles']))
            if path == '/api/track-comments':
                track = controller.track(parse_qs(urlsplit(self.path).query).get('track', [None])[0]).name
                return self.reply(200, controller.discovery.feedback(controller.profiles.catalog()['profiles'], track=track))
            if path == "/api/public-profile":
                query = parse_qs(urlsplit(self.path).query)
                return self.reply(200, controller.public_profile(query.get('profile', ['none'])[0]))
            if path == '/api/diagnostics-export':
                from system_status import diagnostic_export
                return self.reply(200, diagnostic_export(controller))
            if path == "/api/system":
                return self.reply(200, system_snapshot(controller))
            if path == "/api/app-release":
                from app_release import release_info
                return self.reply(200, release_info(ROOT / 'install'))
            if path == "/api/profiles":
                return self.reply(200, controller.profiles.catalog())
            if path == "/api/remotes":
                return self.reply(200, controller.remote_manager.snapshot())
            if path == "/api/profile-data":
                profile = parse_qs(urlsplit(self.path).query).get("profile", [None])[0]
                try:
                    return self.reply(200, controller.profiles.data(profile))
                except ValueError as error:
                    return self.reply(400, {"error": str(error)})
            if path == "/api/track-details":
                query = parse_qs(urlsplit(self.path).query)
                try:
                    return self.reply(200, controller.track_details(query.get("track", [None])[0],
                        query.get("profile", [None])[0]))
                except ValueError as error:
                    return self.reply(400, {"error": str(error)})
            if path == "/api/library-summary":
                profile = parse_qs(urlsplit(self.path).query).get("profile", [None])[0]
                try:
                    return self.reply(200, controller.library_summary(profile))
                except ValueError as error:
                    return self.reply(400, {"error": str(error)})
            if path == "/api/upload-result":
                key=parse_qs(urlsplit(self.path).query).get("key",[""])[0]
                try:return self.reply(200,controller.upload_result(key))
                except ValueError as error:return self.reply(400,{"error":str(error)})
            if path == "/api/artwork":
                track = parse_qs(urlsplit(self.path).query).get("track", [""])[0]
                try:
                    art = controller.artwork_path(track)
                except ValueError:
                    art = None
                if not art:
                    return self.reply(404, {"error": "No image for this audio file."})
                return self.reply(200, art.read_bytes(), mimetypes.guess_type(art.name)[0] or "application/octet-stream")
            if path == "/api/config":
                usage = shutil.disk_usage(controller.tracks)
                audio = controller.audio_settings_snapshot()
                result = {"formats": sorted(AUDIO_EXTENSIONS), "max_upload_bytes": controller.max_upload_bytes, "storage_reserve_mb": controller.storage_reserve_mb, "free_storage_bytes": usage.free, "sleep_minutes": controller.sleep_minutes, "loop": controller.loop, "auto_reconnect": controller.auto_reconnect, "reconnect_retry_minutes": controller.reconnect_retry_minutes, "resume_after_restart": controller.resume_after_restart, "normalization": audio["normalization"], "audio_processing": audio["audio_processing"], "audio_processing_revision": audio["audio_processing_revision"], "audio_processing_defaults": DEFAULT_AUDIO_SETTINGS, "audio_processing_ranges": NUMERIC_RANGES, "audio_processing_eq_modes": [3, 5], "audio_rack_supported": True, "audio_presets_supported": True, "audio_presets_revision": controller.audio_presets.revision, "max_timer_minutes": MAX_SLEEP_MINUTES, "timer_runs_while_paused": True, "stop_cancels_timer": True,
                    "audio_buffer_seconds": controller.audio_buffer_seconds, "active_profile_id": controller.active_profile_id, "audio_edit_lock": controller.audio_edit_lock_status()}
                result['allow_track_deletion'] = controller.allow_track_deletion
                requested = parse_qs(urlsplit(self.path).query).get("profile", [None])[0]
                if requested is not None:
                    try:
                        pid = controller.effective_profile_id(requested)
                        prefs = controller.profiles.data(pid)["preferences"]
                    except ValueError as error:
                        return self.reply(400, {"error": str(error)})
                    result["profile_id"] = pid
                    for key in ("sleep_minutes",):
                        if key in prefs:
                            result[key] = prefs[key]
                    if "play_mode" in prefs:
                        result["loop"] = prefs["play_mode"] == "loop"
                        result["play_mode"] = prefs["play_mode"]
                    result["volume"] = controller.volume
                return self.reply(200, result)
            if path == "/api/audio-edit-lock":
                session = parse_qs(urlsplit(self.path).query).get("editor_session", [None])[0]
                return self.reply(200, controller.audio_edit_lock_status(session))
            if path == "/api/audio-presets":
                return self.reply(200, controller.audio_presets.snapshot())
            if path == "/api/alarm":
                return self.reply(200, controller.alarm.status())
            if path == "/api/outputs":
                return self.reply(200, {"devices": controller.player.get("audio-device-list", []), "selected": controller.output, "speaker_sync": speaker_sync_snapshot(controller.data)})
            if path in {"/install", "/install/"}:
                return self.reply(200, (ROOT / "install" / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/install/SleepSounds.apk":
                apk = ROOT / "install" / "SleepSounds.apk"
                if not apk.is_file():
                    return self.reply(404, {"error": "Android installer is unavailable."})
                return self.reply(200, apk.read_bytes(), "application/vnd.android.package-archive")
            if path.startswith("/ui/"):
                ui = (ROOT / "frontend" / "dist").resolve()
                resource = (ui / (unquote(path[4:]) or "index.html")).resolve()
                if not resource.is_relative_to(ui) or not resource.is_file():
                    return self.reply(404, {"error": "Interface asset is unavailable."})
                return self.reply(200, resource.read_bytes(), mimetypes.guess_type(resource.name)[0] or "application/octet-stream")
            files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8"), "/icon.svg": ("icon.svg", "image/svg+xml")}
            if path in files:
                name, kind = files[path]
                return self.reply(200, (ROOT / "web" / name).read_bytes(), kind)
            self.reply(404, {"error": "Not found."})
        except ValueError as error:
            self.reply(400, {"error": str(error)})
        except Exception:
            LOG.exception("GET failed")
            self.reply(503, {"error": "Player unavailable. Check the Pi service log."})

    def do_POST(self):
        c = self.server.controller
        origin = self.headers.get("Origin")
        if (not self.valid_host() or (origin and origin != "http://" + self.headers.get("Host", "") and origin not in set(filter(None, os.environ.get("SLEEP_SOUNDS_HTTPS_ORIGINS", "").split(","))))
                or not secrets.compare_digest(self.headers.get("X-Sleep-Token", ""), c.token)):
            self.close_connection = True
            return self.reply(403, {"error": "Refresh the page and try again."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked uploads are not supported.")
            url = urlsplit(self.path)
            if url.path == "/api/upload":
                return self.upload(length, parse_qs(url.query).get("name", [""])[0], parse_qs(url.query).get("key", [None])[0])
            if url.path == "/api/artwork":
                query = parse_qs(url.query)
                return self.upload_artwork(length, query.get("track", [""])[0], query.get("name", [""])[0])
            if length < 0 or length > 8192:
                raise ValueError("Request is too large.")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object.")
            # Input recovery must not wait behind a slow playback/output command.
            if url.path == '/api/remotes' and data.get('action') in ('release_all', 'cancel_learn'):
                if data['action'] == 'release_all':
                    c.remote_manager.release_all()
                else:
                    c.remote_manager.cancel(data.get('id'))
                return self.reply(200, c.remote_manager.snapshot())
            with c.lock:
                if url.path == '/api/library-metadata':
                    track = c.track(data.get('track')).name
                    result = c.discovery.edit(track, data.get('values'), data.get('revision'))
                    c.library_revision += 1
                    return self.reply(200, result)
                elif url.path == '/api/library-catalog':
                    if data.get('action') == 'add_tag':
                        result = c.discovery.add_tag(data.get('name'), data.get('revision'))
                    elif data.get('action') == 'remove_tag':
                        result = c.discovery.remove_tag(data.get('tag'), data.get('revision'), data.get('confirm'))
                    elif data.get('action') == 'label':
                        result = c.discovery.label_change(data.get('kind'), data.get('operation'), data.get('revision'),
                            name=data.get('name'), label_id=data.get('id'), confirm=data.get('confirm'), picture=data.get('picture'))
                    else:
                        raise ValueError('Unknown tag action.')
                    c.library_revision += 1
                    return self.reply(200, result)
                elif url.path == '/api/rating':
                    track = c.track(data.get('track')).name
                    pid = c.effective_profile_id(data.get('profile'))
                    c.discovery.rating(track, pid, data.get('rating'))
                    c.library_revision += 1
                    return self.reply(200, c.discovery.ratings(track, c.profiles.catalog()['profiles'], pid))
                elif url.path == '/api/track-delete':
                    return self.reply(200, c.delete_track(data.get('track'), data.get('confirm')))
                elif url.path == '/api/track-comments':
                    track = c.track(data.get('track')).name
                    pid = c.effective_profile_id(data.get('profile'))
                    c.discovery.post(pid, data.get('body'), parent=data.get('parent'), track=track)
                    return self.reply(200, c.discovery.feedback(c.profiles.catalog()['profiles'], track=track))
                elif url.path == '/api/feedback':
                    pid = c.effective_profile_id(data.get('profile'))
                    c.discovery.post(pid, data.get('body'), data.get('url', ''), data.get('parent'))
                    return self.reply(200, c.discovery.feedback(c.profiles.catalog()['profiles']))
                elif url.path == '/api/system-action':
                    from system_status import system_action
                    return self.reply(200, system_action(c, data))
                elif url.path == "/api/remotes":
                    action = data.get('action')
                    if action == 'learn':
                        if type(data.get('modifier', False)) is not bool:
                            raise ValueError('Expected an on/off modifier setting.')
                        return self.reply(200, c.remote_manager.learn(data.get('remote'), data.get('modifier', False)))
                    if action == 'resume':
                        c.remote_manager.resume()
                    else:
                        c.remote_store.change(data, c.remote_manager.discoverer(),
                            {p['id'] for p in c.profiles.catalog()['profiles']}, c.track)
                        c.remote_manager.invalidate()
                    return self.reply(200, c.remote_manager.snapshot())
                elif url.path == "/api/play":
                    c.play(data.get("track"), profile=data.get("profile", "none"))
                elif url.path == "/api/select-track":
                    c.select_library_track(data.get("track"), profile=data.get("profile", "none"),
                                           start_paused=data.get("start_paused", False))
                elif url.path == "/api/sleep":
                    c.sleep(data.get("track"), data.get("minutes"), profile=data.get("profile", "none"))
                elif url.path == "/api/pause":
                    c.set_paused(data.get("paused"))
                elif url.path == "/api/stop":
                    c.stop()
                elif url.path == "/api/settings":
                    # Validate the full request before changing either live or saved settings.
                    if 'allow_track_deletion' in data and type(data['allow_track_deletion']) is not bool:
                        raise ValueError("Allow track deletion must be on or off.")
                    if "audio_buffer_seconds" in data and (type(data["audio_buffer_seconds"]) not in (int, float) or not math.isfinite(data["audio_buffer_seconds"]) or not 0.1 <= data["audio_buffer_seconds"] <= 2.0):
                        raise ValueError("Playback buffer must be between 0.1 and 2.0 seconds.")
                    if "volume" in data and (isinstance(data["volume"], bool) or not isinstance(data["volume"], (int, float)) or not 0 <= data["volume"] <= 100):
                        raise ValueError("Volume must be between 0 and 100.")
                    if "loop" in data and not isinstance(data["loop"], bool):
                        raise ValueError("Loop must be on or off.")
                    if "auto_reconnect" in data and type(data["auto_reconnect"]) is not bool:
                        raise ValueError("Auto reconnect must be on or off.")
                    if "resume_after_restart" in data and type(data["resume_after_restart"]) is not bool:
                        raise ValueError("Resume after restart must be on or off.")
                    if "reconnect_retry_minutes" in data and (type(data["reconnect_retry_minutes"]) is not int or not 1 <= data["reconnect_retry_minutes"] <= 1440):
                        raise ValueError("Bluetooth retry limit must be 1–1440 minutes.")
                    if "sleep_minutes" in data and (type(data["sleep_minutes"]) is not int or not 1 <= data["sleep_minutes"] <= MAX_SLEEP_MINUTES):
                        raise ValueError("Saved sleep duration must be 1–960 minutes.")
                    if "max_upload_bytes" in data and (type(data["max_upload_bytes"]) is not int or not MIB <= data["max_upload_bytes"] <= MAX_UPLOAD_CAP):
                        raise ValueError("Maximum upload size must be between 1 MiB and 50 GiB.")
                    if "storage_reserve_mb" in data and (type(data["storage_reserve_mb"]) is not int or not 0 <= data["storage_reserve_mb"] <= 10240):
                        raise ValueError("Reserved storage must be between 0 and 10240 MiB.")
                    with c.transition_lock:
                        inactive_profile = c.profile_edit_is_inactive(data.get("profile"))
                        if "audio_buffer_seconds" in data:
                            c.set_audio_buffer(data["audio_buffer_seconds"], data.get("editor_session"), data.get("profile"))
                        if "volume" in data:
                            c.check_audio_editor(data.get("editor_session"), data.get("profile"))
                            value = data["volume"]
                            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
                                raise ValueError("Volume must be between 0 and 100.")
                            c.player.command("set_property", "volume", value)
                            c.volume = int(value)
                        if "loop" in data and not inactive_profile:
                            if not isinstance(data["loop"], bool):
                                raise ValueError("Loop must be on or off.")
                            c.set_play_mode("loop" if data["loop"] else "once", data.get("profile"))
                        if "resume_after_restart" in data:
                            c.resume_after_restart = data["resume_after_restart"]
                            if not c.resume_after_restart:
                                c.clear_resume()
                            else:
                                c.resume_last_saved = 0
                                c.persist_resume()
                        if "reconnect_retry_minutes" in data:
                            if c.reconnect_retry_minutes != data["reconnect_retry_minutes"]:
                                c.reconnect_retry_minutes = data["reconnect_retry_minutes"]
                                # Only an actual time-limit change starts a new window.
                                c.reconnect_expires_at = None
                                c.reconnect_next = 0
                        if "auto_reconnect" in data:
                            was_enabled = c.auto_reconnect
                            c.auto_reconnect = data["auto_reconnect"]
                            if c.auto_reconnect and not was_enabled:
                                c.reconnect_suppressed = False
                                c.reconnect_expires_at = None
                                c.reconnect_next = 0
                                c.reconnect_delay = 8
                        if "sleep_minutes" in data and not inactive_profile:
                            c.sleep_minutes = data["sleep_minutes"]
                        if "max_upload_bytes" in data:
                            c.max_upload_bytes = data["max_upload_bytes"]
                        if "storage_reserve_mb" in data:
                            c.storage_reserve_mb = data["storage_reserve_mb"]
                        previous_deletion_setting = c.allow_track_deletion
                        if 'allow_track_deletion' in data:
                            c.allow_track_deletion = data['allow_track_deletion']
                        try:
                            c.save()
                        except Exception:
                            c.allow_track_deletion = previous_deletion_setting
                            raise
                        profile_settings = {key: data[key] for key in ("volume", "sleep_minutes") if key in data}
                        if "loop" in data:
                            profile_settings["play_mode"] = "loop" if data["loop"] else "once"
                        if profile_settings:
                            c.remember_profile_preferences(data.get("profile"), profile_settings)
                elif url.path == "/api/alarm":
                    c.alarm.configure(data)
                elif url.path == "/api/timer":
                    c.set_timer(data.get("minutes"))
                elif url.path == "/api/timer_end":
                    c.set_timer_end(data.get("time"))
                elif url.path == "/api/play_mode":
                    c.set_play_mode(data.get("mode"), data.get("profile"))
                elif url.path == "/api/next":
                    c.skip()
                elif url.path == "/api/previous":
                    c.previous()
                elif url.path == "/api/seek":
                    c.seek(data.get("seconds"))
                elif url.path == "/api/favorite":
                    result=c.set_favorite(data.get("track"),data.get("favorite"),data.get("profile"))
                    return self.reply(200,result)
                elif url.path == "/api/profiles":
                    result = c.profiles.change(data.get("action"),
                        profile=data.get("profile"), name=data.get("name"), enabled=data.get("enabled"))
                    if data.get("action") == "delete":
                        if c.active_profile_id == data.get("profile"):
                            c.observe_listening(playing=False)
                            c.stats_suppressed_session = c.session
                            c.active_profile_id = "none"
                        c.listening_stats.remove_profile(data.get("profile"))
                        c.discovery.remove_profile(data.get("profile"))
                    c.library_revision += 1
                    return self.reply(200, result)
                elif url.path == "/api/profile-data":
                    return self.reply(200, c.profiles.update_preferences(data.get("profile"), data.get("preferences")))
                elif url.path == "/api/audio-meter":
                    return self.reply(200, c.gain_meter.read())
                elif url.path == "/api/audio-edit-lock":
                    return self.reply(200, c.change_audio_edit_lock(data))
                elif url.path == "/api/audio-processing":
                    with c.transition_lock:
                        c.set_audio_processing(data.get("settings"), data.get("expected_revision"), data.get("profile"), data.get("editor_session"))
                        result = c.audio_settings_snapshot()
                    return self.reply(200, result)
                elif url.path == "/api/audio-presets":
                    return self.reply(200, c.audio_presets.change(data))
                elif url.path == "/api/normalization":
                    with c.transition_lock:
                        c.set_normalization(data.get("enabled"), data.get("profile"), data.get("editor_session"))
                        result = c.audio_settings_snapshot()
                    return self.reply(200, result)
                elif url.path == "/api/bluetooth":
                    c.bluetooth_job(data.get("action"), data.get("address"), data.get("confirm"))
                elif url.path == "/api/pairing":
                    if not c.pairing_agent:
                        raise ValueError("Phone pairing service unavailable.")
                    c.pairing_agent.respond(data.get("id"), data.get("approve"), data.get("value"))
                elif url.path == "/api/speaker-sync":
                    with c.transition_lock:
                        if "delta_ms" in data:
                            if type(data["delta_ms"]) is not int or data["delta_ms"] not in (-10, 10):
                                raise ValueError("Sync buttons adjust by 10 ms.")
                            value = max(-500, min(500, read_sync(c.data) + data["delta_ms"]))
                        else:
                            value = data.get("ms")
                        result = save_sync(c.data, value, run, active=c.output == COMBINED_OUTPUT)
                    return self.reply(200, result)
                elif url.path == "/api/output":
                    with c.transition_lock:
                        allowed = [d["name"] for d in c.player.get("audio-device-list", [])]
                        if data.get("name") not in allowed:
                            raise ValueError("That audio output is unavailable.")
                        if not c.player.get("idle-active",True):c.stop()
                        c.validate_bluetooth_output(data["name"], force=True)
                        c.player.command("set_property", "audio-device", data["name"])
                        c.output = data["name"]
                        # Explicit user output selection may still be a Bluetooth sink;
                        # normalize that selected sink only and preserve a matching device.
                        if c.output == COMBINED_OUTPUT:
                            c.speaker = COMBINED_BLUETOOTH_ADDRESS
                        elif c.speaker and c.speaker.replace(":", "_").lower() not in c.output.lower():
                            c.speaker = None
                        c.selected_bluetooth_unity()
                        c.active_output = data["name"]
                        if (c.data / 'speaker-sync.json').exists():
                            apply_sync(read_sync(c.data) if c.output == COMBINED_OUTPUT else 0, run)
                        c.save()
                else:
                    return self.reply(404, {"error": "Not found."})
            self.reply(200, {"ok": True})
        except (ValueError, TypeError, KeyError) as error:
            self.close_connection = True
            self.reply(400, {"error": str(error)})
        except Exception as error:
            LOG.exception("Action failed")
            self.close_connection = True
            self.reply(503, {"error": str(error)[-500:]})

    def upload_artwork(self, length, track, name):
        c = self.server.controller
        c.track(track)
        suffix = Path(name).suffix.lower()
        if suffix not in ARTWORK_CODECS:
            raise ValueError("Choose a JPG, PNG or WebP thumbnail.")
        if not 0 < length <= MAX_ARTWORK_BYTES:
            raise ValueError("Thumbnail must be smaller than 8 MB.")
        if not c.upload_lock.acquire(blocking=False):
            raise ValueError("Another upload is in progress.")
        temporary = c.artwork_dir / (uuid.uuid4().hex + ".pending")
        try:
            if shutil.disk_usage(c.artwork_dir).free < length + c.storage_reserve_mb * MIB:
                raise ValueError("Not enough Pi storage for the thumbnail.")
            with temporary.open("xb") as output:
                remaining = length
                while remaining:
                    block = self.rfile.read(min(MIB, remaining))
                    if not block:
                        raise ValueError("Thumbnail upload was interrupted.")
                    output.write(block)
                    remaining -= len(block)
            try:
                probe = json.loads(run(["ffprobe", "-v", "error", "-protocol_whitelist", "file",
                    "-show_entries", "stream=codec_name,width,height", "-of", "json", str(temporary)], timeout=12))
            except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
                raise ValueError("Could not read this image.") from error
            streams = probe.get("streams", [])
            if not any(s.get("codec_name") == ARTWORK_CODECS[suffix] and
                       type(s.get("width")) is int and type(s.get("height")) is int and
                       1 <= s["width"] <= 8192 and 1 <= s["height"] <= 8192 and
                       s["width"] * s["height"] <= 20_000_000 for s in streams):
                raise ValueError("Invalid or oversized image. Use JPG, PNG or WebP, at most 20 megapixels.")
            key = hashlib.sha256(track.encode("utf-8")).hexdigest()
            extension = ".jpg" if suffix == ".jpeg" else suffix
            destination = c.artwork_dir / (key + extension)
            with c.lock:
                c.track(track)
                temporary.replace(destination)
                for old in (".jpg", ".png", ".webp"):
                    stale = c.artwork_dir / (key + old)
                    if stale != destination:
                        stale.unlink(missing_ok=True)
            c.library_revision += 1
            self.reply(201, {"track": track, "artwork": c.artwork_url(track)})
        finally:
            temporary.unlink(missing_ok=True)
            c.upload_lock.release()

    def upload(self, length, name, key=None):
        c = self.server.controller
        name = re.sub(r"[^\w .()-]", "_", name).strip(" .")
        suffix=Path(name).suffix
        name=name[:max(1,150-len(suffix))]+suffix if len(name)>150 else name
        if key is not None and not re.fullmatch(r"[a-f0-9]{32}",key):
            raise ValueError("Invalid upload receipt.")
        if not 0 < length <= c.max_upload_bytes:
            raise ValueError(f"Choose a nonempty track no larger than {c.max_upload_bytes / GIB:g} GiB.")
        if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError("Unsupported extension. Supported: " + ", ".join(sorted(AUDIO_EXTENSIONS)))
        if not c.upload_lock.acquire(blocking=False):
            raise ValueError("Another upload is in progress.")
        temporary = c.tracks / (uuid.uuid4().hex + ".upload")
        try:
            receipt=c.upload_result(key) if key else {"complete":False}
            if key and "id" in receipt and (receipt["name"]!=name or receipt["size"]!=length):
                raise ValueError("Upload receipt does not match this audio file.")
            if receipt.get("complete"):
                self.close_connection=True
                return self.reply(200,{"id":receipt["id"],"reused":True})
            if key and "id" in receipt:
                destination=c.tracks/receipt["id"]
            else:
                destination=c.tracks/name
                if destination.exists():destination=c.tracks/f"{Path(name).stem} ({uuid.uuid4().hex[:6]}){Path(name).suffix}"
                if key:
                    directory=c.data/"upload-receipts";directory.mkdir(mode=0o700,exist_ok=True)
                    atomic_json(directory/(key+".json"),{"id":destination.name,"name":name,"size":length})
            if shutil.disk_usage(c.tracks).free < length + c.storage_reserve_mb * MIB:
                raise ValueError("Not enough free storage on the Pi.")
            with temporary.open("xb") as output:
                remaining = length
                while remaining:
                    block = self.rfile.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("Upload was interrupted. Please try again.")
                    output.write(block)
                    remaining -= len(block)
            # Force an audio container: a renamed playlist cannot request local/network files.
            try:
                probe = json.loads(run(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-f", FORMATS[Path(name).suffix.lower()], "-show_entries", PROBE_FIELDS, "-of", "json", str(temporary)], timeout=15))
            except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
                raise ValueError("Could not read this audio file. Check the file and format.") from error
            if not any(stream.get("codec_type") == "audio" for stream in probe.get("streams", [])):
                raise ValueError("This file does not contain a supported audio stream.")
            # Destination is reserved in the receipt before publication, so a lost
            # HTTP response never requires creating a duplicate on retry.
            temporary.replace(destination)
            try:
                c.catalog.remember(destination, probe)
                c.discovery.imported(destination.name)
            except (OSError, ValueError) as error:
                LOG.warning("Audio detail cache unavailable after upload: %s", type(error).__name__)
            c.library_revision += 1
            self.reply(201, {"id": destination.name})
        finally:
            temporary.unlink(missing_ok=True)
            c.upload_lock.release()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.umask(0o077)
    data = Path(os.environ.get("SLEEP_SOUNDS_DATA", Path.home() / ".local/share/sleep-sounds"))
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "sleep-sounds"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    player = Player(runtime)
    controller = Controller(data, player)
    from bluetooth_agent import PairingBridge
    controller.pairing_agent = PairingBridge(controller)
    controller.pairing_agent.start()
    hosts = os.environ.get("SLEEP_SOUNDS_HOSTS", "localhost,127.0.0.1").split(",")
    server = Server((os.environ.get("SLEEP_SOUNDS_BIND", "127.0.0.1"), int(os.environ.get("SLEEP_SOUNDS_PORT", "8080"))), controller, hosts)
    try:
        player.start()
        player.command("set_property", "volume", controller.volume)
        player.command("set_property", "loop-file", "inf" if controller.play_mode == "loop" else "no")
        controller.remote_manager.start()
        threading.Thread(target=controller.monitor, daemon=True, name="sleep-sounds-timer").start()
        threading.Thread(target=controller.routing_monitor, daemon=True, name="sleep-sounds-routing").start()
        threading.Thread(target=controller.reconnect_monitor, daemon=True, name="sleep-sounds-reconnect").start()
        threading.Thread(target=controller.alarm_monitor, daemon=True, name="sleep-sounds-alarm").start()
        threading.Thread(target=controller.catalog.warm,
            args=([controller.tracks / row["id"] for row in controller.library()],),
            daemon=True, name="sleep-sounds-detail-cache").start()
        LOG.info("Sleep Sounds ready on port %s", server.server_port)
        server.serve_forever()
    finally:
        controller.closed.set()
        controller.remote_manager.close()
        server.server_close()
        controller.observe_listening(playing=False)
        try:
            controller.listening_stats.flush()
        except (OSError, ValueError):
            LOG.warning("Listening counters could not be saved during shutdown")
        player.close()


if __name__ == "__main__":
    main()
