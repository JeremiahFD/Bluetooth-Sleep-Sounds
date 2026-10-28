"""Versioned audio presets. Named records are data, never filenames or filter code."""
from copy import deepcopy
import json
import re
import threading
import unicodedata
from audio_processing import validate_audio_settings
from persistence import atomic_json

MAX_PRESETS = 64
MAX_NAME = 64
MAX_FILE_BYTES = 262144
PRESONUS = "https://www.presonus.com/blogs/technical/how-to-use-dynamics-processing-getting-started-with-compressors-gates-and-more"
SSL = "https://solidstatelogic.com/products/big-six"
FFMPEG = "https://ffmpeg.org/ffmpeg-filters.html"

def factory(identifier, name, description, icon, changes, source, note, url=FFMPEG):
    return {"id": identifier, "name": name, "description": description, "icon": icon,
            "kind": "builtin", "settings": validate_audio_settings(changes),
            "source": {"label": source, "url": url, "note": note}}

# These are transparent starting points, not analog emulations or listening-verified claims.
BUILTIN_PRESETS = [
    factory("flat", "Flat", "Natural & clean", "wave", {}, "Neutral app settings",
            "No gain, EQ or dynamics. Separate optional normalization is unchanged by presets."),
    factory("master-glue", "Master Glue", "Mix-bus control", "levels",
            {"compressor_enabled": True, "compressor_threshold_db": -18, "compressor_ratio": 4,
             "compressor_attack_ms": 30, "compressor_release_ms": 100, "limiter_enabled": True},
            "SSL-inspired starting point", "Uses the documented BiG SiX 4:1 ratio, 30 ms attack and 100 ms release. The -18 dBFS threshold and peak limiter are app choices. This is not an SSL circuit emulation; adjust threshold for your recording.", SSL),
    factory("voice-focus", "Voice Focus", "Less low-end weight", "voice",
            {"eq_enabled": True, "eq_bands": 5, "eq_bass_db": -3, "eq_lowmid_db": -1,
             "eq_presence_db": 2, "gain_db": -2, "limiter_enabled": True},
            "App EQ starting point", "A broad low-frequency cut and presence lift; not a published factory preset or speech-isolation filter. Input trim leaves room for the boost. Audition for harshness."),
    factory("warm-sleep", "Warm Sleep", "Softer high end", "moon",
            {"eq_enabled": True, "eq_treble_db": -3},
            "App EQ starting point", "A 3 dB broad cut at 8 kHz. Reduces brightness, not a medical sleep treatment or a universal speaker correction."),
    factory("soft-limiter", "Soft Limiter", "Control high peaks", "wave",
            {"limiter_enabled": True, "limiter_ceiling_db": -2, "limiter_attack_ms": 5, "limiter_release_ms": 100},
            "App peak-control starting point", "FFmpeg sample-peak limiting at -2 dBFS, 5 ms lookahead, 100 ms release, automatic leveling off. The name describes the intended light use, not a soft-clipping circuit or true-peak guarantee."),
    factory("rain-focus", "Rain Focus", "Less rumble, more detail", "rain",
            {"eq_enabled": True, "eq_bands": 5, "eq_bass_db": -3, "eq_lowmid_db": -1,
             "eq_presence_db": 1.5, "eq_treble_db": 1, "gain_db": -3, "limiter_enabled": True},
            "App EQ starting point", "A modest detail lift and rumble reduction. It cannot isolate rain from a mixed recording. Values are not auditioned on your speakers."),
    factory("gentle-overheads", "Gentle Dynamics", "Low-ratio smoothing", "levels",
            {"compressor_enabled": True, "compressor_threshold_db": -20, "compressor_ratio": 1.3,
             "compressor_attack_ms": 27, "compressor_release_ms": 128, "limiter_enabled": True},
            "BlueMAX-inspired: stereo overheads", "Ratio 1.3:1, attack 27 ms and release 128 ms match PreSonus's published overhead starting point. Its -13.7 dB hardware threshold is not assumed equivalent to dBFS; the app starts at -20 dBFS. Different detector and knee: not a hardware clone.", PRESONUS),
    factory("piano-balance", "Piano Balance", "Slower gentle control", "music",
            {"compressor_enabled": True, "compressor_threshold_db": -18, "compressor_ratio": 1.9,
             "compressor_attack_ms": 108, "compressor_release_ms": 112, "limiter_enabled": True},
            "BlueMAX-inspired: piano", "Uses the published 1.9:1 ratio, 108 ms attack and 112 ms release. The app's -18 dBFS threshold is an adaptation, not the source's -10.8 dB hardware calibration. Listen and adjust; no analog emulation.", PRESONUS),
    factory("transient-control", "Transient Control", "Keep the initial attack", "wave",
            {"compressor_enabled": True, "compressor_threshold_db": -18, "compressor_ratio": 3.5,
             "compressor_attack_ms": 78, "compressor_release_ms": 300, "limiter_enabled": True},
            "BlueMAX-inspired: snare / kick", "Uses the published 3.5:1 ratio, 78 ms attack and 300 ms release. Threshold is an app digital starting point, not the -2.1 dB hardware threshold. Slow attack allows the beginning of a transient through; the final limiter handles peaks.", PRESONUS),
]

def preset_name(value):
    if not isinstance(value, str):
        raise ValueError("Enter a preset name.")
    name = unicodedata.normalize("NFC", value).strip()
    if not name or len(name) > MAX_NAME or any(unicodedata.category(c).startswith('C') for c in name):
        raise ValueError("Preset names need 1 to 64 characters, without control characters.")
    return name

def preset_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("Invalid custom preset ID.")
    return value

class AudioPresetStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.revision = 0
        self.records = []
        self.error = None
        if not path.exists():
            return
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("Preset file exceeds supported size.")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get('version') != 1:
                raise ValueError("Unsupported preset file version.")
            if type(data.get('revision')) is not int or data['revision'] < 0:
                raise ValueError("Invalid preset revision.")
            records = data.get('presets')
            if not isinstance(records, list) or len(records) > MAX_PRESETS:
                raise ValueError("Invalid preset list.")
            clean, ids, names = [], set(), set()
            for record in records:
                if not isinstance(record, dict): raise ValueError("Invalid preset record.")
                identifier, name = preset_id(record.get('id')), preset_name(record.get('name'))
                if identifier in ids or name.casefold() in names: raise ValueError("Duplicate preset record.")
                ids.add(identifier); names.add(name.casefold())
                clean.append({'id':identifier,'name':name,'kind':'custom','settings':validate_audio_settings(record.get('settings'))})
            self.records, self.revision = clean, data['revision']
        except (OSError, ValueError, TypeError, KeyError):
            # Do not overwrite an unreadable or future-version user data file.
            self.error = "Saved presets could not be read. The original preset file is preserved; saving is disabled until it is recovered."

    def snapshot(self):
        with self.lock:
            return {'builtin':deepcopy(BUILTIN_PRESETS),'custom':deepcopy(self.records),
                    'revision':self.revision,'limit':MAX_PRESETS,'error':self.error}

    def change(self, payload):
        if not isinstance(payload,dict): raise ValueError("Expected a preset request.")
        if set(payload)-{'action','id','name','settings','expected_revision'}:
            raise ValueError("Unknown preset request field.")
        action=payload.get('action')
        if action not in {'create','update','rename','delete'}: raise ValueError("Unknown preset action.")
        identifier=preset_id(payload.get('id'))
        with self.lock:
            if self.error: raise ValueError(self.error)
            index=next((i for i,r in enumerate(self.records) if r['id']==identifier),None)
            name=preset_name(payload.get('name')) if action in {'create','rename'} else None
            settings=validate_audio_settings(payload.get('settings')) if action in {'create','update'} else None
            # Retry a create with the same identity/payload after a lost response without duplicating it.
            if action=='create' and index is not None:
                current=self.records[index]
                if current['name']==name and current['settings']==settings: return self.snapshot()
                raise ValueError("That preset identity already exists. Reload the preset list.")
            expected=payload.get('expected_revision')
            if type(expected) is not int or expected != self.revision:
                raise ValueError("Presets changed on another device. Reload the preset list before saving.")
            records=deepcopy(self.records)
            if action=='create':
                if len(records)>=MAX_PRESETS: raise ValueError("You can save up to 64 custom presets. Remove one first.")
                records.append({'id':identifier,'name':name,'kind':'custom','settings':settings})
            else:
                if index is None: raise ValueError("That custom preset no longer exists.")
                if action=='delete': records.pop(index)
                elif action=='rename': records[index]['name']=name
                else: records[index]['settings']=settings
            names=[r['name'].casefold() for r in records]
            if len(names)!=len(set(names)): raise ValueError("A custom preset with that name already exists. Choose a different name.")
            if records==self.records: return self.snapshot()
            revision=self.revision+1
            atomic_json(self.path,{'version':1,'revision':revision,'presets':records})
            self.records,self.revision=records,revision
            return self.snapshot()
