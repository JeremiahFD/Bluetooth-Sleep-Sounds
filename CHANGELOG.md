# Changelog

## Reliability follow-up — 2026-10-28

The owner reports one full Raspberry Pi listening night with zero stutters, followed by continued clean playback after the stream-lifecycle fix. This build may have resolved that setup’s problem; prior symptoms could be device/configuration-specific. Cause and wider compatibility remain unconfirmed; output combination was not specified. Documentation update only, with no replacement of release binaries or checksums.

## 0.9.0-alpha.1 — Initial public alpha

- Publish the Android local host/controller foundation and fuller Linux backend.
- Include profiles, library tools, timers, themes, Android gain/EQ and experimental Linux processing/routing.
- Fix HTTP request starvation from idle browser preconnections.
- Make startup host selection conditional on distinct reachable host identities.
- Replace installation-specific defaults with manual/discoverable host configuration and synthetic test fixtures.
- Include screenshots from a simulated library, personal-use terms, third-party notices and compatibility/known-stutter documentation.
- No recordings, saved profiles, credentials or household device configuration bundled.

This alpha does not establish overnight reliability or full platform parity. See README for current limits and roadmap; suggestions are welcome.
