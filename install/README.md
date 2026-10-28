# APK distribution

Download the public APK from GitHub Releases. Linux uses the Python server, not an APK. No runtime audio or credentials are bundled. To serve your reviewed APK from a private Linux host, place it at install/SleepSounds.apk and create release.json from those exact bytes using the version_code, version_name, sha256 and signer_sha256 fields expected by app_release.py. Publish APK, manifest and page consistently. Increment versionCode above13 for the next modified distributed build. Preserve package/signing identity for in-place updates. Do not check keys or binaries into Git.
