# Reproducible default-API benchmark

This benchmark compares actual `rapidxmltodict.parse(xml)` and
`xmltodict.parse(xml)` calls with **no parsing options**. It checks dictionary
value equality before timing each workload and refuses to time a primary
comparison if the outputs differ. All validation, native conversion, fallback
checks, UTF-8 preprocessing, and output destruction are inside the timed call.
File loading, fixture generation, module import, warmup, and calibration are
outside timing.

See [`results.md`](results.md) for the final measured summary and
[`results.json`](results.json) for complete raw timing and memory measurements.
`pre-optimization-results.*` preserve the full stable run before the compact-DOM
optimization. Only `results.*` describe the final candidate. Implementation and
native binary hashes in each JSON identify the measured source, and
`implementation_unchanged_during_run` confirms the source remained stable.

## Final measured summary

On the recorded machine, the six native-path workloads were 4.47–6.97× faster
than xmltodict, with equality checked first. The three catalog sizes measured
5.09×, 5.26×, and 4.47×. The depth-300 compatibility fallback measured 0.95×,
so fallback inputs should not be advertised as accelerated.

For the 1,055,391-byte catalog, the final implementation used 35.75 MiB whole-
process peak RSS versus 28.75 MiB for xmltodict. Compact-DOM construction reduced
rapidxmltodict's own pre-optimization peak from 39.46 to 35.75 MiB (9.4%) and
incremental peak from 18.875 to 15.25 MiB (19.2%), but its total memory still
exceeded xmltodict. These results support a speed improvement and a bounded
native-memory improvement, not a claim of lower memory than xmltodict.

The same large fixture's equal-output JSON-round-trip comparison measured
26.89 ms and 42.68 MiB, versus 26.87 ms and 35.75 MiB for rapidxmltodict. These
timings are effectively similar within the observed variation.

## Reproduce

Reference versions:

- CPython 3.12.14, Linux x86-64 (the recorded environment)
- xmltodict 0.14.2
- rapidxmltodict 0.1.0, built from this checkout
- rapidxmltojson 0.2.5 from commit
  `ed40f6bb23a262a26a50653698184541c89f3b50`, optional comparison with a JSON
  round trip. The commit includes the repaired native parser; the version string
  alone does not distinguish it from earlier builds.
- GCC/G++ 14.2.0, C++17, `-O3` (recorded native extension)

From the repository root, in an environment with Python development headers and
GCC/G++ available:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install 'setuptools>=77' wheel
.venv/bin/python -m pip install 'xmltodict==0.14.2'
# Optional; the main direct-dictionary benchmark works without this package.
.venv/bin/python -m pip install 'git+https://github.com/nazarkhanov/rapidxmltojson.git@ed40f6bb23a262a26a50653698184541c89f3b50'
CC=gcc CXX=g++ .venv/bin/python setup.py build_ext --inplace
PYTHONPATH="$PWD/src" .venv/bin/python benchmarks/benchmark.py
```

Exact command used in the supplied workspace:

```sh
PYTHONPATH=/workspace/shared/rapidxmltodict/src \
  /workspace/shared/rapidxml-benchmark/venv/bin/python \
  /workspace/shared/rapidxmltodict/benchmarks/benchmark.py \
  --output /workspace/shared/rapidxmltodict/benchmarks/results.json
```

The reference dependencies are also listed in `requirements.txt`. Build tooling
is not runtime code; raw results record the runtime, operating system, CPU,
compiler, package versions, arguments, native/source hashes, and fixture hashes.
The suite needs the Unix `resource` module. On Linux, it pins execution to the
lowest currently allowed CPU; other programs can still contend for that CPU.

For a short development check rather than final numbers:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python benchmarks/benchmark.py \
  --output benchmarks/quick-results.json \
  --timing-processes 1 --memory-processes 3 --samples 5 --batch-seconds 0.04
```

Use `--only small,medium,large` to select workloads. All fixture files are generated
deterministically by the script under `benchmarks/fixtures/`; no external dataset
or network request is involved.

## Workloads

- `small`, `medium`, `large`: 6, 600, and 6,000 catalog records, approximately
  1 KiB, 102 KiB, and 1 MiB. IDs, prices, names, and inventory vary deterministically.
  Includes attributes, text, nested dictionaries, sibling lists, and `&amp;`.
- `unicode_mixed`: 500 records with accented Latin, CJK, emoji, whitespace,
  mixed text/child elements, CDATA, empty tags, whitespace-only values, and
  numeric-looking strings.
- `deep`: 128 nested elements, within the native depth bound.
- `deep_fallback`: 300 nested elements, above the native depth bound. This
  intentionally measures the compatibility fallback and its overhead.
- `medium_bytes`: the same records as `medium`, supplied as UTF-8 bytes rather
  than a Python string. The main string workloads include string encoding cost.

These are synthetic workloads, not a compatibility proof or a representative
sample of every user's documents. See the separate test suite for correctness.

## Timing method

For each library and workload, the full run starts three fresh subprocesses,
with three warmup and three calibration calls each. Each process measures nine
batches targeting 100 ms. The headline is the median per-call time of all 27
batches. Individual values, batch lengths, and min/max are retained in JSON.
Garbage collection remains enabled. Results are destroyed between calls.
Library order is shuffled reproducibly with seed `20261009`.

`rapidxmltojson.parse(xml)` alone produces JSON, so it is **not** a direct-dict
comparison. The optional comparator is `json.loads(rapidxmltojson.parse(xml))`,
and its conversion costs are included. It is measured only when its complete
output equals `xmltodict.parse` on that workload. Its Unicode/mixed-content
whitespace behavior differs here, so that comparison is explicitly omitted.
The optional comparator is also omitted for bytes input. A matching result on
one fixture does not imply global semantic compatibility.

## Memory method and interpretation

Memory is measured separately from timing and separately from tracemalloc. Each
library/workload gets five fresh subprocesses. Each loads the input and imports
the parser, collects garbage, records its baseline RSS/high-water mark, parses
once, and holds the resulting dictionary alive while recording peak RSS.

- `peak_rss_bytes`: whole-process `resource.getrusage(...).ru_maxrss`, including
  Python objects, the native RapidXML DOM, native buffers/heaps, imports, and input.
  Linux KiB and macOS byte units are normalized to bytes.
- `baseline_peak_rss_bytes`: high-water mark immediately before the parse.
- `baseline_current_rss_bytes`: Linux `/proc/self/status` current RSS before parsing.
- `incremental_peak_rss_bytes`: final peak minus the baseline high-water mark.
  This is an estimate, not exact allocation or retained memory. Startup peaks,
  allocator reuse, measurement granularity, and inherited pre-exec high-water
  marks can hide small increments. Zero does **not** mean no allocation.
- `retained_output_current_rss_bytes`: Linux current RSS after parsing, with the
  result still alive. The allocator can retain freed native arenas.
- `python_traced_peak_bytes`: separate supplemental tracemalloc peak. This does
  **not** measure untraced C++ allocations or whole-process native memory.

Reported memory values are medians of independent processes. Native DOM parsing
can use **more peak RSS** than the SAX-style xmltodict parser despite being faster
and despite using fewer Python-visible allocations. Do not infer lower memory
use from lower runtime or tracemalloc values.
