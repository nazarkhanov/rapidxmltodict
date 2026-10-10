#!/usr/bin/env python3
"""Untimed verification that the final public API selects the measured backend.

Wrap only the two native entry points in an isolated verification process. The
real implementations still parse every byte; complete results/callbacks are
checked against the four-way run. No instrumented timing is benchmarked.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("architecture_benchmark", HERE / "architecture-benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def worker(args):
    native = importlib.import_module("rapidxmltodict._native")
    calls = {"iterative_dom": 0, "native_events": 0}

    def observe(kind, operation):
        def call(*positional, **keywords):
            calls[kind] += 1
            return operation(*positional, **keywords)
        return call

    native.convert = observe("iterative_dom", native.convert)
    native.NativeMappingParser = observe("native_events", native.NativeMappingParser)
    retained = []
    if args.generator or args.retain_callbacks:
        package = importlib.import_module("rapidxmltodict")
        original_parse = package.parse
        def parse_observed(value, **kwargs):
            if args.retain_callbacks:
                original_callback = kwargs["item_callback"]
                def keep_item(path, item):
                    retained.append(item)
                    return original_callback(path, item)
                kwargs["item_callback"] = keep_item
            if args.generator:
                source_value = value
                value = (source_value[offset:offset + 2048] for offset in range(0, len(source_value), 2048))
            return original_parse(value, **kwargs)
        package.parse = parse_observed
    measured_args = argparse.Namespace(
        limit_mib=args.limit_mib, cpu=args.cpu, entrypoint="rapidxmltodict:parse", options=args.options,
        fixture=args.fixture, parse_mode=args.parse_mode, retain_callbacks=args.retain_callbacks,
        check_only=True, standard_timing=False, variant="native_events",
    )
    result = benchmark.worker(measured_args)
    # These checks are instrumented and deliberately omit time/RSS fields.
    keys = ("entrypoint", "parser_module_sha256", "loaded_extension_sha256",
            "output_fingerprint", "callback_content_sha256", "callback_summary")
    output = {**{key: result[key] for key in keys if key in result}, "native_entrypoint_calls": calls}
    if args.retain_callbacks:
        # Observe object contents after the complete parse, not only at the
        # instant each callback fires. Reusing/mutating earlier emitted objects
        # would pass an emission-only checksum but fail this independent check.
        import xmltodict
        reference_items = []
        def keep_reference(path, item):
            reference_items.append(item)
            return True
        with Path(args.fixture).open("rb") as stream:
            xmltodict.parse(stream, item_depth=2, item_callback=keep_reference)
        output["retained_items_fingerprint"] = benchmark.fingerprint(retained)
        output["oracle_retained_items_fingerprint"] = benchmark.fingerprint(reference_items)
        output["retained_objects_match_oracle"] = output["retained_items_fingerprint"] == output["oracle_retained_items_fingerprint"]
    return output


def main(args):
    root = Path(args.candidate).resolve()
    raw = [json.loads(Path(path).read_text()) for path in args.results]
    expected_hashes = raw[0]["metadata"]["source_and_binary_hashes_start"]["native_events"]
    hashes_start = benchmark.source_hashes(root)
    if hashes_start != expected_hashes:
        raise SystemExit("Candidate hashes differ from the benchmark snapshot")
    for data in raw:
        if data["metadata"]["source_and_binary_hashes_start"]["native_events"] != expected_hashes:
            raise SystemExit("Benchmark files use different native-event snapshots")
    fixtures_command = [sys.executable, str(HERE / "architecture-benchmark.py"), "--generate", "--suite", "all",
                        "--sizes", "10", "100", "--fixtures", args.fixtures]
    fixtures = {item["name"]: item for item in json.loads(subprocess.check_output(fixtures_command, text=True))}
    cases = {
        "small": ("small", "iterative_dom", {}, False),
        "medium_bytes": ("medium_bytes", "iterative_dom", {}, False),
        "medium_explicit_default_option": ("medium", "native_events", {"force_list": False}, False),
        "medium_bytes_generator": ("medium_bytes", "native_events", {}, True),
        "deep_10000": ("deep_10000", "iterative_dom", {}, False),
        "late_deep_60000_siblings": ("late_deep_60000_siblings", "iterative_dom", {}, False),
        "records_10mib_direct_str": ("records_10mib_direct_str", "iterative_dom", {}, False),
        "records_10mib_direct_file": ("records_10mib_direct_file", "native_events", {}, False),
        "records_10mib_callback_file_discard": ("records_10mib_callback_file_discard", "native_events", {}, False),
        "records_10mib_callback_file_retain": ("records_10mib_callback_file_retain", "native_events", {}, False),
        "records_100mib_callback_file_retain": ("records_100mib_callback_file_retain", "native_events", {}, False),
        "large_text_10mib_direct_str": ("large_text_10mib_direct_str", "iterative_dom", {}, False),
        "large_text_10mib_direct_file": ("large_text_10mib_direct_file", "native_events", {}, False),
    }
    workloads = {name: value for data in raw for name, value in data["workloads"].items()}
    result = {
        "schema_version": 1,
        "verification_script_sha256": benchmark.sha(__file__),
        "method": "Untimed isolated public-API calls, actual native entry points observed, complete output/callback fingerprints compared with the measured architectures.",
        "source_and_binary_hashes_start": hashes_start,
        "public_dispatch": "Default str/bytes -> iterative DOM; files/generators/options -> direct native events.",
        "checks": {},
    }
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONHASHSEED"] = "0"
    output = Path(args.output)
    for name, (source_name, route, options, generator) in cases.items():
        if source_name not in workloads:
            continue
        fixture = fixtures[source_name]
        if fixture["sha256"] != workloads[source_name]["sha256"]:
            raise SystemExit(f"Fixture differs from the measured input: {name}")
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--fixture", fixture["path"],
                   "--parse-mode", fixture["parse_mode"], "--limit-mib", str(args.limit_mib),
                   "--options", json.dumps(options)]
        if generator:
            command.append("--generator")
        if args.cpu is not None:
            command += ["--cpu", str(args.cpu)]
        if fixture["retain_callbacks"]:
            command.append("--retain-callbacks")
        child = subprocess.run(command, env=env, text=True, capture_output=True, timeout=900)
        if child.returncode:
            raise SystemExit(benchmark.sanitize_error(child.stderr, {"candidate": root}, args.fixtures))
        check = json.loads(child.stdout)
        check["expected_route"] = route
        check["source_workload"] = source_name
        check["parse_options"] = options
        check["generator_input"] = generator
        check["correct_route"] = check["native_entrypoint_calls"] == {
            "iterative_dom": int(route == "iterative_dom"), "native_events": int(route == "native_events")}
        measured = workloads[source_name]
        if fixture["parse_mode"].startswith("callback"):
            check["content_matches_selected_architecture"] = (
                check["callback_content_sha256"] == measured["callback_integrity"]["native_events"]["callback_content_sha256"]
                and check["callback_summary"] == measured["expected_callback_summary"])
        else:
            check["content_matches_selected_architecture"] = (
                check["output_fingerprint"] == measured["samples"][route][0]["output_fingerprint"])
        result["checks"][name] = check
        output.write_text(json.dumps(result, indent=2) + "\n")
        if (not check["correct_route"] or not check["content_matches_selected_architecture"]
                or not check.get("retained_objects_match_oracle", True)):
            raise SystemExit(f"Public route/content mismatch: {name}")
    result["source_and_binary_hashes_end"] = benchmark.source_hashes(root)
    result["source_and_binary_hashes_unchanged"] = hashes_start == result["source_and_binary_hashes_end"]
    result["all_checks_passed"] = bool(result["checks"]) and result["source_and_binary_hashes_unchanged"]
    output.write_text(json.dumps(result, indent=2) + "\n")
    if not result["all_checks_passed"]:
        raise SystemExit("Public route verification incomplete or sources changed")
    print(f"Verified {len(result['checks'])} public routes and complete content fingerprints")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate")
    parser.add_argument("--results", nargs="+")
    parser.add_argument("--output", default=str(HERE / "architecture-public-routing.json"))
    parser.add_argument("--fixtures", default=str(Path(tempfile.gettempdir()) / "rapidxml-architecture-fixtures"))
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--fixture")
    parser.add_argument("--parse-mode")
    parser.add_argument("--retain-callbacks", action="store_true")
    parser.add_argument("--generator", action="store_true")
    parser.add_argument("--options", default="{}")
    parser.add_argument("--cpu", type=int)
    parser.add_argument("--limit-mib", type=int, default=3072)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args)))
    else:
        main(args)
