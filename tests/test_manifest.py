"""Repository packaging checks that do not depend on a running HA instance."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from custom_components.sceneglow.const import DOMAIN

ROOT = Path(__file__).parents[1]


def test_manifest_and_hacs_metadata_agree() -> None:
    """HACS installs exactly one versioned, UI-configurable integration."""
    manifest = json.loads(
        (ROOT / "custom_components" / DOMAIN / "manifest.json").read_text()
    )
    hacs = json.loads((ROOT / "hacs.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert list(manifest) == [
        "domain",
        "name",
        *sorted(set(manifest) - {"domain", "name"}),
    ]
    assert manifest["domain"] == DOMAIN
    assert manifest["version"] == "1.1.0"
    assert manifest["documentation"] == ("https://github.com/AIGenuityLTD/SceneGlowHA")
    assert manifest["issue_tracker"] == (
        "https://github.com/AIGenuityLTD/SceneGlowHA/issues"
    )
    assert project["project"]["version"] == manifest["version"]
    assert project["project"]["authors"] == [{"name": "AIGenuity LTD"}]
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "hub"
    assert manifest["iot_class"] == "local_push"
    assert manifest["zeroconf"] == ["_sceneglow._tcp.local."]
    assert hacs["homeassistant"] == "2025.11.2"
    assert len(list((ROOT / "custom_components").iterdir())) == 1
    assert (ROOT / "install.sh").is_file()
    assert "AIGenuity LTD" in (ROOT / "LICENSE").read_text()
    assert not (ROOT / "scripts" / "run_fake_sceneglow.py").exists()
    assert not (ROOT / "SCENEGLOW_HOME_ASSISTANT_INTEGRATION_REPO_PLAN.md").exists()
    assert not (ROOT / "Screenshot 2026-08-24 224201.png").exists()
    assert not (ROOT / "ic_launcher.png").exists()


def test_ci_uses_an_installation_home_assistant_can_scan() -> None:
    """CI avoids editable path hooks and completes every Python matrix job."""
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text()

    assert "fail-fast: false" in workflow
    assert "pip install -e" not in workflow
    assert "python -m pip install '.[test]' ruff" in workflow


def test_custom_integration_has_complete_english_translation() -> None:
    """Custom integrations ship translations/en.json directly."""
    translation = json.loads(
        (ROOT / "custom_components" / DOMAIN / "translations" / "en.json").read_text()
    )
    assert translation["title"] == "SceneGlow"
    assert "service_state" in translation["entity"]["sensor"]
    assert "button" not in translation["entity"]
    switches = translation["entity"]["switch"]
    assert switches["capture"]["name"] == "Capture session"
    assert switches["capture_processing"]["name"] == "Capture processing"
