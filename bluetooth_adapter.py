"""Optional, explicitly selected BlueZ adapter. Never falls back to another radio."""
from __future__ import annotations

import re
import time
import json

# Initialize GLib's D-Bus thread support before the server starts workers.
# Synchronous private clients must not inherit the pairing agent's default loop:
# that loop dispatches in another thread while these short-lived buses close.
try:
    from dbus.mainloop.glib import threads_init
except ImportError:
    pass  # The unconfigured path and non-Pi unit tests do not require D-Bus.
else:
    threads_init()

MAC = re.compile(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}")
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"


def device_name(props):
    # Keep the legacy line-oriented parser unambiguous for remote-provided names.
    return " ".join(str(props.get("Alias", props["Address"])).split())


def validate_output(adapter_address, output, run_command, *, client_factory=None):
    """Verify both BlueZ connection and actual PipeWire device identity, read-only."""
    match = re.search(r"bluez_(?:output|sink)\.((?:[0-9a-f]{2}_){5}[0-9a-f]{2})", (output or "").lower())
    if not adapter_address or not match:
        return
    if not MAC.fullmatch(adapter_address):
        raise RuntimeError("Invalid selected Bluetooth adapter address.")
    client = None
    try:
        client = (client_factory or BluezClient)()
        objects = client.objects(2)
        adapter = next((str(path) for path, interfaces in objects.items()
                        if str(interfaces.get(ADAPTER, {}).get("Address", "")).upper() == adapter_address.upper()), None)
        if adapter is None:
            raise RuntimeError("Selected Bluetooth adapter is unavailable. Reconnect it before playback.")
        target = adapter + "/dev_" + match.group(1).upper()
        if not bool(objects.get(target, {}).get(DEVICE, {}).get("Connected", False)):
            raise RuntimeError("Speaker is not connected through the selected Bluetooth adapter.")
        rows = json.loads(run_command(["pw-dump"], timeout=2))
        node_name = output.split("/", 1)[-1]
        nodes = [row for row in rows if row.get("info", {}).get("props", {}).get("node.name") == node_name]
        if len(nodes) != 1:
            raise RuntimeError("Cannot verify the selected Bluetooth output. Select its PipeWire output and retry.")
        device_id = nodes[0]["info"]["props"].get("device.id")
        device = next((row for row in rows if row.get("id") == device_id), {})
        if device.get("info", {}).get("props", {}).get("api.bluez5.path") != target:
            raise RuntimeError("Bluetooth output belongs to another adapter. Reconnect using the selected adapter.")
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError("Cannot verify selected Bluetooth output: " + str(error)[-250:]) from error
    finally:
        if client is not None:
            client.close()


class BluezClient:
    def __init__(self):
        try:
            import dbus
        except ImportError as error:
            raise RuntimeError("Selecting a Bluetooth adapter requires the host's python3-dbus package.") from error
        self.dbus = dbus
        # A private connection keeps discovery alive and avoids sharing the pairing
        # agent's connection across HTTP/reconnect worker threads.
        from dbus.mainloop import NULL_MAIN_LOOP
        self.bus = dbus.SystemBus(private=True, mainloop=NULL_MAIN_LOOP)

    def call(self, path, interface, method, *args, timeout=5):
        obj = self.bus.get_object("org.bluez", path, introspect=False)
        if interface == ADAPTER and method == "RemoveDevice":
            args = (self.dbus.ObjectPath(args[0]),)
        return getattr(self.dbus.Interface(obj, interface), method)(*args, timeout=timeout)

    def objects(self, timeout):
        return self.call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", timeout=timeout)

    def trust(self, path, timeout):
        return self.call(path, "org.freedesktop.DBus.Properties", "Set", DEVICE,
                         "Trusted", self.dbus.Boolean(True, variant_level=1), timeout=timeout)

    def close(self):
        self.bus.close()


def execute(adapter_address, arguments, timeout=15, *, client_factory=None, sleep=time.sleep):
    """Return the small bluetoothctl text interface currently consumed by server.py."""
    if not isinstance(adapter_address, str) or not MAC.fullmatch(adapter_address):
        raise RuntimeError("Invalid selected Bluetooth adapter address.")
    args = list(arguments)
    duration = None
    if args[:1] == ["--timeout"]:
        if len(args) < 3 or not args[1].isdigit() or not 1 <= int(args[1]) <= 120:
            raise RuntimeError("Invalid Bluetooth operation timeout.")
        duration = int(args[1])
        args = args[2:]
    if not args:
        raise RuntimeError("Missing Bluetooth operation.")
    action = args[0]
    if action not in {"info", "devices", "scan", "pair", "trust", "connect", "disconnect", "remove"}:
        raise RuntimeError("Unsupported Bluetooth operation for selected adapter.")
    if action in {"info", "pair", "trust", "connect", "disconnect", "remove"}:
        if len(args) != 2 or not MAC.fullmatch(args[1]):
            raise RuntimeError("Invalid Bluetooth device address.")
    elif action == "devices":
        if len(args) > 2 or (len(args) == 2 and args[1] not in {"Paired", "Connected"}):
            raise RuntimeError("Unsupported Bluetooth device filter.")
    elif args != ["scan", "on"] or duration is None:
        raise RuntimeError("Bluetooth discovery must have a bounded duration.")

    deadline = time.monotonic() + timeout
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise RuntimeError("Selected Bluetooth adapter operation timed out.")
        return value

    client = None
    try:
        client = (client_factory or BluezClient)()
        objects = client.objects(min(5, remaining()))
        path = next((str(path) for path, interfaces in objects.items()
                     if str(interfaces.get(ADAPTER, {}).get("Address", "")).upper() == adapter_address.upper()), None)
        if path is None:
            # Deliberately avoid "device not available": server uses that phrase
            # to forget an unpaired speaker. An unplugged radio must retain it.
            raise RuntimeError("Selected Bluetooth adapter is unavailable. Reconnect that adapter to retry.")
        devices = {str(p): interfaces[DEVICE] for p, interfaces in objects.items()
                   if DEVICE in interfaces and str(interfaces[DEVICE].get("Adapter", "")) == path}
        if action == "devices":
            field = args[1] if len(args) == 2 else None
            return "\n".join("Device {} {}".format(str(props["Address"]), device_name(props))
                             for _, props in sorted(devices.items())
                             if not field or bool(props.get(field, False)))
        if action == "scan":
            client.call(path, ADAPTER, "StartDiscovery", timeout=min(5, remaining()))
            try:
                sleep(min(duration, remaining()))
            finally:
                # Discovery is scoped to this private D-Bus client; closing it
                # also releases discovery if stopping fails or the timeout ends.
                client.call(path, ADAPTER, "StopDiscovery", timeout=3)
            return "Discovery started\nDiscovery stopped"
        address = args[1].upper()
        target = path + "/dev_" + address.replace(":", "_")
        props = devices.get(target)
        if props is None:
            raise RuntimeError("Device " + address + " not available on selected Bluetooth adapter.")
        if action == "info":
            return "Device {} {}\n{}".format(address, device_name(props), "\n".join(
                "\t{}: {}".format(name, "yes" if bool(props.get(name, False)) else "no")
                for name in ["Paired", "Connected", "Trusted"]))
        if action == "remove":
            client.call(path, ADAPTER, "RemoveDevice", target, timeout=remaining())
        elif action == "trust":
            client.trust(target, remaining())
        else:
            client.call(target, DEVICE, action.capitalize(), timeout=min(duration or timeout, remaining()))
        return "Pairing successful" if action == "pair" else "Bluetooth operation complete"
    except RuntimeError:
        raise
    except Exception as error:
        # Normalize D-Bus exceptions for the server's existing bounded failure path.
        raise RuntimeError("Selected Bluetooth adapter operation failed: " + str(error)[-400:]) from error
    finally:
        if client is not None:
            client.close()
