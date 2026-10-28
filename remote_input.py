"""Bounded Linux evdev reader for explicitly selected USB/Bluetooth input groups.

No root web server, synthetic input, subprocess polling or global keyboard hook.
Exclusive EVIOCGRAB is applied to every event node in the selected physical group.
"""
from __future__ import annotations

import copy
import hashlib
import logging
import os
from pathlib import Path
import queue
import re
import selectors
import stat
import struct
import sys
import threading
import time

from remote_controls import ACTIONS, InputPolicy, Learning, StickAxis, TOKEN

LOG = logging.getLogger('sleep-sounds.remotes')
EVENT = struct.Struct('@llHHi')  # Native kernel long, including 32-bit Pi input_event.
EVIOCGRAB = 0x40044590
AXES = (0, 1, 2, 3, 4, 5, 16, 17)


def _read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ''


def discover(sys_input=Path('/sys/class/input'), dev_input=Path('/dev/input')):
    """Group composite mouse/keyboard/gamepad interfaces by a stable device identity.

    Bluetooth uses unique address + vendor/product, USB uses physical USB parent +
    optional serial. Never group unrelated same-name controllers or accept API paths.
    """
    if sys.platform != 'linux':
        return []
    groups = {}
    for entry in sorted(sys_input.glob('event*')):
        if not re.fullmatch(r'event[0-9]+', entry.name):
            continue
        device = entry / 'device'
        bus = _read(device / 'id/bustype')
        if bus not in ('0003', '0005'):  # USB, Bluetooth only; exclude platform/power devices.
            continue
        vendor, product = _read(device / 'id/vendor'), _read(device / 'id/product')
        uniq = _read(device / 'uniq').lower()
        physical = device.resolve()
        usb_parent = next((p for p in physical.parents if (p / 'idVendor').exists()), None)
        if bus == '0005':
            # A BT peripheral with no stable address cannot safely be re-identified.
            if not re.fullmatch(r'[a-f0-9]{2}(?::[a-f0-9]{2}){5}', uniq):
                continue
            identity = f'bt:{uniq}:{vendor}:{product}'
        elif usb_parent:
            identity = f'usb:{usb_parent.name}:{_read(usb_parent / "serial")}:{vendor}:{product}'
        else:
            continue
        identifier = hashlib.sha256(identity.encode()).hexdigest()[:32]
        row = groups.setdefault(identifier, {'id': identifier, 'name': _read(device / 'name') or 'Controller',
            'transport': 'Bluetooth' if bus == '0005' else 'USB', 'nodes': [], 'readable': True})
        node = str(dev_input / entry.name)
        row['nodes'].append(node)
        row['readable'] &= os.access(node, os.R_OK)
    return list(groups.values())[:32]


class LinuxNode:
    def __init__(self, path, exclusive, dead_zone):
        import fcntl
        self.fd = None
        self.axes = {}
        self.held = set()
        self.buffer = b''
        try:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
            info = os.fstat(self.fd)
            if not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 13:
                raise OSError('Not a Linux input device')
            if exclusive:
                fcntl.ioctl(self.fd, EVIOCGRAB, 1)
            keys = bytearray(96)
            fcntl.ioctl(self.fd, 0x80004518 | (len(keys) << 16), keys, True)
            self.held = {f'k:{i}' for i in range(768) if keys[i // 8] & (1 << (i % 8))}
            for code in AXES:
                values = bytearray(24)
                try:
                    fcntl.ioctl(self.fd, 0x80184540 + code, values, True)
                except OSError:
                    continue
                value, minimum, maximum, *_ = struct.unpack('@iiiiii', values)
                unipolar = code in (2, 5) and minimum == 0 and value <= minimum + (maximum - minimum) * .05
                axis = self.axes[code] = StickAxis(minimum, maximum, dead_zone, unipolar)
                for direction, down in axis.update(value):
                    if down:
                        self.held.add(f'a:{code}:{"+" if direction > 0 else "-"}')
        except Exception:
            self.close()
            raise

    def read(self):
        raw = os.read(self.fd, EVENT.size * 128)
        if not raw:
            raise OSError('Remote disconnected')
        self.buffer += raw
        result = []
        while len(self.buffer) >= EVENT.size:
            _, _, kind, code, value = EVENT.unpack(self.buffer[:EVENT.size])
            self.buffer = self.buffer[EVENT.size:]
            if kind == 0 and code == 3:  # SYN_DROPPED: discard this session; re-open from current state.
                raise OSError('Input buffer overflow; release all buttons and reconnect')
            changes = []
            if kind == 1 and value in (0, 1):  # EV_KEY; value 2 is OS autorepeat, ignored.
                changes = [(f'k:{code}', value == 1)]
            elif kind == 3 and code in self.axes:
                changes = [(f'a:{code}:{"+" if direction > 0 else "-"}', down)
                           for direction, down in self.axes[code].update(value)]
            # EV_REL motion never invokes actions; grabbing still suppresses it on the desktop.
            for token, down in changes:
                if down:
                    self.held.add(token)
                else:
                    self.held.discard(token)
                result.append((token, down))
        return result

    def close(self):
        if self.fd is not None:
            fd = self.fd
            self.fd = None
            try:
                os.close(fd)  # Kernel releases exclusive grab even on process death.
            except OSError:
                pass


class RemoteManager:
    def __init__(self, store, dispatch, discoverer=discover, node_factory=LinuxNode):
        self.store, self.dispatch = store, dispatch
        self.discoverer, self.node_factory = discoverer, node_factory
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.wake = threading.Event()
        self.sessions = {}
        self.health = {}
        self.learning = None
        self.suspended = False
        self.generation = 0
        self.actions = queue.Queue(maxsize=16)
        self.thread = None
        self.worker = None
        self.supported = sys.platform == 'linux'
        self.allowed = os.environ.get('SLEEP_SOUNDS_REMOTES', 'on').lower() != 'off'
        self.devices = []
        self.discovery_at = -float('inf')

    def _devices(self):
        if time.monotonic() - self.discovery_at >= 3:
            self.devices = self.discoverer()
            self.discovery_at = time.monotonic()
        return self.devices

    def start(self):
        if self.thread or not self.supported or not self.allowed:
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name='sleep-sounds-remote-input')
        self.worker = threading.Thread(target=self._actions, daemon=True, name='sleep-sounds-remote-actions')
        self.thread.start(); self.worker.start()

    def snapshot(self):
        with self.lock:
            learn = self.learning
            learning = None
            if learn:
                learning = {'id': learn.id, 'remote': learn.remote,
                    'seconds': max(0, round(learn.deadline - time.monotonic(), 1)),
                    'result': learn.result, 'expired': time.monotonic() >= learn.deadline}
            return {**self.store.snapshot(), 'devices': copy.deepcopy(self._devices()), 'actions': ACTIONS,
                'supported': self.supported, 'allowed': self.allowed, 'suspended': self.suspended,
                'service_running': bool(self.thread and self.thread.is_alive()),
                'runtime': copy.deepcopy(self.health), 'learning': learning}

    def invalidate(self):
        with self.lock:
            self.generation += 1
            self.learning = None
            self._close_all()
            self.wake.set()

    def release_all(self):
        with self.lock:
            self.suspended = True
            self.invalidate()

    def resume(self):
        with self.lock:
            self.suspended = False
            self.invalidate()

    def learn(self, remote, modifier=False):
        with self.lock:
            if not self.supported or not self.allowed or self.suspended or not self.thread or not self.thread.is_alive():
                raise ValueError('Remote input is unavailable or released. Resume input on the Pi first.')
            if self.learning and time.monotonic() < self.learning.deadline and not self.learning.result:
                raise ValueError('Another button field is listening. Cancel it first.')
            state = self.store.snapshot()
            row = next((r for r in state['remotes'] if r['id'] == remote), None)
            if not row:
                raise ValueError('Choose a saved remote.')
            if not row['app_only']:
                raise ValueError('Turn on App only and save before learning, so presses cannot affect the desktop.')
            layout = next(l for l in state['layouts'] if l['id'] == row['layout'])
            self.generation += 1
            self.learning = Learning(remote, [] if modifier else layout['modifiers'])
            self._close(remote)  # Re-open only this remote, with a neutral-state gate.
            self.discovery_at = -float('inf')
            self._sync()  # Never tell the client to press buttons before isolation succeeds.
            if remote not in self.sessions:
                message = self.health.get(remote, {}).get('error', 'Connect the selected remote before listening.')
                self.learning = None
                self.generation += 1
                self.wake.set()
                raise ValueError(message)
            self.wake.set()
            return {'id': self.learning.id}

    def cancel(self, identifier):
        with self.lock:
            if self.learning and self.learning.id == identifier:
                remote = self.learning.remote
                self.learning = None
                self.generation += 1
                self._close(remote)
                self.wake.set()

    def _close(self, rid):
        session = self.sessions.pop(rid, None)
        if session:
            self.generation += 1  # Reject queued input from before disconnect/reacquisition.
            for node in session['nodes']:
                node.close()
        self.health[rid] = {'state': 'released', 'app_only_active': False}

    def _close_all(self):
        for rid in list(self.sessions):
            self._close(rid)

    def _sync(self):
        if self.learning and time.monotonic() >= self.learning.deadline:
            remote = self.learning.remote
            self.learning = None
            self.generation += 1
            self._close(remote)
        state = self.store.snapshot()
        devices = {d['id']: d for d in self._devices()}
        live_learning = self.learning and not self.learning.result and time.monotonic() < self.learning.deadline
        desired = set()
        if self.suspended or not self.allowed:
            self._close_all()
            return
        for remote in state['remotes']:
            rid = remote['id']
            if not remote['enabled'] and not (live_learning and self.learning.remote == rid):
                continue
            desired.add(rid)
            device = devices.get(remote['device'])
            if not device:
                self._close(rid)
                self.health[rid] = {'state': 'disconnected', 'app_only_active': False}
                continue
            existing = self.sessions.get(rid)
            if existing and existing['paths'] == device['nodes']:
                continue
            self._close(rid)
            layout = next(l for l in state['layouts'] if l['id'] == remote['layout'])
            nodes = []
            try:
                for path in device['nodes']:
                    nodes.append(self.node_factory(path, remote['app_only'], layout['dead_zone']))
                self.sessions[rid] = {'nodes': nodes, 'paths': device['nodes'], 'remote': copy.deepcopy(remote),
                    # Some composite HID remotes advertise unused stick axes resting at
                    # an endpoint. Those must not block every independent button.
                    # Initial axis directions never enter the policy; their first
                    # release is ignored, so connection cannot itself invoke an action.
                    'policy': InputPolicy(layout),
                    'blocked': (not layout['any_button'] and
                                any(t.startswith('k:') for n in nodes for t in n.held)),
                    'generation': self.generation}
                self.health[rid] = {'state': 'ready', 'app_only_active': remote['app_only']}
            except (OSError, PermissionError) as error:
                for node in nodes:
                    node.close()
                self.health[rid] = {'state': 'unavailable', 'app_only_active': False,
                    'error': 'Input access denied or busy. Device permissions and all remote interfaces must be available.'}
                # No partial grab is left active; no actions run on an incompletely isolated group.
        for rid in list(self.sessions):
            if rid not in desired:
                self._close(rid)

    def _run(self):
        try:
            next_sync = 0
            while not self.closed.is_set():
                with self.lock:
                    if self.learning and time.monotonic() >= self.learning.deadline:
                        self.wake.set()
                    if self.wake.is_set() or time.monotonic() >= next_sync:
                        self.wake.clear(); self._sync(); next_sync = time.monotonic() + 3
                    with selectors.DefaultSelector() as selector:
                        for rid, session in self.sessions.items():
                            for node in session['nodes']:
                                selector.register(node.fd, selectors.EVENT_READ, (rid, node))
                        ready = selector.select(0)  # Never block while holding API/configuration lock.
                    for key, _ in ready:
                        rid, node = key.data
                        session = self.sessions.get(rid)
                        if not session:
                            continue
                        try:
                            changes = node.read()
                            if changes:
                                health = self.health[rid]
                                health['input_count'] = health.get('input_count', 0) + len(changes)
                                health['recent_inputs'] = (health.get('recent_inputs', []) +
                                    [{'token': token, 'down': down} for token, down in changes])[-12:]
                                health['waiting_for_release'] = session['blocked']
                            if session['blocked']:
                                if not any(t.startswith('k:') for n in session['nodes'] for t in n.held):
                                    session['blocked'] = False
                                continue
                            for token, down in changes:
                                learning = self.learning
                                if learning and learning.remote == rid:
                                    # Suppress ALL actions throughout learning/result/timeout until explicitly closed.
                                    learning.event(token, down)
                                    continue
                                action = session['policy'].event(token, down)
                                if action and session['remote']['enabled']:
                                    self.health[rid]['last_action'] = action
                                    try:
                                        self.actions.put_nowait((self.generation, copy.deepcopy(session['remote']), action))
                                    except queue.Full:
                                        self.health[rid]['error'] = 'Too many pending actions; input was dropped.'
                        except OSError:
                            self._close(rid)
                            self.health[rid] = {'state': 'disconnected', 'app_only_active': False}
                self.wake.wait(0.05 if self.sessions else 0.2)
        except Exception:
            LOG.exception('Remote input reader stopped; all device captures released')
        finally:
            with self.lock:
                self.generation += 1
                self._close_all()

    def dispatch_if_current(self, generation, remote, action):
        """Caller holds controller.lock before this check, keeping config/actions ordered."""
        with self.lock:
            session = self.sessions.get(remote['id'])
            if (self.closed.is_set() or self.suspended or generation != self.generation or not session
                    or (self.learning and self.learning.remote == remote['id'])):
                return False
            return True

    def _actions(self):
        while not self.closed.is_set():
            try:
                generation, remote, action = self.actions.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.dispatch(self, generation, remote, action)
            except Exception as error:
                with self.lock:
                    self.health.setdefault(remote['id'], {})['error'] = str(error)[:180]
                LOG.warning('Remote action %s failed: %s', action, type(error).__name__)

    def close(self):
        self.closed.set(); self.wake.set()
        with self.lock:
            self.generation += 1
            self._close_all()
        for thread in (self.thread, self.worker):
            if thread:
                thread.join(timeout=2)
