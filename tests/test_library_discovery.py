import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch,Mock
from system_status import diagnostic_export
from library_discovery import DiscoveryStore
from server import Controller,Server
from test_server import FakePlayer
from app_release import release_info

class DiscoveryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'library.json';self.store=DiscoveryStore(self.path)
 def tearDown(self):self.temp.cleanup()
 def test_metadata_revision_conflict_and_unknown_fields_survive(self):
  tag=self.store.snapshot()['tags'][0]['id']
  self.store.edit('rain.mp3',{'title':'Rain','tags':[tag]},0)
  with self.assertRaisesRegex(ValueError,'changed elsewhere'):self.store.edit('rain.mp3',{'title':'Stale'},0)
  doc=json.loads(self.path.read_text(encoding='utf-8'));doc['future']={'a':True};doc['tracks']['rain.mp3']['future_track']=[1,2];self.path.write_text(json.dumps(doc),encoding='utf-8')
  other=DiscoveryStore(self.path);other.rating('rain.mp3','none',5)
  saved=json.loads(self.path.read_text(encoding='utf-8'));self.assertEqual(saved['future'],{'a':True});self.assertEqual(saved['tracks']['rain.mp3']['future_track'],[1,2])
 def test_remove_tag_unassigns_without_removing_track_or_ratings(self):
  tag=self.store.snapshot()['tags'][0]['id'];self.store.edit('rain.mp3',{'tags':[tag],'description':'Keep'},0);self.store.rating('rain.mp3','none',3)
  with self.assertRaises(ValueError):self.store.remove_tag(tag,2,False)
  self.store.remove_tag(tag,2,True);self.assertEqual(self.store.metadata('rain.mp3')['tags'],[]);self.assertEqual(self.store.metadata('rain.mp3')['description'],'Keep')
  self.assertEqual(self.store.ratings('rain.mp3',[{'id':'none','name':'None'}],'none')['rating'],3)
 def test_corrupt_or_newer_data_not_replaced(self):
  for document in ['{bad',json.dumps({'version':2,'tracks':{}})]:
   self.path.write_text(document,encoding='utf-8');store=DiscoveryStore(self.path)
   self.assertTrue(store.read_error)
   with self.assertRaises(ValueError):store.rating('rain','none',4)
   self.assertEqual(self.path.read_text(encoding='utf-8'),document)
 def test_rating_isolation_clear_aggregate_and_deleted_profiles(self):
  profiles=[{'id':'none','name':'None'},{'id':'one','name':'A'}]
  self.store.rating('rain','none',2);self.store.rating('rain','one',5)
  result=self.store.ratings('rain',profiles,'one');self.assertEqual((result['my_rating'],result['rating'],result['rating_count']),(5,3.5,2))
  self.store.rating('rain','one',None);self.assertEqual(self.store.ratings('rain',profiles,'one')['rating'],2)
  self.store.remove_profile('one');self.assertEqual(DiscoveryStore(self.path).ratings('rain',profiles,'none')['my_rating'],2)
  for invalid in [True,False,0,6,2.5,'5']:
   with self.assertRaises(ValueError):self.store.rating('rain','none',invalid)
 def test_feedback_links_replies_and_renamed_deleted_authors(self):
  profiles=[{'id':'none','name':'None'}]
  self.store.post('none','A sound','https://example.org/rain');post=self.store.feedback(profiles)['posts'][0]
  self.store.post('one','Reply',parent=post['id']);feed=self.store.feedback(profiles)['posts'][0]
  self.assertEqual(feed['replies'][0]['name'],'Deleted profile');self.assertEqual(feed['url'],'https://example.org/rain')
  for invalid in ['javascript:alert(1)','file:///secret','https://user:pass@example.org/']:
   with self.assertRaises(ValueError):self.store.post('none','Text',invalid)
  with self.assertRaises(ValueError):self.store.post('none','Text',parent='unknown')
 def test_tag_normalization_duplicates_and_bounds(self):
  self.store.add_tag('  Custom sound  ',0)
  with self.assertRaises(ValueError):self.store.add_tag('custom SOUND',1)
  with self.assertRaises(ValueError):self.store.add_tag('x'*41,1)
  with self.assertRaises(ValueError):self.store.edit('rain',{'tags':['unknown']},1)
 def test_catalog_rename_preserves_assignments_and_custom_categories(self):
  tag=self.store.snapshot()['tags'][0]['id'];self.store.edit('rain',{'tags':[tag]},0)
  self.store.label_change('tags','rename',1,label_id=tag,name='Rain renamed')
  self.assertEqual(self.store.metadata('rain')['tags'],[tag])
  self.store.label_change('categories','add',2,name='Bedtime',picture='water')
  cat=self.store.snapshot()['categories'][-1];self.store.edit('rain',{'categories':[cat['id']]},3)
  self.store.label_change('categories','rename',4,label_id=cat['id'],name='Quiet',picture='nature')
  self.assertEqual(self.store.metadata('rain')['categories'],[cat['id']])
  self.store.label_change('categories','remove',5,label_id=cat['id'],confirm=True)
  self.assertEqual(self.store.metadata('rain')['categories'],[])
  self.assertEqual(self.store.metadata('rain')['tags'],[tag])
 def test_release_unavailable_until_manifest_explicitly_published(self):
  directory=Path(self.temp.name);self.assertFalse(release_info(directory)['available'])
  (directory/'SleepSounds.apk').write_bytes(b'APK')
  self.assertFalse(release_info(directory)['available'])
  doc={'package':'local.sleepsounds.controller','version_code':8,'version_name':'0.8','sha256':'a'*64,'signer_sha256':'b'*64,'mandatory':False}
  (directory/'release.json').write_text(json.dumps(doc),encoding='utf-8');self.assertTrue(release_info(directory)['available'])
  doc['package']='other.app';(directory/'release.json').write_text(json.dumps(doc),encoding='utf-8');self.assertFalse(release_info(directory)['available'])

class DiscoveryHttpTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.player=FakePlayer();self.c=Controller(Path(self.temp.name),self.player)
  (self.c.tracks/'Rain.wav').write_bytes(b'fixture')
  self.server=Server(('127.0.0.1',0),self.c,['127.0.0.1']);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
 def request(self,path,body=None,token=True,origin=None):
  h=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3);headers={}
  if token:headers['X-Sleep-Token']=self.c.token
  if origin:headers['Origin']=origin
  h.request('POST' if body is not None else 'GET',path,body=json.dumps(body) if body is not None else None,headers=headers)
  r=h.getresponse();result=(r.status,json.loads(r.read()));h.close();return result
 def test_all_mutations_require_token_and_same_origin(self):
  for endpoint,data in [('/api/rating',{'track':'Rain.wav','rating':5}),('/api/feedback',{'body':'Hi'}),('/api/library-catalog',{'action':'add_tag','name':'Custom','revision':0}),('/api/library-metadata',{'track':'Rain.wav','values':{'title':'New'},'revision':0}),('/api/system-action',{'action':'shutdown','confirm':True})]:
   self.assertEqual(self.request(endpoint,data,token=False)[0],403)
   self.assertEqual(self.request(endpoint,data,origin='http://evil.example')[0],403)
  self.assertEqual(self.c.discovery.state['revision'],0)
 def test_edit_rating_profile_browse_does_not_touch_audio_or_active_profile(self):
  pid=self.c.profiles.change('add',name='Second')['profiles'][-1]['id'];self.c.profiles.change('enabled',enabled=True)
  self.assertEqual(self.request('/api/library-metadata',{'track':'Rain.wav','values':{'title':'Roof rain'},'revision':0})[0],200)
  self.assertEqual(self.request('/api/rating',{'track':'Rain.wav','rating':5,'profile':pid})[0],200)
  self.assertEqual(self.request('/api/tracks?profile='+pid)[1][0]['my_rating'],5)
  self.assertIsNone(self.request('/api/tracks?profile=none')[1][0]['my_rating'])
  self.c.profiles.change('enabled',enabled=False)
  self.assertEqual(self.request('/api/public-profile?profile='+pid)[1]['ratings'][0]['rating'],5)
  self.assertEqual(self.c.active_profile_id,'none');self.assertEqual(self.player.calls,[])
  self.assertEqual(self.request('/api/rating',{'track':'../secret','rating':4})[0],400)
 def test_host_identity_persists_and_corrupt_identity_is_not_replaced(self):
  identity=self.request('/api/identity')[1]
  self.assertEqual(identity['service'],'sleep-sounds');self.assertEqual(len(identity['host_id']),32)
  other=Controller(Path(self.temp.name),FakePlayer());self.assertEqual(other.host_id,identity['host_id'])
  path=Path(self.temp.name)/'host-identity.json';path.write_text('{broken',encoding='utf-8')
  other=Controller(Path(self.temp.name),FakePlayer());self.assertIsNone(other.host_id);self.assertEqual(path.read_text(encoding='utf-8'),'{broken')
 def test_diagnostics_export_is_bounded_and_redacts_secret_events(self):
  process=Mock();process.returncode=0
  process.communicate.return_value=(b'{"MESSAGE":"Normal playback event","PRIORITY":"6"}\n{"MESSAGE":"csrf token=must-not-export"}\n',None)
  factory=Mock();factory.return_value.__enter__=Mock(return_value=process);factory.return_value.__exit__=Mock(return_value=False)
  with patch('system_status.platform.system',return_value='Linux'),patch('system_status.subprocess.Popen',factory):
   report=diagnostic_export(self.c)
  self.assertEqual(report['max_events'],40);self.assertEqual(report['window_minutes'],15)
  self.assertEqual(report['events'][0]['message'],'Normal playback event')
  self.assertNotIn('must-not-export',json.dumps(report));self.assertNotIn(self.c.token,json.dumps(report))
  self.assertEqual(self.player.calls,[])
 def test_disabled_profiles_store_in_none_and_host_actions_disabled(self):
  self.request('/api/rating',{'track':'Rain.wav','rating':4,'profile':'unknown'})
  self.assertEqual(self.request('/api/tracks')[1][0]['my_rating'],4)
  self.assertEqual(self.request('/api/feedback',{'body':'A request','profile':'unknown'})[1]['posts'][0]['profile'],'none')
  with patch.dict('os.environ',{'SLEEP_SOUNDS_HOST_ACTIONS':'false'}):
   self.assertEqual(self.request('/api/system')[1]['capabilities']['shutdown'],False)
   self.assertEqual(self.request('/api/system-action',{'action':'shutdown','confirm':True})[0],400)
  self.assertEqual(self.player.calls,[])
