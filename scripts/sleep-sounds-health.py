"""Read-only, bounded diagnostics for Sleep Sounds. No playback commands."""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
import urllib.request

STOP = threading.Event()
LOCK = threading.Lock()
BOOT = Path('/proc/sys/kernel/random/boot_id')
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user/1000'))
LAST = {}


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def command(args, timeout=2, max_chars=32768):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return result.stdout[:max_chars] if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def emit(kind, **fields):
    with LOCK:
        print(json.dumps(dict(event=kind, utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                              monotonic=round(time.monotonic(), 3), **fields), allow_nan=False), flush=True)


def changed(kind, value):
    if kind not in LAST or LAST[kind] != value:
        LAST[kind] = value
        emit(kind, value=value)


def pressures():
    return {key: read('/proc/pressure/' + key) for key in ('cpu', 'memory', 'io')}


def memory():
    result = {}
    for line in (read('/proc/meminfo') or '').splitlines():
        key, val = line.split(':', 1)
        if key in ('MemAvailable', 'SwapFree', 'SwapTotal'):
            result[key + '_kib'] = int(val.split()[0])
    return result


def process_usage(cgroup):
    # Some Pi kernels omit cgroup memory/I/O and PSI controllers. /proc works
    # without enabling controllers or changing audio service accounting.
    rss_kib = 0
    io_bytes = {'read_bytes': 0, 'write_bytes': 0}
    count = 0
    for pid in (read(cgroup / 'cgroup.procs') or '').split():
        if not pid.isdigit():
            continue
        status = read('/proc/' + pid + '/status') or ''
        for line in status.splitlines():
            if line.startswith('VmRSS:'):
                rss_kib += int(line.split()[1])
                count += 1
        for line in (read('/proc/' + pid + '/io') or '').splitlines():
            key, value = line.split(':', 1)
            if key in io_bytes:
                io_bytes[key] += int(value)
    return {'process_count': count, 'rss_kib_sum': rss_kib, **io_bytes}


def api_state():
    # Never persist CSRF, media filenames, MACs, pairing codes or request bodies.
    with urllib.request.urlopen('http://127.0.0.1:8080/api/status', timeout=2) as response:
        data = json.loads(response.read(262144))
    keys = ('idle', 'paused', 'mode', 'session_id', 'output_ready', 'clock_ready',
            'timer_ends_at', 'audio_processing_revision', 'auto_reconnect',
            'reconnect_suppressed', 'resume_after_restart')
    result = {key: data.get(key) for key in keys}
    result['playback_error_present'] = bool(data.get('playback_error'))
    result['bluetooth_busy'] = bool(data.get('bluetooth', {}).get('busy'))
    # Hashed identifiers and a bounded timeline locate future failures
    # without persisting filenames, output addresses, profiles or source content.
    for source, dest in [('selected', 'track_fingerprint'), ('active_output', 'output_fingerprint')]:
        value = data.get(source)
        result[dest] = hashlib.sha256(value.encode()).hexdigest()[:16] if isinstance(value, str) else None
    for source, dest in [('position', 'position_seconds'), ('duration', 'duration_seconds')]:
        value = data.get(source)
        result[dest] = round(value, 3) if type(value) in (int, float) and math.isfinite(value) else None
    return result


def graph_serials(text):
    try:
        rows = json.loads(text or '[]')
        return {str(row['id']): str(row['info']['props']['object.serial']) for row in rows
                if row.get('type') == 'PipeWire:Interface:Node'
                and row.get('info', {}).get('props', {}).get('object.serial') is not None}
    except (ValueError, TypeError, KeyError):
        return {}


def graph_increments(previous, current, serials):
    # A fresh pw-top subscription can briefly report zero before its profiler
    # update. Preserve the high-water mark for the same node serial; do not turn
    # a placeholder reset/recovery into a new glitch. A new serial is a baseline.
    live = {(node, serial) for node, serial in serials.items()}
    baselines = {key: value for key, value in previous.items() if key in live}
    increments = {}
    for node, value in current.items():
        if node not in serials:
            continue
        key = (node, serials[node])
        if key in baselines and value > baselines[key]:
            increments[node] = value - baselines[key]
        baselines[key] = max(value, baselines.get(key, value))
    return increments, baselines


def graph_errors(text):
    """Ignore creating rows: pw-top's first frame precedes profiler counters."""
    result = {}
    for line in (text or '').splitlines():
        parts = line.split()
        if (len(parts) >= 10 and parts[0] in ('R', 'S', 'I', 'E')
                and parts[1].isdigit() and parts[8].isdigit()):
            result[parts[1]] = int(parts[8])
    return result


def mpv_events():
    """Independent IPC client: observe only; subscriptions do not alter audio."""
    properties = ('pause', 'idle-active', 'paused-for-cache', 'eof-reached', 'audio-device')
    while not STOP.is_set():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(2)
                conn.connect(str(RUNTIME / 'sleep-sounds/player.sock'))
                for index, prop in enumerate(properties):
                    conn.sendall((json.dumps({'command': ['observe_property', index, prop]}) + '\n').encode())
                conn.sendall(b'{"command":["request_log_messages","warn"]}\n')
                emit('player_observer_connected')
                buffer = b''
                last_warning = {}
                while not STOP.is_set():
                    try:
                        part = conn.recv(8192)
                    except socket.timeout:
                        continue
                    if not part:
                        break
                    buffer += part
                    if len(buffer) > 65536:
                        raise ValueError('oversize IPC line')
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        event = json.loads(line)
                        kind = event.get('event')
                        if kind == 'property-change':
                            name = event.get('name')
                            if name in properties:
                                val = event.get('data')
                                if name == 'audio-device':
                                    val = hashlib.sha256(str(val).encode()).hexdigest()[:12]
                                emit('player_property', name=name, value=val)
                        elif kind in ('start-file', 'file-loaded', 'end-file', 'shutdown', 'audio-reconfig'):
                            emit('player_event', name=kind, reason=event.get('reason'),
                                 error=event.get('file_error'), entry=event.get('playlist_entry_id'))
                        elif kind == 'log-message':
                            # Retain diagnostic category, never mpv's arbitrary text (may contain paths).
                            key = (str(event.get('prefix', ''))[:80], str(event.get('level', ''))[:20])
                            now = time.monotonic()
                            if now - last_warning.get(key, -60) >= 60:
                                emit('player_warning', component=key[0], level=key[1])
                                if len(last_warning) > 128:
                                    last_warning.clear()
                                last_warning[key] = now
                emit('player_observer_disconnected')
        except (OSError, ValueError):
            emit('player_observer_unavailable')
        STOP.wait(30)


def main():
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    emit('observer_start', boot_id=read(BOOT), pid=os.getpid(), interval_seconds=30)
    threading.Thread(target=mpv_events, daemon=True, name='sleep-sounds-health-mpv').start()
    previous_graph = {}
    iteration = 0
    while not STOP.is_set():
        started = time.monotonic()
        try:
            flags = command(['vcgencmd', 'get_throttled'])
            changed('power_flags', flags.strip() if flags else None)
            try:
                changed('app_state', api_state())
            except Exception as error:
                # Class only: urllib exception strings can carry URLs or response content.
                changed('app_state', {'unavailable': type(error).__name__})
            if iteration % 2 == 0:
                service = command(['systemctl', '--user', 'show', 'sleep-sounds.service',
                                   '-p', 'MainPID', '-p', 'NRestarts', '-p', 'ActiveState',
                                   '-p', 'ExecMainStatus', '-p', 'Result', '-p', 'ControlGroup'])
                fields = dict(line.split('=', 1) for line in (service or '').splitlines() if '=' in line)
                changed('app_service', fields)
                group = fields.get('ControlGroup', '')
                cgroup = Path('/sys/fs/cgroup') / group.lstrip('/')
                wireless = read('/proc/net/wireless') or ''
                wlan = next((line.split(':', 1)[1].split()[:4] for line in wireless.splitlines() if 'wlan0:' in line), None)
                stat = os.statvfs(str(Path.home()))
                # The first batch frame can contain only C/creating placeholders.
                # Allow a profiler update before reporting counts as observed.
                graph_text = command(['pw-top', '-b', '-n', '2'], timeout=4)
                graph = graph_errors(graph_text)
                serials = graph_serials(command(['pw-dump'], timeout=4, max_chars=2 * 1024 * 1024))
                increments = {}
                if serials:
                    increments, previous_graph = graph_increments(previous_graph, graph, serials)
                if increments:
                    emit('audio_graph_errors_increased', increments=increments)
                emit('health', temperature_millic=read('/sys/class/thermal/thermal_zone0/temp'),
                     cpu_khz=read('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq'),
                     load=read('/proc/loadavg'), cpu_ticks=read('/proc/stat').splitlines()[0],
                     memory=memory(), pressure=pressures(), wlan=wlan,
                     disk_free_bytes=stat.f_bavail * stat.f_frsize,
                     app_cpu=read(cgroup / 'cpu.stat'), app_memory_bytes=read(cgroup / 'memory.current'),
                     app_io=read(cgroup / 'io.stat'), app_processes=process_usage(cgroup), graph_errors=graph,
                     graph_probe_ok=bool(graph), graph_identity_probe_ok=bool(serials))
            iteration += 1
        except Exception as error:
            emit('observer_sample_error', error_class=type(error).__name__)
        STOP.wait(max(1, 30 - (time.monotonic() - started)))
    emit('observer_stop')


if __name__ == '__main__':
    main()
