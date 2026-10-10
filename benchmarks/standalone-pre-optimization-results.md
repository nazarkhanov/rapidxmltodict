# Initial standalone benchmark, before name-cache optimization

Same-host comparison of exact PR #5 commit `f5ae82c43ba445a52932432198a559b319b67188`, standalone commit `7a735598a7464284eb2434b2bf71a1eedb35a7a3`, and xmltodict 1.0.4. Historical upstream benchmark reports are unchanged.

This is historical pre-optimization evidence. Use `standalone-results.md` for the final candidate once that run is available. All tracked implementation files were verified byte-for-byte against the recorded candidate commit.

## Scope and method

- Recorded 2026-10-09T16:17:38Z on AMD EPYC 9V74 80-Core Processor; CPython 3.12.14, Linux x86-64, G++ 14.2.0, C++17 / `-O3`.
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
| small | 0.0181 | 0.0124 | 0.0856 | 1.46× | 6.90× |
| medium | 1.6049 | 1.3061 | 8.0472 | 1.23× | 6.16× |
| large | 18.1832 | 14.1113 | 82.6453 | 1.29× | 5.86× |
| unicode_mixed | 1.5840 | 1.8457 | 6.9517 | 0.86× | 3.77× |
| deep | 0.0244 | 0.0218 | 0.1947 | 1.12× | 8.93× |
| deep_fallback | 0.4574 | 0.6423 | 0.4172 | 0.71× | 0.65× |
| medium_bytes | 1.5392 | 1.2280 | 7.9591 | 1.25× | 6.48× |

`deep_fallback` preserves the historical fixture name: depth 300 used xmltodict fallback in PR #5; standalone handles it with its own event path.

### Standard whole-process peak RSS

| Workload | PR #5 MiB | Standalone MiB | xmltodict MiB |
|---|---:|---:|---:|
| small | 20.12 | 20.12 | 20.12 |
| medium | 20.12 | 20.12 | 20.12 |
| large | 33.39 | 32.30 | 27.52 |
| unicode_mixed | 20.14 | 20.12 | 20.12 |
| deep | 20.12 | 20.12 | 20.12 |
| deep_fallback | 20.12 | 20.12 | 20.12 |
| medium_bytes | 20.12 | 20.12 | 20.12 |

## 10 / 50 / 100 MiB full-string parsing

Times below include full default public parsing and validation, with the UTF-8 Python string loaded before timing. A full dictionary is retained at the RSS sample.

| Shape | Input MiB | PR #5 s | Standalone s | xmltodict s | PR #5 / standalone speedup | Peak MiB: PR #5 / standalone / reference |
|---|---:|---:|---:|---:|---:|---:|
| records | 10 | 0.187 | 0.155 | 0.884 | 1.20× | 158.1 / 157.2 / 109.1 |
| large_text | 10 | 0.060 | 0.053 | 0.028 | 1.15× | 60.6 / 58.7 / 59.6 |
| records | 50 | 1.067 | 0.787 | 4.898 | 1.36× | 713.2 / 711.3 / 468.8 |
| large_text | 50 | 0.248 | 0.236 | 0.118 | 1.05× | 219.6 / 218.7 / 218.6 |
| records | 100 | 1.976 | 1.644 | 10.037 | 1.20× | 1405.6 / 1403.7 / 918.1 |
| large_text | 100 | 0.497 | 0.513 | 0.250 | 0.97× | 419.6 / 418.7 / 418.6 |

## File parsing versus non-retaining callbacks

The same record fixture is opened as a binary file for both modes. File reads are timed; OS page-cache behavior is not controlled. Full-file mode retains the complete result. Streaming uses `item_depth=2` and a callback that retains only a few integer counters/checksums, never emitted items.

| Input MiB | Mode | PR #5 s | Standalone s | xmltodict s | Peak MiB: PR #5 / standalone / reference | Standalone current RSS MiB |
|---|---|---:|---:|---:|---:|---:|
| 10 | full_file | 0.968 | 1.308 | 0.903 | 88.6 / 102.5 / 87.7 | 102.7 |
| 10 | stream_file | 0.799 | 1.144 | 0.875 | 20.9 / 20.9 / 20.9 | 18.8 |
| 50 | full_file | 5.040 | 6.669 | 4.964 | 367.9 / 436.6 / 366.9 | 436.8 |
| 50 | stream_file | 4.170 | 5.592 | 4.090 | 20.9 / 20.9 / 20.9 | 18.8 |
| 100 | full_file | 10.204 | 13.003 | 10.260 | 717.1 / 854.4 / 716.2 | 854.5 |
| 100 | stream_file | 8.124 | 11.242 | 8.148 | 20.9 / 20.9 / 20.9 | 18.8 |

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

- [standalone-pre-optimization-standard.json](standalone-pre-optimization-standard.json): all standard equality results, timing batches, RSS baselines/samples, tracemalloc and source/binary hashes.
- [standalone-pre-optimization-large-memory.json](standalone-pre-optimization-large-memory.json): all 108 large fresh-process samples, full fingerprints, callback summaries, resource checks and provenance.
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
