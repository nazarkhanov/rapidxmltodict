"""Regression tests for publication guards (no network or publication)."""
import importlib.util
from pathlib import Path

import pytest

# This script is also included in the sdist used by wheel tests.
spec = importlib.util.spec_from_file_location(
    "release_checks", Path(__file__).resolve().parents[1] / "scripts/release_checks.py"
)
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


@pytest.mark.parametrize("tag, version", [
    ("v1.2.3", "1.2.3"), ("v0.1.0rc1", "0.1.0rc1"),
    ("v1.2.3a1", "1.2.3a1"), ("v1.2.3b2", "1.2.3b2"),
    ("v1.2.3.post1", "1.2.3.post1"),
])
def test_supported_tag(tag, version):
    assert checks.tag_version(tag) == version


@pytest.mark.parametrize("tag", [
    "1.2.3", "v1.2", "v01.2.3", "v1.2.3rc01", "v1.2.3.dev1",
    "v1.2.3+local", "release-1.2.3", "v1.2.3;echo bad", "v1.2.3\n",
])
def test_reject_invalid_tag(tag):
    with pytest.raises(ValueError):
        checks.tag_version(tag)


def test_missing_distributions(tmp_path):
    with pytest.raises(ValueError, match="source distribution"):
        checks.check_distributions(tmp_path, "1.2.3")
