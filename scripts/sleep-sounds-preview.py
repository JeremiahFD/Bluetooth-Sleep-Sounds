"""Task-owned local UI preview; simulated audio, no Bluetooth commands allowed.

Lifetime: visual QA only. Stop with Ctrl+C in its terminal session.
"""
from pathlib import Path
import os
import sys
import tempfile
import threading
import math
import struct
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Controller, Server
os.environ["SLEEP_SOUNDS_SERVE_UI"] = "true"


class PreviewPlayer:
    def __init__(self):
        self.lock = threading.RLock()
        self.entry = 0
        self.values = {"idle-active": True, "pause": False, "audio-device": "auto", "audio-device-list": [{"name": "auto", "description": "Preview only — no audio"}]}

    def command(self, *args):
        if args[0] == "set_property":
            self.values[args[1]] = args[2]
        elif args[0] == "loadfile":
            self.values["idle-active"] = False
        elif args[0] == "stop":
            self.values["idle-active"] = True
        elif args == ("cycle", "pause"):
            self.values["pause"] = not self.values["pause"]

    def get(self, name, fallback=None):
        return self.values.get(name, fallback)

    def prepare(self):
        pass

    def load(self, path):
        self.entry += 1
        self.command("loadfile", str(path), "replace")
        return {"generation": 1, "entry": self.entry}

    def playback_status(self, receipt):
        return {"status": "started"}


class PreviewController(Controller):
    class PreviewMeter:
        def __init__(self, owner):
            self.owner = owner
            self.active = False
        def read(self):
            if self.owner.player.get('idle-active', True):
                return {"available":False,"input_peak_dbfs":None,"gain_stage_peak_dbfs":None,
                        "output_peak_dbfs":None,"gain_clipping":False,"output_clipping":False}
            before = -18 + 10 * abs(math.sin(time.monotonic() * 2))
            gain = self.owner.audio_processing.get('gain_db', 0)
            after = before + gain
            return {"available":True,"input_peak_dbfs":round(before,1),
                    "gain_stage_peak_dbfs":round(after,1),"output_peak_dbfs":round(min(after,-1),1),
                    "gain_clipping":after>=0,"output_clipping":False}
    def __init__(self, data, player):
        super().__init__(data, player)
        self.gain_meter = self.PreviewMeter(self)
    def status(self):
        result = super().status()
        result["preview"] = True
        return result

    def bluetooth_job(self, *args):
        raise ValueError("Local preview only. Bluetooth testing requires the Pi.")


with tempfile.TemporaryDirectory(prefix="sleep-sounds-preview-") as folder:
    controller = PreviewController(Path(folder), PreviewPlayer())
    if os.environ.get('SLEEP_SOUNDS_PREVIEW_REMOTES') == 'true':
        # Explicit QA fixture only. Never opens input nodes or runs a remote reader.
        from remote_controls import new_layout
        controller.remote_manager.discoverer = lambda: [{'id':'a'*32, 'name':'VR BOX (simulated)',
            'transport':'Preview', 'nodes':[], 'readable':False}, {'id':'b'*32,'name':'SNES USB (simulated)',
            'transport':'Preview','nodes':[],'readable':False}]
        fixture = controller.remote_store.change({'action':'add','revision':0,'device':'a'*32,'name':'VR BOX (preview)'},
            controller.remote_manager.discoverer(), {'none'}, controller.track)
        lid = fixture['remotes'][0]['layout']
        controller.remote_store.change({'action':'save_layout','revision':1,'layout':lid,'values':{
            'modifiers':['k:310'], 'bindings':[
                {'tokens':['k:304'],'modified':False,'action':'play_pause'},
                {'tokens':['k:305'],'modified':False,'action':'normalization'},
                {'tokens':['a:0:+'],'modified':True,'action':'next'}]}}, [], {'none'}, controller.track)
    for filename,frequency in (("Soft Rain demo.wav",220),("Rolling Thunder demo.wav",110)):
        path = controller.tracks / filename
        with wave.open(str(path), 'wb') as sample:
            sample.setnchannels(1);sample.setsampwidth(2);sample.setframerate(16000)
            samples = [struct.pack('<h',int(3200*math.sin(i*2*math.pi*frequency/16000))) for i in range(16000*3)]
            sample.writeframes(b''.join(samples))
        controller.catalog.remember(path, {"streams":[{"codec_type":"audio","codec_name":"pcm_s16le",
            "sample_rate":"16000","channels":1,"bits_per_sample":16,"bit_rate":"256000"}],
            "format":{"duration":"3.000","bit_rate":"256000","format_name":"wav"}})
    controller.power = {"checked": 1e20, "undervoltage": False, "throttled": False}
    preview_port = int(os.environ.get('SLEEP_SOUNDS_PREVIEW_PORT', '8091'))
    server = Server(("127.0.0.1", preview_port), controller, ["127.0.0.1", "localhost"])
    threading.Thread(target=controller.monitor, daemon=True, name="sleep-sounds-preview-timer").start()
    print(f"Bluetooth Sleep Sounds UI preview PID {os.getpid()} on http://127.0.0.1:{preview_port} — simulated audio; stop with Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.closed.set()
        server.server_close()
