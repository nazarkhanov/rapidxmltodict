"""Keep curated prose and automatically added install instructions in sync."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/prepare_release_notes.py"
spec = importlib.util.spec_from_file_location("prepare_release_notes", SCRIPT)
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


def test_initial_release_overview():
    body = notes.compose_notes("0.1.0", ROOT / "docs/release-notes")
    assert "first public release" in body
    assert "Compatibility and safety" in body
    assert "lower memory use is not guaranteed" in body
    assert body.count("## Install") == 1
    assert body.count("python -m pip install rapidxmltodict==0.1.0") == 1
    assert "https://pypi.org/project/rapidxmltodict/0.1.0/" in body


def test_missing_curated_notes_have_safe_fallback(tmp_path):
    body = notes.compose_notes("0.2.0rc1", tmp_path)
    assert "generated changelog below" in body
    assert "first public release" not in body
    assert body.count("## Install") == 1
    assert "rapidxmltodict==0.2.0rc1" in body


def test_existing_prose_preserved(tmp_path):
    prose = "## Unicode release\n\nPreserve café and **formatting**."
    (tmp_path / "1.2.3.md").write_text(prose + "\n", encoding="utf-8")
    assert notes.compose_notes("1.2.3", tmp_path).startswith(prose + "\n\n")


def test_empty_curated_file_fails(tmp_path):
    (tmp_path / "1.2.3.md").write_text(" \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        notes.compose_notes("1.2.3", tmp_path)


@pytest.mark.parametrize("version", ["../README", "01.2.3", "v1.2.3", "1.2.3\n"])
def test_noncanonical_versions_rejected(version, tmp_path):
    with pytest.raises(ValueError):
        notes.compose_notes(version, tmp_path)


def test_cli_writes_expected_file(tmp_path):
    output = tmp_path / "release-notes.md"
    subprocess.run([sys.executable, str(SCRIPT), "0.1.0", "--output", str(output)],
                   check=True)
    assert output.read_text(encoding="utf-8") == notes.compose_notes(
        "0.1.0", ROOT / "docs/release-notes"
    )
