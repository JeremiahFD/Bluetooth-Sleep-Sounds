"""On-demand, bounded host facts; no playback-thread work or new monitoring service."""
import json
import os
import re
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
import sys
import uuid
from host_maintenance import CONFIRMATIONS, validate_request

STARTED=time.monotonic()

def read(path):
    try:return Path(path).read_text(encoding='utf-8').strip()[:8192]
    except (OSError,ValueError):return None

def interfaces():
    result=[]
    try:
        import fcntl
        import struct
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            for _,name in socket.if_nameindex()[:64]:
                if name=='lo':continue
                try:
                    address=socket.inet_ntoa(fcntl.ioctl(sock.fileno(),0x8915,struct.pack('256s',name.encode()[:15]))[20:24])
                except OSError:address=None
                result.append({'name':name,'ipv4':address,'state':read('/sys/class/net/'+name+'/operstate')})
    except (ImportError,OSError,AttributeError):pass
    return result


def diagnostic_export(c):
    events=[];available=False
    if platform.system()=='Linux':
        try:
            command=['journalctl','--user','-u','sleep-sounds.service','-u','sleep-sounds-health.service',
                     '--since=-15min','-n','40','--no-pager','-o','json','--output-fields=__REALTIME_TIMESTAMP,PRIORITY,MESSAGE']
            # Bounded command/output. Journald does the filtering; no continuously running reader.
            with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL) as process:
                try:
                    raw,_=process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill();process.communicate();raw=b''
                if process.returncode==0 and len(raw)<=131072:
                    available=True
                    for line in raw.splitlines()[-40:]:
                        try:
                            item=json.loads(line);message=str(item.get('MESSAGE',''))[:500]
                            if re.search(r'password|passkey|secret|csrf|token|private.key|BEGIN .* KEY|authorization:',message,re.I):
                                message='[Sensitive event omitted]'
                            events.append({'timestamp_us':item.get('__REALTIME_TIMESTAMP'),'priority':item.get('PRIORITY'),'message':message})
                        except (ValueError,TypeError):continue
        except OSError:pass
    return {'captured_at':time.time(),'system':system_snapshot(c),'events_available':available,
            'window_minutes':15,'max_events':40,'events':events}


def system_snapshot(c):
    memory={}
    for line in (read('/proc/meminfo') or '').splitlines():
        key,_,value=line.partition(':')
        if key in ('MemTotal','MemAvailable'):
            try:memory[key]=int(value.split()[0])*1024
            except (ValueError,IndexError):pass
    try:uptime=float((read('/proc/uptime') or '').split()[0])
    except (ValueError,IndexError):uptime=None
    try:temperature=int(read('/sys/class/thermal/thermal_zone0/temp'))/1000
    except (ValueError,TypeError):temperature=None
    try:load=list(os.getloadavg())
    except (AttributeError,OSError):load=None
    usage=shutil.disk_usage(c.tracks)
    network=interfaces();addresses=[row['ipv4'] for row in network if row['ipv4']]
    enabled=os.environ.get('SLEEP_SOUNDS_HOST_ACTIONS')=='true' and platform.system()=='Linux'
    return {'host':socket.gethostname(),'model':(read('/proc/device-tree/model') or '').rstrip('\x00') or None,
        'os':platform.platform(),'app_version':'0.7.0-library','uptime_seconds':uptime,
        'app_uptime_seconds':round(time.monotonic()-STARTED),'memory_total_bytes':memory.get('MemTotal'),
        'memory_available_bytes':memory.get('MemAvailable'),'load_average':load,'temperature_c':temperature,
        'storage_free_bytes':usage.free,'storage_total_bytes':usage.total,'addresses':addresses,'interfaces':network,
        'audio_output':c.output,'bluetooth':dict(c.bt),'power':dict(c.power),
        'remote_count':len(c.remote_store.snapshot()['remotes']),
        'capabilities':{'restart_app':enabled and bool(shutil.which('systemd-run')),
                        **{action:enabled and bool(shutil.which('systemd-run')) for action in CONFIRMATIONS},
                        'restart_host':enabled and Path('/usr/local/sbin/sleep-sounds-power').is_file(),
                        'shutdown':enabled and Path('/usr/local/sbin/sleep-sounds-power').is_file()}}

def system_action(c,data):
    action=data.get('action')
    if action not in ('restart_app','restart_host','shutdown',*CONFIRMATIONS) or data.get('confirm') is not True:
        raise ValueError('Confirm a supported system action.')
    if action in CONFIRMATIONS:validate_request(data)
    if not system_snapshot(c)['capabilities'][action]:raise ValueError('System actions are not enabled on this host.')
    if action=='restart_app' or action in CONFIRMATIONS:
        # Independent transient unit survives stopping the player. Stop finishes before
        # modifying files; restarting reloads clean state instead of stale in-memory data.
        command=['systemd-run','--user','--collect','--on-active=1s',
                 '--unit=sleep-sounds-maintenance-'+uuid.uuid4().hex,
                 sys.executable,str(Path(__file__).with_name('host_maintenance.py')),
                 '--data',str(c.data.resolve()),'--action',action]
        result=subprocess.run(command,capture_output=True,timeout=5)
        if result.returncode:raise ValueError('App maintenance could not be scheduled. No files were changed.')
    else:
        result=subprocess.run(['sudo','-n','/usr/local/sbin/sleep-sounds-power',action],capture_output=True,timeout=5)
        if result.returncode:raise ValueError('Host power action unavailable. Check its local permission setup.')
    return {'accepted':True,'action':action}
