# Large XML: old fork, upstream RapidXML 1.13, and xmltodict

## Answer

For these measured shapes, **rapidxmltodict did not use less peak memory than
xmltodict at 10, 50 or 100 MiB**. There is a narrower positive result: with many
small records at 50 and 100 MiB, its whole-process current RSS **after parsing,
while retaining input and output**, was lower than xmltodict's.

At 100 MiB of records, upstream rapidxmltodict retained
727.00 MiB versus xmltodict's
818.49 MiB (-11.2%),
but peaked at 1406.61 versus 919.32 MiB
(+53.0%). Upstream lowered peak RSS relative to the old fork by
10.7% on this input. Peak memory and post-parse memory must
not be advertised interchangeably.

Records favored upstream parse speed (4.51–5.07×
xmltodict). A single very large text value did not: upstream achieved only
0.47–0.53× xmltodict's speed. XML shape matters.
These are synthetic, single-machine results rather than guarantees for other
files or allocators.

## Whole-process peak RSS

Median of three fresh subprocesses per parser/input, in MiB. The final column
compares upstream with xmltodict; positive means more memory.

| Input | Old fork | Upstream 1.13 | xmltodict 0.14.2 | Upstream vs xmltodict |
|---|---:|---:|---:|---:|
| records, 10 MiB | 175.47 | 158.47 | 109.76 | +44.4% |
| large_text, 10 MiB | 61.47 | 61.47 | 60.51 | +1.6% |
| records, 50 MiB | 797.98 | 713.98 | 470.20 | +51.8% |
| large_text, 50 MiB | 220.61 | 220.61 | 219.52 | +0.5% |
| records, 100 MiB | 1575.48 | 1406.61 | 919.32 | +53.0% |
| large_text, 100 MiB | 420.61 | 420.61 | 419.52 | +0.3% |

## Incremental peak RSS above the input-loaded baseline

Median of each process's `final peak - baseline peak`, in MiB. This subtracts the
post-import/input-load high-water mark, which can include transient loading
copies. It is not exact allocation, retained memory, or peak minus current RSS.

| Input | Old fork MiB | Upstream MiB | xmltodict MiB |
|---|---:|---:|---:|
| records, 10 MiB | 136.10 | 119.10 | 71.26 |
| large_text, 10 MiB | 22.10 | 22.10 | 22.01 |
| records, 50 MiB | 678.61 | 594.61 | 351.70 |
| large_text, 50 MiB | 101.23 | 101.23 | 101.02 |
| records, 100 MiB | 1356.05 | 1187.23 | 700.82 |
| large_text, 100 MiB | 201.23 | 201.23 | 201.02 |

## Current RSS with input and output retained

Read immediately after parsing, before fingerprinting. These values include the
Python runtime, input, output and any allocator-retained memory. They are not
exact dictionary allocation sizes. A freed native allocation can remain in the
process's allocator; whether it is returned to the OS depends on allocation size
and allocator behavior. Therefore the small- and large-input trends need not be
linear, and this result should not be generalized to long-running services.

| Input | Old fork MiB | Upstream MiB | xmltodict MiB | Upstream vs xmltodict |
|---|---:|---:|---:|---:|
| records, 10 MiB | 175.56 | 158.66 | 109.97 | +44.3% |
| large_text, 10 MiB | 61.54 | 61.54 | 60.60 | +1.6% |
| records, 50 MiB | 373.55 | 374.73 | 419.31 | -10.6% |
| large_text, 50 MiB | 119.67 | 119.66 | 119.72 | ≈0.0% |
| records, 100 MiB | 727.19 | 727.00 | 818.49 | -11.2% |
| large_text, 100 MiB | 219.67 | 219.66 | 219.72 | ≈0.0% |

## Single-call parse time

Median seconds for one default `parse(str_input)` call in each fresh process.
Validation, encoding, native conversion and compatibility checks are included;
imports, input loading, output fingerprinting and output destruction are not.
There is no warmup. This is a cold-parse measurement paired with RSS, not the
batched steady-state timing method in the smaller comparison.

| Input | Old fork seconds | Upstream seconds | xmltodict seconds | Upstream speedup |
|---|---:|---:|---:|---:|
| records, 10 MiB | 0.196 | 0.206 | 0.929 | 4.51× |
| large_text, 10 MiB | 0.050 | 0.046 | 0.024 | 0.53× |
| records, 50 MiB | 1.096 | 1.013 | 5.001 | 4.94× |
| large_text, 50 MiB | 0.256 | 0.253 | 0.119 | 0.47× |
| records, 100 MiB | 2.233 | 2.030 | 10.293 | 5.07× |
| large_text, 100 MiB | 0.527 | 0.512 | 0.243 | 0.48× |

## Input-loaded baseline RSS

Each cell is current RSS / peak RSS in MiB, after parser import and input load,
before parsing. Loading the UTF-8 bytes and decoding the string briefly requires
both representations, so baseline high-water RSS is often above current RSS.
Incremental peak (`final peak - baseline peak`) and all individual baseline,
peak and retained readings are preserved in the raw JSON. Incremental peak is
not an exact allocation count, and `/proc` current RSS and `ru_maxrss` can differ
slightly due to Linux accounting granularity.

| Input | Old fork current / peak | Upstream current / peak | xmltodict current / peak |
|---|---:|---:|---:|
| records, 10 MiB | 29.56 / 39.38 | 29.56 / 39.38 | 28.62 / 38.50 |
| large_text, 10 MiB | 29.56 / 39.38 | 29.55 / 39.38 | 28.62 / 38.50 |
| records, 50 MiB | 69.56 / 119.38 | 69.55 / 119.38 | 68.62 / 118.50 |
| large_text, 50 MiB | 69.56 / 119.38 | 69.55 / 119.38 | 68.62 / 118.50 |
| records, 100 MiB | 119.56 / 219.38 | 119.55 / 219.38 | 118.62 / 218.50 |
| large_text, 100 MiB | 119.56 / 219.38 | 119.55 / 219.38 | 118.62 / 218.50 |

## Inputs and output comparison

- `records`: exact 10, 50 and 100 MiB XML documents containing repeated small
  catalog records with varying IDs, prices, names and inventory, attributes,
  nested dictionaries, lists and escaped text. Record counts are retained in JSON.
  The record structure is the same benign catalog shape as the existing suite.
- `large_text`: exact 10, 50 and 100 MiB documents containing one large ASCII text
  value inside `<document><payload>…</payload></document>`.
- Fixture generation is deterministic and occurs once in the orchestrator, with
  streamed writes outside measured workers. Files are identical across all
  parsers; full input SHA-256 hashes and sizes are recorded. Fixtures total
  320 MiB and are generated locally rather than committed.
- All 54 successful parser runs produced the same complete typed structural
  SHA-256 fingerprint for their corresponding input. Dictionary keys are sorted;
  list order, value types and every string character are included. This compares
  full outputs by a cryptographic fingerprint rather than holding three enormous
  dictionaries in one process. Fingerprinting occurs after the memory readings.
  Basic checks confirmed dictionary-order invariance and distinguished list order,
  types, key boundaries and string content.

## Environment, isolation and bounds

- Same Linux x86-64 host, CPython 3.12.14 and dedicated xmltodict 0.14.2 environment
  as [`upstream-comparison.md`](upstream-comparison.md). Old fork is commit
  `98e7367fa91b7703eeebd160a6090350c821ed0d`; upstream uses the same measured migration
  source/binary hashes. Both use identical GCC 14.2.0 / C++17 / `-O3` build flags.
- The initial available host memory was
  8.13 GiB. Runs are
  sequential, with a 3 GiB `RLIMIT_AS` address-space cap per worker and conservative
  pre-run memory estimates. A worker is skipped if the estimate exceeds 40% of
  currently available memory or 80% of that address-space cap. The larger estimates
  use earlier measured input sizes. No workloads were skipped or failed, and no
  allocation-limit retry was needed.
- Three fresh processes per parser/shape/size. Parser order rotates:
  old/upstream/xmltodict, upstream/xmltodict/old, xmltodict/old/upstream.
  All workers are pinned to the lowest allowed logical CPU (0 here), with garbage
  collection enabled. The host is not exclusively reserved.
- All parser source/native binary hashes remained unchanged throughout. The
  script hash, exact arguments, module paths, process order, memory availability,
  each individual sample and complete fingerprints are in
  [`upstream-large-memory.json`](upstream-large-memory.json).
- RSS is whole-process resident memory, not virtual size. `RLIMIT_AS` caps virtual
  address space only as a safety bound. Peak RSS includes transient allocations
  even when they are freed by the time current RSS is read. This one-shot study
  does not measure leak behavior or long-lived process steady states.

## Reproduce

Build the two isolated checkouts in the same dedicated environment using the
commands in [`upstream-comparison.md`](upstream-comparison.md), then run:

```sh
/path/to/comparison-venv/bin/python benchmarks/upstream-large-memory.py \
  --before /path/to/pre-migration-checkout \
  --after /path/to/upstream-migration-checkout \
  --fixtures /path/to/large-generated-fixtures \
  --output benchmarks/upstream-large-memory.json
```

Defaults are 10/50/100 MiB, three repetitions, and a 3072 MiB address-space cap.
Keep dependency versions unchanged while the comparison runs. The script is
Linux-oriented (`/proc`, CPU affinity and `resource`), performs no network calls,
and records a skip or failure instead of escalating memory bounds. Do not
compare its single-call timing directly with the smaller suite's 27-batch median.
