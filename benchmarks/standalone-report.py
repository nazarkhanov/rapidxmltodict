#!/usr/bin/env python3
"""Render completed three- or four-way benchmark JSON without remeasuring."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MIB = 1024 ** 2


def render(standard, large, standard_name, large_name, candidate_label):
    versions = tuple(standard["metadata"].get("comparison_versions", ("pr5", "standalone", "xmltodict")))
    labels = {"pr5": "PR #5", "hybrid": "Hybrid 8db94cc", "standalone": candidate_label,
              "xmltodict": "xmltodict 1.0.4"}
    metadata = standard["metadata"]
    commit = metadata.get("candidate_commit", "See recorded source hashes")
    for data in (standard, large):
        assert data["metadata"]["source_and_binary_hashes_unchanged"], "Source changed during a run"
    assert large["metadata"]["all_requested_samples_completed"], "Large measurements are incomplete"
    assert len(standard["workloads"]) == 7, "The standard suite is incomplete"
    repetitions = large["metadata"]["method"]["repetitions"]
    sample_count = 0
    for workload in large["workloads"].values():
        assert not workload["skipped"], "A large comparison was skipped"
        assert set(workload["samples"]) == set(versions)
        for runs in workload["samples"].values():
            assert len(runs) == repetitions
            sample_count += len(runs)
        equality = ("all_available_callback_summaries_equal" if workload["parse_mode"] == "stream_file"
                    else "all_available_output_fingerprints_equal")
        assert workload[equality], "Large output/callback checks failed"
    for workload in standard["workloads"].values():
        assert all(workload["equality"][v]["equal_to_xmltodict"] for v in versions)

    lines = [f"# {candidate_label} RapidXML benchmark", "",
             f"Measured candidate: `{commit}`. Baseline PR #5: `{metadata['baseline_commit']}`."]
    if "hybrid" in versions:
        lines.append(f"Hybrid pre-refactor baseline: `{metadata['hybrid_baseline_commit']}`.")
    if metadata.get("source_line_ending_differences"):
        affected = ", ".join(f"`{item['path']}`" for item in metadata["source_line_ending_differences"])
        lines += ["", f"Source-attribution note: {affected} used CRLF in the frozen measured snapshot and LF in the "
                  "published commit. Their contents match after line-ending normalization; all other measured source files "
                  "match byte-for-byte. Both exact header hashes and the measured binary hashes are retained in the raw data. "
                  "The measured snapshot was not changed during the run."]
    lines += ["", "## Findings", ""]
    for baseline in (v for v in ("pr5", "hybrid") if v in versions):
        ratios = [w["summary"][baseline]["median_ms"] / w["summary"]["standalone"]["median_ms"]
                  for w in standard["workloads"].values()]
        lines.append(f"- Candidate medians were faster in {sum(r > 1 for r in ratios)} of seven standard workloads "
                     f"versus {labels[baseline]}; the full observed speedup range was {min(ratios):.2f}–{max(ratios):.2f}×.")
    records = large["workloads"].get("records_100mib_full_str")
    if records:
        candidate = records["medians"]["standalone"]
        comparisons = "; ".join(f'{labels[v]} {records["medians"][v]["elapsed_ns"]/1e9:.3f} s' for v in versions)
        lines.append(f"- 100 MiB record-shaped full-string parsing: {comparisons}. Candidate total peak was "
                     f"{candidate['peak_rss_bytes']/MIB:.2f} MiB; incremental peak above its pre-parse high-water "
                     f"mark was {candidate['incremental_peak_rss_bytes']/MIB:.2f} MiB.")
        if "hybrid" in versions:
            hybrid = records["medians"]["hybrid"]
            change = (candidate["elapsed_ns"] / hybrid["elapsed_ns"] - 1) * 100
            lines.append(f"- On that record input, candidate time changed by {change:+.1f}% versus the hybrid baseline. "
                         f"Hybrid total/incremental peak was {hybrid['peak_rss_bytes']/MIB:.2f} / "
                         f"{hybrid['incremental_peak_rss_bytes']/MIB:.2f} MiB; the full DOM memory cost remains visible.")
    text_case = large["workloads"].get("large_text_100mib_full_str")
    if text_case and "hybrid" in versions:
        a, h = (text_case["medians"][v]["elapsed_ns"] for v in ("standalone", "hybrid"))
        lines.append(f"- Shape matters: 100 MiB single-text-node parsing was {a/1e9:.3f} s versus hybrid {h/1e9:.3f} s "
                     f"({h/a:.2f}× speedup). The separate tables retain all parser and size comparisons.")
    if "hybrid" in versions and "deep_fallback" in standard["workloads"]:
        deep = standard["workloads"]["deep_fallback"]["summary"]
        a, h = (deep[v]["median_ms"] for v in ("standalone", "hybrid"))
        lines.append(f"- Depth 300 measured {a:.3f} ms versus hybrid {h:.3f} ms ({(a/h-1)*100:+.1f}% time). "
                     "The restart/reparsed-prefix limitation is explained below; this run does not isolate its cost.")
    streams = [w for w in large["workloads"].values() if w["parse_mode"] == "stream_file"]
    stream_peaks = " / ".join(f'{w["medians"]["standalone"]["peak_rss_bytes"]/MIB:.2f}' for w in streams)
    stream_sizes = " / ".join(str(w["size_mib"]) for w in streams)
    hybrid_flag = ' --hybrid "$HYBRID"' if "hybrid" in versions else ""
    build_roots = '"$BEFORE" "$HYBRID" "$AFTER"' if "hybrid" in versions else '"$BEFORE" "$AFTER"'
    lines += [f"- Candidate non-retaining callback peaks were {stream_peaks} MiB for {stream_sizes} MiB record inputs. "
              "Callback mode deliberately discards each emitted item and returns `None`, unlike full-result parsing.",
              f"- All seven standard equality checks and all {sample_count} large fresh-process samples passed. "
              "Full-result fingerprints and exact callback counts/checksums agree; no large sample was skipped or retried.",
              "- These are observed medians on synthetic inputs, not statistical-significance or universal speed/memory claims. "
              "Slower shapes remain visible in the complete tables below.", "", "## Environment and complete-call method", "",
              f"- Recorded {metadata['timestamp_utc']}; Python {metadata['python'].split()[0]}; {metadata['platform']}; "
              f"{metadata['cpu']}; CPU affinity {metadata['cpu_affinity']}; {metadata['compiler']}.",
              f"- Oracle: xmltodict {metadata['xmltodict_version']}; reference/baseline backend "
              f"{metadata['reference_expat_provenance'].get('version', metadata['reference_expat_provenance'].get('pyexpat_version'))}. "
              "Its complete feature list is in the raw metadata. Benchmark and compatibility-test environments are distinct.",
              "- One interpreter and environment for all implementations. Native snapshots are selected through isolated "
              "fresh-process `PYTHONPATH` values. Compiler flags, snapshot paths, fixture hashes and all implementation/native "
              "binary hashes are recorded; source and binary hashes stayed unchanged throughout both runs.",
              "- Shared artifacts replace local absolute paths and execution-specific identities with generic relative "
              "snapshot/venv/fixture paths. Numeric measurements and source/binary hashes are preserved.",
              "- Every measurement times the complete public `parse` call, including validation, preprocessing, all internal "
              "passes, conversion and any benchmark callback. One parse per process means one API invocation. These measurements "
              "do not by themselves establish a single-pass implementation.",
              "- Standard suite: three timing processes, nine batches each, three warmups and three calibration calls; five "
              "separate RSS processes. Fixture loading is excluded and output destruction is included in timing. Separate "
              "tracemalloc samples are supplemental and exclude untraced native allocations.",
              f"- Large suite: {repetitions} fresh processes per parser, shape, size and mode. Input files are generated outside "
              "measured workers. One parse is timed; output destruction and output fingerprinting are excluded. Memory is "
              "sampled before fingerprinting while any full result remains alive.",
              "- Full results use complete typed SHA-256 traversals with sorted dictionary keys, preserved list order and every "
              "string value. Streaming checks every callback count, first/last identifier, identifier sum and squared-identifier "
              "sum. Those callback checks are not complete streamed-item fingerprints.",
              f"- Resource guard: {large['metadata']['method']['max_address_space_mib']} MiB per-worker address-space limit; "
              "skip estimated peaks exceeding 40% of available memory or 80% of that limit. No retries follow allocation failure.",
              f"- Ordering: {large['metadata']['method']['ordering']} All realized orders and per-process measurements are retained.",
              "", "## Seven standard workloads", "",
              "| Workload | Bytes | " + " | ".join(f"{labels[v]} ms" for v in versions) + " |",
              "|---|---:|" + "---:|" * len(versions)]
    for name, w in standard["workloads"].items():
        lines.append(f'| {name} | {w["bytes"]:,} | ' + " | ".join(f'{w["summary"][v]["median_ms"]:.4f}' for v in versions) + " |")
    lines += ["", "`deep_fallback` retains the historical fixture name. PR #5 delegates depth 300 to xmltodict; "
              "the candidate is measured through its own public API. The candidate's bounded recursive DOM path can "
              "request a restart through the event interface for nesting beyond 256 levels. Restarting reparses the "
              "already-consumed prefix, which can include earlier siblings as well as ancestors. The depth-300 timing "
              "includes that complete public-call behavior; this benchmark does not isolate restart overhead or attribute "
              "the entire observed slowdown to it. Deeper XML remains supported through the event interface. See the "
              "[implementation boundaries](../docs/compatibility.md#implementation-and-boundaries).", "", "### Standard peak RSS", "",
              "| Workload | " + " | ".join(f"{labels[v]} MiB" for v in versions) + " |",
              "|---|" + "---:|" * len(versions)]
    for name, w in standard["workloads"].items():
        lines.append(f"| {name} | " + " | ".join(f'{w["summary"][v]["median_peak_rss_mib"]:.2f}' for v in versions) + " |")

    lines += ["", "## Full-string timing: 10 / 50 / 100 MiB", "",
              "The complete UTF-8 Python string is loaded before timing; the complete dictionary is retained at the RSS sample.", "",
              "| Shape | Input MiB | " + " | ".join(f"{labels[v]} s" for v in versions) + " |",
              "|---|---:|" + "---:|" * len(versions)]
    for w in large["workloads"].values():
        if w["parse_mode"] == "full_str":
            lines.append(f'| {w["shape"]} | {w["size_mib"]} | ' + " | ".join(f'{w["medians"][v]["elapsed_ns"]/1e9:.3f}' for v in versions) + " |")

    lines += ["", "## Full-string RSS: baseline, total, incremental and retained", "",
              "All figures are median MiB. Baselines are sampled after importing the parser, loading the entire input string "
              "and collecting garbage. Incremental peak is calculated separately in each process as total peak minus its "
              "baseline peak, then summarized by the median.", ""]
    for shape, title in (("records", "Repeated records"), ("large_text", "Single large text node")):
        lines += [f"### {title}", "", "| Input MiB | Parser | Baseline current | Baseline peak | Total peak | Incremental peak | Retained current |",
                  "|---:|---|---:|---:|---:|---:|---:|"]
        for w in large["workloads"].values():
            if w["shape"] != shape or w["parse_mode"] != "full_str":
                continue
            for v in versions:
                metrics = w["medians"][v]
                keys = ("baseline_current_rss_bytes", "baseline_peak_rss_bytes", "peak_rss_bytes",
                        "incremental_peak_rss_bytes", "retained_output_current_rss_bytes")
                lines.append(f'| {w["size_mib"]} | {labels[v]} | ' + " | ".join(f"{metrics[key]/MIB:.2f}" for key in keys) + " |")
        lines.append("")

    lines += ["## File full-result parsing versus non-retaining callbacks", "",
              "Both modes open the same binary record file before timing. File reads are timed; OS page-cache behavior is "
              "uncontrolled. Full-file mode retains its complete result. Callback mode uses `item_depth=2` and stores only "
              "a few integer counters/checksums, never emitted items.", "", "### Timing", "",
              "| Input MiB | Mode | " + " | ".join(f"{labels[v]} s" for v in versions) + " |",
              "|---:|---|" + "---:|" * len(versions)]
    files = [w for w in large["workloads"].values() if w["parse_mode"] != "full_str"]
    for w in files:
        lines.append(f'| {w["size_mib"]} | {w["parse_mode"]} | ' + " | ".join(f'{w["medians"][v]["elapsed_ns"]/1e9:.3f}' for v in versions) + " |")
    lines += ["", "### Peak RSS", "",
              "| Input MiB | Mode | " + " | ".join(f"{labels[v]} MiB" for v in versions) + " | Candidate current MiB |",
              "|---:|---|" + "---:|" * (len(versions) + 1)]
    for w in files:
        lines.append(f'| {w["size_mib"]} | {w["parse_mode"]} | ' + " | ".join(f'{w["medians"][v]["peak_rss_bytes"]/MIB:.2f}' for v in versions) +
                     f' | {w["medians"]["standalone"]["retained_output_current_rss_bytes"]/MIB:.2f} |')
    lines += ["", "### Callback equality", "", "| Input MiB | Count per parser/process | All checks equal |", "|---:|---:|---|"]
    for w in streams:
        lines.append(f'| {w["size_mib"]} | {w["expected_callback_summary"]["count"]:,} | Yes |')
    lines += ["", "Every callback parse returned `None`, and the callback retained zero items. These results demonstrate "
              "non-retaining incremental file processing for this repeated-record shape. They do not establish constant "
              "memory for arbitrary XML, large individual items/text, deep nesting or unbounded distinct names. "
              "Full-result parsing necessarily retains its output.", "", "## Memory interpretation and limitations", "",
              "- RSS is native-aware whole-process memory. `ru_maxrss` is normalized to bytes; Linux current RSS is sampled "
              "separately. Tracemalloc does not replace these measurements.",
              "- Peak-minus-baseline is a high-water subtraction, not an exact allocation count. Input-loading transients, "
              "startup peaks and allocator reuse can hide allocations. Zero incremental peak does not mean zero allocation.",
              "- Linux current RSS and `ru_maxrss` use different, non-atomic interfaces and accounting/sampling behavior. "
              "A current reading slightly above the reported high-water value is not evidence of a parser bug.",
              "- Native allocators may retain freed arenas. Current RSS is not an exact size of live output objects. "
              "String loading can briefly hold both bytes and decoded text; full-file mode starts with an open file rather "
              "than the entire input in memory.",
              "- Standard timing includes output destruction; large timing excludes it. Do not combine their absolute timings "
              "as if they used the same method. Single-host variation and a small number of large samples limit precision.",
              "", "## Raw data and reproduction", "",
              f"- [{standard_name}]({standard_name}): standard equality, timing batches, RSS, tracemalloc and provenance.",
              f"- [{large_name}]({large_name}): every large sample, full-result fingerprints, callback summaries and resource checks.",
              "- [Hybrid baseline](standalone-hybrid-baseline-results.md), [initial run](standalone-pre-optimization-results.md), "
              "and [intermediate run](standalone-intermediate-results.md) remain preserved with their exact measured commits.",
              "", "Use independent frozen snapshots and one Python environment. `BEFORE` is PR #5; `HYBRID` is 8db94cc; "
              "`AFTER` is the candidate; `PY` is the common environment's interpreter.", "", "```sh",
              "\"$PY\" -m pip install 'setuptools==84.0.0' 'wheel==0.48.0' 'setuptools-scm==8.3.1' 'xmltodict==1.0.4'",
              f'for ROOT in {build_roots}; do',
              '  (cd "$ROOT" && SETUPTOOLS_SCM_PRETEND_VERSION=0.1.dev0 CC=gcc CXX=g++ "$PY" setup.py build_ext --inplace --force)',
              'done',
              f'"$PY" benchmarks/standalone-benchmark.py --before "$BEFORE"{hybrid_flag} --after "$AFTER" --output benchmarks/standalone-standard.json',
              f'"$PY" benchmarks/standalone-large-memory.py --before "$BEFORE"{hybrid_flag} --after "$AFTER" --output benchmarks/standalone-large-memory.json',
              '"$PY" benchmarks/standalone-report.py', "```", "",
              "Runtime-independence tests, compatibility, architecture review and sanitizers are separate evidence. "
              "These benign performance measurements do not replace them.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standard", default=str(here / "standalone-standard.json"))
    parser.add_argument("--large", default=str(here / "standalone-large-memory.json"))
    parser.add_argument("--output", default=str(here / "standalone-results.md"))
    parser.add_argument("--candidate-label", default="Integrated candidate")
    args = parser.parse_args()
    standard = json.loads(Path(args.standard).read_text())
    large = json.loads(Path(args.large).read_text())
    rendered = render(standard, large, Path(args.standard).name, Path(args.large).name, args.candidate_label)
    Path(args.output).write_text(rendered)
