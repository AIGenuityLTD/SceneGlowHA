# SceneGlow for Home Assistant

[![Release](https://img.shields.io/github/v/release/AIGenuityLTD/SceneGlowHA)](https://github.com/AIGenuityLTD/SceneGlowHA/releases)
[![Tests](https://github.com/AIGenuityLTD/SceneGlowHA/actions/workflows/test.yml/badge.svg)](https://github.com/AIGenuityLTD/SceneGlowHA/actions/workflows/test.yml)
[![HACS validation](https://github.com/AIGenuityLTD/SceneGlowHA/actions/workflows/hacs.yml/badge.svg)](https://github.com/AIGenuityLTD/SceneGlowHA/actions/workflows/hacs.yml)
[![License](https://img.shields.io/github/license/AIGenuityLTD/SceneGlowHA)](LICENSE)

SceneGlow is a local-push Home Assistant custom integration for Android TV and
Fire TV installations running the SceneGlow app. It discovers SceneGlow on the
local network, pairs with the PIN shown on the TV, exposes capture and fixture
controls, and can broker compatible Home Assistant colour lights without a
Home Assistant long-lived access token.

The SceneGlow app remains authoritative for capture state, fixture
configuration, effects, output addressing, and persisted settings.

## Requirements

- Home Assistant 2025.11.2 or newer.
- A compatible SceneGlow app with its native Home Assistant integration enabled. (>1.7.5 - unreleased at time of writing.)
- Home Assistant and the SceneGlow device on a network where mDNS and the
  SceneGlow API port are reachable.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=AIGenuityLTD&repository=SceneGlowHA&category=integration)

1. Select the button above, or open **HACS → Integrations → ⋮ → Custom
   repositories**.
2. If adding it manually, enter
   `https://github.com/AIGenuityLTD/SceneGlowHA` and select **Integration**.
3. Open SceneGlow in HACS and select **Download**.
4. Restart Home Assistant when prompted.
5. Open **Settings → Devices & services → Add integration → SceneGlow**.

HACS installs only `custom_components/sceneglow/`. Development files from this
repository are not copied into Home Assistant.

### Guided manual installation

1. Download and extract the source archive from the
   [latest SceneGlowHA release](https://github.com/AIGenuityLTD/SceneGlowHA/releases/latest).
2. Open a terminal in the extracted directory.
3. Run the installer with the path containing your Home Assistant
   `configuration.yaml`:

   ```bash
   sh install.sh --config-dir /config
   ```

   A Home Assistant Core installation commonly uses:

   ```bash
   sh install.sh --config-dir "$HOME/.homeassistant"
   ```

4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → SceneGlow**.

The installer validates its source, stages a clean copy, and moves an existing
installation into `<config>/.sceneglow-backups/` before upgrading. It does not
restart Home Assistant or alter configuration files.

To install without the script, copy `custom_components/sceneglow/` to
`<config>/custom_components/sceneglow/`, replacing the complete old directory,
then restart Home Assistant.

## Pairing

1. Enable the native Home Assistant integration in the SceneGlow app.
2. Enable pairing on the TV so that SceneGlow displays its six-digit PIN.
3. Select the discovered SceneGlow installation in Home Assistant.
4. Enter the PIN shown by that installation.
5. Assign the SceneGlow parent device to the Home Assistant Area that should be
   used as SceneGlow's default room.

SceneGlow is normally discovered automatically. If mDNS is unavailable, select
SceneGlow from **Add integration** and enter the device address and port.

## Capture controls

| Entity | On | Off |
| --- | --- | --- |
| Capture session | Start or retain the complete capture session | Stop capture and release Android MediaProjection permission |
| Capture processing | Run or resume frame processing | Pause processing while retaining MediaProjection permission |

Starting a stopped capture session requires confirmation on the SceneGlow
device. Pausing with **Capture processing** does not release permission and can
be resumed without another Android consent prompt.

## Features

- Zeroconf discovery with secure manual-address fallback.
- PIN-authorized pairing and pinned TLS server identity.
- Ordered WebSocket push updates with sequence-gap recovery and independent
  reconciliation.
- Capture session, processing, state, and connectivity entities.
- Dynamic WLED and Home Assistant-backed fixture child devices.
- Typed switch, number, select, and text controls generated from the app's
  advertised capabilities and validation metadata.
- Atomic writes for coupled LED geometry and brightness settings.
- Revision-safe fixture and application configuration changes.
- Constrained Home Assistant light catalogue and colour/brightness broker,
  grouped through Home Assistant Areas.
- Optional output frame rate, processing time, and capture-resolution sensors.
- Redacted Home Assistant diagnostics.

Home Assistant-backed fixtures do not create duplicate light entities. The
original Home Assistant light remains the light; SceneGlow adds only its
capture-participation and configuration entities to the SceneGlow child device.

## Diagnostics and troubleshooting

Enable **Performance Diagnostics** on the SceneGlow parent device to publish
output FPS, processing time, and capture resolution. These sensors become
unavailable when the app is not publishing measurements. Enabling or disabling
diagnostics does not restart capture or request permission again.

Common checks:

- If SceneGlow is not discovered, confirm that both devices are on the same LAN
  and that mDNS is not blocked, then use manual setup if necessary.
- If **Capture processing** is unavailable, first start **Capture session** and
  approve the Android prompt on the TV.
- If a remote start shows **Awaiting capture permission**, open the actionable
  notification on the TV and approve capture.
- If an entity is unavailable, check the **Connected** entity and download the
  integration diagnostics from Home Assistant.

Report integration problems through the
[SceneGlowHA issue tracker](https://github.com/AIGenuityLTD/SceneGlowHA/issues),
not to HACS or Home Assistant. Include the SceneGlowHA version, Home Assistant
version, device platform, reproduction steps, relevant logs, and redacted
integration diagnostics.

## Security and privacy

Normal communication is local and HTTPS-only. First contact captures the
SceneGlow certificate fingerprint, and PIN-authorized pairing binds the stored
credential to that identity. Rediscovery cannot silently replace the trusted
endpoint.

The light broker exposes only compatible colour-light catalogue and apply
operations; it is not a generic Home Assistant service proxy. SceneGlowHA does
not receive screen frames. Credentials, pairing codes, host addresses, light
history, and captured content are excluded from diagnostics.

## Updating and removal

For HACS installations, download the offered update and restart Home Assistant.
For manual installations, extract the new release and run `install.sh` again.

To remove SceneGlowHA:

1. Delete each SceneGlow integration entry from **Settings → Devices & services**.
2. Remove `<config>/custom_components/sceneglow/` or remove the repository in HACS.
3. Restart Home Assistant.
4. Optionally remove `<config>/.sceneglow-backups/` after confirming no rollback
   is needed.

Removing a Home Assistant entry asks the reachable SceneGlow app to revoke that
entry's paired credential.

## Contributing

Development setup, test rationale, and pull-request expectations are documented
in [CONTRIBUTING.md](CONTRIBUTING.md). Automated tests remain in the public
source repository because they protect the protocol and upgrade behavior; HACS
does not install them.

## License

Copyright © AIGenuity LTD. Licensed under the [MIT License](LICENSE).
