"""Headless BlueZ pairing agent: deliberate phone approval for a requested speaker only."""
from __future__ import annotations
import logging
import re
import secrets
import threading
import time

LOG = logging.getLogger("sleep-sounds.pairing")
ADDRESS = re.compile(r"/dev_((?:[0-9A-Fa-f]{2}_){5}[0-9A-Fa-f]{2})$")
INTERFACE = "org.bluez.Agent1"
PATH = "/local/sleepsounds/PairingAgent"


class PairingBridge:
    def __init__(self, controller):
        self.controller = controller
        self.lock = threading.RLock()
        self.pending = None
        self.ready = False
        self.error = "Bluetooth pairing agent is starting."
        self.context = None
        self.timeout_seconds = 55

    def state(self):
        with self.lock:
            public = None if not self.pending else dict(self.pending["public"])
            return {"available": self.ready, "message": self.error, "pending": public}

    def start(self):
        threading.Thread(target=self._run, name="sleep-sounds-bluez-agent", daemon=True).start()

    def _run(self):
        try:
            import dbus
            import dbus.service
            from dbus.mainloop.glib import DBusGMainLoop
            from gi.repository import GLib
            DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()
            self.context = GLib
            bridge = self

            class Agent(dbus.service.Object):
                def __init__(self):
                    super().__init__(bus, PATH)

                def request(self, kind, device, ok, fail, code=None):
                    match = ADDRESS.search(str(device))
                    address = match.group(1).replace("_", ":").upper() if match else None
                    with bridge.controller.lock:
                        expected = bridge.controller.pairing_target
                    if not address or address != expected:
                        fail(dbus.exceptions.DBusException("Pairing was not requested in Sleep Sounds.",
                                                            name="org.bluez.Error.Rejected"))
                        return
                    name = address
                    try:
                        obj = bus.get_object("org.bluez", str(device))
                        prop = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                        name = str(prop.Get("org.bluez.Device1", "Alias")) or address
                    except Exception:
                        pass
                    with bridge.lock:
                        if bridge.pending:
                            fail(dbus.exceptions.DBusException("Another pairing request is pending.",
                                                                name="org.bluez.Error.Rejected"))
                            return
                        request_id = secrets.token_hex(12)
                        bridge.pending = {
                            "public": {"id": request_id, "kind": kind, "name": name,
                                       "address": address, "code": code,
                                       "expires_in": bridge.timeout_seconds},
                            "expires_at": time.monotonic() + bridge.timeout_seconds,
                            "ok": ok, "fail": fail,
                        }

                @dbus.service.method(INTERFACE, in_signature="", out_signature="")
                def Release(self):
                    with bridge.lock:
                        bridge.ready = False
                        bridge.error = "BlueZ released the pairing agent."

                @dbus.service.method(INTERFACE, in_signature="o", out_signature="s", async_callbacks=("ok", "fail"))
                def RequestPinCode(self, device, ok, fail):
                    self.request("pin", device, ok, fail)

                @dbus.service.method(INTERFACE, in_signature="o", out_signature="u", async_callbacks=("ok", "fail"))
                def RequestPasskey(self, device, ok, fail):
                    self.request("passkey", device, ok, fail)

                @dbus.service.method(INTERFACE, in_signature="ou", out_signature="", async_callbacks=("ok", "fail"))
                def RequestConfirmation(self, device, passkey, ok, fail):
                    self.request("confirm", device, ok, fail, f"{int(passkey):06d}")

                @dbus.service.method(INTERFACE, in_signature="o", out_signature="", async_callbacks=("ok", "fail"))
                def RequestAuthorization(self, device, ok, fail):
                    self.request("authorize", device, ok, fail)

                @dbus.service.method(INTERFACE, in_signature="os", out_signature="", async_callbacks=("ok", "fail"))
                def AuthorizeService(self, device, uuid, ok, fail):
                    self.request("authorize", device, ok, fail)

                @dbus.service.method(INTERFACE, in_signature="os", out_signature="")
                def DisplayPinCode(self, device, pincode):
                    # Display-only stage; the external speaker must confirm independently.
                    pass

                @dbus.service.method(INTERFACE, in_signature="ouq", out_signature="")
                def DisplayPasskey(self, device, passkey, entered):
                    # Display-only stage; BlueZ does not expect a reply from the application.
                    pass

                @dbus.service.method(INTERFACE, in_signature="", out_signature="")
                def Cancel(self):
                    bridge.cancel_pending("Bluetooth pairing was canceled.")

            def expire():
                with bridge.lock:
                    req = bridge.pending
                    if req:
                        req["public"]["expires_in"] = max(0, int(req["expires_at"] - time.monotonic()))
                        if time.monotonic() >= req["expires_at"]:
                            bridge.pending = None
                        else:
                            req = None
                if req:
                    req["fail"](dbus.exceptions.DBusException("Phone confirmation timed out.",
                                                              name="org.bluez.Error.Rejected"))
                return True

            agent = Agent()
            manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1")
            manager.RegisterAgent(PATH, "KeyboardDisplay")
            manager.RequestDefaultAgent(PATH)
            with self.lock:
                self.ready = True
                self.error = "Phone pairing approvals ready."
            GLib.timeout_add_seconds(1, expire)
            LOG.info("Headless BlueZ agent registered and selected as default.")
            GLib.MainLoop().run()
        except Exception as exc:
            with self.lock:
                self.ready = False
                self.error = "Phone pairing agent unavailable: " + str(exc)[-180:]
            LOG.exception("Could not register BlueZ agent")

    def cancel_pending(self, reason):
        with self.lock:
            req = self.pending
            self.pending = None
        if req:
            self.context.idle_add(self._reject, req, reason)

    @staticmethod
    def _reject(req, reason):
        import dbus
        req["fail"](dbus.exceptions.DBusException(reason, name="org.bluez.Error.Rejected"))
        return False

    @staticmethod
    def _approve(req, value):
        import dbus
        if req["public"]["kind"] == "pin":
            req["ok"](value)
        elif req["public"]["kind"] == "passkey":
            req["ok"](dbus.UInt32(int(value)))
        else:
            req["ok"]()
        return False

    def respond(self, request_id, approve, value=None):
        if type(approve) is not bool or not isinstance(request_id, str):
            raise ValueError("Choose approve or reject for a valid pairing request.")
        with self.lock:
            req = self.pending
            if not req or req["public"]["id"] != request_id or time.monotonic() > req["expires_at"]:
                raise ValueError("Pairing request expired. Search and connect again.")
            kind = req["public"]["kind"]
            if approve and kind in {"pin", "passkey"}:
                if not isinstance(value, str) or not value.isdigit():
                    raise ValueError("Enter the digits requested by the speaker.")
                if kind == "pin" and not (1 <= len(value) <= 16):
                    raise ValueError("PIN must be 1–16 digits.")
                if kind == "passkey" and not (1 <= len(value) <= 6 and int(value) <= 999999):
                    raise ValueError("Passkey must be 1–6 digits.")
            self.pending = None
        if not approve:
            self.context.idle_add(self._reject, req, "Rejected on phone.")
        else:
            self.context.idle_add(self._approve, req, value)
