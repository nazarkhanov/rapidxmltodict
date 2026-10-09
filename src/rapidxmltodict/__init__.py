"""xmltodict-compatible parsing with a validated RapidXML fast path.

UTF-8 str/bytes and default parse options are accelerated. Other inputs/options
are delegated unchanged to xmltodict. No external entities are loaded by the
native path. See README for the precise compatibility/performance contract.
"""
import re as _re
from xml.parsers import expat as _expat
import xmltodict as _reference
from ._native import convert as _convert

_encoding_re = _re.compile(br"\bencoding\s*=\s*(['\"])([^'\"]+)\1")

from ._version import __version__
ParsingInterrupted = _reference.ParsingInterrupted
unparse = _reference.unparse


def parse(xml_input, encoding=None, expat=_expat, process_namespaces=False,
          namespace_separator=":", disable_entities=True,
          process_comments=False, **kwargs):
    """Parse XML into the same dictionary representation as xmltodict.parse.

    Advanced options, stream/generator inputs, DTDs, non-UTF-8 encodings and
    nesting deeper than 256 elements and whitespace-gap mixed content use the
    reference implementation.
    XML well-formedness is always checked; validation cannot be disabled.
    """
    def reference():
        return _reference.parse(xml_input, encoding=encoding, expat=expat,
            process_namespaces=process_namespaces,
            namespace_separator=namespace_separator,
            disable_entities=disable_entities, process_comments=process_comments,
            **kwargs)

    if (type(xml_input) not in (str, bytes) or encoding is not None
            or expat is not _expat or process_namespaces or process_comments
            or not disable_entities or kwargs or namespace_separator != ":"):
        return reference()
    data = xml_input.encode("utf-8") if type(xml_input) is str else xml_input
    # XML declarations can override byte encoding; the reference also encodes
    # Python str as UTF-8 before parsing its declaration. Preserve that behavior.
    if b"<!DOCTYPE" in data or b"\x00" in data:
        return reference()
    original_data = data
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if data.startswith(b"<?xml"):
        declaration_end = data.find(b"?>")
        declaration = data[:declaration_end + 2]
        declared_encoding = _encoding_re.search(declaration)
        if declared_encoding and declared_encoding.group(2).lower() not in (b"utf-8", b"utf8"):
            return reference()
    validator = _expat.ParserCreate()
    validator.Parse(original_data, True)
    try:
        result = _convert(data)
    except ValueError:
        # The preserved RapidXML fork rejects some valid general XML Names
        # (e.g. <root:/>); Expat has already established well-formedness.
        return reference()
    if result is NotImplemented:  # Depth or mixed-content compatibility guard.
        return reference()
    return result


__all__ = ["parse", "unparse", "ParsingInterrupted", "__version__"]
