"""Shared provenance and isolation helpers for the standalone comparisons."""
from __future__ import annotations

import hashlib
import importlib.metadata
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

MIB = 1024 ** 2
VERSIONS = ("pr5", "standalone", "xmltodict")
ALL_VERSIONS = ("pr5", "hybrid", "standalone", "xmltodict")
BASELINE_COMMIT = "f5ae82c43ba445a52932432198a559b319b67188"
HYBRID_COMMIT = "8db94cc3d4a887038c3644c889c9823027214d35"
ORACLE_VERSION = "1.0.4"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(MIB), b""):
            h.update(block)
    return h.hexdigest()


def implementation_hashes(root):
    root = Path(root)
    paths = [root / "setup.py", root / "pyproject.toml"]
    for folder in (root / "src", root / "vendor"):
        paths.extend(p for p in folder.rglob("*") if p.is_file() and
                     p.suffix in (".py", ".pyi", ".cpp", ".hpp", ".h", ".so", ".pyd"))
    return {str(p.relative_to(root)): sha(p) for p in sorted(paths)}


def pin_cpu():
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
        return sorted(os.sched_getaffinity(0))
    return None


def comparison_versions(args):
    return ALL_VERSIONS if getattr(args, "hybrid", None) else VERSIONS


def child_env(version, before, after, hybrid=None):
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    if version == "xmltodict":
        env.pop("PYTHONPATH", None)
    else:
        root = {"pr5": before, "hybrid": hybrid, "standalone": after}[version]
        if root is None:
            raise ValueError(f"Missing source snapshot for {version}")
        env["PYTHONPATH"] = str(Path(root) / "src")
    return env


def verify_oracle():
    version = importlib.metadata.version("xmltodict")
    if version != ORACLE_VERSION:
        raise RuntimeError(f"Expected xmltodict {ORACLE_VERSION}; found {version}")
    return version


def metadata(args):
    verify_oracle()
    cpu = next((line.split(":", 1)[1].strip() for line in
                Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), platform.processor())
    roots = {"pr5": str(Path(args.before).resolve()),
             "standalone": str(Path(args.after).resolve())}
    if getattr(args, "hybrid", None):
        roots["hybrid"] = str(Path(args.hybrid).resolve())
    import xmltodict
    # Query the baseline/reference backend in a separate process. Candidate
    # timing/memory workers do not import xmltodict or Expat for this metadata.
    expat = subprocess.check_output([
        sys.executable, "-c",
        "import json,pyexpat; print(json.dumps({'version': pyexpat.EXPAT_VERSION, "
        "'version_info': pyexpat.version_info, 'module_origin': pyexpat.__spec__.origin, "
        "'features': pyexpat.features}))"
    ], text=True)
    import json
    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version, "executable": sys.executable,
        "platform": platform.platform(), "cpu": cpu, "cpu_affinity": pin_cpu(),
        "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
        "build_flags": "CC=gcc CXX=g++; setup.py build_ext --inplace --force; -O3 -std=c++17 -Wall -Wextra",
        "baseline_commit": BASELINE_COMMIT, "snapshot_roots": roots,
        "hybrid_baseline_commit": HYBRID_COMMIT if getattr(args, "hybrid", None) else None,
        "comparison_versions": comparison_versions(args),
        "xmltodict_version": verify_oracle(), "xmltodict_source_sha256": sha(xmltodict.__file__),
        "reference_expat_provenance": json.loads(expat),
        "source_and_binary_hashes_start": {v: implementation_hashes(root) for v, root in roots.items()},
        "common_harness_sha256": sha(__file__), "argv": sys.argv,
    }


def finish_metadata(data):
    metadata = data["metadata"]
    metadata["source_and_binary_hashes_end"] = {
        v: implementation_hashes(root) for v, root in metadata["snapshot_roots"].items()}
    metadata["source_and_binary_hashes_unchanged"] = (
        metadata["source_and_binary_hashes_start"] == metadata["source_and_binary_hashes_end"])
    assert metadata["source_and_binary_hashes_unchanged"], "Implementation changed while measuring"


def load_parser(version):
    verify_oracle()
    if version == "xmltodict":
        import xmltodict as parser
    else:
        import rapidxmltodict as parser
    return parser
