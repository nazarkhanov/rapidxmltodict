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

With `item_depth` and `item_callback`, completed items are delivered incrementally
and are not accumulated in the parent result. Keeping them in your callback will
still retain memory. Inputs, a single unfinished token and the current item can
also require substantial memory. See [API details](docs/typing.md).

## Performance

Historical measurements of the earlier Expat-validated implementation on **CPython 3.12.14 / Linux x86-64**,
compared with **xmltodict 0.14.2**:

| Input size | rapidxmltodict | xmltodict | Speedup |
| --- | ---: | ---: | ---: |
| 1,077 bytes | 0.026 ms | 0.134 ms | 5.09× |
| 105,501 bytes | 2.166 ms | 11.383 ms | 5.26× |
| 1,055,391 bytes | 26.866 ms | 120.036 ms | 4.47× |

Outputs are checked for equality before timing complete parse calls, including
validation and conversion. Results depend on the workload and machine.

**Faster parsing can use more memory.** The ~1 MiB case used 35.75 MiB
whole-process peak RSS versus 28.75 MiB for `xmltodict`.

See the [benchmark guide](benchmarks/README.md) for reproduction commands,
methodology and [full results](benchmarks/results.md).

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
