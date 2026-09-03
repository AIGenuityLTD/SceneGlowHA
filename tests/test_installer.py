"""End-user installer tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "install.sh"


def test_installer_creates_clean_install_and_recoverable_upgrade(
    tmp_path: Path,
) -> None:
    """The installer replaces stale files and preserves the previous version."""
    first = subprocess.run(
        ["sh", INSTALLER, "--config-dir", tmp_path],
        check=True,
        capture_output=True,
        text=True,
    )
    target = tmp_path / "custom_components" / "sceneglow"
    assert "SceneGlow 1.1.0.dev0 installed" in first.stdout
    assert json.loads((target / "manifest.json").read_text())["version"] == "1.1.0.dev0"
    assert not (target / "button.py").exists()

    stale = target / "obsolete.py"
    stale.write_text("obsolete")
    second = subprocess.run(
        ["sh", INSTALLER, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    backups = list((tmp_path / ".sceneglow-backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "obsolete.py").read_text() == "obsolete"
    assert not stale.exists()
    assert "Previous installation backed up" in second.stdout


def test_installer_help_and_invalid_directory(tmp_path: Path) -> None:
    """Help succeeds and invalid targets fail without creating files."""
    help_result = subprocess.run(
        ["sh", INSTALLER, "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--config-dir PATH" in help_result.stdout

    missing = tmp_path / "missing"
    invalid = subprocess.run(
        ["sh", INSTALLER, "--config-dir", missing],
        check=False,
        capture_output=True,
        text=True,
    )
    assert invalid.returncode != 0
    assert "does not exist" in invalid.stderr
    assert not missing.exists()
