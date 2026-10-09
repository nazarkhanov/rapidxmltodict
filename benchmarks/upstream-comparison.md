# RapidXML 1.13 migration: same-environment benchmark

Measured on 2026-10-09. The existing default-public-API benchmark was run against
the pre-migration source and the migration candidate in isolated worktrees, using
the same pinned Python environment. All seven workloads passed full dictionary
value equality against xmltodict before either version was timed.

## Result

The large (1,055,391-byte) catalog's median whole-process peak RSS decreased from
35.85 to 34.22 MiB
(-4.5%); incremental peak decreased from
15.250 to 13.625 MiB.
Its median parse time changed from 18.73 to 19.33 ms
(+3.2%). Timing changes below are descriptive single-machine
measurements, not statistically established regressions or improvements. The
candidate remains substantially faster than xmltodict on the native-path
workloads. The depth-300 compatibility fallback was slower in both orders:
+12.3% initially and +6.5% in the reversed repeat (about 0.44–0.46 ms before versus
0.49 ms after). This is an observed fallback performance concern; its cause was
not isolated. There is no claim that this migration is faster on every workload.

### Parse time

Times include the complete default public parse call, validation, preprocessing,
conversion and output destruction. Negative change means faster after migration.

| Workload | Before ms | After ms | Time change | After vs xmltodict |
|---|---:|---:|---:|---:|
| small | 0.01784 | 0.01718 | -3.7% | 5.00× |
| medium | 1.64078 | 1.59216 | -3.0% | 5.23× |
| large | 18.72529 | 19.32763 | +3.2% | 4.35× |
| unicode_mixed | 1.49559 | 1.37879 | -7.8% | 4.80× |
| deep | 0.02653 | 0.02592 | -2.3% | 7.04× |
| deep_fallback | 0.43531 | 0.48892 | +12.3% | 0.84× |
| medium_bytes | 1.57410 | 1.40020 | -11.0% | 5.52× |

### Native-aware memory

These are median whole-process peak RSS values from five fresh processes per
version/workload. They include imports, input, Python objects and native heaps,
with the result held alive. Incremental peak is the final high-water mark minus
the post-import/input-load high-water mark. It is not exact allocation or retained
memory; allocator reuse, page granularity and startup peaks matter. Changes of a
few KiB should not be treated as a meaningful memory improvement.

| Workload | Before peak MiB | After peak MiB | Peak change MiB | Incremental before / after MiB |
|---|---:|---:|---:|---:|
| small | 19.844 | 19.840 | -0.004 | 0.125 / 0.125 |
| medium | 20.844 | 20.715 | -0.129 | 1.125 / 1.000 |
| large | 35.848 | 34.223 | -1.625 | 15.250 / 13.625 |
| unicode_mixed | 21.129 | 21.000 | -0.129 | 1.000 / 0.875 |
| deep | 19.844 | 19.840 | -0.004 | 0.125 / 0.125 |
| deep_fallback | 20.090 | 20.094 | +0.004 | 0.375 / 0.375 |
| medium_bytes | 20.715 | 20.594 | -0.121 | 1.000 / 0.875 |

Memory is not universally lower than xmltodict: on the large workload, its
reference median whole-process peak was 28.71 MiB in both passes, below both
rapidxmltodict builds. Supplemental tracemalloc samples are in the raw results;
they exclude untraced C++ allocations and are not a substitute for RSS.

### xmltodict timing control

The unchanged xmltodict reference was measured independently alongside each
version. Its variation illustrates why these timing differences should be read
cautiously.

| Workload | With before ms | With after ms | Change |
|---|---:|---:|---:|
| small | 0.08494 | 0.08589 | +1.1% |
| medium | 7.99867 | 8.32215 | +4.0% |
| large | 86.01927 | 84.07936 | -2.3% |
| unicode_mixed | 6.73507 | 6.61426 | -1.8% |
| deep | 0.18069 | 0.18259 | +1.1% |
| deep_fallback | 0.41125 | 0.41301 | +0.4% |
| medium_bytes | 8.13030 | 7.72585 | -5.0% |

### Reverse-order timing check

The initial pass showed higher median times for the large catalog and depth-300
fallback. These same two existing workloads were repeated using the same default
settings, with **after then before** order
for each workload. Initial measurements above are retained unchanged, alongside
all repeat samples under `supplemental_reverse_order_runs` in the raw JSON.

| Workload | Repeat before ms | Repeat after ms | Time change | Peak RSS before / after MiB |
|---|---:|---:|---:|---:|
| deep_fallback | 0.45570 | 0.48534 | +6.5% | 20.090 / 20.094 |
| large | 19.04819 | 18.93033 | -0.6% | 35.848 / 34.223 |

The large-catalog timing difference changes sign across passes, while its
1.625 MiB peak-RSS reduction repeats. The fallback timing difference remains
positive. The unchanged xmltodict control moved +0.4% in the initial pass and
+2.7% in the reversed repeat, which does not fully explain the fallback difference.
Its path returns before RapidXML document construction, so these
measurements alone cannot attribute that difference to upstream XML parsing.

## Method and provenance

- Before: commit `98e7367fa91b7703eeebd160a6090350c821ed0d` (pre-migration main).
- After: that same commit plus upstream RapidXML 1.13, the `element_key` wrapper
  adaptation, and a behavior-neutral Python wrapper comment update. The complete
  measured source and binary SHA-256 values are in the raw JSON.
- Upstream: [official RapidXML 1.13 archive](https://sourceforge.net/projects/rapidxml/files/rapidxml/rapidxml%201.13/rapidxml-1.13.zip/download).
  Archive SHA-256: `c3f0b886374981bb20fabcf323d755db4be6dba42064599481da64a85f5b3571`.
  Measured upstream header SHA-256:
  `d61c53fd63f11aef0e18d253746ee800903dc82e4ad3cc533d0fdca69f07c4f9`.
- Runtime: CPython 3.12.14, Linux x86-64; xmltodict **0.14.2**. The dedicated
  comparison environment remained pinned throughout.
- CPU: AMD EPYC 9V74 80-Core Processor; every benchmark process pinned to logical CPU
  0. The machine was not exclusively reserved.
- Native compiler: GCC/G++ 14.2.0. Identical C++17 / `-O3` compile and linker flags
  for both builds; complete invocations are retained in the JSON build logs.
  Build tools: setuptools 84.0.0, setuptools-scm 8.3.1, wheel 0.48.0.
- Unmodified `benchmarks/benchmark.py`, SHA-256
  `38ff9389da978b21b0f97a8cecff489c4c6a2605cfc7e6c3c49402fa3eed34e1`. All seven deterministic synthetic fixtures are
  identical before/after, with byte counts and hashes in JSON.
- Order: before then after for `small`, then before/after for `medium`, `large`,
  `unicode_mixed`, `deep`, `deep_fallback`, and `medium_bytes`. Runs were serial;
  libraries within each workload used the harness's seeded shuffled order.
- Default settings: three fresh timing processes × nine batches targeting 100 ms,
  three warmups and three calibration calls per process; five fresh RSS processes;
  separate tracemalloc process. Garbage collection enabled. Import, fixture
  generation/loading, warmup and calibration excluded from timing.
- Headline timing is the median of all 27 batches per version/workload. These
  batches are clustered within three processes, not 27 independent experiments.
  Process medians and every batch/RSS sample are retained. No confidence interval
  or universal performance claim is made, and execution-order drift is possible.
- Source and binary hashes remained unchanged during all runs. The two local
  source imports were verified to resolve to their respective isolated worktrees.
  The optional rapidxmltojson comparator was not installed; rapidxmltodict's
  distribution-version field is null because these are local in-place builds.

## Raw measurements

[`upstream-comparison.json`](upstream-comparison.json) includes source provenance,
full compiler logs, computed comparison statistics and all fourteen original
per-workload benchmark JSON results unchanged under
`versions.before.workload_runs` and `versions.after.workload_runs`. Four additional
complete benchmark results are retained under `supplemental_reverse_order_runs`.
Each original
result includes environment/arguments, equality checks, fixture/source/native
hashes, all timing/RSS samples and supplemental tracemalloc measurements.
The existing historical `results.*` and `pre-optimization-results.*` are unchanged.

## Reproduce

Use separate checkouts for the baseline commit above and this migration PR.
Set the three paths below to those checkouts and a new, dedicated virtualenv;
do not share that environment with tests that change dependency versions.

```sh
BASELINE=/absolute/path/to/pre-migration-checkout
CANDIDATE=/absolute/path/to/migration-checkout
VENV=/absolute/path/to/new-comparison-venv
python3.12 -m venv "$VENV"
"$VENV/bin/python" -m pip install \
  'setuptools==84.0.0' 'setuptools-scm==8.3.1' \
  'wheel==0.48.0' 'xmltodict==0.14.2'
for tree in "$BASELINE" "$CANDIDATE"; do
  (cd "$tree" && CC=gcc CXX=g++ \
    "$VENV/bin/python" setup.py build_ext --inplace --force)
done
for workload in small medium large unicode_mixed deep deep_fallback medium_bytes; do
  for tree in "$BASELINE" "$CANDIDATE"; do
    (cd "$tree" && PYTHONPATH="$tree/src" "$VENV/bin/python" \
      benchmarks/benchmark.py --only "$workload" \
      --output "benchmarks/upstream-$workload.json")
  done
done
```

The additional reverse-order check used the same benchmark command and defaults
for `deep_fallback` and then `large`, running the candidate first and baseline
second, with separate `repeat-` output filenames.

The commands retain a separate raw JSON and generated summary per workload in
each checkout. Run on the same idle machine with the same runtime/compiler for
both versions; compare the per-library `summary` values and retain individual
samples. These synthetic inputs assess this migration's measured performance,
not compatibility for every XML document or parser memory safety.
