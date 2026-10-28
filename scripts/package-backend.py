"""Create deployable source without Windows locale re-encoding or secret/config files."""
import io
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
names = ["server.py", "scheduler.py", "playback.py", "bluetooth_agent.py", "audio_output.py", "timers.py", "audio_processing.py", "audio_presets.py", "track_details.py", "profiles.py", "persistence.py", "deploy/install-user-service.sh", "deploy/sleep-sounds.service",
         "install/index.html", "install/README.md", "install/SleepSounds.apk"]
names += ["library_discovery.py", "system_status.py", "app_release.py", "install/release.json", "remote_controls.py", "remote_input.py", "docs/PORTABILITY.md"]
names += ["bluetooth_adapter.py", "speaker_sync.py", "LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "scripts/sleep-sounds-health.py", "scripts/sleep-sounds-combined-output.py", "deploy/sleep-sounds-health.service", "deploy/sleep-sounds-combined-output.service"]
names += [path.relative_to(root).as_posix() for path in (root / "third_party").glob("*") if path.is_file()]
names += [path.relative_to(root).as_posix() for path in (root / "frontend/dist").rglob("*") if path.is_file()]
(root / "artifacts").mkdir(exist_ok=True)
with tarfile.open(root / "artifacts/pi-backend.tar.gz", "w:gz") as archive:
    for name in names:
        raw = (root / name).read_bytes()
        if name.endswith((".py", ".sh", ".service")):
            raw = raw.replace(b"\r\n", b"\n")
        info = tarfile.TarInfo(name)
        info.size = len(raw)
        info.mode = 0o700 if name.endswith(".sh") else 0o600
        archive.addfile(info, io.BytesIO(raw))
print("Packaged source and built interface; no device settings, recordings or secrets included.")
