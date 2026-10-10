# Parser architecture prototypes: four-way comparison

These measurements compare separately frozen architectures. The native-event column explicitly selects its private entry point. The final public dispatcher chooses iterative DOM for exact default strings/bytes and native events for files/options; that selection is verified separately below.

- Completed measurement workers: **348** across **29** workloads; every requested sample completed: **True**.
- Host CPU: AMD EPYC 9V74 80-Core Processor; CPU affinity: [8].
- Python: 3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ].
- Compiler: g++ (Debian 14.2.0-19) 14.2.0.
- Reference: xmltodict 1.0.4; expat_2.8.3.
- Baseline commit: `e911c9a5dbdc75974e66120861adc38dc36a39b8`.
- Iterative DOM commit: `cfe17cce26076a1e1fd94228ed271ef4fc22929d`.
- Native-event candidate commit: `a2d5e22ba2bdccedf568ef4d0e757b406d81f849`.
- Each input is generated once outside measured workers. Exact fixture/source/extension hashes, sample order, individual timings and RSS values are included in the raw files.
- Original standalone reports and their prior four-way baseline comparisons are preserved separately; their numbers are not substituted for freshly measured samples here.

## Main findings

- The late-deep case after 60,000 siblings is 6.65× faster with iterative DOM and 4.49× faster with native events than the current baseline. Avoiding abandoned DOM work and a second parse is the major deep-input improvement.
- For 100 MiB record files, native events take 3.258 s versus the baseline's 10.885 s (3.34× faster). Peak RSS is 627.7 versus 719.1 MiB.
- For complete 100 MiB record strings, iterative DOM takes 1.572 s versus native events at 2.451 s. Native-event peak RSS is 1127.7 versus iterative DOM's 1405.2 MiB.
- For 100 MiB discard callbacks, native events are 2.05× faster than the baseline and peak at 21.6 MiB. Retaining every callback item raises the native-event peak to 719.1 MiB. The application retention policy controls whether output memory stays bounded.
- For a 100 MiB text string, native events take 0.888 s and peak at 720.6 MiB, versus iterative DOM's 0.294 s and 420.6 MiB. The choice should account for both time and memory; event mapping does not inherently minimize either.
- On this 100 MiB record-file workload, native events use 12.6% less total peak RSS than xmltodict (627.7 versus 718.1 MiB). This does not generalize to every input path: for record strings, native-event peak RSS is 1127.7 versus xmltodict's 920.4 MiB, even though native-event retained RSS is lower. The table below distinguishes both cases.

### Focus: 100 MiB records versus xmltodict

All values are MiB. Deltas are derived per sample before taking medians; complete output remains alive. These observed cases are not a universal memory-crossover threshold.

| Input | Parser | Pre-parse current | Prior peak | Total peak | Peak − current | Peak − prior peak | Retained current | Retained − current |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| File | Native events | 20.6 | 21.4 | 627.7 | 607.1 | 606.3 | 627.9 | 607.3 |
| File | xmltodict 1.0.4 | 19.6 | 21.4 | 718.1 | 698.5 | 696.7 | 718.2 | 698.6 |
| String | Native events | 120.6 | 220.6 | 1127.7 | 1007.1 | 907.2 | 727.9 | 607.3 |
| String | xmltodict 1.0.4 | 119.6 | 219.5 | 920.4 | 800.8 | 700.9 | 819.5 | 699.9 |

## What is being compared

| Variant | Exact entry point | Implementation |
|---|---|---|
| e911 baseline | `rapidxmltodict:parse` | Current integrated e911 baseline public parse; existing depth limit may trigger a second event parse. |
| Iterative DOM/default | `rapidxmltodict:parse` | Iterative DOM/default public parse: iterative DOM for default in-memory str/bytes, existing Python event mapping for file/callback/options. |
| Native events | `rapidxmltodict._parse:_parse_native_events` | Private direct native-event dictionary mapper, forced via the recorded wrapper entry point. |
| xmltodict 1.0.4 | `xmltodict:parse` | Unmodified xmltodict 1.0.4 public parse, Expat reference. |

The iterative DOM/default variant still uses its existing Python event mapper for file and callback inputs. Those rows compare that snapshot’s actual public behavior; they are not measurements of a DOM streaming implementation.

## Method and caveats

- Fresh workers per parser/workload: [3]. All workers use the same CPU, interpreter, GC setting and PYTHONHASHSEED=0. Parser order rotates by workload and trial.
- Standard timings: 3 warmups, 3 calibration parses, then 9 calibrated batches per worker targeting 0.1 seconds each. Result destruction is timed. RSS comes from the first parse before those batches.
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
| small | 0.014 | 0.013 | 0.023 | 0.089 | 1.10× | 0.62× |
| medium | 1.191 | 1.075 | 1.771 | 7.881 | 1.11× | 0.67× |
| large | 12.889 | 11.716 | 19.290 | 90.182 | 1.10× | 0.67× |
| unicode_mixed | 1.054 | 1.033 | 1.841 | 6.804 | 1.02× | 0.57× |
| medium_bytes | 1.129 | 1.093 | 1.754 | 7.989 | 1.03× | 0.64× |
| deep_128 | 0.021 | 0.018 | 0.033 | 0.184 | 1.13× | 0.64× |
| deep_300 | 0.642 | 0.042 | 0.072 | 0.411 | 15.35× | 8.98× |
| deep_1500 | 2.686 | 0.272 | 0.391 | 2.253 | 9.89× | 6.88× |
| deep_10000 | 17.226 | 2.198 | 2.325 | 15.787 | 7.84× | 7.41× |
| late_deep_6000_siblings | 66.450 | 7.956 | 12.009 | 54.923 | 8.35× | 5.53× |
| late_deep_60000_siblings | 657.861 | 98.877 | 146.459 | 571.722 | 6.65× | 4.49× |

The full fixture suite includes 128, 300, 1,500 and 10,000 nested elements; only measured cases appear in the table. Late-deep workloads place a 1,500-element branch after 6,000 or 60,000 completed shallow siblings, exposing abandoned-DOM-and-reparse work in the baseline. All output fingerprints must match the oracle.

## Large-input timings

Times are median seconds from complete parses in fresh processes.

| Workload | Baseline s | Iterative s | Events s | xmltodict s | Events vs baseline |
|---|---:|---:|---:|---:|---:|
| records_10mib_direct_str | 0.151 | 0.145 | 0.214 | 0.838 | 0.70× |
| records_10mib_direct_file | 0.965 | 0.973 | 0.252 | 0.925 | 3.83× |
| records_10mib_callback_file_discard | 0.918 | 0.914 | 0.455 | 0.802 | 2.02× |
| records_10mib_callback_file_retain | 1.011 | 1.039 | 0.562 | 0.906 | 1.80× |
| large_text_10mib_direct_str | 0.025 | 0.024 | 0.079 | 0.024 | 0.31× |
| large_text_10mib_direct_file | 0.079 | 0.084 | 0.079 | 0.028 | 1.00× |
| records_50mib_direct_str | 0.822 | 0.768 | 1.144 | 4.842 | 0.72× |
| records_50mib_direct_file | 5.550 | 5.471 | 1.609 | 4.935 | 3.45× |
| records_50mib_callback_file_discard | 4.994 | 4.661 | 2.280 | 4.349 | 2.19× |
| records_50mib_callback_file_retain | 5.457 | 5.452 | 3.163 | 4.876 | 1.73× |
| large_text_50mib_direct_str | 0.154 | 0.146 | 0.453 | 0.120 | 0.34× |
| large_text_50mib_direct_file | 0.382 | 0.388 | 0.362 | 0.132 | 1.05× |
| records_100mib_direct_str | 1.765 | 1.572 | 2.451 | 10.086 | 0.72× |
| records_100mib_direct_file | 10.885 | 11.554 | 3.258 | 10.048 | 3.34× |
| records_100mib_callback_file_discard | 9.344 | 9.168 | 4.552 | 8.100 | 2.05× |
| records_100mib_callback_file_retain | 10.704 | 10.863 | 6.208 | 9.734 | 1.72× |
| large_text_100mib_direct_str | 0.293 | 0.294 | 0.888 | 0.232 | 0.33× |
| large_text_100mib_direct_file | 0.783 | 1.013 | 0.763 | 0.286 | 1.03× |

## Total and incremental peak RSS

Each cell is **total peak / peak minus pre-parse current RSS / peak minus prior high-water RSS**, in MiB. Both deltas are clamped at zero and calculated per sample before taking medians. They use the same measured peak; the current-baseline delta does not hide input-loading transients in a previous peak. Neither delta is a precise attribution of parser-only allocations.

| Workload | Baseline MiB | Iterative MiB | Events MiB | xmltodict MiB |
|---|---:|---:|---:|---:|
| small | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.2 / 0.6 / 0.0 |
| medium | 21.3 / 0.7 / 0.8 | 21.3 / 0.7 / 0.8 | 21.1 / 0.5 / 0.5 | 20.4 / 0.8 / 0.1 |
| large | 33.9 / 12.2 / 11.3 | 33.8 / 12.2 / 11.3 | 31.5 / 9.9 / 8.9 | 29.4 / 8.8 / 7.9 |
| unicode_mixed | 21.4 / 0.5 / 0.5 | 21.4 / 0.5 / 0.5 | 21.3 / 0.4 / 0.5 | 20.5 / 0.5 / 0.2 |
| medium_bytes | 21.2 / 0.6 / 0.6 | 21.2 / 0.6 / 0.6 | 21.1 / 0.5 / 0.5 | 20.4 / 0.8 / 0.1 |
| deep_128 | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.2 / 0.6 / 0.0 |
| deep_300 | 20.9 / 0.3 / 0.4 | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.4 / 0.8 / 0.0 |
| deep_1500 | 21.3 / 0.7 / 0.8 | 20.8 / 0.2 / 0.2 | 20.8 / 0.2 / 0.2 | 20.5 / 0.9 / 0.0 |
| deep_10000 | 24.3 / 3.7 / 3.4 | 23.9 / 3.3 / 3.0 | 22.8 / 2.2 / 1.9 | 24.2 / 4.6 / 3.4 |
| late_deep_6000_siblings | 29.0 / 7.8 / 7.3 | 29.3 / 8.1 / 7.6 | 27.5 / 6.3 / 5.8 | 26.2 / 6.0 / 5.2 |
| late_deep_60000_siblings | 99.1 / 72.5 / 66.5 | 108.4 / 81.7 / 75.8 | 89.8 / 63.2 / 57.3 | 75.6 / 50.0 / 44.1 |
| records_10mib_direct_str | 158.5 / 127.9 / 117.9 | 158.5 / 127.9 / 117.9 | 131.1 / 100.5 / 90.5 | 110.8 / 81.2 / 71.3 |
| records_10mib_direct_file | 90.6 / 69.9 / 70.0 | 90.6 / 69.9 / 70.0 | 81.4 / 60.8 / 60.9 | 89.6 / 70.0 / 69.4 |
| records_10mib_callback_file_discard | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.2 / 0.6 / 0.0 |
| records_10mib_callback_file_retain | 90.6 / 69.9 / 70.0 | 90.6 / 69.9 / 70.0 | 90.7 / 70.1 / 70.1 | 89.6 / 70.0 / 69.4 |
| large_text_10mib_direct_str | 60.5 / 29.9 / 19.9 | 60.5 / 29.9 / 19.9 | 90.5 / 59.9 / 49.9 | 61.6 / 31.9 / 22.1 |
| large_text_10mib_direct_file | 40.1 / 19.4 / 19.5 | 40.1 / 19.5 / 19.5 | 40.1 / 19.5 / 19.5 | 38.9 / 19.3 / 18.6 |
| records_50mib_direct_str | 712.6 / 642.0 / 592.1 | 712.6 / 642.0 / 592.1 | 574.2 / 503.6 / 453.7 | 471.2 / 401.6 / 351.8 |
| records_50mib_direct_file | 369.8 / 349.2 / 349.2 | 369.9 / 349.3 / 349.4 | 324.2 / 303.6 / 303.6 | 369.0 / 349.4 / 348.6 |
| records_50mib_callback_file_discard | 20.6 / 0.0 / 0.0 | 20.6 / 0.0 / 0.0 | 20.7 / 0.1 / 0.1 | 20.5 / 0.9 / 0.0 |
| records_50mib_callback_file_retain | 369.8 / 349.2 / 349.2 | 369.8 / 349.2 / 349.2 | 369.9 / 349.3 / 349.4 | 369.0 / 349.4 / 348.5 |
| large_text_50mib_direct_str | 220.6 / 150.0 / 100.1 | 220.6 / 150.0 / 100.0 | 370.6 / 300.0 / 250.0 | 220.6 / 151.0 / 101.1 |
| large_text_50mib_direct_file | 121.6 / 100.9 / 100.6 | 121.6 / 100.9 / 100.6 | 121.4 / 100.8 / 100.4 | 119.2 / 99.6 / 98.2 |
| records_100mib_direct_str | 1405.1 / 1284.5 / 1184.6 | 1405.2 / 1284.6 / 1184.7 | 1127.7 / 1007.1 / 907.2 | 920.4 / 800.8 / 700.9 |
| records_100mib_direct_file | 719.1 / 698.4 / 697.7 | 719.1 / 698.4 / 697.7 | 627.7 / 607.1 / 606.3 | 718.1 / 698.5 / 696.7 |
| records_100mib_callback_file_discard | 21.5 / 0.9 / 0.0 | 21.6 / 1.0 / 0.0 | 21.6 / 1.0 / 0.0 | 21.5 / 1.9 / 0.0 |
| records_100mib_callback_file_retain | 719.1 / 698.4 / 697.4 | 719.1 / 698.4 / 697.3 | 719.1 / 698.5 / 697.4 | 718.1 / 698.5 / 696.4 |
| large_text_100mib_direct_str | 420.6 / 300.0 / 200.1 | 420.6 / 300.0 / 200.0 | 720.6 / 600.0 / 500.0 | 420.6 / 301.0 / 201.1 |
| large_text_100mib_direct_file | 223.3 / 202.7 / 201.3 | 223.3 / 202.7 / 201.3 | 223.2 / 202.6 / 201.2 | 219.6 / 200.0 / 197.6 |

## Pre-parse RSS baselines

Each cell is **current RSS / prior high-water RSS**, in MiB, after imports and input loading/opening and before parsing. These are the two baselines used above.

| Workload | Baseline MiB | Iterative MiB | Events MiB | xmltodict MiB |
|---|---:|---:|---:|---:|
| small | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| medium | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| large | 21.6 / 22.6 | 21.6 / 22.6 | 21.6 / 22.6 | 20.6 / 21.5 |
| unicode_mixed | 20.9 / 20.9 | 20.9 / 20.9 | 20.9 / 20.8 | 19.9 / 20.2 |
| medium_bytes | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| deep_128 | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| deep_300 | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.4 |
| deep_1500 | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.5 |
| deep_10000 | 20.6 / 20.9 | 20.6 / 20.9 | 20.6 / 20.9 | 19.6 / 20.9 |
| late_deep_6000_siblings | 21.2 / 21.7 | 21.2 / 21.7 | 21.2 / 21.7 | 20.2 / 21.0 |
| late_deep_60000_siblings | 26.6 / 32.6 | 26.6 / 32.6 | 26.6 / 32.6 | 25.6 / 31.5 |
| records_10mib_direct_str | 30.6 / 40.6 | 30.6 / 40.6 | 30.6 / 40.6 | 29.6 / 39.5 |
| records_10mib_direct_file | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| records_10mib_callback_file_discard | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| records_10mib_callback_file_retain | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| large_text_10mib_direct_str | 30.6 / 40.6 | 30.6 / 40.6 | 30.6 / 40.6 | 29.6 / 39.5 |
| large_text_10mib_direct_file | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.2 |
| records_50mib_direct_str | 70.6 / 120.6 | 70.6 / 120.6 | 70.6 / 120.6 | 69.6 / 119.5 |
| records_50mib_direct_file | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.4 |
| records_50mib_callback_file_discard | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.5 |
| records_50mib_callback_file_retain | 20.6 / 20.6 | 20.6 / 20.6 | 20.6 / 20.6 | 19.6 / 20.5 |
| large_text_50mib_direct_str | 70.6 / 120.6 | 70.6 / 120.6 | 70.6 / 120.6 | 69.6 / 119.5 |
| large_text_50mib_direct_file | 20.6 / 21.0 | 20.6 / 21.0 | 20.6 / 21.0 | 19.6 / 21.0 |
| records_100mib_direct_str | 120.6 / 220.6 | 120.6 / 220.6 | 120.6 / 220.6 | 119.6 / 219.5 |
| records_100mib_direct_file | 20.6 / 21.4 | 20.6 / 21.4 | 20.6 / 21.4 | 19.6 / 21.4 |
| records_100mib_callback_file_discard | 20.6 / 21.5 | 20.6 / 21.6 | 20.6 / 21.6 | 19.6 / 21.5 |
| records_100mib_callback_file_retain | 20.6 / 21.6 | 20.6 / 21.8 | 20.6 / 21.8 | 19.6 / 21.8 |
| large_text_100mib_direct_str | 120.6 / 220.6 | 120.6 / 220.6 | 120.6 / 220.6 | 119.6 / 219.5 |
| large_text_100mib_direct_file | 20.6 / 22.0 | 20.6 / 22.0 | 20.6 / 22.0 | 19.6 / 22.0 |

## Retained RSS and current-baseline increase

Each cell is **retained current RSS / retained minus pre-parse current RSS**, in MiB. The increase is signed. Inputs and results/application-retained callback items remain alive; this is whole-process memory, not output-object size alone.

| Workload | Baseline MiB | Iterative MiB | Events MiB | xmltodict MiB |
|---|---:|---:|---:|---:|
| small | 20.7 / 0.0 | 20.7 / 0.0 | 20.7 / 0.1 | 19.7 / 0.1 |
| medium | 21.3 / 0.7 | 21.3 / 0.7 | 21.3 / 0.7 | 20.4 / 0.8 |
| large | 29.1 / 7.5 | 29.2 / 7.6 | 29.7 / 8.1 | 27.7 / 7.1 |
| unicode_mixed | 21.5 / 0.5 | 21.5 / 0.5 | 21.4 / 0.5 | 20.5 / 0.6 |
| medium_bytes | 21.2 / 0.6 | 21.2 / 0.6 | 21.3 / 0.7 | 20.4 / 0.8 |
| deep_128 | 20.7 / 0.1 | 20.7 / 0.0 | 20.7 / 0.1 | 19.8 / 0.1 |
| deep_300 | 21.0 / 0.4 | 20.7 / 0.1 | 20.7 / 0.1 | 19.8 / 0.2 |
| deep_1500 | 21.3 / 0.7 | 20.9 / 0.3 | 20.9 / 0.3 | 20.4 / 0.8 |
| deep_10000 | 24.1 / 3.5 | 23.3 / 2.7 | 22.7 / 2.1 | 24.3 / 4.7 |
| late_deep_6000_siblings | 29.0 / 7.8 | 26.8 / 5.6 | 26.6 / 5.4 | 25.6 / 5.4 |
| late_deep_60000_siblings | 99.2 / 72.5 | 102.5 / 75.9 | 90.0 / 63.4 | 75.7 / 50.1 |
| records_10mib_direct_str | 148.6 / 118.0 | 148.6 / 118.0 | 131.3 / 100.6 | 111.0 / 81.3 |
| records_10mib_direct_file | 90.7 / 70.0 | 90.7 / 70.0 | 81.5 / 60.9 | 89.7 / 70.1 |
| records_10mib_callback_file_discard | 20.7 / 0.1 | 20.7 / 0.1 | 20.7 / 0.1 | 19.7 / 0.1 |
| records_10mib_callback_file_retain | 90.7 / 70.0 | 90.7 / 70.0 | 90.7 / 70.1 | 89.7 / 70.1 |
| large_text_10mib_direct_str | 50.5 / 19.9 | 50.5 / 19.9 | 90.6 / 60.0 | 61.6 / 32.0 |
| large_text_10mib_direct_file | 30.7 / 10.1 | 30.7 / 10.1 | 30.7 / 10.1 | 29.7 / 10.1 |
| records_50mib_direct_str | 374.2 / 303.6 | 374.2 / 303.6 | 374.4 / 303.8 | 420.3 / 350.7 |
| records_50mib_direct_file | 370.0 / 349.4 | 370.0 / 349.4 | 324.4 / 303.8 | 369.1 / 349.4 |
| records_50mib_callback_file_discard | 20.7 / 0.1 | 20.7 / 0.0 | 20.7 / 0.1 | 19.7 / 0.1 |
| records_50mib_callback_file_retain | 370.0 / 349.4 | 370.0 / 349.4 | 370.0 / 349.5 | 369.1 / 349.4 |
| large_text_50mib_direct_str | 120.7 / 50.0 | 120.7 / 50.0 | 120.7 / 50.1 | 120.7 / 51.1 |
| large_text_50mib_direct_file | 70.7 / 50.1 | 70.7 / 50.1 | 70.7 / 50.1 | 69.7 / 50.1 |
| records_100mib_direct_str | 727.9 / 607.2 | 727.7 / 607.1 | 727.9 / 607.3 | 819.5 / 699.9 |
| records_100mib_direct_file | 719.2 / 698.6 | 719.2 / 698.6 | 627.9 / 607.3 | 718.2 / 698.6 |
| records_100mib_callback_file_discard | 20.7 / 0.1 | 20.7 / 0.0 | 20.7 / 0.1 | 19.7 / 0.1 |
| records_100mib_callback_file_retain | 719.2 / 698.6 | 719.2 / 698.6 | 719.2 / 698.6 | 718.2 / 698.6 |
| large_text_100mib_direct_str | 220.7 / 100.0 | 220.7 / 100.0 | 220.7 / 100.1 | 220.7 / 101.1 |
| large_text_100mib_direct_file | 120.7 / 100.1 | 120.7 / 100.1 | 120.7 / 100.1 | 119.7 / 100.1 |

## Trial range

Minimum–maximum milliseconds across measured standard batches or large fresh-process parses. These are descriptive ranges, not confidence intervals.

| Workload | Baseline | Iterative | Events | xmltodict |
|---|---:|---:|---:|---:|
| small | 0.012–0.020 | 0.012–0.016 | 0.022–0.031 | 0.082–0.155 |
| medium | 1.070–1.330 | 1.000–1.353 | 1.663–1.977 | 7.435–10.021 |
| large | 11.876–14.956 | 10.777–13.241 | 18.266–21.688 | 77.965–128.467 |
| unicode_mixed | 0.975–1.373 | 0.902–1.284 | 1.680–2.092 | 6.267–8.177 |
| medium_bytes | 1.069–1.865 | 1.019–2.116 | 1.678–1.954 | 7.490–8.530 |
| deep_128 | 0.019–0.026 | 0.017–0.023 | 0.029–0.048 | 0.172–0.205 |
| deep_300 | 0.620–0.944 | 0.040–0.050 | 0.065–0.095 | 0.377–0.684 |
| deep_1500 | 2.554–3.054 | 0.254–0.312 | 0.356–0.469 | 2.124–2.645 |
| deep_10000 | 16.179–20.323 | 2.012–2.773 | 2.233–2.869 | 14.881–17.613 |
| late_deep_6000_siblings | 62.829–84.389 | 7.338–10.806 | 11.140–14.036 | 50.474–63.842 |
| late_deep_60000_siblings | 639.998–870.383 | 94.061–134.722 | 139.585–211.186 | 522.648–595.310 |
| records_10mib_direct_str | 150.871–151.665 | 142.214–166.414 | 210.795–225.479 | 831.207–862.783 |
| records_10mib_direct_file | 950.986–969.238 | 964.323–1013.761 | 236.674–258.433 | 903.206–986.805 |
| records_10mib_callback_file_discard | 904.674–918.625 | 882.601–930.966 | 452.000–496.076 | 793.764–902.765 |
| records_10mib_callback_file_retain | 966.613–1049.425 | 983.271–1043.653 | 540.587–565.236 | 876.767–917.577 |
| large_text_10mib_direct_str | 23.884–26.339 | 23.813–25.783 | 79.273–79.887 | 23.283–24.646 |
| large_text_10mib_direct_file | 76.804–81.439 | 82.844–84.605 | 78.572–79.942 | 27.915–28.525 |
| records_50mib_direct_str | 821.303–822.195 | 757.647–792.953 | 1092.738–1170.334 | 4696.221–4842.678 |
| records_50mib_direct_file | 5416.160–5618.698 | 5344.240–5577.303 | 1517.868–1694.315 | 4878.795–5039.170 |
| records_50mib_callback_file_discard | 4523.685–5154.368 | 4638.681–5170.741 | 2205.287–2399.127 | 3950.545–4487.361 |
| records_50mib_callback_file_retain | 5323.562–5704.108 | 5431.580–5856.664 | 3044.563–3218.418 | 4717.305–5307.059 |
| large_text_50mib_direct_str | 147.798–154.535 | 145.485–150.630 | 415.254–460.226 | 115.722–121.991 |
| large_text_50mib_direct_file | 351.856–396.628 | 386.767–408.266 | 353.940–379.500 | 129.604–148.223 |
| records_100mib_direct_str | 1744.511–1770.686 | 1559.772–1766.265 | 2326.968–2513.778 | 10069.244–10105.215 |
| records_100mib_direct_file | 10777.317–11589.038 | 11138.087–11956.935 | 3243.138–3569.888 | 9981.064–10659.165 |
| records_100mib_callback_file_discard | 9253.578–9487.090 | 9078.887–9226.690 | 4526.185–4612.624 | 7896.018–8277.481 |
| records_100mib_callback_file_retain | 10664.281–11742.801 | 10758.969–11331.573 | 6152.543–6343.352 | 9730.167–10043.299 |
| large_text_100mib_direct_str | 283.614–319.924 | 283.763–323.547 | 864.346–924.657 | 230.267–247.805 |
| large_text_100mib_direct_file | 755.398–866.288 | 806.523–1039.264 | 761.361–900.340 | 256.906–294.605 |

## Selected public dispatcher

The final public API selects iterative DOM for exact default strings/bytes, and direct native events for files, generators, callbacks and non-default mapping options. Read the iterative column for default in-memory input and the native-event column for file/callback behavior. The iterative snapshot's file/callback column is the earlier Python-mapper implementation, not the final public file/callback path.

These remain measurements of the separately frozen architectures. The hybrid public dispatcher is verified independently rather than presented as a fifth timed variant.

[architecture-public-routing.json](architecture-public-routing.json) records 13 isolated, untimed public-API checks. They observe the actual native entry points and compare complete output or callback-content fingerprints with the selected measured architecture. Generator and explicit-option routes are included, and retained callback objects are additionally compared with xmltodict after the complete 10 and 100 MiB parses. All passed, with source/binary hashes unchanged.

## Verification and provenance

- [architecture-standard.json](architecture-standard.json): 132 measured samples; source/binary hashes unchanged: True; complete: True.
- [architecture-large-memory.json](architecture-large-memory.json): 216 measured samples; source/binary hashes unchanged: True; complete: True.

Reproduction commands and selection details: [architecture-README.md](architecture-README.md). The full source and binary SHA-256 manifests are embedded in each raw file. No local usernames, absolute workspace paths or environment IDs are included.
