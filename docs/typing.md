# API and editor hints

The installed wheel and source distribution include `rapidxmltodict/__init__.pyi`
and the PEP 561 `py.typed` marker. Editors using these stubs can show all known
keyword arguments and return types for `parse` and `unparse`. Select the Python
environment where this package is installed. No separate `types-rapidxmltodict`
package is needed. The runtime is independent of xmltodict and Expat.

The stubs describe the xmltodict 1.0.4-compatible API, excluding parser injection. They do not
accept an unrestricted `**kwargs`: misspelled and unknown options are type errors.
Future xmltodict additions require an explicit implementation and stub update.

## `parse`

The first six parameters may also be positional. All following parameters are
keyword-only options implemented by this package.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `xml_input` | required | XML text, bytes/bytearray/memoryview, binary reader, or actual generator of chunks |
| `encoding` | `None` | Explicit input encoding; otherwise declaration/default detection |
| `process_namespaces` | `False` | Expand XML namespaces |
| `namespace_separator` | `":"` | Separator between namespace and local name |
| `disable_entities` | `True` | Reject entity declarations when enabled |
| `process_comments` | `False` | Include XML comments |
| `item_depth` | `0` | Depth at which `item_callback` receives completed items |
| `item_callback` | always truthy | `(path, item)`; a false-ish return raises `ParsingInterrupted` |
| `xml_attribs` | `True` | Include element attributes |
| `attr_prefix` | `"@"` | Attribute-key prefix |
| `cdata_key` | `"#text"` | Text key in dictionary-valued elements |
| `force_cdata` | `False` | Boolean, collection or predicate controlling text dictionaries |
| `cdata_separator` | `""` | Separator for accumulated text chunks |
| `postprocessor` | `None` | `(path, key, value)` → `(new_key, new_value)` or `None` to discard |
| `dict_constructor` | `dict` | Factory supporting empty construction and iterable key/value pairs |
| `strip_whitespace` | `True` | Strip leading/trailing text/comment whitespace |
| `namespaces` | `None` | Namespace URI → prefix mapping; `None`/empty prefix removes namespace |
| `force_list` | `None` | Boolean, collection of keys, or `(path, key, value)` predicate |
| `comment_key` | `"#comment"` | Dictionary key for comments |

Paths are lists of `(name, attributes_or_none)` pairs. Attribute mappings can
contain nested namespace mappings, so their values are `Any`. Item and value
arguments are also `Any`: XML content, callbacks, and custom factories change
their shape. `force_list` runs after the postprocessor, which may change key type.
Only actual generators are accepted as chunked input, not arbitrary iterators;
file-like inputs must return bytes from `read(size)` under CPython.

### Return inference and limits

- Default `item_depth=0` with no postprocessor returns `dict[str, Any]`.
- A typed custom `dict_constructor` preserves its mapping return type.
- A postprocessor or dynamic/nonzero depth widens the return to the mapping type
  or `None`. A postprocessor can discard the entire document or change key types.
- Streaming does **not** promise `None`: xmltodict 0.14.2 can return a mapping at
  depth 1; 1.0.4 drops streamed items, and comments can also affect the result.
- Nested XML schemas are not inferred. Narrow/validate nested values in your
  application; `Any` is deliberate rather than a claim of schema validation.
- Custom factories must implement the mutable-mapping behavior xmltodict needs.
  The callable is deliberately permissive (`Callable[..., MappingType]`), so
  typing does not prove its constructor protocol or runtime correctness.

`force_cdata` accepts a boolean, collection of names or predicate, following
xmltodict 1.0.4 semantics.

```python
from collections import OrderedDict
import rapidxmltodict as xml

plain = xml.parse('<root><item>1</item></root>', force_list=('item',))
# dict[str, Any]
ordered = xml.parse('<root/>', dict_constructor=OrderedDict)
# OrderedDict (nested value schema remains dynamic)
filtered = xml.parse('<root/>', postprocessor=lambda path, key, value: None)
# mapping | None
```

## `unparse`

Serialization is implemented locally, with xmltodict 1.0.4-compatible behavior.
The first six parameters may be positional. Other options are keyword-only.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `input_dict` | required | Root mapping; nested values follow xmltodict serialization rules |
| `output` | `None` | Text/binary output stream, or binary `write(bytes)` writer |
| `encoding` | `"utf-8"` | XML output encoding |
| `full_document` | `True` | Include declaration and enforce a single root |
| `short_empty_elements` | `False` | Emit short empty tags |
| `comment_key` | `"#comment"` | Comment key |
| `attr_prefix` | `"@"` | Attribute-key prefix |
| `cdata_key` | `"#text"` | Text key |
| `depth` | `0` | Initial emission/indent depth |
| `preprocessor` | `None` | `(key, value)` → replacement pair, or `None` to omit |
| `pretty` | `False` | Pretty-print output |
| `newl` | `"\n"` | Pretty-print newline |
| `indent` | `"\t"` | Indent string or number of spaces |
| `namespace_separator` | `":"` | Namespace separator |
| `namespaces` | `None` | Namespace URI → prefix mapping |
| `expand_iter` | `None` | Tag name for nested iterables; may break round-tripping |
| `bytes_errors` | `"replace"` | Byte-decoding error policy |

Without `output` (or with `output=None`), the return type is `str`. With an output
writer it is `None`; optional writers produce `str | None`. All listed options are implemented independently of installed dependencies. Nested non-dict mappings and scalar serialization remain subject
to xmltodict's runtime rules; accepting a top-level mapping does not guarantee all
nested objects serialize as expected.

## Verification

`tests/typing/check.py` copies fixtures outside the checkout and checks the
installed package with mypy and Pyright, targeting Python 3.9 and 3.12. Positive
cases assert return inference; negative cases require errors for typos, wrong
argument types, text readers, arbitrary iterators, and incorrect return assignments.
Jedi signature/completion tests exercise a static editor engine against the
installed stubs. This is not a manual test of every IDE or extension configuration.

## Exceptions and intentional differences

`expat` injection is not accepted. `ParseError` and `ParsingInterrupted` belong
to this package, rather than Expat or xmltodict; catch them from rapidxmltodict.
`ParseError` exposes `code`, `lineno`, `offset` and `byte_index` for diagnostics.
Exception class identity is intentionally different even where messages match.
