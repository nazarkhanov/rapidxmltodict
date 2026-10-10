# Pre-optimization native event prototype: build3 smoke comparison

Archived development result, not the final full benchmark. This smoke check uses one worker per variant/workload, three short standard batches, a seven-case standard subset, and 10 MiB large inputs only. It documents the initial native mapper regression before optimization.

These are private architecture experiments. The native-event entry point is explicitly selected; its numbers are not a claim about the public default dispatcher.

- Completed measurement workers: **52** across **13** workloads; every requested sample completed: **True**.
- Host CPU: AMD EPYC 9V74 80-Core Processor; CPU affinity: [8].
- Python: 3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ].
- Compiler: g++ (Debian 14.2.0-19) 14.2.0.
- Reference: xmltodict 1.0.4; expat_2.8.3.
- Baseline commit: `e911c9a5dbdc75974e66120861adc38dc36a39b8`.
- Iterative DOM commit: `cfe17cce26076a1e1fd94228ed271ef4fc22929d`.
- Each input is generated once outside measured workers. Exact fixture/source/extension hashes, sample order, individual timings and RSS values are included in the raw files.
- Original standalone reports and their prior four-way baseline comparisons are preserved separately; their numbers are not substituted for freshly measured samples here.

## Main findings

- The late-deep case after 60,000 siblings is 6.92× faster with iterative DOM and 1.26× faster with native events than the current baseline. Avoiding abandoned DOM work and a second parse is the major deep-input improvement.

## What is being compared

| Variant | Exact entry point | Implementation |
|---|---|---|
| e911 baseline | `rapidxmltodict:parse` | Current integrated e911 baseline public parse; existing depth limit may trigger a second event parse. |
| Iterative DOM/default | `rapidxmltodict:parse` | Iterative DOM/default public parse: iterative DOM for default in-memory str/bytes, existing Python event mapping for file/callback/options. |
| Native events | `rapidxmltodict._parse:_parse_native_events` | Private direct native-event dictionary mapper, forced via the recorded wrapper entry point. |
| xmltodict 1.0.4 | `xmltodict:parse` | Unmodified xmltodict 1.0.4 public parse, Expat reference. |

The iterative DOM/default variant still uses its existing Python event mapper for file and callback inputs. Those rows compare that snapshot’s actual public behavior; they are not measurements of a DOM streaming implementation.

## Method and caveats

- Fresh workers per parser/workload: [1]. All workers use the same CPU, interpreter, GC setting and PYTHONHASHSEED=0. Parser order rotates by workload and trial.
- Standard timings: 3 warmups, 3 calibration parses, then 3 calibrated batches per worker targeting 0.03 seconds each. Result destruction is timed. RSS comes from the first parse before those batches.
- Large timings: one complete parse per fresh worker, with result destruction excluded. String input is loaded before timing; file reads are included. No OS page-cache eviction is performed, so file results are not cold-storage throughput measurements. Outputs remain alive at the RSS sample.
- Peak RSS is the entire process high-water mark. Both incremental views are shown: peak minus the pre-parse current RSS and peak minus the previous high-water RSS. Retained RSS is current process RSS with input and output alive, not an isolated output allocation count. Input-loading transients can reduce the reported incremental growth. Current RSS and ru_maxrss are separately sampled Linux accounting values and can disagree slightly at page-scale granularity.
- All direct outputs are validated using a complete typed iterative SHA-256 traversal. It preserves list order and string contents without recursion-limit adjustments. Separate unmeasured callback passes hash every emitted path and item. Timed callbacks only compute identical count/order/identifier checksums.
- Discard callbacks retain no item objects. Retaining callbacks keep every item in a list until sampling; this intentionally demonstrates that callback APIs do not make retained application data constant-memory.
- File inputs can reduce input-buffer retention. Native event mapping can avoid an intermediate DOM, but a complete result still grows with the output size. Large text and application-retained callback outputs remain inherently large. The record fixtures repeat a fixed small name vocabulary: flat discard-callback RSS here does not prove constant memory for arbitrary XML; name/entity tables, document vocabulary and nesting can also grow.
- This is a single-host microbenchmark, not a universal performance guarantee. Absolute timings and trial spread are provided; small differences should not be overinterpreted.
- The frozen baseline preserves its existing binary and exact on-disk sources. The previously disclosed CRLF/LF vendor-header difference from Git remains separately accounted for by exact hashes; baseline timings are not relabeled as a different source build.

## Standard and deep-input timings

Times are medians in milliseconds across all batches. A ratio above 1 means the candidate was faster than the current baseline.

| Workload | Baseline ms | Iterative ms | Events ms | xmltodict ms | Iterative vs baseline | Events vs baseline |
|---|---:|---:|---:|---:|---:|---:|
| small | 0.014 | 0.013 | 0.101 | 0.098 | 1.08× | 0.14× |
| medium | 1.191 | 1.098 | 12.595 | 8.736 | 1.08× | 0.09× |
| large | 12.697 | 12.307 | 89.277 | 88.762 | 1.03× | 0.14× |
| unicode_mixed | 1.086 | 1.004 | 7.239 | 6.840 | 1.08× | 0.15× |
| deep_300 | 0.628 | 0.042 | 0.540 | 0.392 | 15.10× | 1.16× |
| deep_10000 | 18.662 | 2.093 | 18.520 | 20.493 | 8.92× | 1.01× |
| late_deep_60000_siblings | 690.197 | 99.699 | 547.145 | 576.290 | 6.92× | 1.26× |

The full fixture suite includes 128, 300, 1,500 and 10,000 nested elements; only measured cases appear in the table. Late-deep workloads place a 1,500-element branch after 6,000 or 60,000 completed shallow siblings, exposing abandoned-DOM-and-reparse work in the baseline. All output fingerprints must match the oracle.

## Large-input timings

Times are median seconds from complete parses in fresh processes.

| Workload | Baseline s | Iterative s | Events s | xmltodict s | Events vs baseline |
|---|---:|---:|---:|---:|---:|
| records_10mib_direct_str | 0.174 | 0.148 | 0.824 | 0.842 | 0.21× |
| records_10mib_direct_file | 1.032 | 0.945 | 0.879 | 0.941 | 1.17× |
| records_10mib_callback_file_discard | 0.897 | 0.948 | 0.849 | 0.778 | 1.06× |
| records_10mib_callback_file_retain | 0.953 | 1.006 | 0.934 | 0.892 | 1.02× |
| large_text_10mib_direct_str | 0.025 | 0.024 | 0.079 | 0.026 | 0.32× |
| large_text_10mib_direct_file | 0.076 | 0.077 | 0.070 | 0.030 | 1.09× |

## Total and incremental peak RSS

Each cell is **total peak / peak minus pre-parse current RSS / peak minus prior high-water RSS**, in MiB. Both deltas are clamped at zero and calculated per sample before taking medians. They use the same measured peak; the current-baseline delta does not hide input-loading transients in a previous peak. Neither delta is a precise attribution of parser-only allocations.

| Workload | Baseline MiB | Iterative MiB | Events MiB | xmltodict MiB |
|---|---:|---:|---:|---:|
| small | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.8 / 0.0 / 0.1 | 20.2 / 0.6 / 0.0 |
| medium | 21.3 / 0.7 / 0.8 | 21.3 / 0.7 / 0.8 | 21.3 / 0.7 / 0.8 | 20.4 / 0.8 / 0.1 |
| large | 33.9 / 12.2 / 11.3 | 33.8 / 12.2 / 11.3 | 32.6 / 11.0 / 10.1 | 29.4 / 8.8 / 7.9 |
| unicode_mixed | 21.4 / 0.5 / 0.5 | 21.4 / 0.5 / 0.5 | 21.6 / 0.6 / 0.6 | 20.5 / 0.5 / 0.2 |
| deep_300 | 20.9 / 0.3 / 0.4 | 20.6 / 0.0 / 0.0 | 20.7 / 0.1 / 0.1 | 20.2 / 0.6 / 0.0 |
| deep_10000 | 24.3 / 3.7 / 3.8 | 23.9 / 3.3 / 3.4 | 23.6 / 3.0 / 3.0 | 24.2 / 4.6 / 4.0 |
| late_deep_60000_siblings | 99.1 / 72.5 / 66.5 | 108.4 / 81.7 / 75.8 | 92.9 / 66.3 / 60.3 | 75.6 / 50.0 / 44.1 |
| records_10mib_direct_str | 158.5 / 127.9 / 117.9 | 158.5 / 127.9 / 117.9 | 140.4 / 109.7 / 99.8 | 110.9 / 81.3 / 71.4 |
| records_10mib_direct_file | 90.6 / 69.9 / 70.0 | 90.6 / 69.9 / 70.0 | 90.7 / 70.1 / 70.1 | 89.6 / 70.0 / 69.4 |
| records_10mib_callback_file_discard | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.7 / 0.1 / 0.1 | 20.2 / 0.6 / 0.0 |
| records_10mib_callback_file_retain | 90.6 / 70.0 / 70.0 | 90.6 / 69.9 / 70.0 | 90.7 / 70.1 / 70.1 | 89.6 / 70.0 / 69.4 |
| large_text_10mib_direct_str | 60.5 / 29.9 / 19.9 | 60.5 / 29.9 / 19.9 | 90.6 / 60.0 / 50.0 | 61.6 / 31.9 / 22.1 |
| large_text_10mib_direct_file | 40.1 / 19.4 / 19.5 | 40.0 / 19.4 / 19.5 | 40.1 / 19.4 / 19.5 | 38.9 / 19.3 / 18.6 |

## Pre-parse RSS baselines

Each cell is **current RSS / prior high-water RSS**, in MiB, after imports and input loading/opening and before parsing. These are the two baselines used above.

| Workload | Baseline MiB | Iterative MiB | Events MiB | xmltodict MiB |
|---|---:|---:|---:|---:|
| small | 20.6 / 20.6 | 20.6 / 20.6 | 20.8 / 20.7 | 19.6 / 20.2 |
| medium | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| large | 21.6 / 22.6 | 21.6 / 22.6 | 21.6 / 22.6 | 20.6 / 21.5 |
| unicode_mixed | 20.9 / 20.9 | 20.9 / 20.9 | 21.0 / 20.9 | 19.9 / 20.2 |
| deep_300 | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| deep_10000 | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| late_deep_60000_siblings | 26.6 / 32.6 | 26.6 / 32.6 | 26.6 / 32.6 | 25.6 / 31.5 |
| records_10mib_direct_str | 30.6 / 40.6 | 30.6 / 40.6 | 30.6 / 40.6 | 29.6 / 39.5 |
| records_10mib_direct_file | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| records_10mib_callback_file_discard | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| records_10mib_callback_file_retain | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| large_text_10mib_direct_str | 30.6 / 40.6 | 30.6 / 40.6 | 30.6 / 40.5 | 29.6 / 39.5 |
| large_text_10mib_direct_file | 20.6 / 20.6 | 20.6 / 20.5 | 20.6 / 20.6 | 19.6 / 20.2 |

## Retained RSS and current-baseline increase

Each cell is **retained current RSS / retained minus pre-parse current RSS**, in MiB. The increase is signed. Inputs and results/application-retained callback items remain alive; this is whole-process memory, not output-object size alone.

| Workload | Baseline MiB | Iterative MiB | Events MiB | xmltodict MiB |
|---|---:|---:|---:|---:|
| small | 20.6 / 0.0 | 20.7 / 0.0 | 21.0 / 0.2 | 19.7 / 0.1 |
| medium | 21.3 / 0.7 | 21.3 / 0.7 | 21.5 / 0.9 | 20.4 / 0.8 |
| large | 29.1 / 7.5 | 29.2 / 7.6 | 30.8 / 9.2 | 27.7 / 7.1 |
| unicode_mixed | 21.5 / 0.5 | 21.5 / 0.5 | 21.6 / 0.6 | 20.5 / 0.6 |
| deep_300 | 21.0 / 0.4 | 20.7 / 0.1 | 20.8 / 0.2 | 19.8 / 0.2 |
| deep_10000 | 24.1 / 3.5 | 23.3 / 2.7 | 23.4 / 2.8 | 24.3 / 4.7 |
| late_deep_60000_siblings | 99.2 / 72.5 | 102.5 / 75.9 | 93.0 / 66.3 | 75.7 / 50.1 |
| records_10mib_direct_str | 148.6 / 118.0 | 148.6 / 118.0 | 140.5 / 109.9 | 111.0 / 81.4 |
| records_10mib_direct_file | 90.7 / 70.0 | 90.7 / 70.1 | 90.8 / 70.2 | 89.7 / 70.1 |
| records_10mib_callback_file_discard | 20.7 / 0.0 | 20.7 / 0.0 | 20.8 / 0.2 | 19.7 / 0.1 |
| records_10mib_callback_file_retain | 90.6 / 70.0 | 90.7 / 70.0 | 90.8 / 70.2 | 89.7 / 70.1 |
| large_text_10mib_direct_str | 50.5 / 19.9 | 50.5 / 19.9 | 90.7 / 60.1 | 61.6 / 32.0 |
| large_text_10mib_direct_file | 30.7 / 10.1 | 30.7 / 10.1 | 30.8 / 10.2 | 29.7 / 10.1 |

## Trial range

Minimum–maximum milliseconds across measured standard batches or large fresh-process parses. These are descriptive ranges, not confidence intervals.

| Workload | Baseline | Iterative | Events | xmltodict |
|---|---:|---:|---:|---:|
| small | 0.013–0.014 | 0.012–0.013 | 0.098–0.125 | 0.090–0.109 |
| medium | 1.189–1.227 | 1.092–1.111 | 12.121–13.861 | 8.693–9.898 |
| large | 12.545–15.559 | 11.904–12.311 | 87.562–89.629 | 82.973–95.584 |
| unicode_mixed | 1.017–1.106 | 0.919–1.017 | 7.235–7.385 | 6.767–7.894 |
| deep_300 | 0.624–0.649 | 0.041–0.042 | 0.495–0.602 | 0.389–0.392 |
| deep_10000 | 17.380–19.047 | 2.089–2.250 | 18.287–18.573 | 18.238–25.390 |
| late_deep_60000_siblings | 683.899–730.276 | 98.630–101.148 | 538.266–566.061 | 537.966–601.045 |
| records_10mib_direct_str | 174.466–174.466 | 148.088–148.088 | 823.706–823.706 | 841.866–841.866 |
| records_10mib_direct_file | 1031.628–1031.628 | 945.341–945.341 | 879.351–879.351 | 940.666–940.666 |
| records_10mib_callback_file_discard | 896.863–896.863 | 948.029–948.029 | 849.250–849.250 | 777.750–777.750 |
| records_10mib_callback_file_retain | 952.828–952.828 | 1006.293–1006.293 | 934.135–934.135 | 892.037–892.037 |
| large_text_10mib_direct_str | 25.093–25.093 | 23.772–23.772 | 78.907–78.907 | 25.522–25.522 |
| large_text_10mib_direct_file | 76.423–76.423 | 76.974–76.974 | 69.955–69.955 | 29.569–29.569 |

## Verification and provenance

- [architecture-pre-optimization-standard.json](architecture-pre-optimization-standard.json): 28 measured samples; source/binary hashes unchanged: True; complete: True.
- [architecture-pre-optimization-large-memory.json](architecture-pre-optimization-large-memory.json): 24 measured samples; source/binary hashes unchanged: True; complete: True.

Reproduction commands and selection details: [architecture-README.md](architecture-README.md). The full source and binary SHA-256 manifests are embedded in each raw file. No local usernames, absolute workspace paths or environment IDs are included.
