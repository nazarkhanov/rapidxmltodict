#!/usr/bin/env python3
"""Seven workloads: PR #5, optional hybrid baseline, candidate, xmltodict 1.0.4.

Reuses benchmark.py's fixtures and measurement workers. Every implementation is
selected in a fresh process using the same interpreter, oracle, and parameters.
No optional JSON round-trip comparator is included in this direct comparison.
Use --hybrid to add the frozen 8db94cc implementation to the same-process-isolated
comparison without changing the measurement parameters for any parser.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import random
import statistics
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


common = module("standalone_common", HERE / "standalone-common.py")
original = module("original_benchmark", HERE / "benchmark.py")


def worker(args):
    common.verify_oracle()
    if args.mode == "fixtures":
        original.HERE = Path(args.fixtures)
        original.HERE.mkdir(parents=True, exist_ok=True)
        return original.create_fixtures()
    parser = common.load_parser(args.version)
    args.library = "xmltodict" if args.version == "xmltodict" else "rapidxmltodict"
    if args.mode == "check":
        import xmltodict
        value = original.load_input(args.fixture, args.input_type)
        expected, actual = xmltodict.parse(value), parser.parse(value)
        return {"equal_to_xmltodict": actual == expected,
                "difference": None if actual == expected else original.diagnose_difference(expected, actual),
                "parser_module": parser.__file__}
    return {**original.worker(args), "parser_module": parser.__file__,
            "xmltodict_version": common.verify_oracle()}


def main(args):
    versions = common.comparison_versions(args)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "metadata": common.metadata(args), "workloads": {}, "run_order": []}
    data["metadata"].update({"script_sha256": common.sha(__file__),
                            "original_harness_sha256": common.sha(HERE / "benchmark.py"),
                            "method": {"timing_processes": args.timing_processes,
                                       "memory_processes": args.memory_processes,
                                       "batches_per_process": args.samples,
                                       "target_batch_seconds": args.batch_seconds,
                                       "warmup_calls": 3, "calibration_calls": 3,
                                       "default_public_api": True, "gc_enabled": True,
                                       "output_destruction_timed": True, "fixture_loading_timed": False,
                                       "ordering_seed": 20261009,
                                       "memory": "Fresh-process ru_maxrss and Linux current RSS with retained output; separate tracemalloc excludes untraced native allocations."}})
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--mode", "fixtures", "--fixtures", args.fixtures]
    fixtures = json.loads(subprocess.check_output(command, text=True))
    orderer = random.Random(20261009)

    def save():
        output.write_text(json.dumps(data, indent=2) + "\n")

    def run(mode, spec, version):
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--mode", mode,
                   "--version", version, "--fixture", spec["path"], "--input-type", spec["input_type"],
                   "--samples", str(args.samples), "--batch-seconds", str(args.batch_seconds)]
        response = subprocess.run(command, env=common.child_env(version, args.before, args.after, args.hybrid),
                                  text=True, capture_output=True, check=True, close_fds=False, timeout=180)
        data["run_order"].append({"workload": spec["name"], "mode": mode, "version": version})
        return json.loads(response.stdout)

    for spec in fixtures:
        name = spec["name"]
        entry = {**spec, "equality": {}, "timing": {}, "rss": {}, "tracemalloc": {}, "summary": {}}
        data["workloads"][name] = entry
        for version in versions:
            entry["equality"][version] = run("check", spec, version)
            save()
            assert entry["equality"][version]["equal_to_xmltodict"], (name, version, entry["equality"][version])
        for mode, repetitions, key in (("time", args.timing_processes, "timing"), ("rss", args.memory_processes, "rss")):
            entry[key] = {v: [] for v in versions}
            for repetition in range(repetitions):
                order = list(versions)
                orderer.shuffle(order)
                for version in order:
                    entry[key][version].append(run(mode, spec, version))
                    save()
        for version in versions:
            entry["tracemalloc"][version] = run("tracemalloc", spec, version)
            samples = [s for run_ in entry["timing"][version] for s in run_["batch_ns_per_call"]]
            entry["summary"][version] = {
                "median_ms": statistics.median(samples) / 1e6,
                "min_ms": min(samples) / 1e6, "max_ms": max(samples) / 1e6,
                "median_peak_rss_mib": statistics.median(x["peak_rss_bytes"] for x in entry["rss"][version]) / common.MIB,
                "median_baseline_peak_mib": statistics.median(x["baseline_peak_rss_bytes"] for x in entry["rss"][version]) / common.MIB,
                "median_incremental_peak_mib": statistics.median(x["incremental_peak_rss_bytes"] for x in entry["rss"][version]) / common.MIB,
            }
        before, after, reference = (entry["summary"][v]["median_ms"] for v in common.VERSIONS)
        entry["standalone_speedup_vs_pr5"] = before / after
        entry["standalone_speedup_vs_xmltodict"] = reference / after
        if args.hybrid:
            entry["standalone_speedup_vs_hybrid"] = entry["summary"]["hybrid"]["median_ms"] / after
        save()
        hybrid_note = (f'; hybrid {entry["summary"]["hybrid"]["median_ms"]:.3f} ms; '
                       f'standalone/hybrid speedup {entry["standalone_speedup_vs_hybrid"]:.3f}x') if args.hybrid else ""
        print(f"{name}: equal; PR5 {before:.3f} ms; standalone {after:.3f} ms; xmltodict {reference:.3f} ms; standalone/PR5 speedup {before/after:.3f}x{hybrid_note}", flush=True)
    common.finish_metadata(data)
    save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before")
    parser.add_argument("--after")
    parser.add_argument("--hybrid", help="Optional exact 8db94cc source snapshot for four-way comparison")
    parser.add_argument("--output", default=str(HERE / "standalone-standard.json"))
    parser.add_argument("--fixtures", default=str(HERE / "fixtures/standalone-standard"))
    parser.add_argument("--timing-processes", type=int, default=3)
    parser.add_argument("--memory-processes", type=int, default=5)
    parser.add_argument("--samples", type=int, default=9)
    parser.add_argument("--batch-seconds", type=float, default=0.1)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--mode", choices=("fixtures", "check", "time", "rss", "tracemalloc"))
    parser.add_argument("--version", choices=common.ALL_VERSIONS, default="xmltodict")
    parser.add_argument("--fixture")
    parser.add_argument("--input-type", choices=("str", "bytes"), default="str")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args)))
    else:
        main(args)
