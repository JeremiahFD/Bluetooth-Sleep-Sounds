#!/bin/bash
# Run as the Pi owner from the deployed app directory after OS update/reboot.
set -euo pipefail
cd "$(dirname "$0")/.."
for dependency in python3 mpv ffprobe bluetoothctl; do
    command -v "$dependency" >/dev/null || { echo "Missing $dependency; install the required package first." >&2; exit 1; }
done
if [[ "$PWD" != "$HOME/.local/share/sleep-sounds/app" ]]; then
    echo "Deploy the application to ~/.local/share/sleep-sounds/app first." >&2
    exit 1
fi
mkdir -p "$HOME/.config/systemd/user" "$HOME/.config/sleep-sounds"
if [[ ! -f "$HOME/.config/sleep-sounds/environment" ]]; then
    host_names="localhost,127.0.0.1,$(hostname | tr '[:upper:]' '[:lower:]').local"
    for address in $(hostname -I); do
        if [[ "$address" =~ ^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.) ]]; then
            host_names="$host_names,$address"
        fi
    done
    printf 'SLEEP_SOUNDS_HOSTS=%s\nSLEEP_SOUNDS_PORT=8080\n' "$host_names" > "$HOME/.config/sleep-sounds/environment"
    chmod 600 "$HOME/.config/sleep-sounds/environment"
fi
install -m 644 deploy/sleep-sounds.service "$HOME/.config/systemd/user/sleep-sounds.service"
systemctl --user daemon-reload
systemctl --user enable --now sleep-sounds.service
systemctl --user status sleep-sounds.service --no-pager
