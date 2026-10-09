#!/usr/bin/env python3
"""Render the architecture comparison from its complete sanitized raw JSON."""
import argparse
import json
import importlib.util
from pathlib import Path

VARIANTS = ("baseline", "iterative_dom", "native_events", "xmltodict")
LABELS = {"baseline": "e911 baseline", "iterative_dom": "Iterative DOM/default",
          "native_events": "Native events", "xmltodict": "xmltodict 1.0.4"}
MIB = 1024 ** 2


def render(paths, destination, title="Parser architecture prototypes: four-way comparison", note=None, public_routing=None):
    helper_spec = importlib.util.spec_from_file_location("architecture_derive_memory", Path(__file__).with_name("architecture-derive-memory.py"))
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    inputs = [(Path(path), helper.derive(json.loads(Path(path).read_text()))) for path in paths]
    first = inputs[0][1]["metadata"]
    for _, data in inputs:
        if not data["metadata"].get("source_and_binary_hashes_unchanged"):
            raise SystemExit("Refusing to report a run with changed or unverified implementation hashes")
        if data["metadata"]["source_and_binary_hashes_start"] != first["source_and_binary_hashes_start"]:
            raise SystemExit("Refusing to combine runs with different source/binary snapshots")
    workloads = {}
    for _, data in inputs:
        duplicate = set(workloads) & set(data["workloads"])
        if duplicate:
            raise SystemExit(f"Duplicate workload names: {sorted(duplicate)}")
        workloads.update(data["workloads"])
    sample_count = sum(len(samples) for workload in workloads.values() for samples in workload["samples"].values())
    complete = all(data["metadata"].get("all_requested_samples_completed") for _, data in inputs)
    standard_method = next((data["metadata"]["method"] for _, data in inputs if data["metadata"]["method"]["suite"] in ("standard", "all")), first["method"])
    timing_method = standard_method["standard_timing"]
    repetitions = sorted({data["metadata"]["method"]["repetitions"] for _, data in inputs})
    lines = ["# " + title, "", *([note, ""] if note else []),
             ("These measurements compare separately frozen architectures. The native-event column explicitly selects its private entry point. The final public dispatcher chooses iterative DOM for exact default strings/bytes and native events for files/options; that selection is verified separately below." if public_routing else "These are private architecture experiments. The native-event entry point is explicitly selected; its numbers are not a claim about the public default dispatcher."), "",
             f"- Completed measurement workers: **{sample_count}** across **{len(workloads)}** workloads; every requested sample completed: **{complete}**.",
             f'- Host CPU: {first["cpu"]}; CPU affinity: {first["cpu_affinity"]}.',
             f'- Python: {first["python"].splitlines()[0]}.',
             f'- Compiler: {first["compiler"]}.',
             f'- Reference: xmltodict {first["xmltodict_version"]}; {first["reference_expat_provenance"]["version"]}.',
             f'- Baseline commit: `{first["baseline_commit"]}`.',
             f'- Iterative DOM commit: `{first.get("iterative_commit")}`.',
             *([f'- Native-event candidate commit: `{first["native_events_commit"]}`.'] if first.get("native_events_commit") else []),
             "- Each input is generated once outside measured workers. Exact fixture/source/extension hashes, sample order, individual timings and RSS values are included in the raw files.",
             "- Original standalone reports and their prior four-way baseline comparisons are preserved separately; their numbers are not substituted for freshly measured samples here.",
             "", "## What is being compared", "",
             "| Variant | Exact entry point | Implementation |", "|---|---|---|"]
    for variant in VARIANTS:
        lines.append(f'| {LABELS[variant]} | `{first["entrypoints"][variant]}` | {first["variant_descriptions"][variant]} |')
    lines.extend(["", "The iterative DOM/default variant still uses its existing Python event mapper for file and callback inputs. Those rows compare that snapshot’s actual public behavior; they are not measurements of a DOM streaming implementation.", "",
                  "## Method and caveats", "",
                  f"- Fresh workers per parser/workload: {repetitions}. All workers use the same CPU, interpreter, GC setting and PYTHONHASHSEED=0. Parser order rotates by workload and trial.",
                  f"- Standard timings: {timing_method['warmup_calls']} warmups, {timing_method['calibration_calls']} calibration parses, then {timing_method['batches_per_process']} calibrated batches per worker targeting {timing_method['target_batch_seconds']} seconds each. Result destruction is timed. RSS comes from the first parse before those batches.",
                  "- Large timings: one complete parse per fresh worker, with result destruction excluded. String input is loaded before timing; file reads are included. No OS page-cache eviction is performed, so file results are not cold-storage throughput measurements. Outputs remain alive at the RSS sample.",
                  "- Peak RSS is the entire process high-water mark. Both incremental views are shown: peak minus the pre-parse current RSS and peak minus the previous high-water RSS. Retained RSS is current process RSS with input and output alive, not an isolated output allocation count. Input-loading transients can reduce the reported incremental growth. Current RSS and ru_maxrss are separately sampled Linux accounting values and can disagree slightly at page-scale granularity.",
                  "- All direct outputs are validated using a complete typed iterative SHA-256 traversal. It preserves list order and string contents without recursion-limit adjustments. Separate unmeasured callback passes hash every emitted path and item. Timed callbacks only compute identical count/order/identifier checksums.",
                  "- Discard callbacks retain no item objects. Retaining callbacks keep every item in a list until sampling; this intentionally demonstrates that callback APIs do not make retained application data constant-memory.",
                  "- File inputs can reduce input-buffer retention. Native event mapping can avoid an intermediate DOM, but a complete result still grows with the output size. Large text and application-retained callback outputs remain inherently large. The record fixtures repeat a fixed small name vocabulary: flat discard-callback RSS here does not prove constant memory for arbitrary XML; name/entity tables, document vocabulary and nesting can also grow.",
                  "- This is a single-host microbenchmark, not a universal performance guarantee. Absolute timings and trial spread are provided; small differences should not be overinterpreted.",
                  "- The frozen baseline preserves its existing binary and exact on-disk sources. The previously disclosed CRLF/LF vendor-header difference from Git remains separately accounted for by exact hashes; baseline timings are not relabeled as a different source build.",
                  "", "## Standard and deep-input timings", "",
                  "Times are medians in milliseconds across all batches. A ratio above 1 means the candidate was faster than the current baseline.", "",
                  "| Workload | Baseline ms | Iterative ms | Events ms | xmltodict ms | Iterative vs baseline | Events vs baseline |", "|---|---:|---:|---:|---:|---:|---:|"])
    for name, workload in workloads.items():
        if workload["suite"] != "standard":
            continue
        medians = workload.get("medians", {})
        def t(variant):
            return medians.get(variant, {}).get("timing_median_ns")
        values = [f"{t(variant) / 1e6:.3f}" if t(variant) is not None else "N/A" for variant in VARIANTS]
        ratios = [f"{t('baseline') / t(variant):.2f}×" if t("baseline") is not None and t(variant) else "N/A" for variant in ("iterative_dom", "native_events")]
        lines.append("| " + " | ".join([name, *values, *ratios]) + " |")
    lines.extend(["", "The full fixture suite includes 128, 300, 1,500 and 10,000 nested elements; only measured cases appear in the table. Late-deep workloads place a 1,500-element branch after 6,000 or 60,000 completed shallow siblings, exposing abandoned-DOM-and-reparse work in the baseline. All output fingerprints must match the oracle.", "",
                  "## Large-input timings", "", "Times are median seconds from complete parses in fresh processes.", "",
                  "| Workload | Baseline s | Iterative s | Events s | xmltodict s | Events vs baseline |", "|---|---:|---:|---:|---:|---:|"])
    for name, workload in workloads.items():
        if workload["suite"] != "large":
            continue
        medians = workload.get("medians", {})
        times = {variant: medians.get(variant, {}).get("timing_median_ns") for variant in VARIANTS}
        values = [f"{times[variant] / 1e9:.3f}" if times[variant] is not None else "N/A" for variant in VARIANTS]
        ratio = f"{times['baseline'] / times['native_events']:.2f}×" if times["baseline"] and times["native_events"] else "N/A"
        lines.append("| " + " | ".join([name, *values, ratio]) + " |")
    lines.extend(["", "## Total and incremental peak RSS", "",
                  "Each cell is **total peak / peak minus pre-parse current RSS / peak minus prior high-water RSS**, in MiB. Both deltas are clamped at zero and calculated per sample before taking medians. They use the same measured peak; the current-baseline delta does not hide input-loading transients in a previous peak. Neither delta is a precise attribution of parser-only allocations.", "",
                  "| Workload | Baseline MiB | Iterative MiB | Events MiB | xmltodict MiB |", "|---|---:|---:|---:|---:|"])
    memory_sections = [
        (("peak_rss_bytes", "incremental_peak_over_current_rss_bytes", "incremental_peak_rss_bytes"), None),
        (("baseline_current_rss_bytes", "baseline_peak_rss_bytes"),
         ["", "## Pre-parse RSS baselines", "", "Each cell is **current RSS / prior high-water RSS**, in MiB, after imports and input loading/opening and before parsing. These are the two baselines used above.", "",
          "| Workload | Baseline MiB | Iterative MiB | Events MiB | xmltodict MiB |", "|---|---:|---:|---:|---:|"]),
        (("retained_output_current_rss_bytes", "retained_current_increase_bytes"),
         ["", "## Retained RSS and current-baseline increase", "", "Each cell is **retained current RSS / retained minus pre-parse current RSS**, in MiB. The increase is signed. Inputs and results/application-retained callback items remain alive; this is whole-process memory, not output-object size alone.", "",
          "| Workload | Baseline MiB | Iterative MiB | Events MiB | xmltodict MiB |", "|---|---:|---:|---:|---:|"]),
    ]
    for metrics, heading in memory_sections:
        if heading:
            lines.extend(heading)
        for name, workload in workloads.items():
            medians = workload.get("medians", {})
            values = []
            for variant in VARIANTS:
                if variant not in medians:
                    values.append("N/A")
                else:
                    values.append(" / ".join(f'{medians[variant][key] / MIB:.1f}' for key in metrics))
            lines.append("| " + " | ".join([name, *values]) + " |")
    lines.extend(["", "## Trial range", "", "Minimum–maximum milliseconds across measured standard batches or large fresh-process parses. These are descriptive ranges, not confidence intervals.", "",
                  "| Workload | Baseline | Iterative | Events | xmltodict |", "|---|---:|---:|---:|---:|"])
    for name, workload in workloads.items():
        medians = workload.get("medians", {})
        values = [f'{medians[variant]["timing_min_ns"] / 1e6:.3f}–{medians[variant]["timing_max_ns"] / 1e6:.3f}' if variant in medians else "N/A" for variant in VARIANTS]
        lines.append("| " + " | ".join([name, *values]) + " |")
    if public_routing:
        routing_path = Path(public_routing)
        routing = json.loads(routing_path.read_text())
        if not routing.get("all_checks_passed") or not routing.get("source_and_binary_hashes_unchanged"):
            raise SystemExit("Public dispatch verification did not pass")
        if routing["source_and_binary_hashes_start"] != first["source_and_binary_hashes_start"]["native_events"]:
            raise SystemExit("Public routing check used a different candidate snapshot")
        lines.extend(["", "## Selected public dispatcher", "",
                      "The final public API selects iterative DOM for exact default strings/bytes, and direct native events for files, generators, callbacks and non-default mapping options. Read the iterative column for default in-memory input and the native-event column for file/callback behavior. The iterative snapshot's file/callback column is the earlier Python-mapper implementation, not the final public file/callback path.", "",
                      "These remain measurements of the separately frozen architectures. The hybrid public dispatcher is verified independently rather than presented as a fifth timed variant.", "",
                      f"[{routing_path.name}]({routing_path.name}) records {len(routing['checks'])} isolated, untimed public-API checks. They observe the actual native entry points and compare complete output or callback-content fingerprints with the selected measured architecture. Generator and explicit-option routes are included, and retained callback objects are additionally compared with xmltodict after the complete 10 and 100 MiB parses. All passed, with source/binary hashes unchanged."])
    lines.extend(["", "## Verification and provenance", ""])
    for path, data in inputs:
        count = sum(len(samples) for workload in data["workloads"].values() for samples in workload["samples"].values())
        lines.append(f'- [{path.name}]({path.name}): {count} measured samples; source/binary hashes unchanged: {data["metadata"]["source_and_binary_hashes_unchanged"]}; complete: {data["metadata"].get("all_requested_samples_completed", False)}.')
    for name, workload in workloads.items():
        if workload.get("skipped"):
            lines.append(f'- **Incomplete {name}:** {json.dumps(workload["skipped"], sort_keys=True)}')
        verification = workload.get("all_output_fingerprints_equal", workload.get("all_callback_content_equal"))
        if not verification:
            lines.append(f'- **Unverified or mismatched output: {name}.**')
    lines.extend(["", "Reproduction commands and selection details: [architecture-README.md](architecture-README.md). The full source and binary SHA-256 manifests are embedded in each raw file. No local usernames, absolute workspace paths or environment IDs are included.", ""])
    findings = []
    def metric(name, variant, key):
        return workloads.get(name, {}).get("medians", {}).get(variant, {}).get(key)
    late = "late_deep_60000_siblings"
    if metric(late, "baseline", "timing_median_ns"):
        base = metric(late, "baseline", "timing_median_ns")
        dom = metric(late, "iterative_dom", "timing_median_ns")
        events = metric(late, "native_events", "timing_median_ns")
        findings.append(f"- The late-deep case after 60,000 siblings is {base / dom:.2f}× faster with iterative DOM and {base / events:.2f}× faster with native events than the current baseline. Avoiding abandoned DOM work and a second parse is the major deep-input improvement.")
    records_file = "records_100mib_direct_file"
    if metric(records_file, "native_events", "timing_median_ns"):
        base = metric(records_file, "baseline", "timing_median_ns")
        events = metric(records_file, "native_events", "timing_median_ns")
        findings.append(f"- For 100 MiB record files, native events take {events / 1e9:.3f} s versus the baseline's {base / 1e9:.3f} s ({base / events:.2f}× faster). Peak RSS is {metric(records_file, 'native_events', 'peak_rss_bytes') / MIB:.1f} versus {metric(records_file, 'baseline', 'peak_rss_bytes') / MIB:.1f} MiB.")
    records_string = "records_100mib_direct_str"
    if metric(records_string, "native_events", "timing_median_ns"):
        dom = metric(records_string, "iterative_dom", "timing_median_ns")
        events = metric(records_string, "native_events", "timing_median_ns")
        findings.append(f"- For complete 100 MiB record strings, iterative DOM takes {dom / 1e9:.3f} s versus native events at {events / 1e9:.3f} s. Native-event peak RSS is {metric(records_string, 'native_events', 'peak_rss_bytes') / MIB:.1f} versus iterative DOM's {metric(records_string, 'iterative_dom', 'peak_rss_bytes') / MIB:.1f} MiB.")
    discard, retain = "records_100mib_callback_file_discard", "records_100mib_callback_file_retain"
    if metric(discard, "native_events", "timing_median_ns") and metric(retain, "native_events", "timing_median_ns"):
        base = metric(discard, "baseline", "timing_median_ns")
        events = metric(discard, "native_events", "timing_median_ns")
        findings.append(f"- For 100 MiB discard callbacks, native events are {base / events:.2f}× faster than the baseline and peak at {metric(discard, 'native_events', 'peak_rss_bytes') / MIB:.1f} MiB. Retaining every callback item raises the native-event peak to {metric(retain, 'native_events', 'peak_rss_bytes') / MIB:.1f} MiB. The application retention policy controls whether output memory stays bounded.")
    text = "large_text_100mib_direct_str"
    if metric(text, "native_events", "timing_median_ns"):
        dom = metric(text, "iterative_dom", "timing_median_ns")
        events = metric(text, "native_events", "timing_median_ns")
        findings.append(f"- For a 100 MiB text string, native events take {events / 1e9:.3f} s and peak at {metric(text, 'native_events', 'peak_rss_bytes') / MIB:.1f} MiB, versus iterative DOM's {dom / 1e9:.3f} s and {metric(text, 'iterative_dom', 'peak_rss_bytes') / MIB:.1f} MiB. The choice should account for both time and memory; event mapping does not inherently minimize either.")
    featured_memory = []
    if metric(records_file, "xmltodict", "peak_rss_bytes") and metric(records_string, "xmltodict", "peak_rss_bytes"):
        file_native = metric(records_file, "native_events", "peak_rss_bytes")
        file_reference = metric(records_file, "xmltodict", "peak_rss_bytes")
        findings.append(f"- On this 100 MiB record-file workload, native events use {100 * (1 - file_native / file_reference):.1f}% less total peak RSS than xmltodict ({file_native / MIB:.1f} versus {file_reference / MIB:.1f} MiB). This does not generalize to every input path: for record strings, native-event peak RSS is {metric(records_string, 'native_events', 'peak_rss_bytes') / MIB:.1f} versus xmltodict's {metric(records_string, 'xmltodict', 'peak_rss_bytes') / MIB:.1f} MiB, even though native-event retained RSS is lower. The table below distinguishes both cases.")
        featured_memory = ["", "### Focus: 100 MiB records versus xmltodict", "",
            "All values are MiB. Deltas are derived per sample before taking medians; complete output remains alive. These observed cases are not a universal memory-crossover threshold.", "",
            "| Input | Parser | Pre-parse current | Prior peak | Total peak | Peak − current | Peak − prior peak | Retained current | Retained − current |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        columns = ("baseline_current_rss_bytes", "baseline_peak_rss_bytes", "peak_rss_bytes",
                   "incremental_peak_over_current_rss_bytes", "incremental_peak_rss_bytes",
                   "retained_output_current_rss_bytes", "retained_current_increase_bytes")
        for name, input_label in ((records_file, "File"), (records_string, "String")):
            for variant in ("native_events", "xmltodict"):
                cells = [f"{metric(name, variant, key) / MIB:.1f}" for key in columns]
                featured_memory.append("| " + " | ".join([input_label, LABELS[variant], *cells]) + " |")
    if findings:
        position = lines.index("## What is being compared")
        lines[position:position] = ["## Main findings", "", *findings, *featured_memory, ""]
    Path(destination).write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--title", default="Parser architecture prototypes: four-way comparison")
    parser.add_argument("--note")
    parser.add_argument("--public-routing")
    parser.add_argument("--output", default=str(Path(__file__).with_name("architecture-results.md")))
    args = parser.parse_args()
    render(args.inputs, args.output, args.title, args.note, args.public_routing)
