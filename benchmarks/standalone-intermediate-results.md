# Intermediate standalone benchmark (39d392f)

Same-host comparison of exact PR #5 commit `f5ae82c43ba445a52932432198a559b319b67188`, standalone commit `39d392f4027bea5d82f9efbd0ef91ea3dcebeb78`, and xmltodict 1.0.4. Historical upstream benchmark reports are unchanged.

This is intermediate optimization evidence, before the final strict-declaration and ASCII hot-loop changes. All tracked implementation files were verified byte-for-byte against the recorded candidate commit.

## Scope and method

- Recorded 2026-10-09T16:30:54Z on AMD EPYC 9V74 80-Core Processor; CPython 3.12.14, Linux x86-64, G++ 14.2.0, C++17 / `-O3`.
- One isolated environment, `xmltodict==1.0.4`, the same interpreter and compiler, and CPU affinity `[0]` for every implementation. Implementation selection uses a fresh process and snapshot-specific `PYTHONPATH`.
- Reference and PR #5 use the benchmark interpreter's built-in Expat 2.8.3. The complete Expat feature list is recorded in the raw metadata; standalone timing and memory workers do not import Expat.
- The standard suite reuses `benchmark.py`: three timing processes × nine batches, three warmups and three calibration calls per process, and five separate RSS processes. Timing includes output destruction; fixture loading does not. One separate tracemalloc sample per parser is supplemental and excludes untraced native allocations.
- Large inputs reuse `upstream-large-memory.py`'s deterministic fixtures and complete typed output fingerprint. Each parser/shape/size/mode has three fresh processes; order rotates by repetition. One parse is timed, and output destruction and fingerprinting are excluded. Memory is recorded before fingerprinting with output retained.
- Standard outputs are checked for equality against xmltodict before timing. Large full-parse outputs are compared using complete typed SHA-256 traversals, including every value and list element. Callback runs validate exact count, first/last identifier, identifier sum and squared-identifier sum; these are not full fingerprints of streamed items.
- All implementation source, three native headers, Python mapper/serializer, setup/pyproject files, upstream RapidXML header, and native binaries are hashed before and after. Both runs confirm unchanged snapshot hashes. The source snapshots are independent of later edits to the working checkout.
- Resource guard: 3072 MiB per-worker address-space limit; skip if estimated peak exceeds 40% of available host memory or 80% of that limit. No automatic retry after allocation failure.

These are synthetic observations from one host. Inputs differ substantially by shape, and timing samples show ordinary host variation. No statistical significance or universal speed/memory claim is implied.

## Seven standard workloads

| Workload | PR #5 ms | Standalone ms | xmltodict ms | PR #5 / standalone speedup | xmltodict / standalone speedup |
|---|---:|---:|---:|---:|---:|
| small | 0.0169 | 0.0123 | 0.0862 | 1.38× | 7.03× |
| medium | 1.6606 | 1.2759 | 8.4009 | 1.30× | 6.58× |
| large | 18.2222 | 14.1822 | 82.9880 | 1.28× | 5.85× |
| unicode_mixed | 1.5286 | 1.2655 | 6.8340 | 1.21× | 5.40× |
| deep | 0.0245 | 0.0196 | 0.1752 | 1.25× | 8.94× |
| deep_fallback | 0.4348 | 0.4910 | 0.4080 | 0.89× | 0.83× |
| medium_bytes | 1.6906 | 1.2666 | 8.2744 | 1.33× | 6.53× |

`deep_fallback` preserves the historical fixture name: depth 300 used xmltodict fallback in PR #5; standalone handles it with its own event path.

### Standard whole-process peak RSS

| Workload | PR #5 MiB | Standalone MiB | xmltodict MiB |
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

| Shape | Input MiB | PR #5 s | Standalone s | xmltodict s | PR #5 / standalone speedup | Peak MiB: PR #5 / standalone / reference |
|---|---:|---:|---:|---:|---:|---:|
| records | 10 | 0.209 | 0.170 | 0.992 | 1.23× | 158.1 / 157.2 / 109.1 |
| large_text | 10 | 0.046 | 0.054 | 0.026 | 0.85× | 60.6 / 58.7 / 59.6 |
| records | 50 | 0.966 | 0.797 | 4.938 | 1.21× | 713.2 / 711.2 / 468.8 |
| large_text | 50 | 0.242 | 0.308 | 0.118 | 0.78× | 219.6 / 218.7 / 218.6 |
| records | 100 | 2.008 | 1.593 | 10.245 | 1.26× | 1405.6 / 1403.8 / 918.1 |
| large_text | 100 | 0.476 | 0.558 | 0.238 | 0.85× | 419.6 / 418.7 / 418.6 |

## File parsing versus non-retaining callbacks

The same record fixture is opened as a binary file for both modes. File reads are timed; OS page-cache behavior is not controlled. Full-file mode retains the complete result. Streaming uses `item_depth=2` and a callback that retains only a few integer counters/checksums, never emitted items.

| Input MiB | Mode | PR #5 s | Standalone s | xmltodict s | Peak MiB: PR #5 / standalone / reference | Standalone current RSS MiB |
|---|---|---:|---:|---:|---:|---:|
| 10 | full_file | 0.914 | 1.106 | 0.956 | 88.6 / 88.8 / 87.6 | 88.9 |
| 10 | stream_file | 0.832 | 0.928 | 0.839 | 20.7 / 20.7 / 20.7 | 18.8 |
| 50 | full_file | 5.051 | 5.576 | 4.967 | 367.9 / 368.1 / 367.0 | 368.3 |
| 50 | stream_file | 4.203 | 4.740 | 4.082 | 20.7 / 20.7 / 20.7 | 18.8 |
| 100 | full_file | 10.168 | 11.849 | 9.891 | 717.2 / 717.3 / 716.1 | 717.5 |
| 100 | stream_file | 7.883 | 9.587 | 8.011 | 20.7 / 20.7 / 20.7 | 18.8 |

### Callback equality

| Input MiB | Callbacks per parser/process | All three parsers × three processes equal |
|---|---:|---|
| 10 | 59,614 | Yes |
| 50 | 298,071 | Yes |
| 100 | 596,143 | Yes |

Every callback parse returned `None`. The callback stored zero items. These measurements demonstrate incremental, non-retaining file parsing for this repeated-record shape. They do not establish constant memory for arbitrary documents, large individual text/items, deep nesting, or unbounded distinct names, nor do they claim that all parse paths avoid a native DOM. Full-result parsing must retain its output.

## Memory interpretation

- RSS is the native-aware whole-process peak (`ru_maxrss`, normalized to bytes); Linux current RSS and the pre-parse peak/current baseline are also stored. Python tracemalloc is never substituted for native memory.
- The baseline peak can contain input-loading transients or process-launch high-water marks. Small workloads and streaming runs can stay below that baseline, so equal peaks or zero incremental peak do not mean zero allocation.
- Full-string loading can briefly hold both bytes and decoded text. Those costs are excluded from timing but visible in baseline/whole-process RSS. Full-file measurements start with an open file, not the entire input in memory.
- RSS can include freed native allocator arenas; retained current RSS is not an exact sum of live output objects. Compare the same mode across implementations.
- Standard timings include output destruction, whereas large timings exclude it. Absolute timings from the two methods should not be directly combined.

## Raw results and reproducibility

- [standalone-intermediate-standard.json](standalone-intermediate-standard.json): all standard equality results, timing batches, RSS baselines/samples, tracemalloc and source/binary hashes.
- [standalone-intermediate-large-memory.json](standalone-intermediate-large-memory.json): all 108 large fresh-process samples, full fingerprints, callback summaries, resource checks and provenance.
- Harnesses: `standalone-benchmark.py`, `standalone-large-memory.py`, `standalone-common.py`; reused fixture/measurement code remains in `benchmark.py` and `upstream-large-memory.py`.

Create an exact PR #5 archive/worktree and a separate frozen copy of the standalone revision to compare. In one isolated Python 3.12 environment:

```sh
python -m pip install 'setuptools==84.0.0' 'wheel==0.48.0' 'setuptools-scm==8.3.1' 'xmltodict==1.0.4'
# BEFORE and AFTER point to the two source snapshots; PY is the same venv interpreter.
for ROOT in "$BEFORE" "$AFTER"; do
  (cd "$ROOT" && SETUPTOOLS_SCM_PRETEND_VERSION=0.1.dev0 CC=gcc CXX=g++ "$PY" setup.py build_ext --inplace --force)
done
"$PY" benchmarks/standalone-benchmark.py --before "$BEFORE" --after "$AFTER" --output benchmarks/standalone-standard.json
"$PY" benchmarks/standalone-large-memory.py --before "$BEFORE" --after "$AFTER" --output benchmarks/standalone-large-memory.json
```

The standalone tests, dependency-isolation checks and sanitizer evidence are separate from these benign performance measurements. This report makes no whole-platform compatibility or security claim.
