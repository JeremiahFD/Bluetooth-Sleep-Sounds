"""Small host-local library metadata, per-profile ratings and feedback.

Does not change audio files, fetch links, or participate in the playback loop.
"""
import copy
import json
import math
import re
import secrets
import threading
import time
import unicodedata
from urllib.parse import urlsplit
from persistence import atomic_json

CATEGORIES = [
    {'id': k, 'name': n, 'symbol': s} for k,n,s in [
        ('weather','Weather','cloud'),('nature','Nature','leaf'),('water','Water','water'),
        ('noise','Noise','normalize'),('home','Home','home'),('travel','Travel','travel'),
        ('music','Music','music'),('tones','Tones','tones')]]
TAG_GROUPS = {
    'Weather': ['Rain','Thunder','Storm','Light rain','Heavy rain','Wind','Snow'],
    'Nature': ['Forest','Birds','Crickets','Frogs','Night','Campfire'],
    'Water': ['Ocean','Waves','River','Stream','Waterfall','Underwater'],
    'Noise': ['White noise','Pink noise','Brown noise','Fan','Air conditioner'],
    'Home': ['Fireplace','Shower','Roof','Window','Cafe','City'],
    'Travel': ['Train','Airplane','Car','Boat'],
    'Music & tones': ['Ambient','Piano','Soft music','Drone','Bells','Meditation']}

def text(value, limit, *, required=False):
    if not isinstance(value,str): raise ValueError('Enter text.')
    value=unicodedata.normalize('NFC',value.strip())
    if len(value)>limit or any(unicodedata.category(c).startswith('C') and c not in '\n\t' for c in value):
        raise ValueError(f'Text must be at most {limit} printable characters.')
    if required and not value: raise ValueError('Enter a name or message.')
    return value

def link(value):
    value=text(value,1000)
    if value:
        try:
            u=urlsplit(value)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:
                raise ValueError()
            _=u.port
        except ValueError: raise ValueError('Use an HTTP or HTTPS link without credentials.') from None
    return value

class DiscoveryStore:
    def __init__(self,path):
        self.path=path;self.lock=threading.RLock();self.read_error=False
        self.state={'version':1,'revision':0,'tags':[
            {'id':secrets.token_hex(8),'name':n,'group':g} for g,names in TAG_GROUPS.items() for n in names],
            'categories':copy.deepcopy(CATEGORIES),'tracks':{},'ratings':{},'posts':[]}
        try:
            state=json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(state,dict) or state.get('version')!=1 or
                type(state.get('revision')) is not int or state['revision']<0 or
                any(not isinstance(state.get(k),t) for k,t in [('tags',list),('categories',list),('tracks',dict),('ratings',dict),('posts',list)])):
                raise ValueError()
            for key in ('tags','categories'):
                ids=set();names=set()
                for row in state[key]:
                    if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not isinstance(row.get('name'),str):raise ValueError()
                    if row['id'] in ids or row['name'].casefold() in names:raise ValueError()
                    ids.add(row['id']);names.add(row['name'].casefold())
            if any(not isinstance(v,dict) for v in state['tracks'].values()):raise ValueError()
            if any(not isinstance(v,dict) or any(type(n) is not int or not 1<=n<=5 for n in v.values()) for v in state['ratings'].values()):raise ValueError()
            if any(not isinstance(p,dict) or not isinstance(p.get('replies'),list) for p in state['posts']):raise ValueError()
            self.state=state
        except FileNotFoundError:pass
        except (OSError,ValueError,TypeError):self.read_error=True

    def commit(self,state):
        if self.read_error:raise ValueError('Library data needs repair; the saved file was left untouched.')
        state['revision']+=1
        atomic_json(self.path,state);self.state=state

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({k:self.state[k] for k in ('revision','tags','categories')})|{'read_error':self.read_error}

    def check_revision(self,expected):
        if type(expected) is not int or expected!=self.state['revision']:
            raise ValueError('Library changed elsewhere. Reload before saving.')

    def metadata(self,track):
        with self.lock:return copy.deepcopy(self.state['tracks'].get(track,{}))

    def edit(self,track,values,revision):
        if not isinstance(values,dict):raise ValueError('Expected audio information.')
        with self.lock:
            self.check_revision(revision)
            allowed={'title':160,'description':3000,'creator':160,'license':500,'attribution':1000}
            if set(values)-set(allowed)-{'source_url','tags','categories'}:raise ValueError('Unsupported audio field.')
            changes={k:text(v,allowed[k]) for k,v in values.items() if k in allowed}
            if 'source_url' in values:changes['source_url']=link(values['source_url'])
            for key in ('tags','categories'):
                if key in values:
                    ids={x['id'] for x in self.state[key]};v=values[key]
                    if not isinstance(v,list) or len(v)>100 or any(not isinstance(x,str) or x not in ids for x in v):
                        raise ValueError('Choose existing '+key+'.')
                    changes[key]=list(dict.fromkeys(v))
            state=copy.deepcopy(self.state);state['tracks'].setdefault(track,{}).update(changes);self.commit(state)
            return self.metadata(track)

    def add_tag(self,name,revision):
        name=text(name,40,required=True)
        with self.lock:
            self.check_revision(revision)
            if len(self.state['tags'])>=256:raise ValueError('Maximum 256 tags.')
            if any(t['name'].casefold()==name.casefold() for t in self.state['tags']):raise ValueError('That tag already exists.')
            state=copy.deepcopy(self.state);state['tags'].append({'id':secrets.token_hex(8),'name':name,'group':'Custom'});self.commit(state)
            return self.snapshot()

    def remove_tag(self,tag,revision,confirm):
        with self.lock:
            self.check_revision(revision)
            if confirm is not True:raise ValueError('Confirm removing this tag from all audio files.')
            if not any(t['id']==tag for t in self.state['tags']):raise ValueError('Tag not found.')
            state=copy.deepcopy(self.state);state['tags']=[t for t in state['tags'] if t['id']!=tag]
            for row in state['tracks'].values():row['tags']=[t for t in row.get('tags',[]) if t!=tag]
            self.commit(state);return self.snapshot()

    def label_change(self,kind,action,revision,*,name=None,label_id=None,confirm=False,picture=None):
        if kind not in ('tags','categories') or action not in ('add','rename','remove'):
            raise ValueError('Unsupported catalog action.')
        with self.lock:
            self.check_revision(revision)
            state=copy.deepcopy(self.state);rows=state[kind]
            row=next((r for r in rows if r['id']==label_id),None)
            if action in ('rename','remove') and row is None:raise ValueError('That catalog entry no longer exists.')
            if action=='remove':
                if confirm is not True:raise ValueError('Confirm removing this entry from all audio files.')
                state[kind]=[r for r in rows if r['id']!=label_id]
                for track in state['tracks'].values():track[kind]=[i for i in track.get(kind,[]) if i!=label_id]
            else:
                name=text(name,40,required=True)
                if any(r['id']!=label_id and r['name'].casefold()==name.casefold() for r in rows):raise ValueError('That name already exists.')
                if action=='add':
                    if len(rows)>=(256 if kind=='tags' else 32):raise ValueError('Catalog limit reached.')
                    row={'id':secrets.token_hex(8),'name':name,**({'group':'Custom'} if kind=='tags' else {'picture':'nature'})};rows.append(row)
                else:row['name']=name
                if kind=='categories' and picture is not None:
                    if picture not in {c['id'] for c in CATEGORIES}:raise ValueError('Choose a built-in category picture.')
                    row['picture']=picture
            self.commit(state);return self.snapshot()

    def imported(self,track):
        with self.lock:
            state=copy.deepcopy(self.state);state['tracks'].setdefault(track,{})['added_at']=time.time();self.commit(state)

    def rating(self,track,pid,value):
        if value is not None and (type(value) is not int or not 1<=value<=5):raise ValueError('Choose 1 to 5 stars, or clear the rating.')
        with self.lock:
            state=copy.deepcopy(self.state);rows=state['ratings'].setdefault(pid,{})
            if value is None:rows.pop(track,None)
            else:rows[track]=value
            self.commit(state)

    def ratings(self,track,profiles,pid):
        with self.lock:
            rows=[{'profile':p['id'],'name':p['name'],'rating':self.state['ratings'].get(p['id'],{}).get(track)} for p in profiles]
            values=[r['rating'] for r in rows if r['rating'] is not None]
            return {'my_rating':self.state['ratings'].get(pid,{}).get(track),'ratings':rows,
                    'rating':sum(values)/len(values) if values else None,'rating_count':len(values)}

    def remove_profile(self,pid):
        if pid=='none':raise ValueError('The None profile cannot be removed.')
        with self.lock:
            if pid not in self.state['ratings']:return
            state=copy.deepcopy(self.state);state['ratings'].pop(pid,None);self.commit(state)

    def feedback(self,profiles,track=None):
        names={p['id']:p['name'] for p in profiles}
        def named(p):return {**copy.deepcopy(p),'name':names.get(p['profile'],'Deleted profile')}
        with self.lock:return {'posts':[{**named(p),'replies':[named(r) for r in p['replies']]} for p in reversed(self.state['posts']) if p.get('track')==track]}

    def post(self,pid,body,url='',parent=None,track=None):
        body=text(body,2000,required=True);url=link(url)
        with self.lock:
            state=copy.deepcopy(self.state)
            if len(json.dumps(state['posts']))>2*1024*1024:raise ValueError('Feedback storage is full.')
            if parent is None:
                if sum(p.get('track')==track for p in state['posts'])>=500:raise ValueError('Maximum 500 posts per discussion.')
                rows=state['posts']
            else:
                post=next((p for p in state['posts'] if p['id']==parent and p.get('track')==track),None)
                if not post:raise ValueError('That post is no longer available.')
                if len(post['replies'])>=50:raise ValueError('Maximum 50 replies per post.')
                rows=post['replies']
            rows.append({'id':secrets.token_hex(8),'profile':pid,'body':body,'url':url,'created_at':time.time(),**({'replies':[],**({'track':track} if track is not None else {})} if parent is None else {})})
            self.commit(state)
