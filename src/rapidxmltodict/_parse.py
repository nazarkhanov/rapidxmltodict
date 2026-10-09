"""Standalone dictionary mapping and incremental input decoding.

The dictionary handler below is adapted from xmltodict 1.0.4. XML tokenization,
validation, DTD processing and entity expansion are implemented by the native
RapidXML-backed event parser; no alternative XML parser is imported here.
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


class _DictSAXHandler:
    def __init__(
        self,
        item_depth=0,
        item_callback=lambda *args: True,
        xml_attribs=True,
        attr_prefix="@",
        cdata_key="#text",
        force_cdata=False,
        cdata_separator="",
        postprocessor=None,
        dict_constructor=dict,
        strip_whitespace=True,
        namespace_separator=":",
        namespaces=None,
        force_list=None,
        comment_key="#comment",
    ):
        self.path = []
        self.stack = []
        self.data = []
        self.item = None
        self.item_depth = item_depth
        self.xml_attribs = xml_attribs
        self.item_callback = item_callback
        self.attr_prefix = attr_prefix
        self.cdata_key = cdata_key
        self.force_cdata = force_cdata
        self.cdata_separator = cdata_separator
        self.postprocessor = postprocessor
        self.dict_constructor = dict_constructor
        self.strip_whitespace = strip_whitespace
        self.namespace_separator = namespace_separator
        self.namespaces = namespaces
        self.namespace_declarations = dict_constructor()
        self.force_list = force_list
        self.comment_key = comment_key

    def _build_name(self, full_name):
        if self.namespaces is None:
            return full_name
        i = full_name.rfind(self.namespace_separator)
        if i == -1:
            return full_name
        namespace, name = full_name[:i], full_name[i+1:]
        try:
            short_namespace = self.namespaces[namespace]
        except KeyError:
            short_namespace = namespace
        if not short_namespace:
            return name
        else:
            return self.namespace_separator.join((short_namespace, name))

    def _attrs_to_dict(self, attrs):
        if isinstance(attrs, dict):
            return attrs
        return self.dict_constructor(zip(attrs[0::2], attrs[1::2]))

    def startNamespaceDecl(self, prefix, uri):
        self.namespace_declarations[prefix or ''] = uri

    def startElement(self, full_name, attrs):
        name = self._build_name(full_name)
        attrs = self._attrs_to_dict(attrs)
        if self.namespace_declarations:
            if not attrs:
                attrs = self.dict_constructor()
            attrs['xmlns'] = self.namespace_declarations
            self.namespace_declarations = self.dict_constructor()
        self.path.append((name, attrs or None))
        if len(self.path) >= self.item_depth:
            self.stack.append((self.item, self.data))
            if self.xml_attribs:
                attr_entries = []
                for key, value in attrs.items():
                    key = self.attr_prefix+self._build_name(key)
                    if self.postprocessor:
                        entry = self.postprocessor(self.path, key, value)
                    else:
                        entry = (key, value)
                    if entry:
                        attr_entries.append(entry)
                attrs = self.dict_constructor(attr_entries)
            else:
                attrs = None
            self.item = attrs or None
            self.data = []

    def endElement(self, full_name):
        name = self._build_name(full_name)
        # If we just closed an item at the streaming depth, emit it and drop it
        # without attaching it back to its parent. This avoids accumulating all
        # streamed items in memory when using item_depth > 0.
        if len(self.path) == self.item_depth:
            item = self.item
            if item is None:
                item = (None if not self.data
                        else self.cdata_separator.join(self.data))

            should_continue = self.item_callback(self.path, item)
            if not should_continue:
                raise ParsingInterrupted
            # Reset state for the parent context without keeping a reference to
            # the emitted item.
            if self.stack:
                self.item, self.data = self.stack.pop()
            else:
                self.item = None
                self.data = []
            self.path.pop()
            return
        if self.stack:
            data = (None if not self.data
                    else self.cdata_separator.join(self.data))
            item = self.item
            self.item, self.data = self.stack.pop()
            if self.strip_whitespace and data:
                data = data.strip() or None
            if data and self._should_force_cdata(name, data) and item is None:
                item = self.dict_constructor()
            if item is not None:
                if data:
                    self.push_data(item, self.cdata_key, data)
                self.item = self.push_data(self.item, name, item)
            else:
                self.item = self.push_data(self.item, name, data)
        else:
            self.item = None
            self.data = []
        self.path.pop()

    def characters(self, data):
        if not self.data:
            self.data = [data]
        else:
            self.data.append(data)

    def comments(self, data):
        if self.strip_whitespace:
            data = data.strip()
        self.item = self.push_data(self.item, self.comment_key, data)

    def push_data(self, item, key, data):
        if self.postprocessor is not None:
            result = self.postprocessor(self.path, key, data)
            if result is None:
                return item
            key, data = result
        if item is None:
            item = self.dict_constructor()
        try:
            value = item[key]
            if isinstance(value, list):
                value.append(data)
            else:
                item[key] = [value, data]
        except KeyError:
            if self._should_force_list(key, data):
                item[key] = [data]
            else:
                item[key] = data
        return item

    def _should_force_list(self, key, value):
        if not self.force_list:
            return False
        if isinstance(self.force_list, bool):
            return self.force_list
        try:
            return key in self.force_list
        except TypeError:
            return self.force_list(self.path[:-1], key, value)

    def _should_force_cdata(self, key, value):
        if not self.force_cdata:
            return False
        if isinstance(self.force_cdata, bool):
            return self.force_cdata
        try:
            return key in self.force_cdata
        except TypeError:
            return self.force_cdata(self.path[:-1], key, value)


_XML_NAMESPACE = 'http://www.w3.org/XML/1998/namespace'
_XMLNS_NAMESPACE = 'http://www.w3.org/2000/xmlns/'
_ENCODING = re.compile(br'\bencoding\s*=\s*([\'\"])([^\'\"]+)\1')


def _error(message, code=4, lineno=1, offset=0, byte_index=0):
    error = ParseError('%s: line %d, column %d' % (message, lineno, offset))
    error.code = code
    error.lineno = lineno
    error.offset = offset
    error.byte_index = byte_index
    return error


class _NamespaceSink:
    """Translate raw native events into xmltodict's namespace-aware events."""

    def __init__(self, handler, process_namespaces, separator, process_comments):
        self.handler = handler
        self.process_namespaces = process_namespaces and separator is not None
        self.separator = separator
        self.process_comments = process_comments
        self.bindings = {'xml': _XML_NAMESPACE}
        self.scopes = []

    def _error(self, message, code=4):
        parser = getattr(self, 'parser', None)
        return _error(message, code, getattr(parser, 'lineno', 1),
                      getattr(parser, 'offset', 0), getattr(parser, 'byte_index', 0))

    def _name(self, name, attribute=False):
        parts = name.split(':')
        if len(parts) > 2 or any(not part for part in parts):
            raise self._error('not well-formed (invalid token)')
        if len(parts) == 2:
            prefix, local = parts
            if prefix not in self.bindings:
                raise self._error('unbound prefix', 27)
            uri = self.bindings[prefix]
        else:
            local = name
            uri = None if attribute else self.bindings.get('')
        if uri:
            return uri + self.separator + local
        return local

    def start(self, name, attributes):
        if not self.process_namespaces:
            self.handler.startElement(name, [value for pair in attributes for value in pair])
            return
        previous = self.bindings
        declarations = []
        ordinary = []
        for key, value in attributes:
            if key == 'xmlns':
                declarations.append(('', value))
            elif key.startswith('xmlns:'):
                prefix = key[6:]
                if not prefix or ':' in prefix:
                    raise self._error('not well-formed (invalid token)')
                declarations.append((prefix, value))
            else:
                ordinary.append((key, value))
        if declarations:
            self.bindings = previous.copy()
        for prefix, uri in declarations:
            if prefix == 'xmlns':
                raise self._error('reserved prefix (xmlns) must not be declared or undeclared', 39)
            if prefix == 'xml' and uri != _XML_NAMESPACE:
                raise self._error('reserved prefix (xml) must not be undeclared or bound to another namespace name', 38)
            if uri == _XMLNS_NAMESPACE or (uri == _XML_NAMESPACE and prefix != 'xml'):
                raise self._error('prefix must not be bound to one of the reserved namespace names', 40)
            if prefix and not uri:
                raise self._error('must not undeclare prefix', 28)
            # A colon in a namespace URI is ordinary. Other nonempty separators
            # may not occur in URIs, matching the namespace parser interface.
            if self.separator and self.separator != ':' and self.separator in uri:
                raise self._error('syntax error', 2)
            self.bindings[prefix] = uri or None
            self.handler.startNamespaceDecl(prefix or None, uri or None)
        expanded = []
        used = set()
        for key, value in ordinary:
            key = self._name(key, attribute=True)
            if key in used:
                raise self._error('duplicate attribute', 8)
            used.add(key)
            expanded.extend((key, value))
        full_name = self._name(name)
        self.scopes.append(previous)
        self.handler.startElement(full_name, expanded)

    def end(self, name):
        if self.process_namespaces:
            self.handler.endElement(self._name(name))
            self.bindings = self.scopes.pop()
        else:
            self.handler.endElement(name)

    def text(self, data):
        self.handler.characters(data)

    def comment(self, data):
        if self.process_comments:
            self.handler.comments(data)


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
    # incremental Python callbacks use the same validating native event engine.
    if (type(xml_input) in (str, bytes) and encoding is None and not kwargs
            and not process_namespaces and not process_comments
            and disable_entities and namespace_separator == ':'):
        data = xml_input.encode('utf-8') if isinstance(xml_input, str) else xml_input
        probe = data[3:] if data.startswith(codecs.BOM_UTF8) else data
        declared = None
        if probe.startswith(b'<?xml'):
            declaration_end = probe.find(b'?>')
            declared = _ENCODING.search(probe[:declaration_end + 2])
        if (b'<!DOCTYPE' not in data and b'\x00' not in data
                and (declared is None or isinstance(xml_input, str)
                     or declared.group(2).lower() == b'utf-8')):
            _native.validate(data, disable_entities=True)
            try:
                result = _native.convert(probe)
            except ValueError:
                result = NotImplemented
            if result is not NotImplemented:
                return result
    handler = _DictSAXHandler(namespace_separator=namespace_separator, **kwargs)
    if process_namespaces and namespace_separator is not None:
        if not isinstance(namespace_separator, str):
            raise TypeError('namespace_separator must be str or None')
        if len(namespace_separator.encode('utf-8')) > 1:
            raise ValueError('namespace_separator must be at most one character, omitted, or None')
        if '\x00' in namespace_separator:
            raise ValueError('embedded null character')
    sink = _NamespaceSink(handler, process_namespaces, namespace_separator,
                          process_comments)
    parser = NativeParser(sink, disable_entities=disable_entities,
                          process_comments=process_comments)
    sink.parser = parser
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
        return handler.item
    finally:
        # The native parser owns its sink. Keep the reverse reference only
        # while callbacks need diagnostic positions, so completed/error parses
        # release their handler, input buffers and output without cyclic GC.
        sink.parser = None
