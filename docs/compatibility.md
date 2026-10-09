# Compatibility contract

The package targets xmltodict **1.0.4**, with an exact canonical test environment:
**CPython 3.12.15, Expat 2.8.5, reparse deferral enabled**. The required
`reference-104` CI job checks the actual runtime versions and regenerates the
version-sensitive expectations in memory. A mismatch fails; CI never silently
updates the checked-in fixtures. Expat and xmltodict are test tools only.

## Deliberate differences

- The `expat` parser-injection parameter is removed.
- `rapidxmltodict.ParseError` and `rapidxmltodict.ParsingInterrupted` are package-owned
  classes. Catching Expat's or xmltodict's classes will not catch these exceptions.
  ParseError includes `code`, `lineno`, `offset`, and `byte_index`.
- XML declaration versions follow `1.[0-9]+`. Older Expat releases accepted
  malformed values such as `104`, `abc` or `2.0`; this implementation rejects them
  consistently across platforms. This follows the [Expat 2.8.5 change](https://github.com/libexpat/libexpat/blob/R_2_8_5/expat/Changes)
  and [XML 1.0 fifth-edition VersionNum grammar](https://www.w3.org/TR/REC-xml/#NT-VersionNum).
- Text-event boundaries follow the canonical modern reference. Older Expat
  builds without reparse deferral can split the same tiny input chunks
  differently, which changes the placement of a nonempty `cdata_separator`.
  [Reparse deferral](https://docs.python.org/3.12/library/pyexpat.html#xmlparser.SetReparseDeferralEnabled)
  is an observable parser behavior, not merely a performance switch.

The general supported-platform tests still compare directly with xmltodict.
For the specifically version-sensitive chunking cases, every platform checks
identical canonical fixtures and also performs a live-oracle comparison using
the default empty separator. Callback order, interruption and input consumption
remain independently tested; empty-separator equality alone is insufficient.

## Implementation and boundaries

The common in-memory UTF-8 path uses bounded strict parsing inside RapidXML.
Well-formedness checks, UTF-8 handling and XML normalization run as its parsing
routines consume input. The native builder then converts the DOM into Python
objects; this necessary output traversal is separate from XML parsing.

The resumable event interface shares consuming opening/closing-tag grammar and
attribute decoding with the DOM parser. It emits directly from parser state,
without synthesizing XML or building temporary tag DOMs. Document/DTD policy and
text-event batching retain their streaming-specific state. Completed items are
not attached back to the document result; a caller retaining callback values
still retains memory.

DTD input or depth beyond 256 levels in the bounded recursive DOM path can
request a restart through the event interface. The depth limit protects the
recursive parser and dictionary builder; it is not a limit on accepted XML.
Restarting reparses the consumed prefix, which can include many earlier siblings,
and is a remaining performance limitation for deep documents. Therefore the
common path has one semantic XML
parse, but the package does not claim every possible path or diagnostic operation
is a single scan. Input decoding and error-location accounting also have costs.

Serialization implements the 1.0.4 output contract using standard-library output
helpers, without loading an XML parser. External entities are never fetched.
Applications must impose suitable input, output, time and memory limits.

The differential corpus, sanitizer checks and installed-artifact tests establish
coverage of exercised behavior. They do not prove equivalence for every XML
input, custom Python object, allocation failure or future reference release.
