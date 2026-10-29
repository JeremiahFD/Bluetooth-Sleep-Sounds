# Changelog

## Experimental combiner follow-up — 2026-10-29

Owner listening is encouraging with an isolated PipeWire 1.6.9 combine-stream client against the existing 1.4.2 system daemon. Signal obstruction reproduces some Bluetooth stutters; earlier wired failures remain unexplained. One possible temporary dropout recovered without intervention, and one wired-sink graph error was observed later. Long-duration reliability remains open. This is a documentation update: the trial libraries, personal output configuration and engine selection are not bundled; APK/Linux release binaries and checksums are unchanged.

## Reliability recurrence — 2026-10-28

The owner subsequently reports stuttering on the wired branch of extended Pi wired + Bluetooth playback. This supersedes the earlier tentative resolution wording below. The lifecycle helper was still installed and the latest APK release did not replace Pi audio code. Root cause remains under investigation. Documentation only; release binaries and checksums unchanged.


## 0.9.0-alpha.2 — Host connections and maintenance

- Remember a preferred playback host per installation; never silently substitute another host.
- Verify/discover hosts and show Connecting within one 20-second budget, with cancellation and stale-result guards.
- Replace the gray toolbar with a compact themed host selector.
- Fix controller Add assignment behavior with unsaved changes and explicit input capture.
- Add host-capability-gated restart, settings reset, factory reset and separate delete-all-audio controls with clear confirmations.
- Linux maintenance is opt-in and interrupts playback; Android maintains its foreground host service.


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
