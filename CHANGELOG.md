# Changelog

All notable changes to SceneGlow for Home Assistant will be documented here.

## 1.1.0.dev0 - Unreleased

- Add Area-first compatible-light discovery and selected-Area catalogue requests,
  while retaining complete catalogue responses for older SceneGlow clients.

## 1.0.0 - 2026-08-25

- Release the complete local-push SceneGlow protocol v1 integration as stable.
- Remove the redundant manual Refresh button and clean its registry entry during
  upgrade, including for offline SceneGlow entries; push events and independent
  reconciliation remain authoritative.
- Route high-frequency performance samples only to their diagnostic sensors,
  avoiding unnecessary state writes across every SceneGlow entity.
- Skip dynamic fixture/configuration inventory work when those collections have
  not changed.
- Strictly validate live diagnostic samples against the canonical protocol and
  correctly map WebSocket HTTP handshake failures into reauthentication or
  reconnect handling.
- Complete the production metadata, documentation, and regression coverage for
  the v1.0.0 release.
- Add a staged manual installer with automatic upgrade backups and document
  HACS, manual installation, updating, removal, troubleshooting, and support.
- Remove internal planning, screenshot, source-artwork, and executable fake-server
  artifacts from the public repository while retaining automated regression tests.
- Correct public repository links and release validation for HACS, Hassfest, and
  the supported Python test matrix.

## 0.1.0-alpha.15 - 2026-08-25

- Apply existing diagnostic-entity migrations before platform forwarding so
  newly enabled metric entities load during the same integration setup.

## 0.1.0-alpha.14 - 2026-08-25

- Make the existing-entity diagnostic migration compatible with Home Assistant
  versions that expose registry disablers by their string value.

## 0.1.0-alpha.13 - 2026-08-25

- Consume SceneGlow's immediate live performance diagnostics from state snapshots
  and push events as output FPS, processing-time, and capture-resolution sensors.
- Enable previously integration-disabled metric entities during upgrade while
  preserving entities that a user explicitly disabled.
- Prevent delayed configuration responses from rolling back a newer settings
  revision and avoid redundant retries when a conflicting write already applied.
- Update the fake protocol server and tests for immediate diagnostics, absent-value
  availability, wildcard reconciliation, and response/event races.

## 0.1.0-alpha.12 - 2026-08-25

- Migrate existing Home Assistant registry records so upgraded SceneGlow
  devices use `AIGenuity LTD` and **Performance Diagnostics** appears in the
  Diagnostic section without requiring the integration to be re-paired.

## 0.1.0-alpha.11 - 2026-08-25

- Add a More Info permission reminder to **Capture session** explaining that a
  new session requires confirmation on the SceneGlow device.
- Classify **Performance Diagnostics** in Home Assistant's Diagnostic section.
- Correct the integration manufacturer and package author to `AIGenuity LTD`.

## 0.1.0-alpha.10 - 2026-08-25

- Rename the parent Start/Stop switch from **Current capture** to
  **Capture session**, clearly distinguishing it from the independent
  **Capture processing** Run/Pause switch without changing its stable identity.

## 0.1.0-alpha.9 - 2026-08-24

- Add the required `capture_pause` protocol capability and recognize `paused` as
  a distinct requested-running capture state.
- Add authenticated pause/resume API and coordinator operations that cache the
  immediate state snapshot while retaining event-stream reconciliation.
- Add a capability-gated parent **Capture processing** switch, independently of
  the existing **Current capture** start/stop control.
- Extend the fake SceneGlow server and regression coverage for pause/resume
  transitions, idempotency, state availability, capability gating, and stopping
  from paused.

## 0.1.0-alpha.8 - 2026-08-24

- Use the supplied SceneGlow artwork as the bundled integration brand icon at
  standard and high-density sizes.
- Restore Home Assistant's domain-appropriate icons for fixture switches,
  numbers, selects, and text entities instead of overriding every entity with
  a fixture-type icon.
- Make end-to-end config-entry test cleanup unconditional and correct its fake
  server entity/device expectations.

## 0.1.0-alpha.7 - 2026-08-24

- Parse the app's typed fixture `controls` arrays with strict type-specific
  validation while ignoring future optional properties.
- Add capability-driven switch, number, select, and text entities for all WLED
  and HA-backed fixture settings without duplicating fixture participation.
- Use stable installation/fixture/control identities, authoritative cached
  values, and dynamic entity addition/removal.
- Support individual key/value and atomic multi-value fixture PATCH forms,
  including coupled LED geometry and HA brightness constraints.
- Reconcile successful responses and fixture events with the shared revision,
  bounded conflict retry, and actionable unavailable/invalid/stale errors.
- Append the advertised WLED Lighting Use to child-device names and follow
  profile changes in the device registry.
- Expand the fake server and regression suite to cover all 47 WLED controls,
  the four HA-backed controls, metadata, validation, and typed entities.

## 0.1.0-alpha.6 - 2026-08-24

- Fetch authenticated server capabilities instead of constructing them inside
  Home Assistant.
- Add strict fixture/configuration models and revision-aware API controls with
  actionable conflict, unavailable, invalid, and stale-control errors.
- Coordinate service state, fixture collection, and configuration collection as
  one reconciled snapshot with shared-revision writes and bounded retries.
- Reconcile wildcard control events, stream epoch changes, sequence gaps, and
  reconnects while coalescing overlapping refreshes.
- Add dynamic WLED and HA-backed fixture child devices with capture-participation
  switches; no duplicate HA light entities are created.
- Add all four application configuration switches and expose their apply timing.
- Expand privacy-preserving diagnostics and the authenticated fake server.
- Declare the live-validated Home Assistant 2025.11.2 minimum in HACS and
  package documentation.
- Add regression coverage for control models, API routes, coordinator behavior,
  entity hierarchy/lifecycle, Amazon availability, and redaction.

## 0.1.0-alpha.5 - 2026-08-23

- Make pairing the sole authorization step and remove the per-light allowlist
  form from first-time setup and Configure.
- Return every enabled compatible colour light with its Home Assistant Area and
  stable entity-registry reference.
- Return the SceneGlow parent device's assigned HA Area as the default-room hint
  and retain unassigned compatible lights in the catalogue.
- Continue to reject arbitrary services and references outside the compatible
  light catalogue.

## 0.1.0-alpha.4 - 2026-08-23

- Add explicit light authorization to first-time pairing as well as Configure.
- Handle authorized-light catalogue and constrained light-apply requests over
  the authenticated SceneGlow event WebSocket.
- Use stable entity-registry entry IDs as opaque broker references and resolve
  the current entity ID only inside Home Assistant.
- Advertise the paired HA-light broker capability to the SceneGlow runtime.

## 0.1.0-alpha.3 - 2026-08-23

- Fix the PIN form HTTP 500 on Home Assistant 2025.11 by keeping its schema
  frontend-serializable and validating six ASCII digits in the flow handler.
- Apply the same PIN validation to first-time pairing and reauthentication.
- Add regression coverage for frontend schema conversion and malformed PINs.

## 0.1.0-alpha.2 - 2026-08-23

- Align HTTP, pairing, state, error, and WebSocket models with the canonical
  SceneGlow control protocol v1 artifacts.
- Add secure first-contact TLS certificate fingerprint capture followed by
  pinned `/info` and PIN-bound pairing.
- Make Zeroconf discovery the primary flow and reduce normal onboarding to the
  six-digit TV PIN; retain address entry as a manual fallback.
- Default new entries to management-only access and move HA-light authorization
  to integration options.
- Use the app's port `47990` and remove the unsupported capabilities request.

## 0.1.0-alpha.1 - 2026-08-23

- Add HACS and Home Assistant custom-integration packaging.
- Add strict SceneGlow control protocol v1 identity, state, capability, pairing,
  and event models.
- Add shared-session async HTTP/WebSocket client with authentication, TLS
  fingerprint pinning, error mapping, and service control.
- Add manual and Zeroconf config flows, pairing, least-privilege light-scope
  selection, reauthentication, reconfiguration, and verified rediscovery.
- Add typed config-entry runtime data and clean unload/removal behavior.
- Add local-push coordinator, independent reconciliation, event-gap recovery,
  and bounded reconnect behavior.
- Add parent device, connected binary sensor, actual service-state sensor,
  requested-running capture switch, diagnostic sensors, and refresh button.
- Add privacy-preserving diagnostics.
- Add local-only fake SceneGlow server and protocol tests.
