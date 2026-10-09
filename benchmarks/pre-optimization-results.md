# Measured results

Generated 2026-10-09T03:56:42Z; Python 3.12.14; xmltodict 0.14.2.

All primary comparisons below passed equality against xmltodict.parse defaults before timing. Times include the complete public parse call, validation, preprocessing, and output destruction. RSS is a whole-process peak, including native heaps and retained output. The paired RSS columns show rapidxmltodict / xmltodict.

| Workload | Input bytes | rapidxmltodict ms | xmltodict ms | Speedup | Peak RSS MiB | Incremental peak MiB |
|---|---:|---:|---:|---:|---:|---:|
| small | 1,077 | 0.024 | 0.123 | 5.07× | 19.74 / 18.87 | 0.12 / 0.12 |
| medium | 105,501 | 2.224 | 10.630 | 4.78× | 21.12 / 19.49 | 1.50 / 0.75 |
| large | 1,055,391 | 27.718 | 114.796 | 4.14× | 39.46 / 28.72 | 18.88 / 9.12 |
| unicode_mixed | 91,903 | 1.983 | 9.171 | 4.62× | 21.07 / 19.70 | 1.12 / 0.62 |
| deep | 900 | 0.033 | 0.231 | 6.98× | 19.74 / 18.87 | 0.12 / 0.12 |
| deep_fallback | 2,104 | 0.572 | 0.533 | 0.93× | 19.99 / 18.99 | 0.38 / 0.25 |
| medium_bytes | 105,501 | 2.224 | 11.129 | 5.00× | 20.99 / 19.49 | 1.38 / 0.75 |

Incremental peak is peak minus the post-import/input-load baseline high-water mark, not precise per-call allocation or retained memory. Small changes can round to zero. Native DOM construction can increase peak RSS despite fewer Python allocations. The JSON file includes baseline RSS, individual measurements, hashes, and supplemental tracemalloc values. These are synthetic single-machine results, not universal performance guarantees.
