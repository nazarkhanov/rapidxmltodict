# Integrated candidate RapidXML benchmark

Measured candidate: `f95684461f3ebe39ca0d3db390326d1a4730f997`. Baseline PR #5: `f5ae82c43ba445a52932432198a559b319b67188`.
Hybrid pre-refactor baseline: `8db94cc3d4a887038c3644c889c9823027214d35`.

Source-attribution note: `vendor/rapidxml/rapidxml.hpp` used CRLF in the frozen measured snapshot and LF in the published commit. Their contents match after line-ending normalization; all other measured source files match byte-for-byte. Both exact header hashes and the measured binary hashes are retained in the raw data. The measured snapshot was not changed during the run.

## Findings

- Candidate medians were faster in 6 of seven standard workloads versus PR #5; the full observed speedup range was 0.66–1.55×.
- Candidate medians were faster in 2 of seven standard workloads versus Hybrid 8db94cc; the full observed speedup range was 0.74–1.12×.
- 100 MiB record-shaped full-string parsing: PR #5 1.897 s; Hybrid 8db94cc 1.516 s; Integrated candidate 1.611 s; xmltodict 1.0.4 9.728 s. Candidate total peak was 1403.80 MiB; incremental peak above its pre-parse high-water mark was 1185.18 MiB.
- On that record input, candidate time changed by +6.3% versus the hybrid baseline. Hybrid total/incremental peak was 1403.80 / 1185.17 MiB; the full DOM memory cost remains visible.
- Shape matters: 100 MiB single-text-node parsing was 0.298 s versus hybrid 0.467 s (1.57× speedup). The separate tables retain all parser and size comparisons.
- Depth 300 measured 0.669 ms versus hybrid 0.495 ms (+35.3% time). The restart/reparsed-prefix limitation is explained below; this run does not isolate its cost.
- Candidate non-retaining callback peaks were 20.63 / 20.63 / 20.63 MiB for 10 / 50 / 100 MiB record inputs. Callback mode deliberately discards each emitted item and returns `None`, unlike full-result parsing.
- All seven standard equality checks and all 144 large fresh-process samples passed. Full-result fingerprints and exact callback counts/checksums agree; no large sample was skipped or retried.
- These are observed medians on synthetic inputs, not statistical-significance or universal speed/memory claims. Slower shapes remain visible in the complete tables below.

## Environment and complete-call method

- Recorded 2026-10-09T17:16:37Z; Python 3.12.14; Linux-6.18.44-x86_64-with-glibc2.41; AMD EPYC 9V74 80-Core Processor; CPU affinity [0]; g++ (Debian 14.2.0-19) 14.2.0.
- Oracle: xmltodict 1.0.4; reference/baseline backend expat_2.8.3. Its complete feature list is in the raw metadata. Benchmark and compatibility-test environments are distinct.
- One interpreter and environment for all implementations. Native snapshots are selected through isolated fresh-process `PYTHONPATH` values. Compiler flags, snapshot paths, fixture hashes and all implementation/native binary hashes are recorded; source and binary hashes stayed unchanged throughout both runs.
- Shared artifacts replace local absolute paths and execution-specific identities with generic relative snapshot/venv/fixture paths. Numeric measurements and source/binary hashes are preserved.
- Every measurement times the complete public `parse` call, including validation, preprocessing, all internal passes, conversion and any benchmark callback. One parse per process means one API invocation. These measurements do not by themselves establish a single-pass implementation.
- Standard suite: three timing processes, nine batches each, three warmups and three calibration calls; five separate RSS processes. Fixture loading is excluded and output destruction is included in timing. Separate tracemalloc samples are supplemental and exclude untraced native allocations.
- Large suite: 3 fresh processes per parser, shape, size and mode. Input files are generated outside measured workers. One parse is timed; output destruction and output fingerprinting are excluded. Memory is sampled before fingerprinting while any full result remains alive.
- Full results use complete typed SHA-256 traversals with sorted dictionary keys, preserved list order and every string value. Streaming checks every callback count, first/last identifier, identifier sum and squared-identifier sum. Those callback checks are not complete streamed-item fingerprints.
- Resource guard: 3072 MiB per-worker address-space limit; skip estimated peaks exceeding 40% of available memory or 80% of that limit. No retries follow allocation failure.
- Ordering: Rotate the recorded comparison_versions order across repetitions; four-way runs also offset by workload so no parser is systematically excluded from the first position. All realized orders and per-process measurements are retained.

## Seven standard workloads

| Workload | Bytes | PR #5 ms | Hybrid 8db94cc ms | Integrated candidate ms | xmltodict 1.0.4 ms |
|---|---:|---:|---:|---:|---:|
| small | 1,077 | 0.0179 | 0.0120 | 0.0129 | 0.0835 |
| medium | 105,501 | 1.5868 | 1.1954 | 1.2794 | 7.8506 |
| large | 1,055,391 | 19.5391 | 14.0918 | 12.5970 | 86.0122 |
| unicode_mixed | 91,903 | 1.5477 | 1.2320 | 1.2148 | 6.5879 |
| deep | 900 | 0.0245 | 0.0202 | 0.0205 | 0.1782 |
| deep_fallback | 2,104 | 0.4428 | 0.4948 | 0.6693 | 0.4077 |
| medium_bytes | 105,501 | 1.5443 | 1.2040 | 1.2795 | 7.8754 |

`deep_fallback` retains the historical fixture name. PR #5 delegates depth 300 to xmltodict; the candidate is measured through its own public API. The candidate's bounded recursive DOM path can request a restart through the event interface for nesting beyond 256 levels. Restarting reparses the already-consumed prefix, which can include earlier siblings as well as ancestors. The depth-300 timing includes that complete public-call behavior; this benchmark does not isolate restart overhead or attribute the entire observed slowdown to it. Deeper XML remains supported through the event interface. See the [implementation boundaries](../docs/compatibility.md#implementation-and-boundaries).

### Standard peak RSS

| Workload | PR #5 MiB | Hybrid 8db94cc MiB | Integrated candidate MiB | xmltodict 1.0.4 MiB |
|---|---:|---:|---:|---:|
| small | 19.50 | 19.50 | 19.50 | 19.50 |
| medium | 20.00 | 19.88 | 19.88 | 19.50 |
| large | 33.40 | 32.32 | 32.38 | 27.54 |
| unicode_mixed | 20.25 | 20.12 | 19.99 | 19.50 |
| deep | 19.50 | 19.50 | 19.50 | 19.50 |
| deep_fallback | 19.50 | 19.50 | 19.50 | 19.50 |
| medium_bytes | 19.86 | 19.75 | 19.74 | 19.50 |

## Full-string timing: 10 / 50 / 100 MiB

The complete UTF-8 Python string is loaded before timing; the complete dictionary is retained at the RSS sample.

| Shape | Input MiB | PR #5 s | Hybrid 8db94cc s | Integrated candidate s | xmltodict 1.0.4 s |
|---|---:|---:|---:|---:|---:|
| records | 10 | 0.217 | 0.161 | 0.160 | 0.858 |
| large_text | 10 | 0.047 | 0.046 | 0.027 | 0.025 |
| records | 50 | 1.011 | 0.768 | 0.818 | 5.149 |
| large_text | 50 | 0.263 | 0.238 | 0.153 | 0.130 |
| records | 100 | 1.897 | 1.516 | 1.611 | 9.728 |
| large_text | 100 | 0.495 | 0.467 | 0.298 | 0.238 |

## Full-string RSS: baseline, total, incremental and retained

All figures are median MiB. Baselines are sampled after importing the parser, loading the entire input string and collecting garbage. Incremental peak is calculated separately in each process as total peak minus its baseline peak, then summarized by the median.

### Repeated records

| Input MiB | Parser | Baseline current | Baseline peak | Total peak | Incremental peak | Retained current |
|---:|---|---:|---:|---:|---:|---:|
| 10 | PR #5 | 28.57 | 38.58 | 158.10 | 119.52 | 158.25 |
| 10 | Hybrid 8db94cc | 28.69 | 38.63 | 157.17 | 118.54 | 157.32 |
| 10 | Integrated candidate | 28.68 | 38.63 | 157.17 | 118.54 | 147.31 |
| 10 | xmltodict 1.0.4 | 27.63 | 37.57 | 108.98 | 71.41 | 109.16 |
| 50 | PR #5 | 68.57 | 118.58 | 713.23 | 594.66 | 612.31 |
| 50 | Hybrid 8db94cc | 68.69 | 118.63 | 711.30 | 592.67 | 611.48 |
| 50 | Integrated candidate | 68.68 | 118.63 | 711.30 | 592.68 | 611.47 |
| 50 | xmltodict 1.0.4 | 67.63 | 117.57 | 468.86 | 351.29 | 418.05 |
| 100 | PR #5 | 118.57 | 218.58 | 1405.61 | 1187.03 | 1204.78 |
| 100 | Hybrid 8db94cc | 118.69 | 218.63 | 1403.80 | 1185.17 | 1203.95 |
| 100 | Integrated candidate | 118.68 | 218.63 | 1403.80 | 1185.18 | 1203.97 |
| 100 | xmltodict 1.0.4 | 117.63 | 217.57 | 918.11 | 700.54 | 817.23 |

### Single large text node

| Input MiB | Parser | Baseline current | Baseline peak | Total peak | Incremental peak | Retained current |
|---:|---|---:|---:|---:|---:|---:|
| 10 | PR #5 | 28.57 | 38.57 | 60.59 | 22.03 | 60.67 |
| 10 | Hybrid 8db94cc | 28.69 | 38.63 | 58.67 | 20.04 | 58.77 |
| 10 | Integrated candidate | 28.69 | 38.63 | 58.67 | 20.04 | 48.81 |
| 10 | xmltodict 1.0.4 | 27.63 | 37.57 | 59.61 | 22.04 | 59.73 |
| 50 | PR #5 | 68.57 | 118.57 | 219.61 | 101.04 | 118.68 |
| 50 | Hybrid 8db94cc | 68.69 | 118.63 | 218.67 | 100.04 | 118.78 |
| 50 | Integrated candidate | 68.69 | 118.63 | 218.68 | 100.05 | 118.76 |
| 50 | xmltodict 1.0.4 | 67.63 | 117.57 | 218.62 | 101.06 | 118.86 |
| 100 | PR #5 | 118.57 | 218.57 | 419.61 | 201.04 | 218.68 |
| 100 | Hybrid 8db94cc | 118.69 | 218.63 | 418.67 | 200.04 | 218.78 |
| 100 | Integrated candidate | 118.68 | 218.63 | 418.68 | 200.05 | 218.76 |
| 100 | xmltodict 1.0.4 | 117.63 | 217.57 | 418.63 | 201.06 | 217.86 |

## File full-result parsing versus non-retaining callbacks

Both modes open the same binary record file before timing. File reads are timed; OS page-cache behavior is uncontrolled. Full-file mode retains its complete result. Callback mode uses `item_depth=2` and stores only a few integer counters/checksums, never emitted items.

### Timing

| Input MiB | Mode | PR #5 s | Hybrid 8db94cc s | Integrated candidate s | xmltodict 1.0.4 s |
|---:|---|---:|---:|---:|---:|
| 10 | full_file | 0.925 | 1.048 | 0.961 | 0.883 |
| 10 | stream_file | 0.795 | 0.971 | 0.923 | 0.819 |
| 50 | full_file | 5.213 | 5.752 | 5.677 | 4.980 |
| 50 | stream_file | 3.933 | 4.634 | 4.446 | 4.044 |
| 100 | full_file | 10.458 | 11.460 | 11.243 | 10.516 |
| 100 | stream_file | 8.106 | 9.350 | 9.805 | 8.022 |

### Peak RSS

| Input MiB | Mode | PR #5 MiB | Hybrid 8db94cc MiB | Integrated candidate MiB | xmltodict 1.0.4 MiB | Candidate current MiB |
|---:|---|---:|---:|---:|---:|---:|
| 10 | full_file | 88.58 | 88.75 | 88.63 | 87.69 | 88.84 |
| 10 | stream_file | 20.63 | 20.63 | 20.63 | 20.63 | 18.77 |
| 50 | full_file | 367.95 | 368.13 | 368.00 | 366.94 | 368.18 |
| 50 | stream_file | 20.63 | 20.63 | 20.63 | 20.63 | 18.78 |
| 100 | full_file | 717.08 | 717.25 | 717.25 | 716.19 | 717.36 |
| 100 | stream_file | 20.63 | 20.63 | 20.63 | 20.63 | 18.77 |

### Callback equality

| Input MiB | Count per parser/process | All checks equal |
|---:|---:|---|
| 10 | 59,614 | Yes |
| 50 | 298,071 | Yes |
| 100 | 596,143 | Yes |

Every callback parse returned `None`, and the callback retained zero items. These results demonstrate non-retaining incremental file processing for this repeated-record shape. They do not establish constant memory for arbitrary XML, large individual items/text, deep nesting or unbounded distinct names. Full-result parsing necessarily retains its output.

## Memory interpretation and limitations

- RSS is native-aware whole-process memory. `ru_maxrss` is normalized to bytes; Linux current RSS is sampled separately. Tracemalloc does not replace these measurements.
- Peak-minus-baseline is a high-water subtraction, not an exact allocation count. Input-loading transients, startup peaks and allocator reuse can hide allocations. Zero incremental peak does not mean zero allocation.
- Linux current RSS and `ru_maxrss` use different, non-atomic interfaces and accounting/sampling behavior. A current reading slightly above the reported high-water value is not evidence of a parser bug.
- Native allocators may retain freed arenas. Current RSS is not an exact size of live output objects. String loading can briefly hold both bytes and decoded text; full-file mode starts with an open file rather than the entire input in memory.
- Standard timing includes output destruction; large timing excludes it. Do not combine their absolute timings as if they used the same method. Single-host variation and a small number of large samples limit precision.

## Raw data and reproduction

- [standalone-standard.json](standalone-standard.json): standard equality, timing batches, RSS, tracemalloc and provenance.
- [standalone-large-memory.json](standalone-large-memory.json): every large sample, full-result fingerprints, callback summaries and resource checks.
- [Hybrid baseline](standalone-hybrid-baseline-results.md), [initial run](standalone-pre-optimization-results.md), and [intermediate run](standalone-intermediate-results.md) remain preserved with their exact measured commits.

Use independent frozen snapshots and one Python environment. `BEFORE` is PR #5; `HYBRID` is 8db94cc; `AFTER` is the candidate; `PY` is the common environment's interpreter.

```sh
"$PY" -m pip install 'setuptools==84.0.0' 'wheel==0.48.0' 'setuptools-scm==8.3.1' 'xmltodict==1.0.4'
for ROOT in "$BEFORE" "$HYBRID" "$AFTER"; do
  (cd "$ROOT" && SETUPTOOLS_SCM_PRETEND_VERSION=0.1.dev0 CC=gcc CXX=g++ "$PY" setup.py build_ext --inplace --force)
done
"$PY" benchmarks/standalone-benchmark.py --before "$BEFORE" --hybrid "$HYBRID" --after "$AFTER" --output benchmarks/standalone-standard.json
"$PY" benchmarks/standalone-large-memory.py --before "$BEFORE" --hybrid "$HYBRID" --after "$AFTER" --output benchmarks/standalone-large-memory.json
"$PY" benchmarks/standalone-report.py
```

Runtime-independence tests, compatibility, architecture review and sanitizers are separate evidence. These benign performance measurements do not replace them.
