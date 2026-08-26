# SceneGlow Home Assistant User Guide

This guide explains how to install, pair, operate, automate, diagnose, and
remove the SceneGlow Home Assistant integration. It covers the SceneGlow
parent device, WLED fixture devices, and Home Assistant-backed fixture devices.

SceneGlow is the authority for capture state and fixture configuration. Home
Assistant sends a request, then displays the state reported by the SceneGlow
app. A control can therefore pass through a transitional state before the
requested operation finishes.

## Contents

- [Before you begin](#before-you-begin)
- [Install the integration](#install-the-integration)
- [Pair SceneGlow](#pair-sceneglow)
- [Understand the devices and entities](#understand-the-devices-and-entities)
- [Capture controls](#capture-controls)
- [Parent-device controls and sensors](#parent-device-controls-and-sensors)
- [Fixture devices](#fixture-devices)
- [Use SceneGlow in dashboards](#use-sceneglow-in-dashboards)
- [Automations](#automations)
- [Troubleshooting](#troubleshooting)
- [Download diagnostics and request support](#download-diagnostics-and-request-support)
- [Security and privacy](#security-and-privacy)
- [Update or remove the integration](#update-or-remove-the-integration)

## Before you begin

You need:

- Home Assistant 2025.11.2 or newer.
- A compatible SceneGlow app with its native Home Assistant integration
  enabled.
- The SceneGlow device and Home Assistant on a local network where they can
  reach each other.
- Access to the SceneGlow device during initial pairing and whenever its
  operating system requires screen-capture permission.

For installation and version requirements, see the project
[README](../README.md#installation).

## Install the integration

### HACS

1. Open **HACS → Integrations**.
2. Search for **SceneGlow**. If it is not listed, add
   `https://github.com/AIGenuityLTD/SceneGlowHA` as a custom integration
   repository.
3. Select **Download**.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → SceneGlow**.

### Manual installation

Download and extract the latest release, then run this command from the
extracted repository, replacing `/config` if your Home Assistant configuration
directory is elsewhere:

```bash
sh install.sh --config-dir /config
```

Restart Home Assistant, then open **Settings → Devices & services → Add
integration → SceneGlow**.

## Pair SceneGlow

SceneGlow normally appears as a discovered integration.

1. In the SceneGlow app, enable its native Home Assistant integration.
2. Enable pairing so that the TV displays a six-digit PIN.
3. In Home Assistant, open the discovered SceneGlow installation and select
   **Configure**.
4. Enter the PIN displayed by that SceneGlow installation.
5. Assign the SceneGlow parent device to the Home Assistant Area that should be
   used as its default room.

If automatic discovery is unavailable, select SceneGlow from **Add
integration**, enter the SceneGlow device's host name or IP address and API
port, then pair in the same way.

Pairing uses a short-lived PIN and pins the SceneGlow server identity. Do not
accept an unexpected identity-change warning. If a legitimate network change
moves the same installation to another address, use **Reconfigure** on the
integration entry; the integration verifies that it is still the same
SceneGlow installation.

If Home Assistant requests reauthentication, enable pairing in SceneGlow and
enter a new PIN. You do not need to delete and recreate the integration.

## Understand the devices and entities

One integration entry creates:

- A **SceneGlow parent device** for capture, application settings,
  connectivity, and performance measurements.
- A **child device for each WLED fixture** configured in SceneGlow.
- A **child device for each Home Assistant light fixture** used by SceneGlow.

The app advertises the controls it supports. A control described in this guide
may be absent or unavailable on an older app build, a different platform
variant, or a fixture for which it does not apply. The values, allowed ranges,
and choices shown by Home Assistant come from the app.

Home Assistant assigns entity IDs when the entities are first created. To find
an entity ID, open **Settings → Devices & services → SceneGlow**, select the
device, then select the entity and open its settings. You can also use
**Developer tools → States**. The IDs in the automation examples below are
examples and must be replaced with your own.

## Capture controls

The two capture switches have intentionally different jobs:

| Entity | When turned on | When turned off |
| --- | --- | --- |
| **Capture session** | Starts or requests the complete MediaProjection capture session | Stops the session and releases screen-capture permission |
| **Capture processing** | Runs or resumes frame processing | Pauses processing while retaining the current MediaProjection session and permission |

Use **Capture processing**, not **Capture session**, for a temporary pause.
Stopping a session is deliberately a stronger action than pausing processing.

### Capture session: Start and Stop

Turn **Capture session** on when no session exists to request a new capture
session. Android or Fire OS may require the user to approve screen capture on
the SceneGlow device. If SceneGlow is in the background, the app can report
**Awaiting capture permission** and show an actionable notification on the TV.
Open that notification and complete the operating-system prompt.

Turn **Capture session** off to stop completely. This also:

- stops frame processing;
- cancels a pending capture request or notification;
- releases the MediaProjection permission token; and
- makes **Capture processing** unavailable.

A later Start is a new session and follows the platform's normal permission
flow. Turning Capture session off while processing is paused still performs a
complete Stop and releases permission.

### Capture processing: Run and Pause

**Capture processing** is available only while the session is running or
paused.

- Turn it off to pause frame processing without ending the capture session.
- Turn it on to resume processing using the retained session, normally without
  another permission prompt.

While paused, **Capture session remains on** and **Capture processing is off**.
This is the preferred state for short idle periods and for automations that
need reliable, unattended resumption.

Retaining a session does not guarantee that it survives a device reboot, app
process termination, operating-system permission revocation, force-stop, or
some app/OS updates. If the platform invalidates MediaProjection, a new Start
and user approval may still be required.

### Capture-state reference

The **Capture state** sensor reports actual progress:

| State | Meaning | Capture session | Capture processing |
| --- | --- | --- | --- |
| `stopped` | No capture session or retained permission | Off | Unavailable |
| `starting` | SceneGlow is preparing a new session | Usually on | Unavailable |
| `awaiting_capture_permission` | The request is active but requires device interaction | On | Unavailable |
| `running` | Frames are being captured and processed | On | On |
| `paused` | Processing is paused; the session is retained | On | Off |
| `stopping` | SceneGlow is releasing the session | Usually off | Unavailable |
| `error` | SceneGlow could not complete or retain the operation | Reflects the requested target | Unavailable |

The **Capture session** switch represents the requested session target. This is
why it remains on while permission is pending. The **Capture state** sensor is
the better entity to use when an automation must know that capture has
actually reached `running` or `paused`.

### Permission behavior on Fire TV and Android TV

The integration cannot approve, bypass, or suppress a platform screen-capture
consent prompt.

On devices that require consent for every new session, an automation can
request Start, but capture will remain at `awaiting_capture_permission` until a
person approves it on the device. Such devices cannot provide guaranteed
unattended restart after Stop. Prefer Pause/Resume if unattended recovery is
important.

In testing, some Fire TV devices show a checkbox on the first permission
request that allows later capture-session requests to be approved
automatically. If that option is selected, subsequent Starts may work without
interaction. This behavior belongs to the Fire TV operating system and can
vary by model, Fire OS version, app build, policy, and the wording or presence
of the checkbox. It is not guaranteed by SceneGlowHA. A reinstall, data clear,
permission reset, OS update, or policy change may make approval necessary
again.

Choose the operating-system option only if automatic future capture is
appropriate for the device and household. Use Stop when releasing capture
permission is more important than unattended restart.

## Parent-device controls and sensors

### Controls

- **Capture session** — Start or Stop the complete screen-capture session.
- **Capture processing** — Run or Pause processing while retaining the
  session.
- **Home Assistant Ambience** — Enables the SceneGlow app's Home
  Assistant-backed ambience behavior. The app reports whether this takes
  effect immediately or on the next capture.
- **Detect Black Bars** — Enables the app's black-bar-aware capture behavior.
- **Ignore Screen Capture Indicator** — Enables the app's supported exclusion
  behavior for the platform capture indicator. This option may not be
  available on every platform build.

Open an entity's details in Home Assistant to inspect its `apply_behavior`
attribute:

- `immediate` means the app applies the saved value to the active session.
- `next_capture` means the saved value applies when the next capture starts.

Pause and Resume retain the current capture session, so they should not be
used to force a `next_capture` setting to apply. Applying such a setting may
require a complete Stop and Start, including any permission interaction the
device normally requires.

### State and connectivity

- **Capture state** — The authoritative lifecycle state described above.
- **Connected** — Whether Home Assistant currently has a working SceneGlow
  connection. Normal local push updates reconnect automatically and perform a
  full refresh if an event gap is detected.

### Diagnostics

- **Performance Diagnostics** — Immediately enables or disables SceneGlow's
  live metrics without stopping, restarting, pausing, or requesting capture
  permission.
- **Output frame rate** — The current output rate in frames per second.
- **Processing time** — The current processing time in milliseconds.
- **Capture resolution** — The active capture dimensions reported by the app.

The metric sensors are unavailable when the app is not publishing a live
value, including when Performance Diagnostics is off or capture is not
running. Turning diagnostics on starts measurement and publication; a short
adjustment delay is normal. Turning it off removes the measurement overhead
while normal error reporting continues.

## Fixture devices

SceneGlow creates child devices from the app's current fixture collection.
Adding, removing, or changing fixtures in the app is reflected in Home
Assistant automatically.

### Included in current capture

Every writable fixture has an **Included in current capture** switch:

- On includes the fixture in SceneGlow output.
- Off stops output to the fixture and asks SceneGlow to black or turn it off.

This is useful in scenes and automations, for example to exclude bedroom
lighting late at night while leaving the TV backlight active.

### WLED fixtures

A WLED fixture can expose app-defined controls in these groups:

- Connection and output: host, port, first LED, LED count, maximum FPS,
  maximum payload size, and black-on-stop behavior.
- Colour processing: brightness, saturation, gamma, white suppression, black
  threshold, smoothing, motion sensitivity, and synchronization delay.
- Screen geometry: edge depth; left, top, right, and bottom LED counts; start
  corner; direction; and LED offset.
- Free-form geometry: relative position, orientation, span, reverse order,
  layout, placement, direction, width, height, L-shape behavior, ring start,
  and cluster flow.
- Motion effects: effect, strength, trail, continuation delay, viscosity,
  colour persistence, ambient coverage/fade, and scene-change protection.
- Lighting use/profile: ScreenGlow, CabinetGlow, SkirtingGlow, LampGlow, or
  SpotGlow when supported by the app.

Only controls advertised for that fixture appear. Home Assistant enforces the
minimum, maximum, step, text length, and choices sent by SceneGlow. Some
geometry values are coupled; the integration submits them together so the app
can validate the complete layout. If a change is rejected as invalid, correct
the related LED counts or geometry before retrying.

Most fixture configuration is commonly marked `next_capture`; **Included in
current capture** is immediate. Check each entity's `apply_behavior` attribute
instead of assuming an apply time.

### Home Assistant-backed light fixtures

A Home Assistant-backed fixture can expose:

- Included in current capture.
- Position, including screen-relative positions and ambient placement.
- Minimum brightness.
- Maximum brightness.

Minimum brightness cannot exceed maximum brightness. The integration updates
these related values atomically so the app receives a consistent pair.

SceneGlow does not create a duplicate light entity. Continue using the
original Home Assistant light entity for ordinary on/off, colour, and
brightness control. The SceneGlow child device contains only the controls that
describe how that light participates in capture.

Compatible colour lights are offered to SceneGlow through a restricted local
broker and are grouped by Home Assistant Area. Assigning the parent SceneGlow
device to the intended Area helps identify the default room. SceneGlow does not
receive a general-purpose Home Assistant access token.

## Use SceneGlow in dashboards

Home Assistant does not guarantee the order of entities on a device page. To
make capture priority clear, create an Entities card containing, in this
order:

1. Capture state.
2. Capture session.
3. Capture processing.
4. Connected.

Add fixture participation switches to the same dashboard or to room-specific
cards. Put Performance Diagnostics and its three sensors in a separate
diagnostic card; diagnostics normally do not need to remain enabled.

## Automations

Automations should express the intended lifecycle action:

- For a temporary pause, turn **Capture processing** off.
- To resume a retained session, turn **Capture processing** on.
- To release capture permission, turn **Capture session** off.
- To create a new session, turn **Capture session** on and wait for **Capture
  state** to become `running`.

Do not repeatedly call Start while the state is `starting` or
`awaiting_capture_permission`. SceneGlow treats the HTTP response as an
immediate snapshot and publishes the final state later. Repeated retries cannot
approve the TV prompt and can make an automation noisy.

### Create an automation in the UI

For a simple Pause automation:

1. Open **Settings → Automations & scenes → Create automation**.
2. Choose a trigger such as a media player becoming paused or a room becoming
   unoccupied.
3. Add a State condition requiring **Capture state** to be `running`.
4. Add the action **Switch: Turn off** and select **Capture processing**.
5. Save and test it while watching the Capture state entity.

Create the matching Resume automation with a `paused` condition and **Switch:
Turn on** targeting Capture processing.

### YAML example: pause when playback pauses

Replace every example entity ID with the IDs from your Home Assistant system.

```yaml
alias: SceneGlow - Pause processing with playback
triggers:
  - trigger: state
    entity_id: media_player.living_room_tv
    from: "playing"
    to: "paused"
conditions:
  - condition: state
    entity_id: sensor.living_room_sceneglow_capture_state
    state: "running"
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.living_room_sceneglow_capture_processing
mode: single
```

This leaves Capture session on and retains the permission token.

### YAML example: resume when playback starts

```yaml
alias: SceneGlow - Resume processing with playback
triggers:
  - trigger: state
    entity_id: media_player.living_room_tv
    to: "playing"
conditions:
  - condition: state
    entity_id: sensor.living_room_sceneglow_capture_state
    state: "paused"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.living_room_sceneglow_capture_processing
mode: single
```

Because the condition requires `paused`, this automation will not attempt to
Resume when the session has been stopped and permission no longer exists.

### YAML example: intentionally stop and release permission

```yaml
alias: SceneGlow - Stop session when everyone leaves
triggers:
  - trigger: state
    entity_id: zone.home
    to: "0"
conditions: []
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.living_room_sceneglow_capture_session
mode: single
```

This is a complete Stop, not a Pause. A later Start may need approval on the
SceneGlow device.

### YAML example: start once and report a permission wait

```yaml
alias: SceneGlow - Start session for movie mode
triggers:
  - trigger: state
    entity_id: input_boolean.movie_mode
    to: "on"
conditions:
  - condition: state
    entity_id: sensor.living_room_sceneglow_capture_state
    state: "stopped"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.living_room_sceneglow_capture_session
  - wait_template: >-
      {{ states('sensor.living_room_sceneglow_capture_state') in
         ['running', 'stopped', 'error'] }}
    timeout: "00:02:00"
    continue_on_timeout: true
  - if:
      - condition: template
        value_template: >-
          {{ not is_state('sensor.living_room_sceneglow_capture_state',
                          'running') }}
    then:
      - action: persistent_notification.create
        data:
          notification_id: sceneglow_capture_permission
          title: SceneGlow needs attention
          message: >-
            Capture did not reach Running. Check the SceneGlow device for a
            screen-capture permission notification or error.
mode: single
```

`mode: single` prevents the same automation from issuing overlapping Start
requests while it waits. The Home Assistant notification does not approve the
TV prompt; it only tells a Home Assistant user that device interaction may be
needed.

### YAML example: exclude a fixture at night

```yaml
alias: SceneGlow - Exclude cabinet fixture overnight
triggers:
  - trigger: time
    at: "23:00:00"
conditions: []
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.cabinet_glow_included_in_current_capture
mode: single
```

Use a second automation or a scene to turn the fixture back on at the desired
time. This changes only that fixture's participation; it does not stop the
capture session.

## Troubleshooting

### SceneGlow is not discovered

- Confirm Home Assistant and SceneGlow are on the same reachable LAN.
- Check that mDNS/multicast is not blocked between VLANs or wireless clients.
- Confirm the native Home Assistant integration is enabled in SceneGlow.
- Use manual host and port setup if multicast discovery is unavailable.

### Pairing is rejected

- Confirm pairing is currently enabled in SceneGlow.
- Use the six-digit PIN displayed by the same device being added.
- Generate a fresh PIN if the previous code expired.
- Check the TV clock and Home Assistant clock if short-lived credentials fail
  unexpectedly.

### Capture session is on but nothing is being processed

Check **Capture state**:

- `awaiting_capture_permission`: open SceneGlow's actionable notification on
  the TV and approve the platform prompt.
- `paused`: turn Capture processing on.
- `starting`: allow the transition to finish; do not repeatedly call Start.
- `error`: inspect SceneGlow and Home Assistant logs, then resolve the reported
  device or capture problem.

### Both capture switches went off

If **Capture session** was turned off, this is expected: Stop releases the
session, so Capture processing becomes off/unavailable. To pause without losing
permission, leave Capture session on and turn Capture processing off.

### Capture processing is unavailable

It is writable only in `running` or `paused`. Start Capture session and finish
any device-side permission flow first. It is intentionally unavailable while
stopped, starting, stopping, awaiting permission, or errored.

### A fixture control did not take effect immediately

Open the entity details and check `apply_behavior`. A `next_capture` setting is
saved immediately but used on the next new capture. Also check that the fixture
is available and Included in current capture.

### Performance sensors are unavailable

Turn on **Performance Diagnostics**, confirm Capture state is `running`, and
allow a short publication delay. No manual refresh button is required; values
arrive from the app. Disable Performance Diagnostics after testing when the
extra measurements are not needed.

### Entities or controls are missing

The app advertises supported capabilities and fixture controls. Update both the
SceneGlow app and SceneGlowHA, restart Home Assistant after an integration
update, and confirm the relevant fixture exists in the app. Platform-specific
controls may legitimately be absent.

### The integration is unavailable

Check the **Connected** entity and network reachability. If Home Assistant asks
for reauthentication, enable pairing in the app and enter a fresh PIN. A
reconnect automatically refreshes authoritative state; avoid adding duplicate
integration entries.

## Download diagnostics and request support

To download Home Assistant diagnostics:

1. Open **Settings → Devices & services → SceneGlow**.
2. Open the integration entry's menu.
3. Select **Download diagnostics**.

SceneGlowHA redacts credentials, pairing codes, network addresses, light
history, and captured content. Review any diagnostic file before sharing it,
as you would with other system information.

Report integration problems through the
[SceneGlowHA issue tracker](https://github.com/AIGenuityLTD/SceneGlowHA/issues).
Include the SceneGlowHA version, Home Assistant version, SceneGlow app version,
device model/platform, reproduction steps, relevant logs, and redacted
diagnostics.

## Security and privacy

- Communication is local and HTTPS-only during normal use.
- PIN pairing binds the Home Assistant credential to the pinned SceneGlow
  server identity.
- SceneGlowHA receives state, configuration, and diagnostic measurements; it
  does not receive captured screen frames.
- The Home Assistant light broker exposes only compatible colour-light
  catalogue and apply operations. It is not a general service proxy.
- Pausing processing retains MediaProjection. Use Stop when you explicitly
  want the permission and capture session released.

## Update or remove the integration

For HACS installations, download the offered SceneGlow update and restart Home
Assistant. For manual installations, download the latest release and run
`install.sh` again.

To remove SceneGlowHA:

1. Delete the SceneGlow entry from **Settings → Devices & services**. If the
   app is reachable, this asks it to revoke the paired credential.
2. Remove the integration in HACS, or delete
   `<config>/custom_components/sceneglow/` for a manual installation.
3. Restart Home Assistant.
