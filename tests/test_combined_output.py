import unittest
from unittest.mock import patch
from audio_output import COMBINED_OUTPUT, COMBINED_BT, COMBINED_WIRED, COMBINED_BLUETOOTH_ADDRESS, validate_combined_devices
from tests.test_server import FakePlayer
from server import Controller
from pathlib import Path
import tempfile


class CombinedOutputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.player = FakePlayer()
        self.controller = Controller(Path(self.temporary.name), self.player)

    def tearDown(self):
        self.temporary.cleanup()

    def combined(self):
        self.controller.output = COMBINED_OUTPUT
        self.controller.speaker = COMBINED_BLUETOOTH_ADDRESS
        self.player.properties['audio-device-list'] = [{'name': n} for n in [COMBINED_OUTPUT, COMBINED_BT, COMBINED_WIRED]]

    def test_no_physical_outputs_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'at least one'):
            validate_combined_devices([{'name': COMBINED_OUTPUT}])

    def test_configure_retains_combined_with_saved_speaker(self):
        self.combined()
        with patch('server.validate_selected_bluetooth_output'), patch('server.normalize_selected_bluetooth_volume'):
            self.controller.configure_output()
        self.assertEqual(self.controller.output, COMBINED_OUTPUT)
        self.assertEqual(self.player.properties['audio-device'], COMBINED_OUTPUT)

    def test_combined_validates_real_usb_output(self):
        self.combined()
        with patch.dict('os.environ', {'SLEEP_SOUNDS_BLUETOOTH_ADAPTER': '02:00:00:00:00:04'}), patch('server.validate_selected_bluetooth_output') as validate:
            self.controller.validate_bluetooth_output(COMBINED_OUTPUT, force=True)
        self.assertEqual(validate.call_args.args[1], COMBINED_BT)

    def test_loss_of_creative_keeps_wired_playing(self):
        self.combined()
        self.controller.active_output = COMBINED_OUTPUT
        self.player.properties['idle-active'] = False
        self.player.properties['audio-device-list'] = [{'name': COMBINED_OUTPUT}, {'name': COMBINED_WIRED}]
        self.assertFalse(self.controller.check_output())
        self.assertFalse(self.player.properties['idle-active'])

    def test_loss_of_wired_keeps_creative_playing(self):
        self.combined()
        self.controller.active_output = COMBINED_OUTPUT
        self.player.properties['idle-active'] = False
        self.player.properties['audio-device-list'] = [{'name': COMBINED_OUTPUT}, {'name': COMBINED_BT}]
        with patch('server.validate_selected_bluetooth_output'):
            self.assertFalse(self.controller.check_output())
        self.assertFalse(self.player.properties['idle-active'])

    def test_stale_bluetooth_node_does_not_stop_wired(self):
        self.combined()
        with patch.dict('os.environ', {'SLEEP_SOUNDS_BLUETOOTH_ADAPTER': '02:00:00:00:00:04'}), patch('server.validate_selected_bluetooth_output', side_effect=RuntimeError('Disconnected')):
            self.controller.validate_bluetooth_output(COMBINED_OUTPUT)

    def test_explicit_disconnect_keeps_combined_session(self):
        self.combined()
        self.player.properties['idle-active'] = False
        with patch('server.run', return_value='Disconnected'):
            self.controller._bluetooth('disconnect', COMBINED_BLUETOOTH_ADDRESS)
        self.assertFalse(self.player.properties['idle-active'])
        self.assertEqual(self.controller.output, COMBINED_OUTPUT)
