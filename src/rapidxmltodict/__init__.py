"""RapidXML-based XML dictionaries, compatible with xmltodict 1.0.4.

Parsing and serialization have no xmltodict or Expat runtime dependency.
Expat injection is intentionally unsupported; ParseError and ParsingInterrupted
are package-owned exception classes.
"""
from ._version import __version__
from ._native import ParseError
from ._parse import ParsingInterrupted, parse
from ._serialize import unparse

__all__ = ['parse', 'unparse', 'ParsingInterrupted', 'ParseError', '__version__']
