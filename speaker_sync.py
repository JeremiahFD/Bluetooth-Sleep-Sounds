"""Bounded relative sync for the fixed combined output; no codec/DSP changes."""
import json
from pathlib import Path
from persistence import atomic_json
from audio_output import COMBINED_BT, COMBINED_WIRED


def validate_ms(value):
    if type(value) is not int or not -500 <= value <= 500:
        raise ValueError("Speaker sync must be a whole number from -500 to 500 ms.")
    return value


def read_sync(data):
    try:
        return validate_ms(json.loads((Path(data) / 'speaker-sync.json').read_text())['ms'])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def snapshot(data):
    return {'ms': read_sync(data), 'step_ms': 10, 'min_ms': -500, 'max_ms': 500}


def offsets(ms):
    validate_ms(ms)
    # Reporting more latency on one member makes combine-stream delay the other.
    return {COMBINED_WIRED.split('/', 1)[1]: max(ms, 0) * 1000000,
            COMBINED_BT.split('/', 1)[1]: max(-ms, 0) * 1000000}


def apply_sync(ms, run):
    desired = offsets(ms)
    rows = json.loads(run(['pw-dump'], timeout=5))
    for row in rows:
        info = row.get('info', {})
        name = info.get('props', {}).get('node.name')
        if name not in desired:
            continue
        props = info.get('params', {}).get('Props', [])
        current = next((p['latencyOffsetNsec'] for p in props if 'latencyOffsetNsec' in p), None)
        target = desired[name]
        if current == target:
            continue
        # Exact node ID comes only from PipeWire, never user input.
        run(['pw-cli', 'set-param', str(row['id']), 'Props',
             '{ latencyOffsetNsec = ' + str(target) + ' }'], timeout=5)


def save_sync(data, value, run, active=True):
    value = validate_ms(value)
    previous = read_sync(data)
    path = Path(data) / 'speaker-sync.json'
    atomic_json(path, {'ms': value})
    try:
        apply_sync(value if active else 0, run)
    except Exception:
        atomic_json(path, {'ms': previous})
        try:
            apply_sync(previous if active else 0, run)
        except Exception:
            pass
        raise
    return snapshot(data)
