import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bluetooth_adapter import ADAPTER, DEVICE, execute, validate_output
import json
import server

BUILTIN = "02:00:00:00:00:07"
USB = "02:00:00:00:00:04"
SPEAKER = "02:00:00:00:00:03"


class FakeBluez:
    def __init__(self, usb_path="/org/bluez/hci1", usb_present=True):
        self.usb_path = usb_path
        self.calls = []
        self.closed = False
        self.values = {"/org/bluez/hci0": {ADAPTER: {"Address": BUILTIN}}}
        if usb_present:
            self.values[usb_path] = {ADAPTER: {"Address": USB}}
        for adapter in list(self.values):
            self.values[adapter + "/dev_" + SPEAKER.replace(":", "_")] = {DEVICE: {
                "Adapter": adapter, "Address": SPEAKER, "Alias": "Belkin",
                "Paired": True, "Connected": adapter == "/org/bluez/hci0", "Trusted": True}}

    def objects(self, timeout):
        return self.values

    def call(self, path, interface, method, *args, timeout=5):
        self.calls.append((path, interface, method, args))

    def trust(self, path, timeout):
        self.calls.append((path, DEVICE, "Trusted", (True,)))

    def close(self):
        self.closed = True


class AdapterTests(unittest.TestCase):
    def test_private_sync_bus_does_not_inherit_pairing_mainloop(self):
        import sys
        import types
        from unittest.mock import Mock
        from bluetooth_adapter import BluezClient
        null_loop = object()
        fake_dbus = types.ModuleType("dbus")
        fake_dbus.SystemBus = Mock()
        fake_mainloop = types.ModuleType("dbus.mainloop")
        fake_mainloop.NULL_MAIN_LOOP = null_loop
        with patch.dict(sys.modules, {"dbus": fake_dbus, "dbus.mainloop": fake_mainloop}):
            client = BluezClient()
        fake_dbus.SystemBus.assert_called_once_with(private=True, mainloop=null_loop)
        client.close()
        fake_dbus.SystemBus.return_value.close.assert_called_once()

    def command(self, client, args, **kwargs):
        return execute(USB, args, client_factory=lambda: client, **kwargs)

    def test_duplicate_speaker_address_uses_selected_adapter_state(self):
        client = FakeBluez()
        result = self.command(client, ["info", SPEAKER])
        self.assertIn("Paired: yes", result)
        self.assertIn("Connected: no", result)
        self.assertTrue(client.closed)

    def test_stable_mac_selection_survives_hci_index_change(self):
        client = FakeBluez(usb_path="/org/bluez/hci7")
        self.command(client, ["--timeout", "12", "connect", SPEAKER])
        self.assertEqual(client.calls, [("/org/bluez/hci7/dev_02_00_00_00_00_03", DEVICE, "Connect", ())])

    def test_unplugged_adapter_never_falls_back_or_forgets_speaker(self):
        client = FakeBluez(usb_present=False)
        with self.assertRaisesRegex(RuntimeError, "adapter is unavailable") as caught:
            self.command(client, ["connect", SPEAKER])
        self.assertNotIn("not available", str(caught.exception))
        self.assertEqual(client.calls, [])
        self.assertTrue(client.closed)

    def test_device_lists_are_scoped_to_adapter_and_filter_state(self):
        client = FakeBluez()
        self.assertEqual(self.command(client, ["devices", "Connected"]), "")
        self.assertEqual(self.command(FakeBluez(), ["devices", "Paired"]), "Device " + SPEAKER + " Belkin")

    def test_remote_alias_cannot_inject_extra_device_rows(self):
        client = FakeBluez()
        client.values[client.usb_path + "/dev_02_00_00_00_00_03"][DEVICE]["Alias"] = "Belkin\nDevice 02:00:00:00:00:06 Fake"
        self.assertEqual(len(self.command(client, ["devices", "Paired"]).splitlines()), 1)

    def test_remove_and_trust_affect_only_target_adapter(self):
        client = FakeBluez()
        self.command(client, ["remove", SPEAKER])
        self.assertEqual(client.calls, [(client.usb_path, ADAPTER, "RemoveDevice",
                                        (client.usb_path + "/dev_02_00_00_00_00_03",))])
        client = FakeBluez()
        self.command(client, ["trust", SPEAKER])
        self.assertEqual(client.calls[0][0], client.usb_path + "/dev_02_00_00_00_00_03")

    def test_discovery_keeps_private_client_until_stop_even_on_failure(self):
        client = FakeBluez()
        def fail(_):
            self.assertFalse(client.closed)
            raise RuntimeError("interrupted")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.command(client, ["--timeout", "12", "scan", "on"], sleep=fail)
        self.assertEqual([c[2] for c in client.calls], ["StartDiscovery", "StopDiscovery"])
        self.assertTrue(client.closed)

    def test_pair_success_requires_successful_device_pair_call(self):
        client = FakeBluez()
        self.assertEqual(self.command(client, ["--timeout", "65", "pair", SPEAKER], timeout=70), "Pairing successful")
        self.assertEqual(client.calls[0][2], "Pair")
        client = FakeBluez()
        client.call = lambda *a, **k: (_ for _ in ()).throw(Exception("authentication failed"))
        with self.assertRaisesRegex(RuntimeError, "authentication failed"):
            self.command(client, ["--timeout", "65", "pair", SPEAKER], timeout=70)

    def test_invalid_arguments_never_open_dbus(self):
        for args in [["connect", SPEAKER + ";reboot"], ["scan", "on"], ["--timeout", "999", "scan", "on"], ["devices", "Other"], ["clear"]]:
            with self.subTest(args=args), patch("bluetooth_adapter.BluezClient") as factory:
                with self.assertRaises(RuntimeError):
                    execute(USB, args, client_factory=factory)
                factory.assert_not_called()

    def test_server_dispatches_only_bluetooth_commands_to_preferred_adapter(self):
        with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": USB}), patch("server.selected_bluetooth_command", return_value="selected") as selected:
            self.assertEqual(server.run(["bluetoothctl", "info", SPEAKER], 5), "selected")
            selected.assert_called_once_with(USB, ["info", SPEAKER], 5)
            with patch("server.subprocess.run") as raw:
                raw.return_value.returncode = 0
                raw.return_value.stdout = "pactl output"
                self.assertEqual(server.run(["pactl", "list"]), "pactl output")

    def test_no_preference_preserves_existing_single_adapter_behavior(self):
        with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": ""}), patch("server.subprocess.run") as raw:
            raw.return_value.returncode = 0
            raw.return_value.stdout = "old path"
            self.assertEqual(server.run(["bluetoothctl", "devices"]), "old path")
            self.assertEqual(raw.call_args.args[0], ["bluetoothctl", "devices"])

    def test_reconnect_does_not_clear_saved_speaker_when_usb_is_unplugged(self):
        from tests.test_server import FakePlayer
        with tempfile.TemporaryDirectory() as folder:
            controller = server.Controller(Path(folder), FakePlayer())
            controller.speaker = SPEAKER
            with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": USB}), patch("bluetooth_adapter.BluezClient", return_value=FakeBluez(usb_present=False)):
                self.assertFalse(controller.reconnect_once())
            self.assertEqual(controller.speaker, SPEAKER)
            self.assertFalse(controller.reconnect_suppressed)

    def test_reconnect_checks_and_connects_usb_even_if_builtin_is_connected(self):
        from tests.test_server import FakePlayer
        client = FakeBluez()
        original_call = client.call
        def connect(path, interface, method, *args, **kwargs):
            original_call(path, interface, method, *args, **kwargs)
            if method == "Connect":
                client.values[path][DEVICE]["Connected"] = True
        client.call = connect
        with tempfile.TemporaryDirectory() as folder:
            player = FakePlayer()
            player.properties["audio-device-list"].append({"name": "pipewire/bluez_output.02_00_00_00_00_03.1"})
            controller = server.Controller(Path(folder), player)
            controller.speaker = SPEAKER
            with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": USB}), patch("bluetooth_adapter.BluezClient", return_value=client), patch("server.normalize_selected_bluetooth_volume"), patch("server.validate_selected_bluetooth_output"):
                self.assertTrue(controller.reconnect_once())
            self.assertEqual([c[0] for c in client.calls], ["/org/bluez/hci1/dev_02_00_00_00_00_03"])
            self.assertFalse(any(call[0] == "loadfile" for call in player.calls))


class OutputIdentityTests(unittest.TestCase):
    output = "pipewire/bluez_output.02_00_00_00_00_03.1"

    def graph(self, path):
        return json.dumps([{"id": 4, "info": {"props": {"api.bluez5.path": path}}},
                           {"id": 5, "info": {"props": {"node.name": self.output.split("/", 1)[1], "device.id": 4}}}])

    def connected(self, path="/org/bluez/hci1"):
        client = FakeBluez(usb_path=path)
        client.values[path + "/dev_02_00_00_00_00_03"][DEVICE]["Connected"] = True
        return client

    def test_matching_output_with_reindexed_usb_is_accepted(self):
        client = self.connected("/org/bluez/hci7")
        validate_output(USB, self.output, lambda *a, **k: self.graph("/org/bluez/hci7/dev_02_00_00_00_00_03"), client_factory=lambda: client)
        self.assertTrue(client.closed)

    def test_same_named_sink_on_builtin_is_rejected_even_if_usb_connected(self):
        with self.assertRaisesRegex(RuntimeError, "another adapter"):
            validate_output(USB, self.output, lambda *a, **k: self.graph("/org/bluez/hci0/dev_02_00_00_00_00_03"), client_factory=self.connected)

    def test_disconnected_or_unplugged_usb_is_rejected_before_graph_query(self):
        for client in [FakeBluez(), FakeBluez(usb_present=False)]:
            with self.subTest(client=client), patch("server.run") as command:
                with self.assertRaises(RuntimeError):
                    validate_output(USB, self.output, command, client_factory=lambda: client)
                command.assert_not_called()

    def test_nonbluetooth_output_does_not_open_dbus(self):
        with patch("bluetooth_adapter.BluezClient") as client:
            validate_output(USB, "pipewire/alsa_output.analog", None)
            client.assert_not_called()

    def test_play_and_alarm_never_load_file_when_selected_radio_cannot_be_verified(self):
        from tests.test_server import FakePlayer
        for explicit in [False, True]:
            with tempfile.TemporaryDirectory() as folder:
                player = FakePlayer()
                controller = server.Controller(Path(folder), player)
                (controller.tracks / "Rain.mp3").write_bytes(b"test")
                controller.output = self.output
                player.properties["audio-device-list"].append({"name": self.output})
                with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": USB}), patch("server.validate_selected_bluetooth_output", side_effect=RuntimeError("wrong radio")):
                    with self.assertRaisesRegex(RuntimeError, "wrong radio"):
                        controller.play("Rain.mp3", **({"mode": "alarm", "output": self.output} if explicit else {}))
                self.assertFalse(any(c[0] == "loadfile" for c in player.calls))

    def test_active_playback_stops_if_identical_name_moves_to_builtin(self):
        from tests.test_server import FakePlayer
        with tempfile.TemporaryDirectory() as folder:
            player = FakePlayer()
            controller = server.Controller(Path(folder), player)
            controller.active_output = self.output
            player.properties["idle-active"] = False
            player.properties["audio-device-list"].append({"name": self.output})
            with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": USB}), patch("server.validate_selected_bluetooth_output", side_effect=RuntimeError("wrong radio")):
                self.assertTrue(controller.check_output())
            self.assertIn(("stop",), player.calls)
            self.assertIn("wrong radio", controller.playback_error)

    def test_resume_requires_fresh_identity_check(self):
        from tests.test_server import FakePlayer
        with tempfile.TemporaryDirectory() as folder:
            player = FakePlayer()
            controller = server.Controller(Path(folder), player)
            controller.active_output = self.output
            player.properties.update({"idle-active": False, "pause": True})
            player.properties["audio-device-list"].append({"name": self.output})
            with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": USB}), patch("server.validate_selected_bluetooth_output", side_effect=RuntimeError("wrong radio")):
                with self.assertRaisesRegex(RuntimeError, "wrong radio"):
                    controller.set_paused(False)
            self.assertNotIn(("set_property", "pause", False), player.calls)

    def test_idle_status_does_not_report_wrong_adapter_ready(self):
        from tests.test_server import FakePlayer
        with tempfile.TemporaryDirectory() as folder:
            player = FakePlayer()
            controller = server.Controller(Path(folder), player)
            controller.output = self.output
            controller.power["checked"] = server.time.monotonic()
            player.properties["audio-device-list"].append({"name": self.output})
            with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": USB}), patch("server.validate_selected_bluetooth_output", side_effect=RuntimeError("wrong radio")):
                state = controller.status()
            self.assertFalse(state["output_ready"])
            self.assertIn("wrong radio", state["playback_error"])

    def test_alarm_rejects_wrong_radio_before_changing_sink_volume(self):
        from tests.test_server import FakePlayer
        with tempfile.TemporaryDirectory() as folder:
            player = FakePlayer()
            controller = server.Controller(Path(folder), player)
            (controller.tracks / "Wake.mp3").write_bytes(b"test")
            controller.output = self.output
            player.properties["audio-device-list"].append({"name": self.output})
            with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": USB}), patch("server.validate_selected_bluetooth_output", side_effect=RuntimeError("wrong radio")), patch("server.normalize_selected_bluetooth_volume") as volume:
                with self.assertRaisesRegex(RuntimeError, "wrong radio"):
                    controller.run_alarm({"track": "Wake.mp3", "volume": 60, "loop": False, "ring_minutes": 3})
                volume.assert_not_called()
            self.assertFalse(any(c[0] == "loadfile" for c in player.calls))

    def test_cached_probe_is_bounded_and_forced_checks_are_fresh(self):
        from tests.test_server import FakePlayer
        with tempfile.TemporaryDirectory() as folder:
            controller = server.Controller(Path(folder), FakePlayer())
            with patch.dict(os.environ, {"SLEEP_SOUNDS_BLUETOOTH_ADAPTER": USB}), patch("server.validate_selected_bluetooth_output") as validate:
                controller.validate_bluetooth_output(self.output)
                controller.validate_bluetooth_output(self.output)
                self.assertEqual(validate.call_count, 1)
                controller.validate_bluetooth_output(self.output, force=True)
                self.assertEqual(validate.call_count, 2)
                controller.bluetooth_route_cache = (controller.bluetooth_route_cache[0], server.time.monotonic()-2, None)
                controller.validate_bluetooth_output(self.output)
                self.assertEqual(validate.call_count, 3)


if __name__ == "__main__":
    unittest.main()
