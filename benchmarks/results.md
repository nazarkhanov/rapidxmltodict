# Measured results

Generated 2026-10-09T03:59:22Z; Python 3.12.14; xmltodict 0.14.2.

All primary comparisons below passed equality against xmltodict.parse defaults before timing. Times include the complete public parse call, validation, preprocessing, and output destruction. RSS is a whole-process peak, including native heaps and retained output. The paired RSS columns show rapidxmltodict / xmltodict.

| Workload | Input bytes | rapidxmltodict ms | xmltodict ms | Speedup | Peak RSS MiB | Incremental peak MiB |
|---|---:|---:|---:|---:|---:|---:|
| small | 1,077 | 0.026 | 0.134 | 5.09× | 19.75 / 18.88 | 0.12 / 0.12 |
| medium | 105,501 | 2.166 | 11.383 | 5.26× | 20.75 / 19.50 | 1.12 / 0.75 |
| large | 1,055,391 | 26.866 | 120.036 | 4.47× | 35.75 / 28.75 | 15.25 / 9.00 |
| unicode_mixed | 91,903 | 2.035 | 9.728 | 4.78× | 21.10 / 19.72 | 1.12 / 0.62 |
| deep | 900 | 0.034 | 0.237 | 6.97× | 19.88 / 18.88 | 0.25 / 0.12 |
| deep_fallback | 2,104 | 0.549 | 0.523 | 0.95× | 20.00 / 19.00 | 0.38 / 0.25 |
| medium_bytes | 105,501 | 2.025 | 10.574 | 5.22× | 20.62 / 19.50 | 1.00 / 0.75 |

Incremental peak is peak minus the post-import/input-load baseline high-water mark, not precise per-call allocation or retained memory. Small changes can round to zero. Native DOM construction can increase peak RSS despite fewer Python allocations. The JSON file includes baseline RSS, individual measurements, hashes, and supplemental tracemalloc values. These are synthetic single-machine results, not universal performance guarantees.

## Baseline whole-process peak RSS

Before the measured parse, after importing the parser and loading the input:

| Workload | rapidxmltodict baseline MiB | xmltodict baseline MiB |
|---|---:|---:|
| small | 19.62 | 18.75 |
| medium | 19.62 | 18.75 |
| large | 20.50 | 19.75 |
| unicode_mixed | 19.98 | 19.10 |
| deep | 19.62 | 18.75 |
| deep_fallback | 19.62 | 18.75 |
| medium_bytes | 19.62 | 18.75 |

## Optional JSON round trip

Only output-equivalent fixtures are measured below. This calls `json.loads(rapidxmltojson.parse(xml))`; it does not establish general semantic compatibility. Unicode/mixed input is excluded for different whitespace semantics; bytes input is omitted.

| Workload | JSON round-trip ms | Peak RSS MiB |
|---|---:|---:|
| small | 0.019 | 18.68 |
| medium | 2.461 | 20.30 |
| large | 26.885 | 42.68 |
| deep | 0.028 | 18.68 |
| deep_fallback | 0.063 | 18.68 |
