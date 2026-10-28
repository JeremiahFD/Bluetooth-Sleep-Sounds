import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from system_status import system_action


class SystemMaintenanceTests(unittest.TestCase):
    def test_wrong_confirmation_never_schedules(self):
        with patch('system_status.subprocess.run') as run:
            with self.assertRaises(ValueError):
                system_action(SimpleNamespace(),{'action':'delete_audio','confirm':True,'confirmation':'RESET SETTINGS'})
            run.assert_not_called()

    def test_disabled_host_never_schedules(self):
        with patch('system_status.system_snapshot',return_value={'capabilities':{'factory_reset':False}}),patch('system_status.subprocess.run') as run:
            with self.assertRaises(ValueError):
                system_action(SimpleNamespace(),{'action':'factory_reset','confirm':True,'confirmation':'FACTORY RESET'})
            run.assert_not_called()

    def test_confirmed_request_schedules_independent_delayed_worker(self):
        with patch('system_status.system_snapshot',return_value={'capabilities':{'factory_reset':True}}),patch('system_status.subprocess.run',return_value=SimpleNamespace(returncode=0)) as run:
            result=system_action(SimpleNamespace(data=Path('fixture data')),{'action':'factory_reset','confirm':True,'confirmation':'FACTORY RESET'})
            args=run.call_args.args[0]
            self.assertEqual(args[:4],['systemd-run','--user','--collect','--on-active=1s'])
            self.assertEqual(args[-4:],['--data',str(Path('fixture data').resolve()),'--action','factory_reset'])
            self.assertTrue(result['accepted'])

    def test_scheduler_failure_is_not_reported_as_accepted(self):
        with patch('system_status.system_snapshot',return_value={'capabilities':{'restart_app':True}}),patch('system_status.subprocess.run',return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(ValueError):system_action(SimpleNamespace(data=Path('.')),{'action':'restart_app','confirm':True})
