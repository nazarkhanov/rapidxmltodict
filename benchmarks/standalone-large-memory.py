#!/usr/bin/env python3
"""Bounded 10/50/100 MiB full-parse and non-retaining callback comparisons.

Fixtures and typed output fingerprints reuse upstream-large-memory.py unchanged.
All parsers use xmltodict 1.0.4 as the oracle and run in fresh isolated processes.
File callback mode retains scalar counts/checksums only, never emitted items.
Pass --hybrid to include the 8db94cc pre-refactor baseline as a fourth parser.
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import json
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


common = module("standalone_common", HERE / "standalone-common.py")
original = module("original_large", HERE / "upstream-large-memory.py")
MIB = common.MIB
METRICS = ("elapsed_ns", "baseline_current_rss_bytes", "baseline_peak_rss_bytes", "peak_rss_bytes",
           "incremental_peak_rss_bytes", "retained_output_current_rss_bytes", "retained_current_increase_bytes")


def worker(args):
    resource.setrlimit(resource.RLIMIT_AS, (args.limit_mib * MIB, args.limit_mib * MIB))
    affinity = common.pin_cpu()
    parser = common.load_parser(args.version)
    xml = Path(args.fixture).read_bytes().decode("utf-8") if args.parse_mode == "full_str" else Path(args.fixture).open("rb")
    gc.enable()
    gc.collect()
    baseline_current, baseline_peak = original.current_rss(), original.peak_rss()
    callback_count, id_sum, id_square_sum = 0, 0, 0
    first_id = last_id = None

    def consume(path, item):
        nonlocal callback_count, id_sum, id_square_sum, first_id, last_id
        identifier = int(item["@id"])
        if first_id is None:
            first_id = identifier
        last_id = identifier
        callback_count += 1
        id_sum += identifier
        id_square_sum += identifier * identifier
        return True

    start = time.perf_counter_ns()
    if args.parse_mode == "stream_file":
        output = parser.parse(xml, item_depth=2, item_callback=consume)
    else:
        output = parser.parse(xml)
    elapsed = time.perf_counter_ns() - start
    # Memory is sampled before fingerprinting, with the full result kept alive.
    peak, retained = original.peak_rss(), original.current_rss()
    result = {
        "elapsed_ns": elapsed, "baseline_current_rss_bytes": baseline_current,
        "baseline_peak_rss_bytes": baseline_peak, "peak_rss_bytes": peak,
        "incremental_peak_rss_bytes": max(0, peak - baseline_peak),
        "retained_output_current_rss_bytes": retained,
        "retained_current_increase_bytes": retained - baseline_current,
        "parser_module": parser.__file__, "xmltodict_version": common.verify_oracle(),
        "cpu_affinity": affinity, "gc_enabled": gc.isenabled(),
    }
    if args.parse_mode == "stream_file":
        result["callback_summary"] = {"count": callback_count, "id_sum": id_sum,
                                      "id_square_sum": id_square_sum,
                                      "first_id": first_id, "last_id": last_id,
                                      "parse_returned_none": output is None,
                                      "retained_items": 0}
    else:
        result["output_fingerprint"] = original.fingerprint(output)
    if args.parse_mode != "full_str":
        xml.close()
    return result


def main(args):
    versions = common.comparison_versions(args)
    output = Path(args.output).resolve()
    fixtures = Path(args.fixtures).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fixtures.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "metadata": common.metadata(args), "workloads": {}, "run_order": []}
    data["metadata"].update({
        "script_sha256": common.sha(__file__),
        "original_harness_sha256": common.sha(HERE / "upstream-large-memory.py"),
        "initial_available_memory_bytes": original.available_memory(),
        "method": {"repetitions": args.repetitions, "fresh_process_per_sample": True,
                   "one_parse_per_process": True, "gc_enabled": True,
                   "output_destruction_timed": False, "memory_sample_before_fingerprint": True,
                   "max_address_space_mib": args.limit_mib,
                   "full_str": "Input loaded before timing; dictionary retained at memory sample.",
                   "full_file": "Binary file opened before timing; reading and complete dictionary construction timed; dictionary retained.",
                   "stream_file": "Binary file opened before timing; item_depth=2 callback retains count, first/last identifier and integer checksums only; no items retained.",
                   "fingerprint": "Complete typed SHA-256 traversal for full output, sorted dictionary keys and preserved lists. Streaming validates all callback counts and identifier sums, not a complete item fingerprint.",
                   "resource_guard": "RLIMIT_AS hard limit; skip estimated peak above 40% of MemAvailable or 80% of address-space cap. No retries after allocation failure.",
                   "ordering": "Rotate the recorded comparison_versions order across repetitions; four-way runs also offset by workload so no parser is systematically excluded from the first position."}})
    specs = [original.create_fixture(fixtures, shape, size) for size in args.sizes for shape in ("records", "large_text")]

    def save():
        output.write_text(json.dumps(data, indent=2) + "\n")

    for spec in specs:
        modes = ("full_str", "full_file", "stream_file") if spec["shape"] == "records" else ("full_str",)
        for mode in modes:
            workload_index = len(data["workloads"])
            name = f'{spec["shape"]}_{spec["size_mib"]}mib_{mode}'
            entry = {**spec, "input_type": "str" if mode == "full_str" else "binary_file",
                     "parse_mode": mode, "samples": {v: [] for v in versions}, "skipped": {}}
            data["workloads"][name] = entry
            for repetition in range(args.repetitions):
                offset = workload_index if len(versions) == 4 else 0
                rotation = (offset + repetition) % len(versions)
                order = versions[rotation:] + versions[:rotation]
                for version in order:
                    available = original.available_memory()
                    estimate = 128 * MIB if mode == "stream_file" else spec["bytes"] * (24 if spec["shape"] == "records" else 8) + 64 * MIB
                    prior = [w for w in data["workloads"].values() if w["shape"] == spec["shape"] and
                             w["parse_mode"] == mode and w["size_mib"] < spec["size_mib"] and w["samples"][version]]
                    if prior and mode != "stream_file":
                        previous = max(prior, key=lambda w: w["size_mib"])
                        ratio = max(s["peak_rss_bytes"] for s in previous["samples"][version]) / previous["bytes"]
                        estimate = spec["bytes"] * ratio * 1.25 + 64 * MIB
                    if estimate > min(available * 0.4, args.limit_mib * MIB * 0.8):
                        entry["skipped"][version] = {"reason": "Conservative memory budget exceeded",
                                                     "estimated_peak_bytes": estimate, "available_memory_bytes": available}
                        save()
                        continue
                    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--version", version,
                               "--fixture", spec["path"], "--parse-mode", mode, "--limit-mib", str(args.limit_mib)]
                    run = subprocess.run(command, env=common.child_env(version, args.before, args.after, args.hybrid), text=True,
                                         capture_output=True, close_fds=False, timeout=600)
                    data["run_order"].append({"workload": name, "repetition": repetition, "version": version,
                                              "available_memory_bytes": available})
                    if run.returncode:
                        entry["skipped"][version] = {"reason": "Worker failed; no automatic retry", "returncode": run.returncode,
                                                     "stderr": run.stderr[-4000:]}
                        save()
                        raise SystemExit(f"{name}/{version}: worker failed; results saved")
                    sample = json.loads(run.stdout)
                    assert sample["xmltodict_version"] == common.ORACLE_VERSION
                    entry["samples"][version].append(sample)
                    save()
                    print(f'{name} {version} #{repetition+1}: {sample["elapsed_ns"]/1e9:.3f}s; peak {sample["peak_rss_bytes"]/MIB:.1f} MiB; retained {sample["retained_output_current_rss_bytes"]/MIB:.1f} MiB', flush=True)
            if mode == "stream_file":
                n = spec["records"]
                expected = {"count": n, "id_sum": n * (n - 1) // 2,
                            "id_square_sum": n * (n - 1) * (2 * n - 1) // 6,
                            "first_id": 0, "last_id": n - 1, "parse_returned_none": True, "retained_items": 0}
                entry["expected_callback_summary"] = expected
                entry["all_available_callback_summaries_equal"] = all(
                    sample["callback_summary"] == expected for samples in entry["samples"].values() for sample in samples)
                assert entry["all_available_callback_summaries_equal"], f"Callback mismatch: {name}"
            else:
                matching = [w for w in data["workloads"].values() if w["shape"] == spec["shape"] and
                            w["size_mib"] == spec["size_mib"] and w["parse_mode"] != "stream_file"]
                fingerprints = {s["output_fingerprint"]["sha256"] for w in matching for samples in w["samples"].values() for s in samples}
                entry["all_available_output_fingerprints_equal"] = len(fingerprints) == 1
                assert len(fingerprints) <= 1, f"Output mismatch: {name}"
            entry["medians"] = {v: {key: statistics.median(s[key] for s in samples) for key in METRICS}
                                for v, samples in entry["samples"].items() if samples}
            save()
    common.finish_metadata(data)
    data["metadata"]["all_requested_samples_completed"] = all(
        len(samples) == args.repetitions for w in data["workloads"].values() for samples in w["samples"].values())
    save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before")
    parser.add_argument("--after")
    parser.add_argument("--hybrid", help="Optional exact 8db94cc source snapshot for four-way comparison")
    parser.add_argument("--output", default=str(HERE / "standalone-large-memory.json"))
    parser.add_argument("--fixtures", default=str(HERE / "fixtures/standalone-large"))
    parser.add_argument("--sizes", nargs="+", type=int, default=[10, 50, 100])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--limit-mib", type=int, default=3072)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--version", choices=common.ALL_VERSIONS)
    parser.add_argument("--fixture")
    parser.add_argument("--parse-mode", choices=("full_str", "full_file", "stream_file"))
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args)))
    else:
        main(args)
