#!/usr/bin/env python3
"""Default public API benchmark, with correctness checks and native-aware RSS.

Run from the repository root after building the extension; see README.md here.
Only benchmark files are generated. Stdlib-only harness; xmltodict is required.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import resource
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PRIMARY = ("rapidxmltodict", "xmltodict")
JSON_ROUNDTRIP = "rapidxmltojson+json.loads"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def implementation_hashes():
    paths = [REPO / "src/rapidxmltodict/__init__.py", REPO / "src/native.cpp"]
    paths.extend(sorted((REPO / "src/rapidxmltodict").glob("_native*.so")))
    return {str(p.relative_to(REPO)): sha256(p) for p in paths if p.exists()}


def pin_cpu():
    if hasattr(os, "sched_setaffinity"):
        affinity = os.sched_getaffinity(0)
        os.sched_setaffinity(0, {min(affinity)})
        return sorted(os.sched_getaffinity(0))
    return None


def version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def load_parser(name):
    if name == JSON_ROUNDTRIP:
        native = importlib.import_module("rapidxmltojson").parse
        return lambda xml: json.loads(native(xml))
    return importlib.import_module(name).parse


def load_input(path, input_type):
    raw = Path(path).read_bytes()
    return raw if input_type == "bytes" else raw.decode("utf-8")


def rss_bytes():
    # getrusage uses KiB on Linux and bytes on macOS. Do not report traced Python
    # allocations as total/native memory. The baseline is a high-water mark too.
    scale = 1 if sys.platform == "darwin" else 1024
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale)


def linux_current_rss_bytes():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def diagnose_difference(a, b, path="$", budget=40):
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return f"{path}: different keys {list(a)[:8]!r} / {list(b)[:8]!r}"
        for key in a:
            if a[key] != b[key]:
                return diagnose_difference(a[key], b[key], f"{path}.{key}", budget - 1) if budget else path
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: different list lengths {len(a)} / {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return diagnose_difference(x, y, f"{path}[{i}]", budget - 1) if budget else path
    return f"{path}: unequal values {str(a)[:100]!r} / {str(b)[:100]!r}"


def worker(args):
    pin_cpu()
    if args.mode == "fixtures":
        return create_fixtures()
    xml = load_input(args.fixture, args.input_type)
    if args.mode == "check":
        reference = load_parser("xmltodict")(xml)
        result = {"rapidxmltodict": {"equal_to_xmltodict": False}}
        actual = load_parser("rapidxmltodict")(xml)
        equal = actual == reference
        result["rapidxmltodict"] = {"equal_to_xmltodict": equal}
        if not equal:
            result["rapidxmltodict"]["difference"] = diagnose_difference(reference, actual)
        del actual
        # The historical JSON parser accepts str, and its non-equivalent
        # semantics are never included in a like-for-like performance claim.
        if args.input_type == "bytes":
            result[JSON_ROUNDTRIP] = {"equal_to_xmltodict": False, "omitted": "str-only comparator; bytes workload"}
        else:
            try:
                actual = load_parser(JSON_ROUNDTRIP)(xml)
                equal = actual == reference
                result[JSON_ROUNDTRIP] = {"equal_to_xmltodict": equal}
                if not equal:
                    result[JSON_ROUNDTRIP]["difference"] = diagnose_difference(reference, actual)
            except Exception as exc:
                result[JSON_ROUNDTRIP] = {"equal_to_xmltodict": False, "omitted": f"{type(exc).__name__}: {exc}"}
        return result

    parse = load_parser(args.library)
    gc.enable()
    gc.collect()
    if args.mode == "time":
        # Output destruction is included. Warmups and fixture loading are not.
        for _ in range(3):
            parse(xml)
        start = time.perf_counter_ns()
        for _ in range(3):
            parse(xml)
        estimate = (time.perf_counter_ns() - start) / 3
        loops = max(1, min(100000, round(args.batch_seconds * 1e9 / max(estimate, 1))))
        samples = []
        for _ in range(args.samples):
            start = time.perf_counter_ns()
            for _ in range(loops):
                parse(xml)
            samples.append((time.perf_counter_ns() - start) / loops)
        return {"loops_per_batch": loops, "batch_ns_per_call": samples,
                "median_ns_per_call": statistics.median(samples), "gc_enabled": gc.isenabled()}
    if args.mode == "rss":
        baseline_current = linux_current_rss_bytes()
        baseline_peak = rss_bytes()
        output = parse(xml)  # Keep output alive while measuring the peak.
        peak = rss_bytes()
        current = linux_current_rss_bytes()
        return {"baseline_current_rss_bytes": baseline_current,
                "baseline_peak_rss_bytes": baseline_peak, "peak_rss_bytes": peak,
                "incremental_peak_rss_bytes": max(0, peak - baseline_peak),
                "retained_output_current_rss_bytes": current,
                "result_type": type(output).__name__}
    if args.mode == "tracemalloc":
        import tracemalloc
        tracemalloc.start()
        output = parse(xml)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {"python_traced_retained_bytes": current, "python_traced_peak_bytes": peak,
                "result_type": type(output).__name__, "excludes_untraced_native_allocations": True}
    raise ValueError(args.mode)


def create_fixtures():
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    workloads = []
    # No random or network input: decimal identifiers, repeated sibling arrays,
    # nested records, attribute-bearing text, and escaped strings.
    def records(count):
        items = []
        for i in range(count):
            items.append(f'<item id="{i:06d}" active="{"true" if i % 3 else "false"}">'
                         f'<name>Widget-{i % 97:02d} &amp; spare</name>'
                         f'<price currency="USD">{10 + i % 80}.{i % 100:02d}</price>'
                         '<details><tag>alpha</tag><tag>beta</tag>'
                         f'<stock>{i % 250}</stock></details></item>')
        return '<catalog region="us">' + ''.join(items) + '</catalog>'
    specifications = [
        ("small", records(6), "str", "6 realistic catalog records"),
        ("medium", records(600), "str", "600 realistic catalog records"),
        ("large", records(6000), "str", "6000 realistic catalog records"),
        ("unicode_mixed", '<root>' + ''.join(
            f'<entry id="{i}" label="café 東京"><name>  Zoë 🙂 &amp; 李  </name>'
            '<p>before <b>bold</b> between <![CDATA[x < y]]> after</p>'
            '<empty/><space> \t\n </space><value>0012</value></entry>'
            for i in range(500)) + '</root>', "str", "500 Unicode and mixed-content records; empty/whitespace nodes"),
        ("deep", '<n>' * 128 + 'leaf' + '</n>' * 128, "str", "128 nested elements; native supported depth"),
        ("deep_fallback", '<n>' * 300 + 'leaf' + '</n>' * 300, "str", "300 nested elements; documented xmltodict fallback"),
        ("medium_bytes", records(600), "bytes", "Same medium records supplied as UTF-8 bytes"),
    ]
    for name, xml, input_type, description in specifications:
        path = folder / f"{name}.xml"
        raw = xml.encode("utf-8")
        path.write_bytes(raw)
        workloads.append({"name": name, "path": str(path), "input_type": input_type,
                          "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                          "description": description})
    return workloads


def run_child(args, mode, workload, library="xmltodict"):
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--mode", mode,
               "--library", library, "--fixture", workload["path"], "--input-type", workload["input_type"],
               "--samples", str(args.samples), "--batch-seconds", str(args.batch_seconds)]
    # On supported Python/Linux this allows posix_spawn rather than inheriting
    # a large parent heap before exec. Each measurement still has its own baseline.
    child = subprocess.run(command, text=True, capture_output=True, check=True, close_fds=False)
    return json.loads(child.stdout)


def aggregate(runs, key):
    return statistics.median(run[key] for run in runs)


def environment_metadata(args):
    try:
        cpu = next(line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                   if line.startswith("model name"))
    except (OSError, StopIteration):
        cpu = platform.processor()
    try:
        compiler = subprocess.check_output(["g++", "--version"], text=True).splitlines()[0]
    except (OSError, subprocess.CalledProcessError):
        compiler = None
    return {"timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
            "cpu": cpu, "cpu_affinity": pin_cpu(), "compiler": compiler,
            "packages": {name: version(name) for name in ("rapidxmltodict", "xmltodict", "rapidxmltojson")},
            "rapidxmltodict_distribution_version": version("rapidxmltodict"),
            "implementation_hashes_start": implementation_hashes(),
            "benchmark_sha256": sha256(__file__), "argv": sys.argv,
            "method": {"default_public_api": True, "validation_and_preprocessing_included": True,
                       "timing_processes": args.timing_processes, "batches_per_process": args.samples,
                       "target_batch_seconds": args.batch_seconds, "warmup_calls": 3, "calibration_calls": 3,
                       "memory_processes": args.memory_processes, "gc_enabled": True,
                       "fixture_loading_timed": False, "output_destruction_timed": True,
                       "memory": "Fresh subprocess per measurement, one parse, retained output; ru_maxrss normalized to bytes; post-import/input-load baseline peak and Linux current RSS reported.",
                       "tracemalloc": "Separate fresh subprocess, supplemental Python-visible allocation measure, excludes untraced native memory.",
                       "ordering_seed": 20261009}}


def write_summary(data, path):
    rows = []
    baseline_rows = []
    optional_rows = []
    for name, result in data["workloads"].items():
        if "summary" not in result:
            continue
        s = result["summary"]
        a, b = s["rapidxmltodict"], s["xmltodict"]
        rows.append(f'| {name} | {result["bytes"]:,} | {a["median_ms"]:.3f} | {b["median_ms"]:.3f} | '
                    f'{b["median_ms"] / a["median_ms"]:.2f}× | {a["median_peak_rss_mib"]:.2f} / {b["median_peak_rss_mib"]:.2f} | '
                    f'{a["median_incremental_peak_mib"]:.2f} / {b["median_incremental_peak_mib"]:.2f} |')
        baseline_rows.append(f'| {name} | {a["median_baseline_peak_mib"]:.2f} | {b["median_baseline_peak_mib"]:.2f} |')
        if JSON_ROUNDTRIP in s:
            j = s[JSON_ROUNDTRIP]
            optional_rows.append(f'| {name} | {j["median_ms"]:.3f} | {j["median_peak_rss_mib"]:.2f} |')
    path.write_text("# Measured results\n\n"
                    f'Generated {data["metadata"]["timestamp_utc"]}; Python {platform.python_version()}; '
                    f'xmltodict {data["metadata"]["packages"]["xmltodict"]}.\n\n'
                    "All primary comparisons below passed equality against xmltodict.parse defaults before timing. "
                    "Times include the complete public parse call, validation, preprocessing, and output destruction. "
                    "RSS is a whole-process peak, including native heaps and retained output. "
                    "The paired RSS columns show rapidxmltodict / xmltodict.\n\n"
                    "| Workload | Input bytes | rapidxmltodict ms | xmltodict ms | Speedup | Peak RSS MiB | Incremental peak MiB |\n"
                    "|---|---:|---:|---:|---:|---:|---:|\n" + '\n'.join(rows) +
                    "\n\nIncremental peak is peak minus the post-import/input-load baseline high-water mark, "
                    "not precise per-call allocation or retained memory. Small changes can round to zero. "
                    "Native DOM construction can increase peak RSS despite fewer Python allocations. "
                    "The JSON file includes baseline RSS, individual measurements, hashes, and supplemental tracemalloc values. "
                    "These are synthetic single-machine results, not universal performance guarantees.\n\n"
                    "## Baseline whole-process peak RSS\n\n"
                    "Before the measured parse, after importing the parser and loading the input:\n\n"
                    "| Workload | rapidxmltodict baseline MiB | xmltodict baseline MiB |\n"
                    "|---|---:|---:|\n" + '\n'.join(baseline_rows) +
                    "\n\n## Optional JSON round trip\n\n"
                    "Only output-equivalent fixtures are measured below. This calls "
                    "`json.loads(rapidxmltojson.parse(xml))`; it does not establish general semantic compatibility. "
                    "Unicode/mixed input is excluded for different whitespace semantics; bytes input is omitted.\n\n"
                    "| Workload | JSON round-trip ms | Peak RSS MiB |\n|---|---:|---:|\n" +
                    '\n'.join(optional_rows) + '\n')


def main(args):
    pin_cpu()
    # Generate input in a separate process so the orchestrator does not retain
    # large temporary strings that inflate an inherited subprocess high-water mark.
    generated = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--mode", "fixtures"],
                               text=True, capture_output=True, check=True, close_fds=False)
    workloads = json.loads(generated.stdout)
    if args.only:
        selected = set(args.only.split(','))
        workloads = [x for x in workloads if x["name"] in selected]
        unknown = selected - {x["name"] for x in workloads}
        if unknown:
            raise SystemExit(f"Unknown workload(s): {sorted(unknown)}")
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = {"metadata": environment_metadata(args), "workloads": {}}
    randomizer = random.Random(20261009)
    for workload in workloads:
        name = workload["name"]
        result = {k: v for k, v in workload.items() if k not in ("path", "name")}
        data["workloads"][name] = result
        result["equality"] = run_child(args, "check", workload)
        if not result["equality"]["rapidxmltodict"]["equal_to_xmltodict"]:
            destination.write_text(json.dumps(data, indent=2) + '\n')
            raise SystemExit(f"Cannot benchmark non-equivalent output for {name}: {result['equality']}")
        libs = list(PRIMARY)
        if result["equality"][JSON_ROUNDTRIP]["equal_to_xmltodict"]:
            libs.append(JSON_ROUNDTRIP)
        result["timing"] = {lib: [] for lib in libs}
        result["rss"] = {lib: [] for lib in libs}
        result["tracemalloc"] = {}
        for repetition in range(args.timing_processes):
            order = libs.copy()
            randomizer.shuffle(order)
            for lib in order:
                result["timing"][lib].append(run_child(args, "time", workload, lib))
        for repetition in range(args.memory_processes):
            order = libs.copy()
            randomizer.shuffle(order)
            for lib in order:
                result["rss"][lib].append(run_child(args, "rss", workload, lib))
        for lib in libs:
            result["tracemalloc"][lib] = run_child(args, "tracemalloc", workload, lib)
        result["summary"] = {}
        for lib in libs:
            samples = [sample for run in result["timing"][lib] for sample in run["batch_ns_per_call"]]
            result["summary"][lib] = {
                "median_ms": statistics.median(samples) / 1e6,
                "min_ms": min(samples) / 1e6, "max_ms": max(samples) / 1e6,
                "median_peak_rss_mib": aggregate(result["rss"][lib], "peak_rss_bytes") / 2**20,
                "median_baseline_peak_mib": aggregate(result["rss"][lib], "baseline_peak_rss_bytes") / 2**20,
                "median_incremental_peak_mib": aggregate(result["rss"][lib], "incremental_peak_rss_bytes") / 2**20,
            }
        result["speedup_vs_xmltodict"] = result["summary"]["xmltodict"]["median_ms"] / result["summary"]["rapidxmltodict"]["median_ms"]
        result["implementation_hashes_after_workload"] = implementation_hashes()
        destination.write_text(json.dumps(data, indent=2) + '\n')
        print(f'{name}: equal; {result["speedup_vs_xmltodict"]:.2f}x speedup; '
              f'peak RSS {result["summary"]["rapidxmltodict"]["median_peak_rss_mib"]:.2f} / '
              f'{result["summary"]["xmltodict"]["median_peak_rss_mib"]:.2f} MiB', flush=True)
    data["metadata"]["implementation_hashes_end"] = implementation_hashes()
    data["metadata"]["implementation_unchanged_during_run"] = (
        data["metadata"]["implementation_hashes_start"] == data["metadata"]["implementation_hashes_end"] and
        all(x["implementation_hashes_after_workload"] == data["metadata"]["implementation_hashes_start"]
            for x in data["workloads"].values()))
    destination.write_text(json.dumps(data, indent=2) + '\n')
    write_summary(data, destination.with_suffix('.md'))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(HERE / "results.json"))
    parser.add_argument("--only", help="Comma-separated workload names")
    parser.add_argument("--timing-processes", type=int, default=3)
    parser.add_argument("--memory-processes", type=int, default=5)
    parser.add_argument("--samples", type=int, default=9)
    parser.add_argument("--batch-seconds", type=float, default=0.1)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("fixtures", "check", "time", "rss", "tracemalloc"), help=argparse.SUPPRESS)
    parser.add_argument("--library", help=argparse.SUPPRESS)
    parser.add_argument("--fixture", help=argparse.SUPPRESS)
    parser.add_argument("--input-type", choices=("str", "bytes"), default="str", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.worker:
        print(json.dumps(worker(arguments)))
    else:
        main(arguments)
