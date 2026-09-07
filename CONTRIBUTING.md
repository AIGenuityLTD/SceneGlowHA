# Contributing to SceneGlowHA

Thank you for helping improve SceneGlow for Home Assistant.

## Development setup

SceneGlowHA requires Python 3.13 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install '.[dev]'
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

## Gitflow and versions

- `main` contains released code only. Release tags use `v<version>`.
- `develop` is the integration branch for the next release.
- Create `feature/*` branches from `develop` and merge them back through a pull
  request after tests pass.
- Create `release/*` branches from `develop`; replace the development version
  with the final version, complete the changelog, merge into both `main` and
  `develop`, and tag the `main` merge.
- Create urgent `hotfix/*` branches from `main`, then merge the result into both
  `main` and `develop` and tag the `main` merge.
- During development, use the next minor version with a PEP 440 development
  suffix such as `1.1.0.dev0`. Keep `pyproject.toml`, the integration manifest,
  installer expectations, manifest tests, and the changelog version aligned.
