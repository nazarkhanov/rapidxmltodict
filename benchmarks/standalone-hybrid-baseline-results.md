# Hybrid baseline before integrated RapidXML refactor (8db94cc)

This is the preserved pre-refactor baseline for commit `8db94cc3d4a887038c3644c889c9823027214d35`. Its default path validates separately before RapidXML DOM conversion, and its event path uses bounded fragment tokenization. These measurements do not describe the subsequently authorized integrated RapidXML implementation. The standalone/hybrid results below refer only to this exact earlier commit.

Same-host comparison of exact PR #5 commit `f5ae82c43ba445a52932432198a559b319b67188`, standalone commit `8db94cc3d4a887038c3644c889c9823027214d35`, and xmltodict 1.0.4. Historical upstream benchmark reports are unchanged.

## Findings

- All six standard fast-path cases were 1.18–1.45× faster than PR #5. The three catalog cases were 6.13–7.44× faster than xmltodict 1.0.4. Every standard equality check passed.
- At 100 MiB, full-string record parsing took 1.549 s standalone versus 2.082 s PR #5 and 9.986 s xmltodict. Its peak RSS was 1403.79 / 1405.59 / 918.08 MiB respectively. Faster parsing does not establish lower memory than xmltodict.
- File callback parsing retained no items and stayed near 20.7 MiB peak RSS across 10, 50 and 100 MiB. Same-file full-result parsing grew with retained output; the tables below keep those different output contracts explicit.
- All 108 requested large samples completed without skips or allocation failures. Full-result fingerprints, exact callback counts/checksums, and source/binary stability checks passed. Fixture hashes and output fingerprints also match the preserved initial and intermediate runs.
- Tradeoffs remain: the depth-300 event path and record-shaped file/event parsing are slower than PR #5. Large-text string parsing is approximately comparable to PR #5 and remains slower than xmltodict. This is not a universal acceleration claim.

Both baseline and candidate tracked source files were verified byte-for-byte against their exact Git commits. The compatibility-test environment is separately pinned to CPython 3.12.15 / Expat 2.8.5; these benchmark results truthfully use CPython 3.12.14 / Expat 2.8.3.

## Scope and method

- Recorded 2026-10-09T16:43:24Z on AMD EPYC 9V74 80-Core Processor; CPython 3.12.14, Linux x86-64, G++ 14.2.0, C++17 / `-O3`.
- One isolated environment, `xmltodict==1.0.4`, the same interpreter and compiler, and CPU affinity `[0]` for every implementation. Implementation selection uses a fresh process and snapshot-specific `PYTHONPATH`.
- Reference and PR #5 use the benchmark interpreter's built-in Expat 2.8.3. The complete Expat feature list is recorded in the raw metadata; standalone timing and memory workers do not import Expat.
- The standard suite reuses `benchmark.py`: three timing processes × nine batches, three warmups and three calibration calls per process, and five separate RSS processes. Timing includes output destruction; fixture loading does not. One separate tracemalloc sample per parser is supplemental and excludes untraced native allocations.
- Large inputs reuse `upstream-large-memory.py`'s deterministic fixtures and complete typed output fingerprint. Each parser/shape/size/mode has three fresh processes; order rotates by repetition. One parse is timed, and output destruction and fingerprinting are excluded. Memory is recorded before fingerprinting with output retained.
- Every timed call includes validation, preprocessing, all internal passes and conversion. "One parse per process" means one public API invocation; it does not imply a single-pass implementation.
- Standard outputs are checked for equality against xmltodict before timing. Large full-parse outputs are compared using complete typed SHA-256 traversals, including every value and list element. Callback runs validate exact count, first/last identifier, identifier sum and squared-identifier sum; these are not full fingerprints of streamed items.
- All implementation source, three native headers, Python mapper/serializer, setup/pyproject files, upstream RapidXML header, and native binaries are hashed before and after. Both runs confirm unchanged snapshot hashes. The source snapshots are independent of later edits to the working checkout.
- Resource guard: 3072 MiB per-worker address-space limit; skip if estimated peak exceeds 40% of available host memory or 80% of that limit. No automatic retry after allocation failure.

These are synthetic observations from one host. Inputs differ substantially by shape, and timing samples show ordinary host variation. No statistical significance or universal speed/memory claim is implied.

## Seven standard workloads

| Workload | PR #5 ms | Hybrid 8db94cc ms | xmltodict ms | PR #5 / standalone speedup | xmltodict / standalone speedup |
|---|---:|---:|---:|---:|---:|
| small | 0.0174 | 0.0120 | 0.0891 | 1.45× | 7.44× |
| medium | 1.5759 | 1.2416 | 8.0527 | 1.27× | 6.49× |
| large | 19.4564 | 14.5739 | 89.4042 | 1.34× | 6.13× |
| unicode_mixed | 1.5070 | 1.2730 | 6.6816 | 1.18× | 5.25× |
| deep | 0.0241 | 0.0199 | 0.1756 | 1.21× | 8.82× |
| deep_fallback | 0.4230 | 0.4835 | 0.4143 | 0.87× | 0.86× |
| medium_bytes | 1.5820 | 1.2589 | 8.2791 | 1.26× | 6.58× |

`deep_fallback` preserves the historical fixture name: depth 300 used xmltodict fallback in PR #5; standalone handles it with its own event path.

### Standard whole-process peak RSS

| Workload | PR #5 MiB | Hybrid 8db94cc MiB | xmltodict MiB |
|---|---:|---:|---:|
| small | 19.50 | 19.50 | 19.50 |
| medium | 19.89 | 19.88 | 19.50 |
| large | 33.39 | 32.36 | 27.53 |
| unicode_mixed | 20.14 | 20.12 | 19.50 |
| deep | 19.50 | 19.50 | 19.50 |
| deep_fallback | 19.50 | 19.50 | 19.50 |
| medium_bytes | 19.89 | 19.75 | 19.50 |

## 10 / 50 / 100 MiB full-string parsing

Times below include full default public parsing and validation, with the UTF-8 Python string loaded before timing. A full dictionary is retained at the RSS sample.

| Shape | Input MiB | PR #5 s | Hybrid 8db94cc s | xmltodict s | PR #5 / standalone speedup | Peak MiB: PR #5 / standalone / reference |
|---|---:|---:|---:|---:|---:|---:|
| records | 10 | 0.202 | 0.152 | 0.899 | 1.33× | 158.1 / 157.2 / 109.1 |
| large_text | 10 | 0.047 | 0.046 | 0.025 | 1.02× | 60.6 / 58.7 / 59.6 |
| records | 50 | 0.996 | 0.783 | 5.127 | 1.27× | 713.2 / 711.2 / 468.8 |
| large_text | 50 | 0.284 | 0.279 | 0.170 | 1.02× | 219.6 / 218.7 / 218.6 |
| records | 100 | 2.082 | 1.549 | 9.986 | 1.34× | 1405.6 / 1403.8 / 918.1 |
| large_text | 100 | 0.494 | 0.472 | 0.254 | 1.05× | 419.6 / 418.7 / 418.6 |

## File parsing versus non-retaining callbacks

The same record fixture is opened as a binary file for both modes. File reads are timed; OS page-cache behavior is not controlled. Full-file mode retains the complete result. Streaming uses `item_depth=2` and a callback that retains only a few integer counters/checksums, never emitted items.

| Input MiB | Mode | PR #5 s | Hybrid 8db94cc s | xmltodict s | Peak MiB: PR #5 / standalone / reference | Standalone current RSS MiB |
|---|---|---:|---:|---:|---:|---:|
| 10 | full_file | 0.927 | 1.060 | 0.908 | 88.6 / 88.8 / 87.6 | 88.9 |
| 10 | stream_file | 0.813 | 0.964 | 0.812 | 20.7 / 20.7 / 20.7 | 18.8 |
| 50 | full_file | 5.111 | 5.769 | 5.050 | 367.9 / 368.1 / 367.0 | 368.3 |
| 50 | stream_file | 4.070 | 4.746 | 4.095 | 20.7 / 20.7 / 20.7 | 18.8 |
| 100 | full_file | 10.134 | 11.531 | 10.096 | 717.2 / 717.3 / 716.1 | 717.5 |
| 100 | stream_file | 8.038 | 9.355 | 7.968 | 20.7 / 20.7 / 20.7 | 18.8 |

### Callback equality

| Input MiB | Callbacks per parser/process | All three parsers × three processes equal |
|---|---:|---|
| 10 | 59,614 | Yes |
| 50 | 298,071 | Yes |
| 100 | 596,143 | Yes |

Callback mode deliberately discards items rather than retaining the complete result. Every callback parse returned `None`. The callback stored zero items. These measurements demonstrate incremental, non-retaining file parsing for this repeated-record shape. They do not establish constant memory for arbitrary documents, large individual text/items, deep nesting, or unbounded distinct names, nor do they claim that all parse paths avoid a native DOM. Full-result parsing must retain its output.

## Full-string RSS: baseline, total, incremental and retained

Medians of three fresh processes; all figures are MiB. Both baseline readings are taken after importing the parser, loading the entire UTF-8 string and collecting garbage. Incremental peak is computed in each process as total peak minus its pre-parse peak, then the three increments are summarized by their median.

### Repeated records

| Input MiB | Parser | Baseline current | Baseline peak | Total peak | Incremental peak | Retained current |
|---:|---|---:|---:|---:|---:|---:|
| 10 | PR #5 | 28.55 | 38.55 | 158.08 | 119.52 | 158.23 |
| 10 | Hybrid 8db94cc | 28.68 | 38.63 | 157.17 | 118.54 | 157.31 |
| 10 | xmltodict 1.0.4 | 27.62 | 37.55 | 109.09 | 71.54 | 109.15 |
| 50 | PR #5 | 68.55 | 118.55 | 713.21 | 594.66 | 612.29 |
| 50 | Hybrid 8db94cc | 68.68 | 118.63 | 711.17 | 592.54 | 611.34 |
| 50 | xmltodict 1.0.4 | 67.61 | 117.55 | 468.83 | 351.28 | 418.04 |
| 100 | PR #5 | 118.55 | 218.55 | 1405.59 | 1187.04 | 1204.77 |
| 100 | Hybrid 8db94cc | 118.68 | 218.63 | 1403.79 | 1185.16 | 1203.94 |
| 100 | xmltodict 1.0.4 | 117.61 | 217.55 | 918.08 | 700.53 | 817.21 |

### Single large text node

| Input MiB | Parser | Baseline current | Baseline peak | Total peak | Incremental peak | Retained current |
|---:|---|---:|---:|---:|---:|---:|
| 10 | PR #5 | 28.55 | 38.56 | 60.58 | 22.02 | 60.66 |
| 10 | Hybrid 8db94cc | 28.68 | 38.63 | 58.66 | 20.04 | 58.76 |
| 10 | xmltodict 1.0.4 | 27.61 | 37.50 | 59.59 | 22.09 | 59.71 |
| 50 | PR #5 | 68.55 | 118.55 | 219.59 | 101.04 | 118.66 |
| 50 | Hybrid 8db94cc | 68.68 | 118.63 | 218.66 | 100.04 | 118.77 |
| 50 | xmltodict 1.0.4 | 67.61 | 117.50 | 218.61 | 101.11 | 118.84 |
| 100 | PR #5 | 118.55 | 218.55 | 419.59 | 201.04 | 218.67 |
| 100 | Hybrid 8db94cc | 118.68 | 218.63 | 418.66 | 200.04 | 218.77 |
| 100 | xmltodict 1.0.4 | 117.61 | 217.50 | 418.61 | 201.11 | 217.84 |

This high-water subtraction is not an exact allocation count: startup/input-loading peaks and allocator reuse can hide memory allocated during the parse. The raw data retain every per-process reading. Linux current RSS and `ru_maxrss` are collected through different, non-atomic interfaces with accounting/sampling differences. A current-RSS reading slightly above the reported high-water value is therefore not evidence of a parser bug; interpret small differences cautiously.

## Memory interpretation

- RSS is the native-aware whole-process peak (`ru_maxrss`, normalized to bytes); Linux current RSS and the pre-parse peak/current baseline are also stored. Python tracemalloc is never substituted for native memory.
- The baseline peak can contain input-loading transients or process-launch high-water marks. Small workloads and streaming runs can stay below that baseline, so equal peaks or zero incremental peak do not mean zero allocation.
- Full-string loading can briefly hold both bytes and decoded text. Those costs are excluded from timing but visible in baseline/whole-process RSS. Full-file measurements start with an open file, not the entire input in memory.
- RSS can include freed native allocator arenas; retained current RSS is not an exact sum of live output objects. Compare the same mode across implementations.
- Standard timings include output destruction, whereas large timings exclude it. Absolute timings from the two methods should not be directly combined.

## Preserved earlier measurements

- [Initial standalone run](standalone-pre-optimization-results.md), commit `7a735598a7464284eb2434b2bf71a1eedb35a7a3`: recorded the Unicode, file-memory and event-path regressions before optimization.
- [Intermediate optimization run](standalone-intermediate-results.md), commit `39d392f4027bea5d82f9efbd0ef91ea3dcebeb78`: verified the name-cache memory correction and identified the ASCII-text slowdown before its final fix.
- Each earlier report links its unchanged raw timing and memory samples. Their commit IDs, source hashes and reference-backend versions distinguish them from this hybrid-baseline run.

## Raw results and reproducibility

- [standalone-hybrid-baseline-standard.json](standalone-hybrid-baseline-standard.json): all standard equality results, timing batches, RSS baselines/samples, tracemalloc and source/binary hashes.
- [standalone-hybrid-baseline-large-memory.json](standalone-hybrid-baseline-large-memory.json): all 108 large fresh-process samples, full fingerprints, callback summaries, resource checks and provenance.
- Harnesses: `standalone-benchmark.py`, `standalone-large-memory.py`, `standalone-common.py`; reused fixture/measurement code remains in `benchmark.py` and `upstream-large-memory.py`.

Create an exact PR #5 archive/worktree and a separate frozen copy of the standalone revision to compare. In one isolated Python 3.12 environment:

```sh
python -m pip install 'setuptools==84.0.0' 'wheel==0.48.0' 'setuptools-scm==8.3.1' 'xmltodict==1.0.4'
# BEFORE and AFTER point to the two source snapshots; PY is the same venv interpreter.
for ROOT in "$BEFORE" "$AFTER"; do
  (cd "$ROOT" && SETUPTOOLS_SCM_PRETEND_VERSION=0.1.dev0 CC=gcc CXX=g++ "$PY" setup.py build_ext --inplace --force)
done
"$PY" benchmarks/standalone-benchmark.py --before "$BEFORE" --after "$AFTER" --output benchmarks/standalone-hybrid-baseline-standard.json
"$PY" benchmarks/standalone-large-memory.py --before "$BEFORE" --after "$AFTER" --output benchmarks/standalone-hybrid-baseline-large-memory.json
```

The standalone tests, dependency-isolation checks and sanitizer evidence are separate from these benign performance measurements. This report makes no whole-platform compatibility or security claim.
