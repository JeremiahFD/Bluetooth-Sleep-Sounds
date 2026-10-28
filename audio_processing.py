"""Validated app-owned DSP. Original recordings and hardware volume are untouched."""
import math
from copy import deepcopy
import threading
import time

NORMALIZATION_GRAPH = ("dynaudnorm=f=250:g=21:p=0.89:m=2:r=0.12:b=0,"
                       "alimiter=limit=0.891:level=0:attack=5:release=100:latency=1")
DEFAULT_AUDIO_SETTINGS = {
    "noise1_enabled": False, "noise1_color": "pink", "noise1_db": -36.0,
    "noise2_enabled": False, "noise2_color": "brown", "noise2_db": -36.0,
    "bypass": False, "gain_db": 0.0, "gain_enabled": True,
    "rack_order": ["gain", "eq", "compressor", "limiter"],
    "echo_enabled": False, "echo_delay_ms": 180.0, "echo_decay": 0.2,
    "normalization_strength": "balanced", "normalization_ceiling_db": -1.0,
    "limiter_enabled": False, "limiter_ceiling_db": -1.0,
    "limiter_attack_ms": 5.0, "limiter_release_ms": 100.0,
    "compressor_enabled": False, "compressor_threshold_db": -24.0,
    "compressor_ratio": 2.0, "compressor_attack_ms": 20.0,
    "compressor_release_ms": 250.0, "compressor_makeup_db": 0.0,
    "eq_enabled": False, "eq_bands": 3,
    "eq_bass_db": 0.0, "eq_lowmid_db": 0.0, "eq_mid_db": 0.0, "eq_presence_db": 0.0, "eq_treble_db": 0.0,
}
NOISE_COLORS = ("white", "pink", "brown", "blue", "violet", "velvet")
RACK_EFFECTS = ("gain", "eq", "compressor", "limiter", "echo")
NUMERIC_RANGES = {
    "noise1_db": (-60.0, -12.0), "noise2_db": (-60.0, -12.0),
    "echo_delay_ms": (10.0, 2000.0), "echo_decay": (0.01, 0.6),
    "normalization_ceiling_db": (-12.0, 0.0),
    "gain_db": (-12.0, 18.0), "limiter_ceiling_db": (-12.0, 0.0),
    "limiter_attack_ms": (0.1, 80.0), "limiter_release_ms": (1.0, 2000.0),
    "compressor_threshold_db": (-60.0, 0.0), "compressor_ratio": (1.0, 20.0),
    "compressor_attack_ms": (0.1, 200.0), "compressor_release_ms": (10.0, 2000.0),
    "compressor_makeup_db": (0.0, 18.0),
    "eq_bass_db": (-12.0, 12.0), "eq_lowmid_db": (-12.0, 12.0),
    "eq_mid_db": (-12.0, 12.0), "eq_presence_db": (-12.0, 12.0), "eq_treble_db": (-12.0, 12.0),
}

ENUM_VALUES = {"eq_bands": (3, 5)}
NORMALIZATION_STRENGTHS = {"light": 1.5, "balanced": 2.0, "night": 2.5}
EQ_FREQUENCIES = {"eq_bass_db": 125, "eq_lowmid_db": 500, "eq_mid_db": 1000, "eq_presence_db": 4000, "eq_treble_db": 8000}

def validate_audio_settings(values, current=None):
    """Merge only typed, bounded fields; never accept arbitrary filter expressions."""
    if not isinstance(values, dict):
        raise ValueError("Audio processing settings must be an object.")
    # New fields receive defaults when loading older settings or presets.
    result = deepcopy(DEFAULT_AUDIO_SETTINGS)
    if current is not None:
        result.update(validate_audio_settings(current))
    for key, value in values.items():
        if key not in DEFAULT_AUDIO_SETTINGS:
            raise ValueError("Unknown audio processing setting: " + str(key))
        if key == 'rack_order':
            if (not isinstance(value, list) or len(value) > len(RACK_EFFECTS)
                    or any(type(v) is not str or v not in RACK_EFFECTS for v in value)
                    or len(set(value)) != len(value)):
                raise ValueError('Effect order must contain unique supported effects.')
            result[key] = list(value)
        elif key in ENUM_VALUES:
            if type(value) is not int or value not in ENUM_VALUES[key]:
                raise ValueError("EQ bands must be 3 or 5.")
            result[key] = value
        elif key in ('noise1_color', 'noise2_color'):
            if type(value) is not str or value not in NOISE_COLORS:
                raise ValueError('Choose a supported noise color.')
            result[key] = value
        elif key == 'normalization_strength':
            if type(value) is not str or value not in NORMALIZATION_STRENGTHS:
                raise ValueError('Normalization strength must be light, balanced, or night.')
            result[key] = value
        elif key in NUMERIC_RANGES:
            low, high = NUMERIC_RANGES[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{key.replace('_', ' ')} must be between {low:g} and {high:g}.")
            result[key] = float(value)
        else:
            if type(value) is not bool:
                raise ValueError(key.replace('_', ' ') + " must be on or off.")
            result[key] = value
    return result

def _n(value):
    return format(value, '.10g')

def _amplitude(db):
    return _n(10 ** (db / 20))

def normalization_graph(settings):
    """Bounded presets retain the legacy sound and ceiling at the defaults."""
    if settings['normalization_strength'] == 'balanced' and settings['normalization_ceiling_db'] == -1:
        return NORMALIZATION_GRAPH
    maximum = NORMALIZATION_STRENGTHS[settings['normalization_strength']]
    return ('dynaudnorm=f=250:g=21:p=0.89:m=' + _n(maximum) + ':r=0.12:b=0,'
            'alimiter=limit=' + _amplitude(settings['normalization_ceiling_db']) +
            ':level=0:attack=5:release=100:latency=1')

def manual_filter_chain(s, source_sample_rate=None):
    """Only app-owned filters; list order is the audible order. No file rewrite."""
    stages = {}
    if s['gain_enabled'] and s['gain_db']:
        stages['gain'] = ['volume=' + _n(s['gain_db']) + 'dB:precision=float']
    if s['eq_enabled']:
        eq = []
        keys = ('eq_bass_db', 'eq_mid_db', 'eq_treble_db') if s['eq_bands'] == 3 else tuple(EQ_FREQUENCIES)
        if (type(source_sample_rate) in (int, float) and 0 < source_sample_rate <= 16000
                and any(s[k] and EQ_FREQUENCIES[k] >= source_sample_rate / 2 for k in keys)):
            eq.append('aresample=32000')
        for key in keys:
            if s[key]:
                eq.append(f'equalizer=f={EQ_FREQUENCIES[key]}:t=q:w=0.7:g=' + _n(s[key]))
        stages['eq'] = eq
    if s['compressor_enabled']:
        stages['compressor'] = ['acompressor=threshold=' + _amplitude(s['compressor_threshold_db']) +
            ':ratio=' + _n(s['compressor_ratio']) + ':attack=' + _n(s['compressor_attack_ms']) +
            ':release=' + _n(s['compressor_release_ms']) + ':makeup=' + _amplitude(s['compressor_makeup_db']) +
            ':knee=2.828427:link=maximum:detection=peak:mode=downward']
    if s['limiter_enabled']:
        stages['limiter'] = ['alimiter=limit=' + _amplitude(s['limiter_ceiling_db']) + ':level=0:attack=' +
            _n(s['limiter_attack_ms']) + ':release=' + _n(s['limiter_release_ms']) + ':latency=1']
    if s['echo_enabled']:
        # Leave headroom for the delayed copy; decay0.6 means a maximum1.6 sum.
        # No feedback loop, automatic makeup, downsampling or lossy encoding.
        stages['echo'] = ['aecho=in_gain=1:out_gain=' + _n(1 / (1 + s['echo_decay'])) +
            ':delays=' + _n(s['echo_delay_ms']) + ':decays=' + _n(s['echo_decay'])]
    return [f for effect in s['rack_order'] for f in stages.get(effect, [])]

def noise_mix_graph(s, processing, rate=None):
    """Two bounded procedural layers; the first (recording) input owns duration.
    Mix at the recording's rate; unknown rate uses FFmpeg's first-input negotiation.
    No generated PCM crosses the network, no full-length temporary noise files.
    """
    active = [i for i in (1, 2) if s[f'noise{i}_enabled']]
    if not active:
        return processing
    sample_rate = int(rate) if type(rate) in (int, float) and 8000 <= rate <= 384000 else 48000
    dry = processing or 'anull'
    parts = ['[in]' + dry + '[dry]']
    for i in active:
        parts.append(f"anoisesrc=r={sample_rate}:c={s[f'noise{i}_color']}:a={_amplitude(s[f'noise{i}_db'])},afade=t=in:d=0.03[noise{i}]")
    inputs = '[dry]' + ''.join(f'[noise{i}]' for i in active)
    parts.append(inputs + f'amix=inputs={1+len(active)}:duration=first:dropout_transition=0:normalize=0,'
                 'alimiter=limit=0.8912509381:level=0:attack=5:release=100:latency=1[out]')
    return ';'.join(parts)

# A short rolling group preserves transient peaks between the phone's polls.
METER_FILTER = 'lavfi=[astats=metadata=1:reset=12:measure_perchannel=none:measure_overall=Peak_level+RMS_level]'
METER_INPUT_LABEL = 'sleep_meter_input'
METER_OUTPUT_LABEL = 'sleep_meter_output'

def audio_filter_graph(settings=None, normalization=False, meter=False, source_sample_rate=None):
    if type(normalization) is not bool:
        raise ValueError("Normalization must be on or off.")
    if type(meter) is not bool:
        raise ValueError("Meter must be on or off.")
    s = validate_audio_settings({} if settings is None else settings)
    processing = ''
    if normalization:
        # Normalization owns the chain while enabled. Manual settings remain
        # saved so they can be restored by switching back to the DSP page.
        processing = '@sleep_normalization:lavfi=[' + normalization_graph(s) + ']'
    elif not s['bypass']:
        filters = manual_filter_chain(s, source_sample_rate)
        if filters:
            processing = '@sleep_processing:lavfi=[aformat=sample_fmts=fltp,' + ','.join(filters) + ']'
    if (normalization or not s['bypass']) and any(s[f'noise{i}_enabled'] for i in (1, 2)):
        # Unwrap the owned graph before adding parallel generators inside one filter.
        dry = normalization_graph(s) if normalization else ','.join(manual_filter_chain(s, source_sample_rate))
        processing = '@sleep_processing:lavfi=[' + noise_mix_graph(s, dry, source_sample_rate) + ']'
    if not meter:
        return processing
    # The probes pass audio through unchanged. They run only while a page asks for
    # metering; the server removes them when that page's short lease expires.
    return ','.join(part for part in (
        '@' + METER_INPUT_LABEL + ':' + METER_FILTER,
        processing,
        '@' + METER_OUTPUT_LABEL + ':' + METER_FILTER,
    ) if part)

def _peak_db(metadata):
    if not isinstance(metadata, dict):
        return None
    try:
        value = float(metadata['lavfi.astats.Overall.Peak_level'])
    except (KeyError, TypeError, ValueError):
        return None
    # Silence is -inf in FFmpeg. Omit it rather than emitting invalid JSON.
    return max(-96.0, min(24.0, value)) if math.isfinite(value) else None

def gain_meter_snapshot(player, settings, normalization=False):
    """Return finite, bounded peaks from mpv's in-chain metadata, with no PCM transfer."""
    s = validate_audio_settings(settings)
    before = _peak_db(player.get('af-metadata/' + METER_INPUT_LABEL))
    output = _peak_db(player.get('af-metadata/' + METER_OUTPUT_LABEL))
    gain = s['gain_db'] if not s['bypass'] and not normalization and s['gain_enabled'] and 'gain' in s['rack_order'] else 0.0
    gain_first = bool(s['rack_order']) and s['rack_order'][0] == 'gain'
    after_gain = min(42.0, before + gain) if before is not None and gain_first else None
    return {'available': before is not None, 'input_peak_dbfs': before,
            'gain_stage_peak_dbfs': after_gain, 'output_peak_dbfs': output,
            'gain_clipping': after_gain is not None and after_gain >= 0.0,
            'output_clipping': output is not None and output >= 0.0}

class GainMeter:
    """Short, page-renewed lease for in-chain metering on the shared player.

    Controller.lock serializes this with playback, DSP edits, and alarm changes.
    The filter chain is only changed at lease start/end, never for each sample.
    """
    LEASE_SECONDS = 4.0

    def __init__(self, controller):
        self.controller = controller
        self.active = False
        self.deadline = 0.0
        self._timer = None

    def _schedule(self, delay):
        timer = threading.Timer(max(0.05, delay), self._expire)
        timer.daemon = True
        timer.name = 'sleep-sounds-gain-meter-lease'
        self._timer = timer
        timer.start()

    def _expire(self):
        c = self.controller
        with c.transition_lock:
            if not self.active:
                return
            remaining = self.deadline - time.monotonic()
            if remaining > 0:
                self._schedule(remaining)
                return
            self.active = False
            self._timer = None
            try:
                apply_normalization(c.player, c.normalization and c.mode != 'alarm',
                                    c.audio_processing if c.mode != 'alarm' else {'bypass': True})
            except (OSError, RuntimeError, ValueError):
                # The meter is observational. An unavailable player must not keep
                # a timer running or fail an otherwise healthy request.
                pass

    def read(self):
        c = self.controller
        unavailable = {'available': False, 'input_peak_dbfs': None,
                       'gain_stage_peak_dbfs': None, 'output_peak_dbfs': None,
                       'gain_clipping': False, 'output_clipping': False}
        with c.transition_lock:
            if c.mode in ('idle', 'alarm'):
                return unavailable
            if c.player.get('pause', False):
                return unavailable
            self.deadline = time.monotonic() + self.LEASE_SECONDS
            if not self.active:
                try:
                    apply_normalization(c.player, c.normalization, c.audio_processing, meter=True)
                except (OSError, RuntimeError, ValueError):
                    try:
                        apply_normalization(c.player, c.normalization, c.audio_processing)
                    except (OSError, RuntimeError, ValueError):
                        pass
                    return unavailable
                self.active = True
                self._schedule(self.LEASE_SECONDS)
            return gain_meter_snapshot(c.player, c.audio_processing, c.normalization)

def apply_normalization(player, enabled, settings=None, meter=False, source_sample_rate=None):
    """Apply one complete chain so changing normalization cannot erase gain/EQ/dynamics."""
    if source_sample_rate is None:
        params = player.get('audio-params')
        source_sample_rate = params.get('samplerate') if isinstance(params, dict) else None
    player.command('af', 'set', audio_filter_graph(settings, enabled, meter, source_sample_rate))
