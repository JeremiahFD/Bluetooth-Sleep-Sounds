"""Expose only an explicitly published local APK manifest, never infer a new release."""
import json
import re
from pathlib import Path

def release_info(directory):
    directory=Path(directory)
    try:
        doc=json.loads((directory/'release.json').read_text(encoding='utf-8'))
        if (not isinstance(doc,dict) or doc.get('package')!='local.sleepsounds.controller' or
            type(doc.get('version_code')) is not int or doc['version_code']<1 or
            not isinstance(doc.get('version_name'),str) or len(doc['version_name'])>80 or
            not re.fullmatch('[A-Fa-f0-9]{64}',str(doc.get('sha256',''))) or
            not re.fullmatch('[A-Fa-f0-9]{64}',str(doc.get('signer_sha256',''))) or
            type(doc.get('mandatory')) is not bool or not (directory/'SleepSounds.apk').is_file()):
            raise ValueError()
        return {'available':True,**{k:doc[k] for k in ('package','version_code','version_name','sha256','signer_sha256','mandatory')},
                'url':'/install/SleepSounds.apk'}
    except (OSError,ValueError,TypeError):return {'available':False,'message':'No verified app release has been published on this host.'}
