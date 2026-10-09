"""The installed runtime and distribution must report the same version."""
from importlib.metadata import version

import rapidxmltodict


def test_runtime_version_matches_distribution():
    assert rapidxmltodict.__version__ == version("rapidxmltodict")
    assert rapidxmltodict.__version__
