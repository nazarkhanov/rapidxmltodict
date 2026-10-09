# rapidxmltodict

A C++/CPython XML-to-dictionary parser using RapidXML, with the familiar
`xmltodict` output format. It constructs Python `dict`, `list`, `str` and `None`
directly: **no intermediate JSON string and no `json.loads`**.

```python
import rapidxmltodict

rapidxmltodict.parse('<root id="7"><item>A</item><item>B</item></root>')
# {'root': {'@id': '7', 'item': ['A', 'B']}}
```

## Install

From this checkout (CPython 3.9+, a C++17 compiler and Python development headers):

```sh
python -m pip install .
```

This repository has not been published to PyPI. The initial release builds a
native extension from source; it does not promise prebuilt platform wheels.
`xmltodict` is a runtime dependency for compatibility fallback and `unparse`.

## Compatibility contract

`parse` accepts the same signature as `xmltodict.parse`. The native path handles
UTF-8 `str` and `bytes`, including UTF-8 declarations and BOM, with default parse
options. Output preserves:

- attributes with `@`, text with `#text`, repeated children as lists;
- empty elements as `None`, insertion order and namespace prefixes;
- text/CDATA concatenation, Unicode strings and Unicode `str.strip` behavior;
- XML line-ending normalization and distinct literal/reference attribute whitespace;
- predefined/numeric XML entity references.

The following use **the installed `xmltodict` implementation**, transparently:

- custom options passed in `**kwargs` (even explicitly supplied default values),
  including `force_list`, `force_cdata`, `postprocessor`, `item_callback`,
  `item_depth`, custom dictionary constructors, attributes/text prefixes,
  `strip_whitespace` and `cdata_separator`;
- namespace processing/mapping, comments, custom Expat module, explicit encoding,
  or `disable_entities=False`;
- file objects, generators and other input types; non-UTF-8 declarations/input;
- DTDs; more than 256 nested elements; unusual XML names rejected by this
  RapidXML fork; mixed content with whitespace-only gaps between markup nodes.

The last mixed-content fallback is important: the unchanged RapidXML fork drops
those gaps, while xmltodict preserves them. Ordinary element-only, pretty-printed
XML still uses the native path. `unparse` and `ParsingInterrupted` are re-exported
from `xmltodict`. This is **not an all-native reimplementation of every option**.
Fallback behavior follows the installed xmltodict version. Differential tests and
reported benchmarks use xmltodict 0.14.2; CI also tests the currently resolved
compatible version. Conversion holds the GIL, so threads do not accelerate it.

## Validation and security

The public API validates the original input with Expat before RapidXML parsing.
Malformed XML raises the same `xml.parsers.expat.ExpatError` class as xmltodict.
This validation is included in every end-to-end timing; there is no unsafe
"skip validation" flag. A non-recursive scan bounds native nesting before
RapidXML enters its recursive parser. All Python results own their data, and
native buffers/DOM allocations and temporary references are freed on exit.

The default path does not fetch external entities. DTD-containing inputs go to
xmltodict with the original `disable_entities` setting (default `True`), preserving
its behavior, including DTD-supplied default attributes. `disable_entities=False`
explicitly opts into reference-parser entity behavior and its risks. There is no
application-level input-size or output-size limit: callers handling untrusted
large documents should enforce their own resource limits. Deep/streaming inputs
use xmltodict, not an unbounded native recursion path.

## Performance and memory

On the recorded CPython 3.12/Linux synthetic catalog workloads, the complete
API is **4.47–5.26× faster than xmltodict 0.14.2**. The ~1 MiB case takes
26.866 ms versus 120.036 ms, with whole-process peak RSS of **35.754 MiB versus
28.750 MiB**. The equal-output RapidXML-to-JSON + `json.loads` pipeline takes
26.885 ms and 42.684 MiB: essentially equal speed, about 16.2% lower peak memory
for the direct-dictionary parser. These are machine/workload-specific
measurements, not universal guarantees.

See [reproducible benchmark results](benchmarks/README.md) and the raw JSON there.
The comparison measures complete `rapidxmltodict.parse` versus
`xmltodict.parse`, verifies equal outputs first, and includes validation,
normalization, native parsing and Python object creation. Historical
`rapidxmltojson.parse` + `json.loads` is only compared on fixtures where its
output actually agrees.

The binding caches repeated element/attribute keys per parse and uses native
value spans directly. A compatibility preflight selects RapidXML's existing
`parse_no_data_nodes` mode when every element has at most one meaningful text
segment and no CDATA. This avoids a separate native data node per scalar; mixed
segments and CDATA use the full DOM path. The vendored header is unchanged.

RapidXML builds a DOM in addition to the Python result. Faster parsing does
**not** imply lower peak memory: large-record cases can use more process RSS
than xmltodict. Whole-process peak RSS (fresh subprocesses) is reported
separately from Python-only `tracemalloc`; the latter omits native DOM buffers.
Fallback workloads can be slower than calling xmltodict directly.

## Development

```sh
python -m pip install '.[test]' 'xmltodict==0.14.2'
python -m pytest -q
python -m build
python benchmarks/benchmark.py --help
```

Tests cover differential fixtures, deterministic generated documents, malformed
input mutations, advanced-option fallback, namespace names, BOMs, encodings,
entities, ownership, deep nesting and concurrent calls. CI builds/tests on Linux,
macOS and Windows with CPython 3.9, 3.12 and 3.13. Those CI targets are not a claim
that all platforms were tested locally; see the published commit's checks.

## Vendor and license

MIT for the binding; RapidXML's original Boost/MIT dual license is preserved.
`vendor/rapidxml/rapidxml.hpp` is **byte-for-byte unchanged** from the existing
`nazarkhanov/rapidxmltojson` repository at commit
`ed40f6bb23a262a26a50653698184541c89f3b50`. It is a pre-existing RapidXML 1.13 fork,
not a pristine upstream release. Its source, license and SHA-256 are recorded in
[vendor/rapidxml/README.md](vendor/rapidxml/README.md), and the checksum is tested.
Neither that existing repository nor its RapidXML header is modified.
