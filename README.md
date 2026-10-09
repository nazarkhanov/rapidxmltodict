# rapidxmltodict

[![PyPI](https://img.shields.io/pypi/v/rapidxmltodict)](https://pypi.org/project/rapidxmltodict/)
[![CI](https://github.com/nazarkhanov/rapidxmltodict/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/nazarkhanov/rapidxmltodict/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Fast XML-to-dictionary parsing for Python, powered by RapidXML.

`rapidxmltodict` combines a C++ parser with the familiar `xmltodict` API and
output format. Parsing, streaming callbacks and serialization are implemented
locally, with no xmltodict or Expat runtime dependency.

## Installation

```sh
python -m pip install rapidxmltodict
```

Requires **CPython 3.9+**. Wheels are available for CPython **3.9–3.14** on
Linux x86-64 (manylinux), Windows x64, and macOS Intel/Apple Silicon.
Source builds require a C++17 compiler and Python development headers.

There are no third-party Python runtime dependencies. Tests use xmltodict 1.0.4
as the compatibility reference.

## Quick start

```python
import rapidxmltodict

data = rapidxmltodict.parse(
    '<root id="7"><item>A</item><item>B</item><empty/></root>'
)

assert data == {"root": {"@id": "7", "item": ["A", "B"], "empty": None}}
```

Attributes use `@`, text alongside attributes or children uses `#text`,
repeated elements become lists, and empty elements become `None`.
Values remain strings; leading and trailing text whitespace is stripped.

### Read a file

```python
from pathlib import Path

data = rapidxmltodict.parse(Path("catalog.xml").read_bytes())
```

This loads the whole file into memory. Binary file objects and chunk generators
are also supported, including incremental `item_callback` processing.

### Use parsing options

```python
data = rapidxmltodict.parse(
    "<catalog><book>Python</book></catalog>",
    force_list=("book",),
)

assert data == {"catalog": {"book": ["Python"]}}
```

### Write XML

```python
xml = rapidxmltodict.unparse(data, pretty=True)
```

`unparse` follows xmltodict 1.0.4 serialization rules. XML round trips are not lossless.

## Compatibility

The compatibility target is **xmltodict 1.0.4**, including namespace mappings,
comments, postprocessors, custom dictionaries, callbacks and serialization.
Default UTF-8 documents use a native dictionary fast path; other inputs/options
use the independent native event parser and mapping layer. Native work holds the GIL.

Intentional differences:
- The `expat` parameter is removed; parser injection is unsupported.
- Catch `rapidxmltodict.ParseError` and `rapidxmltodict.ParsingInterrupted`.
  They are independent classes, not the exceptions exported by Expat/xmltodict.
- XML declaration versions must match `1.[0-9]+`, following the modern reference.
- Chunk-sensitive text joining follows the pinned modern reference behavior;
  older Expat builds can place a nonempty `cdata_separator` differently.

The test oracle is pinned to CPython 3.12.15 / Expat 2.8.5; neither is a parser
dependency. See the [compatibility contract](docs/compatibility.md).

With `item_depth` and `item_callback`, completed items are delivered incrementally
and are not accumulated in the parent result. Keeping them in your callback will
still retain memory. Inputs, a single unfinished token and the current item can
also require substantial memory. See [API details](docs/typing.md).

## Performance

Integrated-parser measurements on **CPython 3.12.14 / Linux x86-64**, compared
with **xmltodict 1.0.4**:

| Input size | rapidxmltodict | xmltodict | Speedup |
| --- | ---: | ---: | ---: |
| 1,077 bytes | 0.013 ms | 0.084 ms | 6.5× |
| 105,501 bytes | 1.279 ms | 7.851 ms | 6.1× |
| 1,055,391 bytes | 12.597 ms | 86.012 ms | 6.8× |

These catalog-shaped inputs are checked for equal output before timing complete
parse calls, including validation and conversion. Results depend on input shape,
options and machine. Deep XML can trigger an event-path restart and remains
slower than the earlier implementation; some record-shaped inputs also regressed
relative to the pre-refactor hybrid parser.

**Faster parsing can use more memory.** The ~1 MiB case used 32.38 MiB
whole-process peak RSS versus 27.54 MiB for `xmltodict`. At 100 MiB, repeated
records used 1403.80 MiB versus 918.11 MiB; increasing input size did not reverse
that difference. Non-retaining callback parsing stayed near 20.63 MiB across
10/50/100 MiB, with a different output-retention contract.

See the [complete comparison](benchmarks/standalone-results.md) for raw data,
reproduction commands, total and incremental RSS, retained output, streaming
results and all slower cases. The benchmark reference uses Expat 2.8.3; the
separate compatibility gate uses the exact modern oracle described above.

## Type hints

PEP 561 type information is included for editor completion and static checking,
with parameter hints, callback signatures and return overloads.
Nested XML values remain dynamic. See [typing details](docs/typing.md).

## Security

XML is validated by the native parser; Expat is not loaded. External entities
are not fetched. Keep `disable_entities=True` to reject entity declarations for
untrusted input.

There is no application-level input-size or output-size limit. Enforce suitable
size, time and memory limits when processing untrusted documents.

## Development

```sh
python -m pip install ".[test,typing]"
python -m pytest -q
```

Pull requests should target `main` and include tests for behavior changes.
See the [sanitizer guide](tests/SANITIZERS.md) and [release guide](docs/releasing.md)
for additional checks and publishing instructions.

## License

[MIT](LICENSE). Includes RapidXML under its
[Boost/MIT dual license](vendor/rapidxml/license.txt).
