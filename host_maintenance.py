"""Explicit, confirmed host-local maintenance. Never changes OS pairing/network data."""
from pathlib import Path
import os
import uuid
import json
from persistence import atomic_json

CONFIRMATIONS = {'reset_settings':'RESET SETTINGS','factory_reset':'FACTORY RESET','delete_audio':'DELETE ALL AUDIO'}
SETTINGS = ('settings.json','speaker-sync.json','resume.json','alarm.json')
FACTORY = SETTINGS + ('profiles.json','favorites.json','library.json','remotes.json','audio-presets.json','track-details.json','listening-stats.json')

def validate_request(data):
    action=data.get('action')
    if action not in CONFIRMATIONS or data.get('confirm') is not True or data.get('confirmation')!=CONFIRMATIONS[action]:
        raise ValueError('Confirm the selected action and its warning before continuing.')
    return action

def apply_files(directory,action):
    """Run only after playback/inputs stop, under the host's storage locks."""
    base=Path(directory).resolve()
    if action not in CONFIRMATIONS:raise ValueError('Unsupported maintenance action.')
    if action=='delete_audio':
        files=[]
        for name in ('tracks','artwork'):
            folder=base/name
            if folder.is_symlink():raise ValueError('Refusing a linked media directory.')
            if folder.exists():
                for p in folder.iterdir():
                    if p.is_symlink():raise ValueError('Refusing linked media. Remove the link manually first.')
                    if p.is_file():
                        if p.resolve().parent!=folder.resolve():raise ValueError('Media path is outside its directory.')
                        files.append(p)
        # Validation completes before any deletion. Does not recurse into unrelated folders.
        for p in files:p.unlink()
        return {'deleted_files':len(files),'backup_available':False}
    files=[]
    profiles=None
    if action=='reset_settings' and (base/'profiles.json').exists():
        profile_path=base/'profiles.json'
        if profile_path.is_symlink():raise ValueError('Refusing linked profile settings.')
        profiles=json.loads(profile_path.read_text(encoding='utf-8'))
        if not isinstance(profiles.get('profiles'),list):raise ValueError('Invalid profile data; nothing was reset.')
        for profile in profiles['profiles']:profile['preferences']={}
        profiles['revision']=profiles.get('revision',0)+1
        files.append(profile_path)
    for name in SETTINGS if action=='reset_settings' else FACTORY:
        p=base/name
        if p.is_symlink():raise ValueError('Refusing linked application settings.')
        if p.is_file():files.append(p)
    if (base/'maintenance-backups').is_symlink():raise ValueError('Refusing a linked recovery directory.')
    recovery=base/'maintenance-backups'/uuid.uuid4().hex
    recovery.mkdir(parents=True,mode=0o700)
    moved=[]
    try:
        for p in files:os.replace(p,recovery/p.name);moved.append(p)
        if profiles is not None:atomic_json(base/'profiles.json',profiles)
    except OSError:
        for p in reversed(moved):os.replace(recovery/p.name,p)
        raise
    return {'reset_files':len(moved),'backup_available':True}


def run_service_action(directory,action,run=None):
    """Runs in a separate systemd user unit, outside the player's cgroup."""
    import subprocess
    run=run or subprocess.run
    service=['systemctl','--user']
    run(service+['stop','sleep-sounds.service'],check=True,timeout=30)
    try:
        if action!='restart_app':apply_files(directory,action)
    finally:
        run(service+['start','sleep-sounds.service'],check=True,timeout=30)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',required=True)
    parser.add_argument('--action',required=True,choices=['restart_app',*CONFIRMATIONS])
    args=parser.parse_args()
    run_service_action(args.data,args.action)
