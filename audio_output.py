"""Configure only the explicitly selected Bluetooth output; never change unrelated sinks."""
import re
import os
import subprocess


def sink_id_for_speaker(status_text, address):
    needle = "bluez_output." + address.replace(":", "_").lower()
    in_sinks = False
    for line in status_text.splitlines():
        if "Sinks:" in line:
            in_sinks = True
            continue
        if in_sinks and "Sources:" in line:
            break
        if in_sinks and needle in line.lower():
            match = re.search(r"(?<!\d)(\d+)\.\s+(\S+)", line)
            if match and needle in match.group(2).lower():
                return match.group(1)
    return None


def normalize_selected_bluetooth_volume(speaker, output, run_command):
    """Pin PipeWire to unity gain for current explicit Bluetooth output.

    Only the selected Bluetooth sink is touched. Software mpv volume remains 0–100%.
    """
    # The user may select a Bluetooth output directly from Devices rather than Pair.
    # Extract its exact MAC from the chosen output; never change a different sink.
    selected = re.search(r"bluez_(?:output|sink)\.([0-9a-f]{2}(?:_[0-9a-f]{2}){5})", (output or "").lower())
    if not selected:
        return False
    address = selected.group(1).replace("_", ":")
    if speaker and speaker.lower() != address:
        return False
    status = run_command(["wpctl", "status", "-n"], timeout=6)
    sink = sink_id_for_speaker(status, address)
    if not sink:
        raise RuntimeError("Selected Bluetooth output not available for volume control.")
    run_command(["wpctl", "set-volume", "-l", "1.0", sink, "1.0"], timeout=5)
    return True


COMBINED_OUTPUT = "pipewire/sleep_sounds_combined"
COMBINED_BLUETOOTH_ADDRESS = os.environ.get("SLEEP_SOUNDS_COMBINED_BLUETOOTH_ADDRESS", "02:00:00:00:00:01")
COMBINED_BT = os.environ.get("SLEEP_SOUNDS_COMBINED_BLUETOOTH", "pipewire/bluez_output.02_00_00_00_00_01.1")
COMBINED_WIRED = os.environ.get("SLEEP_SOUNDS_COMBINED_WIRED", "pipewire/alsa_output.example.stereo")


def validate_combined_devices(devices):
    names = {d["name"] for d in devices}
    if COMBINED_OUTPUT not in names or not ({COMBINED_BT, COMBINED_WIRED} & names):
        raise RuntimeError("The combined output needs at least one available speaker.")
