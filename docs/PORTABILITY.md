# Linux deployment and portability

Android runs the APK; Linux runs the Python server with mpv. The Linux backend is the fuller implementation. Native EQ, codecs, Bluetooth routing, alarms, remotes and background behavior differ by platform. Test your own hardware.

## Linux user service

Build the frontend first. Copy the repository contents into `~/.local/share/sleep-sounds/app` (not into the data root itself). Keep recordings and runtime settings outside Git. Then, as the normal playback user:

```sh
cd ~/.local/share/sleep-sounds/app
bash deploy/install-user-service.sh
sudo loginctl enable-linger "$USER"
journalctl --user -u sleep-sounds -n 50
```

The installer creates a private user environment file and a systemd user service. Review its generated allowed hosts, port and network binding. It does not configure your Wi-Fi or pair speakers. A headless PipeWire user session and correct group/input permissions may need distro-specific setup. Do not run the player as root.

## Experimental wired + Bluetooth output

The helper and service template are included in both the repository and Linux release archive. Its virtual combined output can appear in the existing output selector once running. A general UI for choosing group members, adding outputs and saving groups is not implemented; you can use an AI coding tool to build it from these components (see the README customization example).

The optional helper is not installed/enabled by the basic installer. First find your own exact output names through the app/`wpctl status`/`pw-dump`. Configure the same environment for the app and helper:

- `SLEEP_SOUNDS_COMBINED_WIRED=pipewire/<your-wired-sink-name>`
- `SLEEP_SOUNDS_COMBINED_BLUETOOTH=pipewire/<your-bluetooth-sink-name>`
- `SLEEP_SOUNDS_COMBINED_BLUETOOTH_ADDRESS=<your-speaker-address>`

The shipped defaults are synthetic, deliberately nonfunctional example targets, not a device configuration. The virtual output name is `sleep_sounds_combined`. Set `PYTHONPATH` to the app directory if running the helper from a different diagnostics directory. Review service paths and add an EnvironmentFile directive for your configuration before enabling the optional helper. The on-demand metadata path requires a compatible PipeWire release; the implementation was developed against1.4.2. It is experimental and may stutter or drift. Do not claim support for arbitrary numbers of Bluetooth devices.

## Optional monitoring

`scripts/sleep-sounds-health.py` and its service template provide bounded local diagnostics. Review paths, CPU/memory limits, journal retention and exported contents before enabling. Monitoring does not prove the final speaker was uninterrupted. No historical device logs are included.

## Build Android

Use JDK17, SDK35 and the Gradle wrapper. Build the frontend, then copy its **contents** to `android/app/src/main/assets/full-ui/` before assembling. The build ships no saved host addresses or recordings. Phones start as remotes; TV mode enables the local host by default. Enable local hosting explicitly to use a phone/tablet as the player. Fresh debug keys are generated locally; never publish those keys.

## Current limits

Android host alarms, controller mapping, multi-output mixing, normalization and Linux effect parity are not implemented. No boot receiver or forced recovery from Android force-stop is included. Local server access after opening/Home has been checked; overnight Bluetooth/standby acceptance remains open. Native desktop applications and alternate Linux distributions are future compatibility work, not tested promises.
