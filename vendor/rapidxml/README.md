# Vendored RapidXML

This is a **modified RapidXML 1.13** integration. The base header comes from the
[official release archive](https://sourceforge.net/projects/rapidxml/files/rapidxml/rapidxml%201.13/rapidxml-1.13.zip/download).

- Upstream archive SHA-256: `c3f0b886374981bb20fabcf323d755db4be6dba42064599481da64a85f5b3571`
- Unmodified upstream header SHA-256: `d61c53fd63f11aef0e18d253746ee800903dc82e4ad3cc533d0fdca69f07c4f9`

Project changes integrate strict, bounded UTF-8/XML parsing and normalization
into RapidXML's parsing routines, with compact text spans and a resumable event
interface. The bounded read-only DOM mode exposes validated immutable raw spans
and packed normalization metadata without increasing node or attribute sizes;
the Python binding performs normalization directly into final output strings. DOM and stream parsing share consuming tag/attribute grammar and
lexical primitives through the additional headers in this directory. The header
is no longer byte-for-byte upstream; the hashes above identify its base, not the
modified files. The separate PR #5 retains the unmodified upstream migration.

The original Boost/MIT dual license and copyright remain unchanged in
`license.txt` and the upstream header. Copyright: Marcin Kalicinski. Project
extension headers identify their origin and are covered by the repository's
MIT license.
