"""Input decoding and dispatch for native RapidXML parsing and mapping.

Both dictionary construction paths are implemented in C++. Python only drives
input decoding and reading; user-requested callbacks retain their Python API.
"""
# Copyright (C) 2012 Martin Blech and individual contributors.
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import codecs
from inspect import isgenerator
import re

from . import _native
from ._native import NativeParser, ParseError


class ParsingInterrupted(Exception):
    """Raised when an item callback asks to stop parsing."""


_ENCODING = re.compile(br'\bencoding\s*=\s*([\'\"])([^\'\"]+)\1')


def _error(message, code=4, lineno=1, offset=0, byte_index=0):
    error = ParseError('%s: line %d, column %d' % (message, lineno, offset))
    error.code = code
    error.lineno = lineno
    error.offset = offset
    error.byte_index = byte_index
    return error


class _SingleByteDecoder:
    """The encoding callback's one-byte mapping, without an XML dependency."""

    def __init__(self, encoding):
        # XML's unknown-encoding hook only supports character maps that decode
        # one byte to one Unicode character. Do not silently enable UTF-7,
        # Shift-JIS, or other encodings the reference interface rejects.
        mapping = bytes(range(256)).decode(encoding, 'replace')
        if len(mapping) != 256:
            raise ValueError('multi-byte encodings are not supported')
        # XML's unknown-encoding callback requires an ASCII-compatible map.
        # EBCDIC and similar codecs must not become newly accepted encodings.
        if any(mapping[byte] != chr(byte) for byte in (*range(32, 127), 9, 10, 13)):
            raise _error('unknown encoding', 18)
        self.mapping = mapping.replace('\ufffd', '\ufffe')

    def decode(self, data, final=False):
        return codecs.charmap_decode(data, 'strict', self.mapping)[0]

    def getstate(self):
        return b'', 0

    def setstate(self, state):
        pass


class _DeclarationDecoder:
    """Handle an unknown single-byte declaration following a UTF-16 prefix.

    The reference encoding callback switches at the declaration boundary even
    for this unusual mixed-encoding input. Preserve that behavior rather than
    accepting the entire document as UTF-16 regardless of its declaration.
    """

    def __init__(self, initial_encoding, declaration_bytes, tail):
        self.initial = codecs.getincrementaldecoder(initial_encoding)('strict')
        self.remaining = declaration_bytes
        self.tail = tail

    def decode(self, data, final=False):
        prefix_size = min(self.remaining, len(data))
        prefix = self.initial.decode(data[:prefix_size], final and prefix_size == len(data))
        self.remaining -= prefix_size
        try:
            return prefix + self.tail.decode(data[prefix_size:], final)
        except UnicodeDecodeError as error:
            raise UnicodeDecodeError(error.encoding, data, prefix_size + error.start,
                                     prefix_size + error.end, error.reason) from None

    def getstate(self):
        state = self.initial.getstate()
        return state[0], (self.remaining, state)

    def setstate(self, state):
        self.remaining, initial_state = state[1]
        self.initial.setstate(initial_state)


class _InputDecoder:
    """Decode only consumed chunks, including declarations split across reads."""

    def __init__(self, parser, encoding):
        if encoding is not None and not isinstance(encoding, str):
            raise TypeError('encoding must be str or None')
        self.parser = parser
        self.encoding = encoding
        self.decoder = None
        self.native_utf8 = False
        self.input_started = False
        self.pending = bytearray()
        self.pending_chunks = []
        self.line = 1
        self.column = 0
        self.byte_index = 0

    def _select(self, final):
        data = bytes(self.pending)
        if len(data) < 4 and not final:
            return False
        magic = None
        if data.startswith(b'\xff\xfe'):
            magic = 'utf-16-le'
        elif data.startswith(b'\xfe\xff'):
            magic = 'utf-16-be'
        elif data.startswith(b'<\x00'):
            magic = 'utf-16-le'
        elif data.startswith(b'\x00<'):
            magic = 'utf-16-be'
        override = self.encoding.lower() if self.encoding is not None else None
        builtin = ('utf-8', 'utf-16', 'utf-16le', 'utf-16be', 'iso-8859-1', 'us-ascii')
        # Built-in XML encodings retain signature autodetection even when an
        # explicit encoding was supplied; Python codec aliases do not.
        if override in builtin and magic:
            self.decoder = codecs.getincrementaldecoder(magic)('strict')
            return True
        if override in builtin and data.startswith(codecs.BOM_UTF8):
            self.native_utf8 = True
            self.decoder = codecs.getincrementaldecoder('utf-8-sig')('strict')
            return True
        if magic and self.encoding is None:
            probe = data.decode(magic, 'ignore').lstrip('\ufeff')
            if '<?xml'.startswith(probe) and not final:
                return False
            if probe.startswith('<?xml') and (len(probe) == 5 or probe[5:6] in ' \t\r\n'):
                end = probe.find('?>')
                if end < 0 and not final:
                    return False
                match = _ENCODING.search(probe[:end + 2].encode('utf-8'))
                if match:
                    label = match.group(2).decode('ascii', 'replace').lower()
                    valid = ('utf-16', 'utf-16le' if magic == 'utf-16-le' else 'utf-16be')
                    if label in builtin and label not in valid:
                        bom_column = int(data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)))
                        column = match.start(2) + bom_column
                        raise _error('encoding specified in XML declaration is incorrect',
                                     19, offset=column, byte_index=column * 2)
                    if label not in builtin and re.fullmatch(r'[a-z][a-z0-9._-]*', label):
                        tail = _SingleByteDecoder(label)
                        bom_size = 2 if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else 0
                        self.decoder = _DeclarationDecoder(magic, (end + 2) * 2 + bom_size, tail)
                        return True
        if self.encoding is not None:
            name = self.encoding
        elif magic:
            name = 'utf-16'
        else:
            probe = data[3:] if data.startswith(codecs.BOM_UTF8) else data
            if b'<?xml'.startswith(probe) and not final:
                return False
            if probe.startswith(b'<?xml') and (len(probe) == 5 or probe[5:6] in b' \t\r\n'):
                end = probe.find(b'?>')
                if end < 0 and not final:
                    return False
                match = _ENCODING.search(probe[:end + 2] if end >= 0 else probe)
                label = match.group(2) if match else b'utf-8'
                # Invalid declaration labels belong to XML validation, not the
                # Python codec registry (which would raise the wrong error).
                name = (label.decode('ascii') if re.fullmatch(br'[A-Za-z][A-Za-z0-9._-]*', label)
                        else 'utf-8')
            else:
                name = 'utf-8'
        canonical = name.lower()
        if canonical == 'utf-8':
            self.native_utf8 = True
            self.decoder = codecs.getincrementaldecoder('utf-8-sig')('strict')
        elif canonical in ('utf-16', 'utf-16le', 'utf-16be'):
            if magic is None:
                if self.encoding is not None:
                    raise _error('not well-formed (invalid token)', 4)
                column = match.start(2) + int(data.startswith(codecs.BOM_UTF8)) if match else 0
                raise _error('encoding specified in XML declaration is incorrect', 19,
                             offset=column, byte_index=column)
            # Preserve the BOM as U+FEFF for native position accounting.
            self.decoder = codecs.getincrementaldecoder(magic)('strict')
        elif canonical in ('iso-8859-1', 'us-ascii') and magic:
            # Preserve the BOM as U+FEFF for native position accounting.
            self.decoder = codecs.getincrementaldecoder(magic)('strict')
        else:
            self.decoder = _SingleByteDecoder(name)
        return True

    def _feed_text(self, text, final=False, undecoded_bytes=0):
        # Do not filter empty feeds: boundaries are observable to cdata_separator.
        self.parser.feed(text, final, undecoded_bytes=undecoded_bytes)
        if '\n' in text:
            self.line += text.count('\n')
            self.column = len(text.rsplit('\n', 1)[1])
        else:
            self.column += len(text)

    def feed(self, data, final=False):
        if isinstance(data, str):
            # A first Unicode Parse call selects UTF-8. Once parsing has begun,
            # subsequent Unicode chunks are UTF-8 bytes interpreted using the
            # already-selected input encoding, including a declaration's codec.
            if not self.input_started:
                self.encoding = 'utf-8'
            data = data.encode('utf-8')
        try:
            data = memoryview(data).tobytes()
        except TypeError:
            raise TypeError("a bytes-like object is required, not '%s'" % type(data).__name__) from None
        self.input_started = True
        if self.decoder is None:
            self.pending.extend(data)
            self.pending_chunks.append(data)
            if not self._select(final):
                return
            if self.native_utf8:
                self.parser.set_source_encoding('utf8')
            elif isinstance(self.decoder, _SingleByteDecoder):
                self.parser.set_source_encoding('singlebyte')
            else:
                self.parser.set_source_encoding('utf16')
            chunks = self.pending_chunks
            self.pending_chunks = []
            self.pending.clear()
            # Replay the original feed boundaries after sniffing the encoding.
            # Joining them would change buffer_text/cdata_separator behavior.
            for index, chunk in enumerate(chunks):
                self.feed(chunk, final and index == len(chunks) - 1)
            return
        if self.native_utf8:
            # Native UTF-8 validation preserves partial-byte input boundaries
            # and exact byte positions without a decode/re-encode round trip.
            self.parser.feed(data, final)
            self.byte_index += len(data)
            return
        state = self.decoder.getstate()
        try:
            text = self.decoder.decode(data, final)
        except UnicodeDecodeError as error:
            # Preserve item callback ordering: completed items before an invalid
            # byte still run, and can interrupt before that byte is processed.
            self.decoder.setstate(state)
            prefix_length = max(0, error.start - len(state[0]))
            prefix = self.decoder.decode(data[:prefix_length], False)
            if prefix:
                self._feed_text(prefix)
            raise _error('not well-formed (invalid token)', 4, self.line,
                         self.column, self.byte_index + prefix_length) from None
        self._feed_text(text, final, len(self.decoder.getstate()[0]))
        self.byte_index += len(data)


def parse(xml_input, encoding=None, process_namespaces=False,
          namespace_separator=':', disable_entities=True, process_comments=False,
          **kwargs):
    """Parse XML into dictionaries using the standalone native XML engine.

    Supports xmltodict 1.0.4's mapping, namespace, comment and streaming options.
    ``xml_input`` may be text, bytes-like data, a binary file, or a generator of
    text/byte chunks. An item callback returning false stops both parsing and
    input consumption immediately with :class:`ParsingInterrupted`.

    Entity declarations raise ValueError by default. With disable_entities=False,
    internal entities are processed; external resources are never fetched.
    There is deliberately no ``expat`` parser-injection parameter.
    """
    # Keep the all-native default mapping path. Documents/options requiring
    # incremental input or mapping options use direct native event construction.
    if (type(xml_input) in (str, bytes) and encoding is None and not kwargs
            and process_namespaces is False and process_comments is False
            and disable_entities is True and type(namespace_separator) is str
            and namespace_separator == ':'):
        data = xml_input.encode('utf-8') if isinstance(xml_input, str) else xml_input
        # Only inspect the encoding declaration/prefix to select the decoder.
        # Strict well-formedness validation happens inside RapidXML conversion.
        begin = 3 if data.startswith(codecs.BOM_UTF8) else 0
        declared = None
        if data.startswith(b'<?xml', begin):
            declaration_end = data.find(b'?>', begin)
            declared = _ENCODING.search(data[begin:declaration_end + 2])
        wide_input = (data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
                      or b'\x00' in data[:4])
        if (not wide_input and (declared is None or isinstance(xml_input, str)
                                or declared.group(2).lower() == b'utf-8')):
            result = _native.convert(data)
            if result is not NotImplemented:
                return result
    return _parse_native_events(
        xml_input, encoding=encoding, process_namespaces=process_namespaces,
        namespace_separator=namespace_separator, disable_entities=disable_entities,
        process_comments=process_comments, **kwargs)


def _parse_native_events(xml_input, encoding=None, process_namespaces=False,
                         namespace_separator=':', disable_entities=True,
                         process_comments=False, **kwargs):
    """Private architecture comparator: direct C++ mapping, without a DOM."""
    parser = _native.NativeMappingParser(
        disable_entities=disable_entities, process_namespaces=process_namespaces,
        namespace_separator=namespace_separator, process_comments=process_comments,
        interrupted=ParsingInterrupted, **kwargs)
    try:
        if isinstance(xml_input, str):
            encoding = encoding or 'utf-8'
            xml_input = xml_input.encode(encoding)
        decoder = _InputDecoder(parser, encoding)
        if hasattr(xml_input, 'read'):
            while True:
                chunk = xml_input.read(2048)
                if not isinstance(chunk, bytes):
                    raise TypeError('read() did not return a bytes object (type=%s)' % type(chunk).__name__)
                if not chunk:
                    decoder.feed(b'', True)
                    break
                decoder.feed(chunk)
        elif isgenerator(xml_input):
            for chunk in xml_input:
                decoder.feed(chunk)
            decoder.feed(b'', True)
        else:
            decoder.feed(xml_input, True)
        return parser.result
    finally:
        parser.close()
