"""Own the optional Wired + Bluetooth virtual output; systemd owns this process."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from audio_output import COMBINED_OUTPUT, COMBINED_BT, COMBINED_WIRED
from speaker_sync import read_sync, apply_sync


def configuration():
    name = COMBINED_OUTPUT.split('/', 1)[1]
    return {
        'combine.mode': 'sink', 'node.name': name,
        'node.description': 'Both speakers — Wired + Bluetooth',
        'combine.latency-compensate': True, 'combine.on-demand-streams': True,
        'node.latency': '2048/48000',
        'combine.props': {'audio.position': ['FL', 'FR'], 'priority.session': 0,
                          'node.latency': '2048/48000'},
        'stream.props': {'stream.dont-remix': True, 'node.passive': False,
                         'node.latency': '2048/48000'},
        # Never create eager branches. This helper owns only its two metadata keys.
        'stream.rules': [],
    }



def merge_nodes(nodes, rows):
    """pw-dump -m emits partial updates; retain unchanged node properties."""
    for row in rows:
        key = row.get('id')
        if 'info' in row and row['info'] is None:
            nodes.pop(key, None)
            continue
        if row.get('type') not in ('PipeWire:Interface:Node', 'PipeWire:Interface:Link') and key not in nodes:
            continue
        old = nodes.get(key, {})
        info = dict(old.get('info', {}))
        update = row.get('info') or {}
        props = {**info.get('props', {}), **update.get('props', {})}
        info.update(update)
        info['props'] = props
        nodes[key] = {**old, **row, 'info': info}


def route_plan(nodes, selected):
    """Fresh branches only while the selected virtual sink is processing audio."""
    name = COMBINED_OUTPUT.split('/', 1)[1]
    by_name = {row.get('info', {}).get('props', {}).get('node.name'): row
               for row in nodes.values()}
    sink = by_name.get(name)
    if not sink:
        return None, {}
    # Non-passive members can keep the virtual sink running even after its
    # producer pauses/exits. Follow the actual incoming producer, not that feedback.
    producing = any(row.get('type') == 'PipeWire:Interface:Link'
                    and row.get('info', {}).get('input-node-id') == sink['id']
                    and row.get('info', {}).get('state') == 'active'
                    and nodes.get(row['info'].get('output-node-id'), {}).get('info', {}).get('state') == 'running'
                    for row in nodes.values())
    if selected != COMBINED_OUTPUT or not producing:
        return sink['id'], {}
    members = {}
    for label, target in [('wired', COMBINED_WIRED), ('bluetooth', COMBINED_BT)]:
        physical = by_name.get(target.split('/', 1)[1])
        if physical:
            props = physical['info']['props']
            members[label] = (physical['id'], props.get('object.serial'))
    return sink['id'], members


def member_properties(label):
    target = {'wired': COMBINED_WIRED, 'bluetooth': COMBINED_BT}[label]
    name = COMBINED_OUTPUT.split('/', 1)[1]
    return {'target.object': target.split('/', 1)[1],
            'node.group': name + '.' + label,
            'node.link-group': name + '.' + label,
            'resample.disable': False}


class GraphWatch:
    def __init__(self):
        self.nodes = {}
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.error = None
        self.child = subprocess.Popen(['pw-dump', '-m'], stdout=subprocess.PIPE,
                                      text=True, bufsize=1)
        self.thread = threading.Thread(target=self.read, daemon=True,
                                       name='sleep-sounds-output-graph')
        self.thread.start()

    def read(self):
        chunks = []
        size = 0
        try:
            for line in self.child.stdout:
                chunks.append(line)
                size += len(line)
                if size > 8 * 1024 * 1024:
                    raise RuntimeError('PipeWire graph update exceeded bounded buffer')
                # pw-dump's pretty monitor output ends each top-level array in
                # column zero. Decode once per batch, never once per growing line.
                if not line.startswith(']'):
                    continue
                rows = json.loads(''.join(chunks))
                chunks.clear(); size = 0
                if not isinstance(rows, list):
                    raise RuntimeError('Unexpected PipeWire graph update')
                with self.lock:
                    merge_nodes(self.nodes, rows)
                self.changed.set()
        except Exception as error:
            self.error = type(error).__name__
        finally:
            self.changed.set()

    def snapshot(self):
        with self.lock:
            return dict(self.nodes)

    def close(self):
        if self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill(); self.child.wait(timeout=5)
        self.thread.join(timeout=1)
        self.child.stdout.close()


def metadata(sink, label, value=None):
    argv = ['pw-metadata', '-n', 'default', str(sink), 'combine.on-demand-stream.' + label]
    if value is not None:
        argv += [json.dumps(value), 'Spa:String:JSON']
    else:
        argv.insert(1, '--delete')
    subprocess.run(argv, stdout=subprocess.DEVNULL, check=True, timeout=5)


def main():
    done = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: done.set())
    child = subprocess.Popen(['pw-cli'], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, text=True)
    watcher = None
    applied = {}
    sink_id = None
    try:
        child.stdin.write('load-module libpipewire-module-combine-stream ' + json.dumps(configuration()) + '\n')
        child.stdin.flush()
        watcher = GraphWatch()
        data = Path(__file__).resolve().parent.parent
        last_sync = None
        last_attempt = {}
        print('Sleep Sounds on-demand combined output started; members follow actual playback.', flush=True)
        while not done.is_set():
            if child.poll() is not None or watcher.child.poll() is not None or watcher.error:
                raise RuntimeError('Combined output graph owner exited')
            watcher.changed.wait(1)
            watcher.changed.clear()
            try:
                selected = json.loads((data / 'settings.json').read_text()).get('output')
                nodes = watcher.snapshot()
                current_id, desired = route_plan(nodes, selected)
                if current_id != sink_id:
                    applied.clear(); last_attempt.clear(); last_sync = None
                    sink_id = current_id
                if sink_id is None:
                    continue
                for label in set(applied) - set(desired):
                    metadata(sink_id, label)
                    del applied[label]
                    last_attempt.pop(label, None)
                for label, signature in desired.items():
                    expected = 'output.' + COMBINED_OUTPUT.split('/', 1)[1] + '_' + label
                    present = any(row.get('info', {}).get('props', {}).get('node.name') == expected
                                  for row in nodes.values())
                    retry = not present and time.monotonic() - last_attempt.get(label, 0) >= 5
                    if applied.get(label) != signature or retry:
                        metadata(sink_id, label, member_properties(label))
                        applied[label] = signature
                        last_attempt[label] = time.monotonic()
                sync = read_sync(data) if desired else 0
                # apply_sync checks exact node offsets; no repeated writes to unchanged nodes.
                if sync != last_sync or any(time.monotonic() - t < 1 for t in last_attempt.values()):
                    apply_sync(sync, lambda argv, timeout: subprocess.check_output(argv, text=True, timeout=timeout))
                    last_sync = sync
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print('Combined output pending: ' + type(error).__name__, flush=True)
            done.wait(.2)
    finally:
        if sink_id is not None:
            for label in list(applied):
                try: metadata(sink_id, label)
                except (OSError, subprocess.SubprocessError): pass
        if watcher is not None:
            watcher.close()
        if child.poll() is None:
            try:
                child.stdin.write('quit\n'); child.stdin.flush(); child.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                child.terminate(); child.wait(timeout=5)
        if child.stdin: child.stdin.close()


if __name__ == '__main__':
    main()
