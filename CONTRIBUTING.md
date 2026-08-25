# Contributing to SceneGlowHA

Thank you for helping improve SceneGlow for Home Assistant.

## Development setup

SceneGlowHA requires Python 3.13 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
ruff format --check .
ruff check .
pytest
```

The `tests/` directory is intentionally part of the public source repository.
It contains automated protocol, coordinator, entity, configuration-flow, and
package regression coverage. HACS does not install it into Home Assistant; only
`custom_components/sceneglow/` is installed.

`tests/fake_sceneglow.py` is an in-process test fixture. It binds only to the
test runner's loopback server and is not an end-user executable.

## Pull requests

- Keep changes focused and explain their user-visible effect.
- Add or update tests for protocol and entity behavior changes.
- Keep credentials, pairing codes, host addresses, and captured screen data out
  of commits, fixtures, logs, and diagnostics.
- Ensure Ruff, pytest, Hassfest, and HACS validation pass.
- Update `CHANGELOG.md` for user-visible changes.

The SceneGlow app owns the canonical LAN protocol. Protocol changes must first
be defined in the app repository's `docs/protocol/sceneglow-control-v1/`
contract and then implemented here.
