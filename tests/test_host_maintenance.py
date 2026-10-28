import tempfile,unittest
from pathlib import Path
from host_maintenance import validate_request,apply_files,run_service_action
from unittest.mock import Mock,patch
import json

class MaintenanceTests(unittest.TestCase):
    def test_confirmation_is_specific_and_explicit(self):
        for body in ({'action':'factory_reset','confirm':True},{'action':'delete_audio','confirm':True,'confirmation':'FACTORY RESET'},{'action':'reset_settings','confirm':False,'confirmation':'RESET SETTINGS'}):
            with self.assertRaises(ValueError):validate_request(body)
        self.assertEqual(validate_request({'action':'delete_audio','confirm':True,'confirmation':'DELETE ALL AUDIO'}),'delete_audio')
    def test_settings_reset_keeps_identity_profiles_and_media(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'tracks').mkdir();(p/'tracks/a.wav').write_bytes(b'audio')
            for name in ('settings.json','profiles.json','host-identity.json'):(p/name).write_text(json.dumps({'profiles':[{'id':'none','preferences':{'theme':'forest'},'favorites':['a.wav']}],'revision':1}) if name=='profiles.json' else '{}')
            apply_files(p,'reset_settings')
            self.assertFalse((p/'settings.json').exists());self.assertTrue((p/'profiles.json').exists());self.assertTrue((p/'host-identity.json').exists());self.assertEqual((p/'tracks/a.wav').read_bytes(),b'audio')
            self.assertEqual(len(list((p/'maintenance-backups').glob('*/settings.json'))),1)
    def test_factory_reset_keeps_media_identity_and_unrelated_files(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);(p/'tracks').mkdir();(p/'tracks/a.wav').write_bytes(b'audio')
            for name in ('profiles.json','settings.json','host-identity.json','private.txt'):(p/name).write_text('{}')
            apply_files(p,'factory_reset');self.assertFalse((p/'profiles.json').exists());self.assertTrue((p/'host-identity.json').exists());self.assertTrue((p/'private.txt').exists());self.assertTrue((p/'tracks/a.wav').exists())
    def test_delete_media_does_not_remove_profiles_or_unrelated_data(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);(p/'tracks').mkdir();(p/'artwork').mkdir();(p/'tracks/a.wav').write_bytes(b'audio');(p/'artwork/a.png').write_bytes(b'image');(p/'profiles.json').write_text('{}')
            self.assertEqual(apply_files(p,'delete_audio')['deleted_files'],2);self.assertTrue((p/'profiles.json').exists());self.assertEqual(list((p/'tracks').iterdir()),[])

    def test_worker_stops_before_files_and_restarts_after_failure(self):
        runner=Mock()
        with patch('host_maintenance.apply_files',side_effect=OSError('disk full')) as files:
            with self.assertRaises(OSError):run_service_action('/tmp/example','factory_reset',runner)
        self.assertEqual(runner.call_args_list[0].args[0],['systemctl','--user','stop','sleep-sounds.service'])
        self.assertEqual(runner.call_args_list[-1].args[0],['systemctl','--user','start','sleep-sounds.service'])
    def test_failed_stop_does_not_modify_files(self):
        with patch('host_maintenance.apply_files') as files:
            with self.assertRaises(OSError):run_service_action('/tmp/example','factory_reset',Mock(side_effect=OSError('stop failed')))
            files.assert_not_called()
    def test_settings_clears_preferences_preserves_unknown_fields(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);before={'revision':3,'future':True,'profiles':[{'id':'none','favorites':['a.wav'],'future_field':42,'preferences':{'theme':'forest'}}]}
            (p/'profiles.json').write_text(json.dumps(before));apply_files(p,'reset_settings');after=json.loads((p/'profiles.json').read_text())
            self.assertEqual(after['profiles'][0]['preferences'],{});self.assertEqual(after['profiles'][0]['favorites'],['a.wav']);self.assertEqual(after['profiles'][0]['future_field'],42);self.assertTrue(after['future'])
