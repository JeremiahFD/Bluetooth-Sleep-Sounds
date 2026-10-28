"""Persistent remote layouts and platform-independent input policy.

Interaction adapted from AI Browser's BrowserButtonCapture/Bindings/Layouts:
full press/release, no OS autorepeat, bounded learning, conflict replacement + Undo.
Linux device access is kept in remote_input.py, not in this policy module.
"""
from __future__ import annotations

import copy
import json
import math
import re
import secrets
import threading
import time

from persistence import atomic_json

CURRENT_TRACK = '@current'

ACTIONS = {
    "none": "Do nothing", "play_pause": "Play / pause", "play_stop": "Play / stop", "play_default": "Play default sound",
    "sleep_default": "Start default sound with sleep timer", "stop": "Stop",
    "next": "Next track", "previous": "Previous track", "loop": "Toggle loop",
    "normalization": "Toggle normalization", "volume_up": "Volume up", "volume_down": "Volume down",
    "timer": "Set saved sleep timer", "cancel_timer": "Cancel sleep timer",
    "processing": "Toggle audio processing",
}
TOKEN = re.compile(r"^(?:k:[0-9]{1,3}|a:(?:0|1|2|3|4|5|16|17):[+-])$")
ID = re.compile(r"^[a-f0-9]{16}$")


def name_of(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40 or any(ord(c) < 32 for c in value):
        raise ValueError("Use a name with 1–40 printable characters.")
    return value.strip()


def tokens_of(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 4 or any(not isinstance(v, str) or not TOKEN.fullmatch(v) for v in value):
        raise ValueError("Choose one to four buttons or stick directions.")
    if len(set(value)) != len(value) or any(v.startswith('k:') and int(v[2:]) > 767 for v in value):
        raise ValueError("Invalid or duplicate input.")
    return sorted(value)


def binding_key(tokens, modified=False):
    return ('m|' if modified else 'r|') + ','.join(sorted(tokens))


def validate_layout(value):
    if not isinstance(value, dict):
        raise ValueError("Expected a controller layout.")
    result = copy.deepcopy(value)
    result['name'] = name_of(value.get('name'))
    for key, default in [('regular_delay', 0.3), ('modified_delay', 0.3), ('dead_zone', 0.35)]:
        number = value.get(key, default)
        if type(number) not in (float, int) or not math.isfinite(number) or not 0 <= number <= (0.8 if key == 'dead_zone' else 60):
            raise ValueError("Delays must be 0–60 seconds; stick dead zone must be 0–0.8.")
        result[key] = float(number)
    for key in ('any_button',):
        if type(value.get(key, False)) is not bool:
            raise ValueError("Expected an on/off setting.")
        result[key] = value.get(key, False)
    result['any_action'] = value.get('any_action', 'play_pause')
    if result['any_action'] not in ACTIONS:
        raise ValueError("Choose an available action.")
    modifiers = value.get('modifiers', [])
    if not isinstance(modifiers, list) or len(modifiers) > 2:
        raise ValueError("Choose up to two modifier buttons.")
    result['modifiers'] = tokens_of(modifiers) if modifiers else []
    bindings = value.get('bindings', [])
    if not isinstance(bindings, list) or len(bindings) > 48:
        raise ValueError("A layout supports up to 48 assignments.")
    keys = set()
    result['bindings'] = []
    for row in bindings:
        if not isinstance(row, dict) or row.get('action') not in ACTIONS or type(row.get('modified')) is not bool:
            raise ValueError("Invalid assignment.")
        item = {**row, 'tokens': tokens_of(row.get('tokens'))}
        key = binding_key(item['tokens'], item['modified'])
        if key in keys:
            raise ValueError("That combination is already assigned. Replace it or choose another.")
        if item['modified'] and set(item['tokens']) & set(modifiers):
            raise ValueError("A modified assignment must use separate action buttons.")
        keys.add(key)
        result['bindings'].append(item)
    return result


def new_layout(name='Bedtime'):
    return validate_layout({'id': secrets.token_hex(8), 'name': name, 'bindings': []})


class RemoteStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.state = {'version': 1, 'revision': 0, 'remotes': [], 'layouts': []}
        self.read_error = False
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or value.get('version') != 1 or type(value.get('revision')) is not int or value['revision'] < 0:
                raise ValueError()
            if not isinstance(value.get('remotes'), list) or not isinstance(value.get('layouts'), list) or len(value['remotes']) > 16 or len(value['layouts']) > 32:
                raise ValueError()
            layouts = [validate_layout(row) for row in value['layouts']]
            ids = [row.get('id') for row in layouts]
            if any(not isinstance(i, str) or not ID.fullmatch(i) for i in ids) or len(set(ids)) != len(ids):
                raise ValueError()
            seen = set()
            devices = set()
            for row in value['remotes']:
                self.validate_remote(row, ids)
                if row['id'] in seen or row['device'] in devices:
                    raise ValueError()
                seen.add(row['id']); devices.add(row['device'])
            self.state = {**value, 'layouts': layouts}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError):
            self.read_error = True

    @staticmethod
    def validate_remote(row, layouts):
        if not isinstance(row, dict) or not ID.fullmatch(str(row.get('id', ''))) or not isinstance(row.get('device'), str) or not re.fullmatch(r'[a-f0-9]{32}', row['device']):
            raise ValueError("Choose a detected USB or Bluetooth controller.")
        name_of(row.get('name'))
        if row.get('layout') not in layouts or any(type(row.get(k)) is not bool for k in ('enabled', 'app_only')):
            raise ValueError("Invalid remote settings.")
        if row.get('profile') != 'none' and not ID.fullmatch(str(row.get('profile', ''))):
            raise ValueError("Choose a user profile.")
        if row.get('default_track') is not None and (not isinstance(row['default_track'], str) or len(row['default_track']) > 255):
            raise ValueError("Choose a default sound.")

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({**self.state, 'read_error': self.read_error})

    def change(self, data, devices, profiles, validate_track):
        with self.lock:
            if self.read_error:
                raise ValueError("Remote settings need repair; the existing file has been preserved.")
            if type(data.get('revision')) is not int or data['revision'] != self.state['revision']:
                raise ValueError("Remote settings changed elsewhere. Reload before saving.")
            state = copy.deepcopy(self.state)
            action = data.get('action')
            remote = next((r for r in state['remotes'] if r['id'] == data.get('remote')), None)
            layout = next((r for r in state['layouts'] if r['id'] == data.get('layout')), None)
            if action == 'add':
                if len(state['remotes']) >= 16 or len(state['layouts']) >= 32:
                    raise ValueError("Remote or layout limit reached.")
                device = next((d for d in devices if d['id'] == data.get('device')), None)
                if not device or any(r['device'] == device['id'] for r in state['remotes']):
                    raise ValueError("Choose a detected remote that has not already been added.")
                existing_names = {l['name'].casefold() for l in state['layouts']}
                layout_name = 'Bedtime'
                suffix = 2
                while layout_name.casefold() in existing_names:
                    layout_name = f'Bedtime {suffix}'; suffix += 1
                layout = new_layout(layout_name)
                state['layouts'].append(layout)
                state['remotes'].append({'id': secrets.token_hex(8), 'device': device['id'],
                    'name': name_of(data.get('name', device['name'][:40])), 'layout': layout['id'],
                    'profile': 'none', 'default_track': None, 'enabled': False, 'app_only': True})
            elif action == 'save_remote' and remote:
                fields = data.get('values')
                if not isinstance(fields, dict) or set(fields) - {'name','enabled','app_only','profile','layout','default_track'}:
                    raise ValueError("Invalid remote settings.")
                remote.update(fields)
                self.validate_remote(remote, [l['id'] for l in state['layouts']])
                if remote['profile'] not in profiles:
                    raise ValueError("That user profile no longer exists.")
                if remote['default_track'] and remote['default_track'] != CURRENT_TRACK:
                    validate_track(remote['default_track'])
            elif action == 'remove' and remote:
                state['remotes'].remove(remote)  # Layouts are reusable; removing a remote doesn't remove them.
            elif action == 'save_layout' and layout:
                fields = data.get('values')
                if not isinstance(fields, dict) or set(fields) - {'name','bindings','modifiers','any_button','any_action','regular_delay','modified_delay','dead_zone'}:
                    raise ValueError("Invalid controller layout.")
                updated = validate_layout({**layout, **fields})
                if any(l['id'] != layout['id'] and l['name'].casefold() == updated['name'].casefold() for l in state['layouts']):
                    raise ValueError("A layout with that name already exists.")
                state['layouts'][state['layouts'].index(layout)] = updated
            elif action == 'copy_layout' and layout:
                if len(state['layouts']) >= 32:
                    raise ValueError("Layout limit reached.")
                name = name_of(data.get('name'))
                if any(l['name'].casefold() == name.casefold() for l in state['layouts']):
                    raise ValueError("A layout with that name already exists.")
                state['layouts'].append({**copy.deepcopy(layout), 'id': secrets.token_hex(8), 'name': name})
            elif action == 'delete_layout' and layout:
                if any(r['layout'] == layout['id'] for r in state['remotes']):
                    raise ValueError("Choose another layout for its remotes before deleting this layout.")
                state['layouts'].remove(layout)
            else:
                raise ValueError("Choose an available remote or layout action.")
            state['revision'] += 1
            atomic_json(self.path, state)
            self.state = state
            return self.snapshot()


class InputPolicy:
    """One logical physical remote. Modifier persists until release; no held-key repeat.

    Actions occur on release, so a chord suppresses its constituent single actions.
    Exactly two cooldown buckets exist across the entire remote, not per binding.
    """
    def __init__(self, layout, clock=time.monotonic):
        self.layout = validate_layout(layout)
        self.clock = clock
        self.held = set()
        self.peak = set()
        self.modified = False
        self.used_modifiers = set()
        self.fired = False
        self.last = {False: -math.inf, True: -math.inf}

    def event(self, token, down):
        modifiers = set(self.layout['modifiers'])
        if self.layout['any_button']:
            # An override is one action per new input press, not a chord.
            # Composite HID remotes can leave unrelated keys held indefinitely.
            # EV_KEY autorepeat is rejected by the reader; the shared cooldown
            # suppresses duplicate interfaces without waiting for all releases.
            if not down:
                self.held.discard(token)
                return None
            self.held.add(token)
            modified = token in modifiers or bool(self.held & modifiers)
            return self._action([token], modified)
        if down:
            if token in self.held:
                return None
            self.held.add(token)
            ordinary = self.held - modifiers
            if ordinary:
                self.peak |= ordinary
                self.modified |= bool(self.held & modifiers)
                if self.modified:
                    self.used_modifiers |= self.held & modifiers
            return None
        if token not in self.held:
            return None
        self.held.remove(token)
        result = None
        if token in modifiers:
            if token not in self.used_modifiers and not self.peak:
                result = self._action([token], False, cooldown_modified=True)
            self.used_modifiers.discard(token)
        elif self.peak and not self.fired:
            result = self._action(self.peak, self.modified)
            self.fired = True
        if not self.held - modifiers:
            self.peak.clear()
            self.modified = False
            self.fired = False
        return result

    def _action(self, tokens, modified, cooldown_modified=None):
        action = self.layout['any_action'] if self.layout['any_button'] else next((r['action'] for r in self.layout['bindings']
            if r['modified'] == modified and set(r['tokens']) == set(tokens)), 'none')
        bucket = modified if cooldown_modified is None else cooldown_modified
        now = self.clock()
        delay = self.layout['modified_delay' if bucket else 'regular_delay']
        if action == 'none' or now - self.last[bucket] < delay:
            return None
        self.last[bucket] = now
        return action


class Learning:
    def __init__(self, remote, modifiers=(), clock=time.monotonic):
        self.id = secrets.token_hex(12)
        self.remote = remote
        self.modifiers = set(modifiers)
        self.clock = clock
        self.deadline = clock() + 20
        self.held = set()
        self.peak = set()
        self.modified = False
        self.result = None

    def event(self, token, down):
        if self.clock() >= self.deadline or self.result:
            return
        if down:
            if token in self.held:
                return
            self.held.add(token)
            ordinary = self.held - self.modifiers
            if ordinary:
                self.peak |= ordinary
                self.modified |= bool(self.held & self.modifiers)
        elif token in self.held:
            self.held.remove(token)
            if self.peak and not self.held - self.modifiers:
                self.result = {'tokens': sorted(self.peak), 'modified': self.modified}
            elif not self.held and not self.peak:
                self.result = {'tokens': [token], 'modified': False}


class StickAxis:
    def __init__(self, minimum, maximum, dead_zone, unipolar=False):
        self.minimum, self.maximum, self.dead_zone = minimum, maximum, dead_zone
        self.unipolar = unipolar
        self.direction = 0

    def update(self, value):
        if self.maximum <= self.minimum:
            return []
        normalized = ((value - self.minimum) / (self.maximum - self.minimum) if self.unipolar else
                      (value - (self.maximum + self.minimum) / 2) / ((self.maximum - self.minimum) / 2))
        threshold = max(0.05, self.dead_zone - (0.1 if self.direction else 0))
        direction = (1 if normalized > threshold else -1 if normalized < -threshold else 0)
        if direction == self.direction:
            return []
        result = []
        if self.direction:
            result.append((self.direction, False))
        if direction:
            result.append((direction, True))
        self.direction = direction
        return result
