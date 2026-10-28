import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import quote
from unittest.mock import Mock, patch

from server import Controller, Player, Server


class FakePlayer:
    def __init__(self):
        self.lock = threading.RLock()
        self.calls = []
        self.properties = {"idle-active": True, "pause": False, "audio-device": "auto", "audio-device-list": [{"name": "auto", "description": "Default"}]}

    def command(self, *args):
        self.calls.append(args)
        if args[0] == "set_property":
            self.properties[args[1]] = args[2]
        if args[0] == "loadfile":
            self.properties["idle-active"] = False
        if args[0] == "stop":
            self.properties["idle-active"] = True

    def get(self, name, fallback=None):
        return self.properties.get(name, fallback)

    def close(self):
        self.calls.append(("force-stop",))

    def load(self, path):
        self.command("loadfile", str(path), "replace")
        return {"generation": 1, "entry": len(self.calls)}

    def playback_status(self, receipt):
        return {"status": "started"}

    def prepare(self):
        pass


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.player = FakePlayer()
        self.controller = Controller(Path(self.temporary.name), self.player)

    def tearDown(self):
        self.temporary.cleanup()

    def test_timer_stops_without_any_phone_requests(self):
        c = self.controller
        with patch("server.time.monotonic", return_value=100):
            c.set_timer(1)
        with patch("server.time.monotonic", return_value=159):
            c.tick()
        self.assertNotIn(("stop",), self.player.calls)
        with patch("server.time.monotonic", return_value=160):
            c.tick()
            c.tick()
        self.assertEqual(self.player.calls.count(("stop",)), 1)
        self.assertIsNone(c.deadline)

    def test_cancel_timer_and_invalid_values(self):
        self.controller.set_timer(1)
        self.controller.set_timer(0)
        self.assertIsNone(self.controller.deadline)
        for invalid in [-1, 1441, float("nan"), float("inf"), True, None, "10"]:
            with self.assertRaises(ValueError):
                self.controller.set_timer(invalid)

    def test_cannot_play_outside_library(self):
        for name in ["../secret.mp3", r"..\secret.mp3", "/tmp/secret.mp3", None]:
            with self.assertRaises(ValueError):
                self.controller.track(name)
        self.assertEqual(self.player.calls, [])

    def test_bluetooth_rejects_injected_command(self):
        with self.assertRaises(ValueError):
            self.controller.bluetooth_job("connect", "02:00:00:00:00:06;reboot")
        self.assertFalse(self.controller.bt["busy"])

    def test_clear_pairings_requires_explicit_owner_confirmation(self):
        with self.assertRaisesRegex(ValueError, "Confirm"):
            self.controller.bluetooth_job("clear_pairings")
        with self.assertRaisesRegex(ValueError, "Invalid Bluetooth"):
            self.controller.bluetooth_job("remove", "02:00:00:00:00:06;rm")
        self.assertFalse(self.controller.bt["busy"])

    def test_unpair_selected_speaker_clears_only_its_saved_output(self):
        address = "02:00:00:00:00:06"
        self.controller.speaker = address
        self.controller.output = "pulse/bluez_sink.02_00_00_00_00_06"
        with patch("server.run", return_value=""):
            self.controller._bluetooth("remove", address)
        self.assertIsNone(self.controller.speaker)
        self.assertIsNone(self.controller.output)
        self.assertIn(("stop",), self.player.calls)
        self.assertIn("unpaired", self.controller.bt["message"])
        self.assertIsNone(Controller(Path(self.temporary.name), FakePlayer()).speaker)

    def test_clear_all_only_removes_returned_paired_addresses(self):
        address = "02:00:00:00:00:06"
        self.controller.speaker = address
        commands = []
        def fake_run(args, timeout=15):
            commands.append(args)
            if args == ["bluetoothctl", "devices", "Paired"]:
                return "Device 02:00:00:00:00:06 Speaker\nDevice 02:00:00:00:00:05 Other\\n"
            return ""
        with patch("server.run", side_effect=fake_run):
            self.controller._bluetooth("clear_pairings", None)
        self.assertEqual(sum(x[:2]==["bluetoothctl","remove"] for x in commands), 2)
        self.assertIsNone(self.controller.speaker)
        self.assertIn("Removed 2", self.controller.bt["message"])

    def test_auto_reconnect_default_on_and_persists_off(self):
        c=self.controller
        self.assertTrue(c.auto_reconnect)
        c.auto_reconnect = False
        c.save()
        self.assertFalse(Controller(Path(self.temporary.name), FakePlayer()).auto_reconnect)
        with patch("server.run") as caller:
            c.speaker="02:00:00:00:00:06"
            self.assertFalse(c.reconnect_once())
            caller.assert_not_called()

    def test_reconnect_only_last_explicitly_paired_device(self):
        c=self.controller
        c.speaker="02:00:00:00:00:06"
        c.auto_reconnect=True
        c.reconnect_next=0
        with patch("server.run", return_value="Paired: no\\nConnected: no") as caller:
            self.assertFalse(c.reconnect_once())
            self.assertEqual(caller.call_count,1)
            self.assertEqual(caller.call_args.args[0], ["bluetoothctl","info","02:00:00:00:00:06"])
            self.assertIsNone(c.speaker)
        self.assertNotIn(("stop",),self.player.calls)

    def test_auto_reconnect_restores_selected_audio_without_playback(self):
        c=self.controller
        c.speaker="02:00:00:00:00:06"
        self.player.properties["audio-device-list"].append({"name":"pulse/bluez_output.02_00_00_00_00_06"})
        reads=["Paired: yes\\nConnected: no","", "Paired: yes\\nConnected: yes"]
        with patch("server.run", side_effect=reads) as cmd, patch("server.normalize_selected_bluetooth_volume", return_value=True):
            self.assertTrue(c.reconnect_once())
        self.assertEqual(cmd.call_count,3)
        self.assertEqual(c.output, "pulse/bluez_output.02_00_00_00_00_06")
        self.assertNotIn(("loadfile",),self.player.calls)
        self.assertNotIn(("stop",),self.player.calls)

    def test_explicit_disconnect_suppresses_retries(self):
        c=self.controller
        c.speaker="02:00:00:00:00:06"
        with patch("server.threading.Thread") as thread:
            c.bluetooth_job("disconnect",c.speaker)
        self.assertTrue(c.reconnect_suppressed)
        with patch("server.run") as caller:
            self.assertFalse(c.reconnect_once())
            caller.assert_not_called()

    def test_clear_all_forgets_stale_app_speaker_even_when_bluez_empty(self):
        c = self.controller
        c.speaker = "02:00:00:00:00:06"
        c.output = "pulse/bluez_output.02_00_00_00_00_06"
        c.save()
        with patch("server.run", return_value=""):
            c._bluetooth("clear_pairings", None)
        self.assertIsNone(c.speaker)
        self.assertIsNone(c.output)
        self.assertIn("saved speaker cleared", c.bt["message"])
        reloaded = Controller(Path(self.temporary.name), FakePlayer())
        self.assertIsNone(reloaded.speaker)
        self.assertIsNone(reloaded.output)

    def test_reconnect_stops_when_saved_pairing_was_removed(self):
        c = self.controller
        c.speaker = "02:00:00:00:00:06"
        c.save()
        def fake_run(args, timeout=15):
            if args[:2] == ["bluetoothctl", "info"]:
                raise RuntimeError("Device 02:00:00:00:00:06 not available")
            if args == ["bluetoothctl", "devices", "Paired"]:
                return ""
            raise AssertionError(args)
        with patch("server.run", side_effect=fake_run) as cmd:
            self.assertFalse(c.reconnect_once())
            self.assertFalse(c.reconnect_once())
            self.assertEqual(cmd.call_count, 2)
        self.assertIsNone(c.speaker)
        self.assertIn("Find Bluetooth speakers", c.reconnect_message)

    def test_play_requires_explicit_output_and_restores_it(self):
        c = self.controller
        (c.tracks / "Rain.mp3").write_bytes(b"fixture")
        with self.assertRaises(ValueError):
            c.play("Rain.mp3")
        c.output = "auto"  # Owner explicitly chooses system default.
        c.play("Rain.mp3")
        self.assertIn(("set_property", "audio-device", "auto"), self.player.calls)

    def test_timer_can_expire_while_controller_lock_is_busy(self):
        c = self.controller
        c.deadline = time.monotonic() - 1
        with c.lock:
            worker = threading.Thread(target=c.tick)
            worker.start()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
        self.assertIn(("stop",), self.player.calls)

    def test_timer_forces_owned_player_stop_on_ipc_failure(self):
        self.controller.deadline = time.monotonic() - 1
        with patch.object(self.player, "command", side_effect=RuntimeError("IPC failed")):
            self.controller.tick()
        self.assertIn(("force-stop",), self.player.calls)

    def test_failed_new_speaker_routing_cannot_reuse_previous_output(self):
        c = self.controller
        c.output = "auto"
        responses = ["Paired: yes", "", "", "Connected: yes", "", "", ""]
        with patch("server.run", side_effect=responses), patch("server.time.sleep"):
            c._bluetooth("connect", "02:00:00:00:00:06")
        self.assertIsNone(c.output)
        self.assertEqual(c.speaker, "02:00:00:00:00:06")
        with self.assertRaises(ValueError):
            c.configure_output()

    def test_stale_timer_cannot_stop_a_new_session(self):
        c = self.controller
        (c.tracks / "Rain.wav").write_bytes(b"fixture")
        c.output = "auto"
        c.play("Rain.wav")
        stale_owner = c.session
        c.play("Rain.wav")
        self.player.calls.clear()
        c.stop(expected_session=stale_owner)
        self.assertNotIn(("stop",), self.player.calls)

    def test_replacement_stops_paused_audio_before_controls_change(self):
        c = self.controller
        (c.tracks / "Rain.wav").write_bytes(b"fixture")
        c.output = "auto"
        self.player.properties["pause"] = True
        c.play("Rain.wav")
        self.assertEqual(self.player.calls[0], ("stop",))
        self.assertLess(self.player.calls.index(("stop",)), self.player.calls.index(("set_property", "pause", False)))

    def test_stale_output_probe_cannot_stop_new_playback(self):
        c = self.controller
        c.active_output = "old"
        self.player.properties["idle-active"] = False
        original_get = self.player.get
        def get(name, fallback=None):
            if name == "audio-device-list":
                with c.transition_lock:
                    c.session += 1
                    c.active_output = "new"
                return []
            return original_get(name, fallback)
        with patch.object(self.player, "get", side_effect=get):
            self.assertFalse(c.check_output())
        self.assertNotIn(("stop",), self.player.calls)

    def test_startup_timeout_stops_only_its_session(self):
        c = self.controller
        (c.tracks / "Rain.wav").write_bytes(b"fixture")
        c.output = "auto"
        with patch("server.time.monotonic", return_value=100):
            receipt = c.play("Rain.wav")
        with patch.object(self.player, "playback_status", return_value={"status": "starting"}), patch("server.time.monotonic", return_value=111):
            self.assertEqual(c.playback_status(receipt)["status"], "failed")
        self.assertEqual(c.mode, "idle")
        c.play("Rain.wav")
        c.playback_status(receipt)
        self.assertEqual(c.mode, "normal")

    def test_control_failure_cannot_load_with_default_routing(self):
        c = self.controller
        (c.tracks / "Rain.wav").write_bytes(b"fixture")
        c.output = "auto"
        original = self.player.command
        def command(*args):
            if args[:2] == ("set_property", "volume"):
                raise RuntimeError("Event listener disconnected")
            return original(*args)
        with patch.object(self.player, "command", side_effect=command):
            with self.assertRaises(RuntimeError):
                c.play("Rain.wav")
        self.assertFalse(any(call[0] == "loadfile" for call in self.player.calls))

    def test_player_does_not_restart_mid_command_after_event_failure(self):
        player = Player(Path(self.temporary.name))
        player.process = Mock()
        player.process.poll.return_value = None
        player.error = "Event listener disconnected"
        with patch("server.subprocess.Popen") as launch:
            with self.assertRaises(RuntimeError):
                player.command("loadfile", "Rain.wav", "replace")
        launch.assert_not_called()

    def test_sleep_and_alarm_replace_deadlines(self):
        c = self.controller
        (c.tracks / "Rain.wav").write_bytes(b"fixture")
        self.player.properties["audio-device-list"].append({"name": "pulse/speaker"})
        c.output = "pulse/speaker"
        with patch("server.time.monotonic", return_value=100):
            c.sleep("Rain.wav", 60)
        self.assertEqual(c.deadline, 3700)
        with patch("server.time.monotonic", return_value=200):
            c.run_alarm({"track": "Rain.wav", "output": "pulse/speaker", "volume": 60, "loop": True, "ring_minutes": 10})
        self.assertEqual(c.deadline, 800)
        self.assertEqual(c.mode, "alarm")
        self.assertEqual(c.timer_session, c.session)


    def test_manual_disconnect_survives_restart_and_stays_off(self):
        c = self.controller
        c.speaker = "02:00:00:00:00:06"
        c.save()
        with patch("server.threading.Thread"):
            c.bluetooth_job("disconnect", c.speaker)
        restarted = Controller(Path(self.temporary.name), FakePlayer())
        self.assertTrue(restarted.reconnect_suppressed)
        self.assertEqual(restarted.speaker, c.speaker)
        with patch("server.run") as calls:
            self.assertFalse(restarted.reconnect_once())
            calls.assert_not_called()

    def test_reconnect_deadline_survives_reboot_and_never_starts_audio(self):
        c = self.controller
        c.speaker = "02:00:00:00:00:06"
        c.reconnect_retry_minutes = 1
        c.save()
        def fail_connect(args, timeout=15):
            if args[:2] == ["bluetoothctl", "info"]:
                return "Paired: yes\\nConnected: no"
            if args[:3] == ["bluetoothctl", "--timeout", "12"]:
                raise RuntimeError("Speaker unavailable")
            raise AssertionError(args)
        with patch("server.time.time", return_value=1000), patch("server.run", side_effect=fail_connect):
            self.assertFalse(c.reconnect_once())
        self.assertEqual(c.reconnect_expires_at,1060)
        restarted = Controller(Path(self.temporary.name), FakePlayer())
        self.assertEqual(restarted.reconnect_expires_at,1060)
        with patch("server.time.time", return_value=1061), patch("server.run", side_effect=fail_connect) as calls:
            self.assertFalse(restarted.reconnect_once())
        self.assertEqual(calls.call_count,1)
        self.assertIn("limit reached", restarted.reconnect_message)
        self.assertNotIn(("loadfile",), restarted.player.calls)

    def test_reconnect_deadline_resets_after_success(self):
        c = self.controller
        c.speaker = "02:00:00:00:00:06"
        c.reconnect_expires_at = 9999999999
        self.player.properties["audio-device-list"].append({"name":"pulse/bluez_output.02_00_00_00_00_06"})
        with patch("server.run", return_value="Paired: yes\\nConnected: yes"), patch("server.normalize_selected_bluetooth_volume", return_value=True):
            self.assertTrue(c.reconnect_once())
        self.assertIsNone(c.reconnect_expires_at)
        self.assertIsNone(Controller(Path(self.temporary.name), FakePlayer()).reconnect_expires_at)
        self.assertNotIn(("loadfile",),self.player.calls)

    def test_auto_resume_opt_in_and_elapsed_timer(self):
        c=self.controller
        (c.tracks/"Rain.mp3").write_bytes(b"fixture")
        c.output="auto"
        c.resume_after_restart=True
        c.save()
        c.play("Rain.mp3")
        c.set_timer(2)
        self.player.properties["time-pos"]=36
        c.resume_last_saved=-60  # Advance past the checkpoint created when setting the timer.
        c.persist_resume()
        self.assertTrue((c.data/"resume.json").is_file())
        restarted=Controller(Path(self.temporary.name),FakePlayer())
        self.assertTrue(restarted.resume_after_restart)
        self.assertIsNotNone(restarted.resume_pending)
        restarted.tick()
        self.assertEqual(restarted.selected,"Rain.mp3")
        self.assertEqual(restarted.mode,"normal")
        self.assertGreater(restarted.deadline-time.monotonic(),60)
        self.assertTrue(any(x[0]=="seek" and x[1]==36 for x in restarted.player.calls))

    def test_no_resume_after_manual_stop_or_expired_timer(self):
        c=self.controller
        (c.tracks/"Rain.mp3").write_bytes(b"fixture")
        c.output="auto"
        c.resume_after_restart=True
        c.save()
        c.play("Rain.mp3")
        c.persist_resume()
        c.stop()
        self.assertFalse((c.data/"resume.json").exists())
        self.assertIsNone(Controller(c.data,FakePlayer()).resume_pending)
        candidate={"track":"Rain.mp3","mode":"sleep","position":22,"paused":False,
                   "updated":time.time()-5,"timer_end":time.time()-1}
        (c.data/"resume.json").write_text(json.dumps(candidate))
        self.assertIsNone(Controller(c.data,FakePlayer()).resume_pending)
        candidate["timer_end"]=time.time()+100
        candidate["updated"]=time.time()-350
        (c.data/"resume.json").write_text(json.dumps(candidate))
        self.assertIsNone(Controller(c.data,FakePlayer()).resume_pending)

    def test_resume_disabled_never_starts_stale_audio(self):
        c=self.controller
        (c.tracks/"Rain.mp3").write_bytes(b"fixture")
        (c.data/"resume.json").write_text(json.dumps(
            {"track":"Rain.mp3","mode":"normal","position":10,"paused":False,
             "updated":time.time(),"timer_end":None}))
        self.assertIsNone(Controller(c.data,FakePlayer()).resume_pending)

    def test_play_mode_next_shuffle_and_once_are_saved(self):
        c=self.controller
        for name in ("Alpha.mp3","Beta.mp3","Gamma.mp3"):
            (c.tracks/name).write_bytes(b"audio")
        c.output="auto"
        c.set_play_mode("next")
        self.assertEqual(c.play_mode,"next")
        self.assertFalse(c.loop)
        c.play("Alpha.mp3")
        self.assertEqual(c.choose_next_file(),"Beta.mp3")
        c.skip()
        self.assertEqual(c.selected,"Beta.mp3")
        c.set_play_mode("shuffle")
        self.assertNotEqual(c.choose_next_file(),"Beta.mp3")
        c.set_play_mode("once")
        self.assertFalse(c.loop)
        self.assertEqual(Controller(c.data,FakePlayer()).play_mode,"once")
        with self.assertRaises(ValueError):c.set_play_mode("invalid")

    def test_end_of_file_advances_once_in_next_mode(self):
        c=self.controller
        for name in ("A.mp3","B.mp3"):
            (c.tracks/name).write_bytes(b"audio")
        c.output="auto";c.set_play_mode("next")
        c.play("A.mp3")
        self.player.playback_status=lambda receipt:{"status":"completed"}
        c.tick()
        self.assertEqual(c.selected,"B.mp3")
        self.player.playback_status=lambda receipt:{"status":"started"}
        self.assertEqual(c.play_mode,"next")

    def test_timer_16_hour_bound_and_absolute_endpoint(self):
        c=self.controller
        c.set_timer(960)
        with self.assertRaises(ValueError):c.set_timer(961)
        with patch("server.seconds_to_end_time",return_value=3600) as convert:
            c.set_timer_end("03:15")
        self.assertLess(abs((c.deadline-time.monotonic())-3600),5)
        convert.assert_called_once_with("03:15","America/Chicago")

    def test_unity_volume_only_for_selected_bluetooth_on_play(self):
        c=self.controller
        c.speaker="02:00:00:00:00:06"
        c.output="pulse/bluez_output.02_00_00_00_00_06"
        self.player.properties["audio-device-list"].append({"name":c.output})
        (c.tracks/"Storm.mp3").write_bytes(b"fixture")
        with patch("server.normalize_selected_bluetooth_volume",return_value=True) as normalize:
            c.play("Storm.mp3")
        normalize.assert_called_once()
        self.assertEqual(normalize.call_args.args[:2],("02:00:00:00:00:06",c.output))
        self.assertIn(("set_property","volume",c.volume),self.player.calls)

    def test_alarm_preempts_audio_and_uses_current_selected_device(self):
        c=self.controller
        for name in ("Storm.mp3","Wake.mp3"):
            (c.tracks/name).write_bytes(b"audio")
        c.output="pulse/selected-output"
        self.player.properties["audio-device-list"].append({"name":c.output})
        c.play("Storm.mp3")
        c.set_timer(90)
        receipt=c.run_alarm({"track":"Wake.mp3","output":"pulse/obsolete-device",
                             "volume":50,"loop":False,"ring_minutes":3})
        self.assertIsInstance(receipt,dict)
        self.assertEqual(c.selected,"Wake.mp3")
        self.assertEqual(c.active_output,"pulse/selected-output")
        self.assertEqual(c.mode,"alarm")
        self.assertLess(c.deadline-time.monotonic(),190)
        self.assertGreater(c.deadline-time.monotonic(),170)
        self.assertIn(("stop",),self.player.calls)

    def test_alarm_scheduling_does_not_require_output_selection(self):
        c=self.controller
        (c.tracks/"Wake.mp3").write_bytes(b"audio")
        from test_scheduler import chicago
        with patch("scheduler.ZoneInfo",side_effect=chicago):
            c.alarm.configure({"enabled":True,"track":"Wake.mp3","output":None})
        self.assertTrue(c.alarm.state["config"]["enabled"])

    def test_unavailable_alarm_output_never_falls_back_to_default(self):
        c=self.controller
        (c.tracks/"Wake.mp3").write_bytes(b"audio")
        c.output=None
        with self.assertRaisesRegex(ValueError,"selected audio output is unavailable"):
            c.run_alarm({"track":"Wake.mp3","volume":50,"loop":False,"ring_minutes":3})
        self.assertNotIn(("loadfile",str(c.tracks/"Wake.mp3"),"replace"),self.player.calls)

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.player = FakePlayer()
        self.controller = Controller(Path(self.temporary.name), self.player)
        self.server = Server(("127.0.0.1", 0), self.controller, ["127.0.0.1"])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def request(self, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        raw = json.dumps(body).encode() if isinstance(body, dict) else body
        connection.request("GET" if body is None else "POST", path, body=raw, headers=headers or {})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_rejects_cross_origin_and_unknown_host(self):
        status, _ = self.request("/api/stop", {}, {"X-Sleep-Token": self.controller.token, "Origin": "http://attacker.test"})
        self.assertEqual(status, 403)
        status, _ = self.request("/api/stop", {})
        self.assertEqual(status, 403)
        status, _ = self.request("/api/status", headers={"Host": "attacker.test"})
        self.assertEqual(status, 403)
        self.assertEqual(self.player.calls, [])

    def test_upload_duplicate_does_not_overwrite(self):
        headers = {"X-Sleep-Token": self.controller.token}
        with patch("server.run", return_value='{"streams":[{"codec_type":"audio"}]}'):
            self.assertEqual(self.request("/api/upload?name=Rain.mp3", b"first", headers)[0], 201)
            self.assertEqual(self.request("/api/upload?name=Rain.mp3", b"second", headers)[0], 201)
        self.assertEqual((self.controller.tracks / "Rain.mp3").read_bytes(), b"first")
        self.assertEqual(len(self.controller.library()), 2)

    def test_thumbnail_upload_is_associated_and_replaced_after_validation(self):
        headers={"X-Sleep-Token":self.controller.token}
        (self.controller.tracks/"Rain.mp3").write_bytes(b"audio")
        (self.controller.tracks/"Thunder.mp3").write_bytes(b"other")
        self.assertIsNone(self.controller.artwork_url("Rain.mp3"))
        result='{"streams":[{"codec_name":"png","width":300,"height":300}]}'
        with patch("server.run",return_value=result):
            status, payload=self.request("/api/artwork?track=Rain.mp3&name=rain.png",b"png bytes",headers)
        self.assertEqual(status,201)
        art=json.loads(payload)["artwork"]
        self.assertIn("/api/artwork?track=Rain.mp3",art)
        self.assertEqual(self.request(art)[1],b"png bytes")
        library=json.loads(self.request("/api/tracks")[1])
        self.assertIsNotNone(next(x for x in library if x["id"]=="Rain.mp3")["artwork"])
        self.assertIsNone(next(x for x in library if x["id"]=="Thunder.mp3")["artwork"])
        old=self.controller.artwork_path("Rain.mp3")
        invalid='{"streams":[{"codec_name":"mpeg4","width":600,"height":600}]}'
        with patch("server.run",return_value=invalid):
            status,_=self.request("/api/artwork?track=Rain.mp3&name=other.jpg",b"invalid",headers)
        self.assertEqual(status,400)
        self.assertEqual(old.read_bytes(),b"png bytes")
        valid='{"streams":[{"codec_name":"mjpeg","width":400,"height":400}]}'
        with patch("server.run",return_value=valid):
            status,_=self.request("/api/artwork?track=Rain.mp3&name=new.jpg",b"updated jpeg",headers)
        self.assertEqual(status,201)
        self.assertEqual(self.controller.artwork_path("Rain.mp3").suffix,".jpg")
        self.assertEqual(self.controller.artwork_path("Rain.mp3").read_bytes(),b"updated jpeg")
        self.assertFalse(old.exists())
        self.assertEqual(self.request(self.controller.artwork_url("Rain.mp3"))[1],b"updated jpeg")
        self.assertEqual(self.controller.artwork_dir.joinpath("NoOtherFile").exists(),False)

    def test_thumbnails_reject_orphans_unsafe_paths_and_huge_files(self):
        headers={"X-Sleep-Token":self.controller.token}
        (self.controller.tracks/"Rain.mp3").write_bytes(b"audio")
        for path in ("/api/artwork?track=NotHere.mp3&name=image.png",
                     "/api/artwork?track=../Rain.mp3&name=image.png",
                     "/api/artwork?track=Rain.mp3&name=image.svg"):
            self.assertEqual(self.request(path,b"invalid",headers)[0],400)
        self.assertEqual(self.request("/api/artwork?track=Rain.mp3")[0],404)
        self.assertEqual(self.request("/api/artwork?track=../settings.json")[0],404)
        with patch("server.run",return_value='{"streams":[{"codec_name":"png","width":9000,"height":1000}]}'):
            self.assertEqual(self.request("/api/artwork?track=Rain.mp3&name=oversized.png",b"not image",headers)[0],400)
        self.assertEqual(list(self.controller.artwork_dir.iterdir()),[])

    def test_duplicate_named_audio_has_separate_artwork(self):
        headers={"X-Sleep-Token":self.controller.token}
        with patch("server.run",return_value='{"streams":[{"codec_type":"audio"}]}'):
            first=json.loads(self.request("/api/upload?name=Rain.mp3",b"first",headers)[1])["id"]
            second=json.loads(self.request("/api/upload?name=Rain.mp3",b"second",headers)[1])["id"]
        self.assertNotEqual(first,second)
        with patch("server.run",return_value='{"streams":[{"codec_name":"webp","width":200,"height":200}]}'):
            status,_=self.request("/api/artwork?track="+quote(second,safe="")+"&name=art.webp",b"webp",headers)
        self.assertEqual(status,201)
        self.assertIsNone(self.controller.artwork_url(first))
        self.assertIsNotNone(self.controller.artwork_url(second))

    def test_upload_validation_and_static_traversal(self):
        headers = {"X-Sleep-Token": self.controller.token}
        self.assertEqual(self.request("/api/upload?name=payload.exe", b"payload", headers)[0], 400)
        self.assertEqual(self.request("/../server.py")[0], 404)
        self.assertEqual(list(self.controller.tracks.iterdir()), [])

    def test_react_assets_cannot_escape_bundle_directory(self):
        root = Path(self.temporary.name)
        (root / "frontend/dist").mkdir(parents=True)
        (root / "frontend/dist/index.html").write_text("React integration fixture")
        (root / "private.txt").write_text("outside bundle")
        with patch("server.ROOT", root):
            self.assertEqual(self.request("/ui/")[0], 200)
            self.assertEqual(self.request("/ui/%2e%2e/%2e%2e/private.txt")[0], 404)

    def test_apk_installer_serves_only_fixed_public_assets(self):
        root = Path(self.temporary.name)
        folder = root / "install"
        folder.mkdir()
        (folder / "index.html").write_text("<h1>Install</h1>")
        (folder / "SleepSounds.apk").write_bytes(b"fake-apk-for-route-test")
        with patch("server.ROOT", root):
            self.assertEqual(self.request("/install/")[0], 200)
            self.assertEqual(self.request("/install/SleepSounds.apk"), (200, b"fake-apk-for-route-test"))
            self.assertEqual(self.request("/install/../server.py")[0], 404)

    def test_reconnect_setting_saved_over_http(self):
        headers={"X-Sleep-Token":self.controller.token}
        self.assertTrue(json.loads(self.request("/api/config")[1])["auto_reconnect"])
        self.assertEqual(self.request("/api/settings", {"auto_reconnect":False}, headers)[0],200)
        self.assertFalse(json.loads(self.request("/api/config")[1])["auto_reconnect"])
        self.assertFalse(Controller(Path(self.temporary.name),FakePlayer()).auto_reconnect)
        self.assertEqual(self.request("/api/settings",{"auto_reconnect":"no"},headers)[0],400)

    def test_reconnect_cutoff_http_validation_and_persistence(self):
        headers={"X-Sleep-Token":self.controller.token}
        self.assertEqual(json.loads(self.request("/api/config")[1])["reconnect_retry_minutes"],10)
        self.assertEqual(self.request("/api/settings",{"reconnect_retry_minutes":90},headers)[0],200)
        self.assertEqual(Controller(Path(self.temporary.name),FakePlayer()).reconnect_retry_minutes,90)
        for value in (0,-1,1441,2.5,"60",True):
            self.assertEqual(self.request("/api/settings",{"reconnect_retry_minutes":value},headers)[0],400)

    def test_resume_option_is_explicit_and_validated(self):
        headers={"X-Sleep-Token":self.controller.token}
        self.assertFalse(json.loads(self.request("/api/config")[1])["resume_after_restart"])
        self.assertEqual(self.request("/api/settings",{"resume_after_restart":True},headers)[0],200)
        self.assertTrue(Controller(Path(self.temporary.name),FakePlayer()).resume_after_restart)
        self.assertEqual(self.request("/api/settings",{"resume_after_restart":"true"},headers)[0],400)

    def test_invalid_media_is_not_published_and_temp_file_is_cleaned(self):
        with patch("server.run", return_value='{"streams":[{"codec_type":"video"}]}'):
            status, _ = self.request("/api/upload?name=Fake.mp3", b"not audio", {"X-Sleep-Token": self.controller.token})
        self.assertEqual(status, 400)
        self.assertEqual(list(self.controller.tracks.iterdir()), [])

    def test_adjustable_limits_persist_and_validate(self):
        headers = {"X-Sleep-Token": self.controller.token}
        self.assertEqual(json.loads(self.request("/api/config")[1])["max_upload_bytes"], 5 * 1024 ** 3)
        new_size = 10 * 1024 ** 3
        status, _ = self.request("/api/settings", {"max_upload_bytes": new_size, "storage_reserve_mb": 512, "sleep_minutes": 90}, headers)
        self.assertEqual(status, 200)
        config = json.loads(self.request("/api/config")[1])
        self.assertEqual(config["max_upload_bytes"], new_size)
        self.assertEqual(config["storage_reserve_mb"], 512)
        saved = Controller(Path(self.temporary.name), FakePlayer())
        self.assertEqual(saved.max_upload_bytes, new_size)
        self.assertEqual(saved.storage_reserve_mb, 512)
        self.assertEqual(saved.sleep_minutes, 90)
        for data in ({"max_upload_bytes": True}, {"max_upload_bytes": 0}, {"max_upload_bytes": 51*1024**3},
                     {"storage_reserve_mb": -1}, {"storage_reserve_mb": 10241}, {"sleep_minutes": 3000, "max_upload_bytes": 1024**3}):
            self.assertEqual(self.request("/api/settings", data, headers)[0], 400)
            self.assertEqual(self.controller.max_upload_bytes, new_size)
            self.assertEqual(self.controller.storage_reserve_mb, 512)

    def test_upload_checks_configured_disk_reserve(self):
        headers = {"X-Sleep-Token": self.controller.token}
        self.assertEqual(self.request("/api/settings", {"storage_reserve_mb": 1024}, headers)[0], 200)
        with patch("server.shutil.disk_usage") as disk:
            disk.return_value.free = 512 * 1024**2
            status, body = self.request("/api/upload?name=Rain.mp3", b"audio", headers)
        self.assertEqual(status, 400)
        self.assertIn(b"Not enough free storage", body)
        self.assertFalse(list(self.controller.tracks.iterdir()))

    def test_settings_persist_and_invalid_output_rejected(self):
        headers = {"X-Sleep-Token": self.controller.token}
        status, _ = self.request("/api/settings", {"loop": False, "volume": 22}, headers)
        self.assertEqual(status, 200)
        saved = Controller(Path(self.temporary.name), FakePlayer())
        self.assertFalse(saved.loop)
        self.assertEqual(saved.volume, 22)
        status, _ = self.request("/api/output", {"name": "unavailable"}, headers)
        self.assertEqual(status, 400)

    def test_upload_receipt_retry_reuses_saved_file(self):
        key='a'*32;headers={"X-Sleep-Token":self.controller.token}
        url='/api/upload?name=Repeat.wav&key='+key
        with patch("server.run",return_value='{"streams":[{"codec_type":"audio"}]}'):
            first=json.loads(self.request(url,b'first audio',headers)[1])
            second=json.loads(self.request(url,b'first audio',headers)[1])
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(list(self.controller.tracks.glob('*.wav'))),1)
        self.assertTrue(json.loads(self.request('/api/upload-result?key='+key)[1])['complete'])
        self.assertEqual(self.request('/api/upload-result?key=../bad')[0],400)

    def test_favorites_http_and_shared_library_revision(self):
        (self.controller.tracks/'Rain.wav').write_bytes(b'audio')
        headers={"X-Sleep-Token":self.controller.token}
        self.assertEqual(self.request('/api/favorite',{'track':'Rain.wav','favorite':True},headers)[0],200)
        rows=json.loads(self.request('/api/tracks')[1]);self.assertTrue(rows[0]['favorite'])
        self.assertGreater(self.controller.library_revision,0)
        self.assertEqual(self.request('/api/favorite',{'track':'Rain.wav','favorite':'true'},headers)[0],400)

    def test_normalization_http_validation(self):
        headers={"X-Sleep-Token":self.controller.token}
        self.assertEqual(self.request('/api/normalization',{'enabled':True},headers)[0],200)
        self.assertTrue(json.loads(self.request('/api/config')[1])['normalization'])
        self.assertEqual(self.request('/api/normalization',{'enabled':1},headers)[0],400)


if __name__ == "__main__":
    unittest.main()
