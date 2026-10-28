# Host connection and device-selection plan

Status: **Planned for the next reviewed build. Not implemented by this document.**

## One application, local configuration

Use the same application code, features and connection behavior for the public GitHub version and household installations. Addresses, enrolled host identities, selected defaults and device names belong in local runtime settings, never hardcoded into a separate private application build. Preserve existing saved connections/profile data during migration. The current private working source and public snapshot differ; reconcile those changes before claiming parity. Keep private project records, credentials, audio and diagnostics outside public Git history.

## Default sleep device

- Add Default sleep device under Settings → Connections; save it separately on each phone and preserve it across in-place updates.
- Store the verified host identity with its connection candidates, not just an IP/name. Address changes must not select a different host with a similar name.
- If a default is configured, connect to it without opening the picker. If it is unavailable, offer Retry and Choose another device. Never silently switch to another host.
- Without a default, choose the sole reachable verified host; show the picker when multiple distinct hosts are available. Keep manual selection and manual address entry available.
- Include Remember as default when choosing a device. A host's user profiles are independent of this phone-local preference.

## Discovery

Combine saved connections and verified discovery results into one list, deduplicated by host identity. Another installation should appear when its playback-host service is enabled/running and advertises on a reachable network; installing a remote-only app must not create a fake host entry. Check new hosts as well as the currently seeded entries. Support manual-address recovery when multicast is blocked. Native Android discovery and browser-accessible discovery need explicit platform acceptance; do not assume an ordinary browser has a native mDNS browsing API.

## Connecting, failure and timeout

- On launch/reconnect show Connecting to <selected host> with a calm progress indicator. Do not render a Cannot connect heading while connection attempts are still in progress.
- Use one **20-second overall connection/retry budget** as the initial app default. This is a product choice, not a claimed universal standard. Do not apply a separate20seconds to each address, discovery result or retry.
- Try LAN first, then an explicitly configured mesh address within the same budget; keep retries bounded and limited to the intended verified host when a default is selected.
- Mark connected only after host identity verification and the control page is ready. Stop retries after success.
- At the deadline, show a clear failure state with Retry, Choose another device and Connection settings. Allow cancellation/device selection while connecting. Invalid settings or explicit security/permission errors can show specific immediate guidance.
- A retry starts a fresh budget; cancel/ignore older attempts so a late result cannot reopen the wrong host or overwrite newer UI state.
- Reconnecting the controller must not stop/restart playback, change outputs, select tracks or alter pairings/settings on the playback host.

## Themed selector

Remove the large separate gray native toolbar. Put a compact selected-host name, connection indicator and chevron in the existing themed header. Use the theme's translucent/glass styling, accessible contrast and adequate touch targets. Tapping it opens the host picker/settings. Keep native recovery controls available when the web interface is unavailable. Avoid depending on the failed page to recover the connection.

## Acceptance before release

1. A phone with a saved default continues choosing that host even when another host appears or answers faster; offline default never silently selects another host.
2. Defaults survive app restarts/upgrades and remain independent between installations.
3. A newly advertised host appears without a hardcoded address; one host at two addresses appears only once.
4. Slow startup stays in Connecting, including beyond10seconds; at20seconds an unsuccessful attempt shows recovery options. Successful attempts dismiss Connecting promptly.
5. Retry/cancel/switch safely ignore stale completions. Controller reconnect does not interrupt ongoing audio.
6. Host selection looks integrated in every theme and on phone/tablet/TV layouts; offline recovery remains usable.
7. Test public and household configurations against the same source and behavior. Public packages contain no household configuration. Include the separately prepared controller-assignment fix during the reviewed source reconciliation.

No APK build, device installation or deployment is authorized merely by this planning document. Retain the existing release/versioning checklist for the later approved build.
