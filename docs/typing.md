# API and editor hints

The installed wheel and source distribution include `rapidxmltodict/__init__.pyi`
and the PEP 561 `py.typed` marker. Editors using these stubs can show all known
keyword arguments and return types for `parse` and `unparse`. Select the Python
environment where this package is installed. No separate `types-rapidxmltodict`
package is needed. Runtime signatures and forwarding behavior are unchanged.

The stubs describe the supported API of xmltodict 0.14.2 and 1.0.4. They do not
accept an unrestricted `**kwargs`: misspelled and unknown options are type errors.
Future xmltodict additions may require a stub update. The installed dependency
still determines which version-specific options work and how they behave.

## `parse`

The first seven parameters may also be positional. All following parameters are
keyword-only, forwarded unchanged to xmltodict when provided.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `xml_input` | required | XML text, bytes/bytearray/memoryview, binary reader, or actual generator of chunks |
| `encoding` | `None` | Explicit input encoding; otherwise declaration/default detection |
| `expat` | standard Expat module | Compatible custom parser module; intentionally typed `Any` |
| `process_namespaces` | `False` | Expand XML namespaces |
| `namespace_separator` | `":"` | Separator between namespace and local name |
| `disable_entities` | `True` | Installed xmltodict's entity restriction policy |
| `process_comments` | `False` | Include XML comments |
| `item_depth` | `0` | Depth at which `item_callback` receives completed items |
| `item_callback` | always truthy | `(path, item)`; a false-ish return raises `ParsingInterrupted` |
| `xml_attribs` | `True` | Include element attributes |
| `attr_prefix` | `"@"` | Attribute-key prefix |
| `cdata_key` | `"#text"` | Text key in dictionary-valued elements |
| `force_cdata` | `False` | Force text into dictionaries; see version note below |
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

With 1.0.4, `force_cdata` also accepts a collection of names or a predicate.
With 0.14.2, **any truthy collection/callable forces all text**, without selective
matching or invoking that predicate. Use booleans for version-independent behavior.

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

This remains the installed `xmltodict.unparse` function, re-exported unchanged.
The first five parameters may be positional; `comment_key` is additionally
positional in 1.0.4. Other options are keyword-only.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `input_dict` | required | Root mapping; nested values follow xmltodict serialization rules |
| `output` | `None` | Text/binary output stream, or binary `write(bytes)` writer |
| `encoding` | `"utf-8"` | XML output encoding |
| `full_document` | `True` | Include declaration and enforce a single root |
| `short_empty_elements` | `False` | Emit short empty tags |
| `comment_key` | `"#comment"` | Comment key; **requires xmltodict 1.0.4** in the tested versions |
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
| `bytes_errors` | `"replace"` | Byte-decoding error policy; **requires xmltodict 1.0.4** in tested versions |

Without `output` (or with `output=None`), the return type is `str`. With an output
writer it is `None`; optional writers produce `str | None`. `comment_key` and
`bytes_errors` are shown by static tooling but are rejected by xmltodict 0.14.2
when explicitly passed. Type checkers cannot select signatures from a dependency's
installed version. Nested non-dict mappings and scalar serialization remain subject
to xmltodict's runtime rules; accepting a top-level mapping does not guarantee all
nested objects serialize as expected.

## Verification

`tests/typing/check.py` copies fixtures outside the checkout and checks the
installed package with mypy and Pyright, targeting Python 3.9 and 3.12. Positive
cases assert return inference; negative cases require errors for typos, wrong
argument types, text readers, arbitrary iterators, and incorrect return assignments.
Jedi signature/completion tests exercise a static editor engine against the
installed stubs. This is not a manual test of every IDE or extension configuration.
