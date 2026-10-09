# rapidxmltodict

[![PyPI](https://img.shields.io/pypi/v/rapidxmltodict)](https://pypi.org/project/rapidxmltodict/)
[![CI](https://github.com/nazarkhanov/rapidxmltodict/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/nazarkhanov/rapidxmltodict/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Fast XML-to-dictionary parsing for Python, powered by RapidXML.

`rapidxmltodict` combines a C++ parser with the familiar `xmltodict` API and
output format. Common UTF-8 documents use native acceleration; advanced
options are handled by `xmltodict`.

## Installation

```sh
python -m pip install rapidxmltodict
```

Requires **CPython 3.9+**. Wheels are available for CPython **3.9–3.14** on
Linux x86-64 (manylinux), Windows x64, and macOS Intel/Apple Silicon.
Source builds require a C++17 compiler and Python development headers.

`xmltodict>=0.14.2,<2` is installed automatically as a runtime dependency.

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
are also supported through `xmltodict`, including its streaming callbacks.

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

`unparse` is provided by `xmltodict`. XML round trips are not lossless.

## Compatibility

Native acceleration handles UTF-8 `str` and `bytes` with default options,
including attributes, repeated elements, namespace prefixes, Unicode and CDATA.

Custom options such as `force_list`, namespace processing, comments and
postprocessors use the installed `xmltodict`. Extra options passed through
`**kwargs` trigger fallback even when explicitly set to their defaults.

File objects, generators, non-UTF-8 input, DTDs, nesting beyond 256 elements,
and certain mixed-content or XML-name edge cases also use fallback.
Behavior follows the installed dependency version; these calls may be slower
than calling `xmltodict` directly. Native conversion holds the GIL.

## Performance

Recorded synthetic catalog benchmarks on **CPython 3.12.14 / Linux x86-64**,
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

The native path validates XML with Expat before parsing. External entities are
not fetched by the default path; DTD and entity behavior follows the installed
`xmltodict`. Keep `disable_entities=True` for untrusted input.

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
