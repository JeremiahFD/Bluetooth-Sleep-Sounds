"""Isolated, task-owned browser QA. Simulated player, no live Pi access."""
import sys,os,time,json,tempfile,threading,wave,shutil
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server,scheduler,timers
from server import Controller,Server
root=Path(__file__).resolve().parents[1]
with (root/'tests/Chicago.tzif').open('rb') as f: zone=ZoneInfo.from_file(f,'America/Chicago')
def chicago(key):
 if key!='America/Chicago':raise ValueError('Preview timezone unavailable')
 return zone
scheduler.ZoneInfo=chicago;timers.ZoneInfo=chicago
class Player:
 def __init__(self):
  self.lock=threading.RLock();self.entry=0;self.started=time.monotonic();self.calls=[]
  self.values={'idle-active':True,'pause':False,'audio-device':'pulse/preview','volume':30,'time-pos':754,'duration':3600,
   'audio-device-list':[{'name':'pulse/preview','description':'Bluetooth speaker'},{'name':'pipewire/preview','description':'Bluetooth speaker'},{'name':'pulse/hdmi','description':'HDMI audio'},{'name':'auto','description':'System default'}]}
 def command(self,*args):
  self.calls.append(args)
  if args[0]=='set_property':self.values[args[1]]=args[2]
  elif args[0]=='stop':self.values['idle-active']=True
  elif args[0]=='seek':self.values['time-pos']=args[1];self.started=time.monotonic()
  elif args[0]=='loadfile':self.values['idle-active']=False;self.values['time-pos']=754;self.started=time.monotonic()
 def get(self,key,default=None):
  if key=='time-pos' and not self.values['idle-active'] and not self.values['pause']:return self.values[key]+time.monotonic()-self.started
  return self.values.get(key,default)
 def prepare(self):pass
 def load(self,path):self.entry+=1;self.command('loadfile',str(path),'replace');return {'generation':1,'entry':self.entry}
 def playback_status(self,receipt):return {'status':'started'}
 def close(self):pass
class PreviewController(Controller):
 def bluetooth_job(self,*args):raise ValueError('Bluetooth changes disabled in design preview.')
 def status(self):return {**super().status(),'preview':True}
with tempfile.TemporaryDirectory(prefix='sleep-review-') as d:
 c=PreviewController(Path(d),Player());c.output='pulse/preview';c._clock={'ready':True,'checked':time.monotonic()};c.power={'checked':1e20,'undervoltage':False,'throttled':False}
 names=['Peaceful Night.wav','Rain on the Cabin Roof.wav','Quiet Thunder Across the Valley - Extended Sleep Audio with a Deliberately Long File Name.wav']
 for name in names:
  with wave.open(str(c.tracks/name),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(bytes(16000))
 tags={t['name']:t['id'] for t in c.discovery.snapshot()['tags']}
 c.discovery.edit(names[0],{'description':'Soft rain beside an open window. A quiet night without thunder.','tags':[tags['Rain'],tags['Window']],'categories':['weather','water']},c.discovery.state['revision'])
 c.discovery.edit(names[1],{'description':'Rain against a wooden cabin roof.','tags':[tags['Rain'],tags['Roof']],'categories':['weather','home']},c.discovery.state['revision'])
 c.discovery.edit(names[2],{'description':'Distant thunder and heavy rain.','tags':[tags['Rain'],tags['Thunder'],tags['Storm']],'categories':['weather','nature']},c.discovery.state['revision'])
 for name in names:c.discovery.imported(name)
 other=c.profiles.change('add',name='Guest')['profiles'][-1]['id'];c.profiles.change('enabled',enabled=True)
 c.profiles.update_preferences('none',{'theme':'cloudstorm'})
 c.discovery.rating(names[0],'none',4);c.discovery.rating(names[0],other,5);c.discovery.rating(names[1],other,3)
 c.profiles.set_favorite(other,names[2],True)
 c.discovery.post(other,'Can we add more gentle rain without thunder?','https://example.com/rain')
 for name in names:
  c.catalog.remember(c.tracks/name,{'streams':[{'codec_type':'audio','codec_name':'pcm_s16le','sample_rate':'8000','channels':1,'bits_per_sample':16,'bit_rate':'128000'}],'format':{'duration':'1','format_name':'wav'}})
 fake_devices=[{'id':'11111111111111111111111111111111','name':'VR BOX (preview only)','transport':'Bluetooth','nodes':[],'capabilities':[]}]
 c.remote_manager.discoverer=lambda:fake_devices
 c.remote_store.change({'action':'add','device':'11111111111111111111111111111111','revision':0},fake_devices,{p['id'] for p in c.profiles.catalog()['profiles']},c.track)
 c.set_favorite(names[0],True);c.set_favorite(names[1],True);c.play(names[0]);c.player.values['duration']=3600;c.player.values['time-pos']=754
 c.bt['devices']=[{'address':'02:00:00:00:00:06','name':'Bluetooth speaker','paired':True,'connected':True}]
 c.bt['message']='Ready to play';srv=Server(('127.0.0.1',8096),c,['127.0.0.1','localhost'])
 threading.Thread(target=c.monitor,daemon=True).start()
 print('PID='+str(os.getpid()),flush=True)
 print('REVIEW_PREVIEW_READY http://127.0.0.1:8096/ui/ simulated audio only',flush=True)
 try:srv.serve_forever()
 finally:c.closed.set();srv.server_close()
