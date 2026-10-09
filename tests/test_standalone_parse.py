"""The 1.0.4 oracle is a test dependency, never a runtime parser backend."""

from collections import OrderedDict
from copy import deepcopy
from io import BytesIO, StringIO

import pytest
import xmltodict

import rapidxmltodict
from rapidxmltodict._parse import parse


DOCUMENT = '<r z="a"> before <!-- note --><a>one</a><a/><b> two </b><![CDATA[ after ]]></r>'


@pytest.mark.parametrize('options', [
    {}, {'xml_attribs': False}, {'attr_prefix': '$'}, {'cdata_key': 'text'},
    {'force_cdata': True}, {'force_cdata': ('a',)},
    {'force_cdata': lambda path, key, value: key == 'b'},
    {'force_list': True}, {'force_list': ('b',)},
    {'force_list': lambda path, key, value: key == 'b'},
    {'strip_whitespace': False}, {'cdata_separator': '|'},
    {'dict_constructor': OrderedDict}, {'process_comments': True},
    {'process_comments': True, 'comment_key': 'comments', 'strip_whitespace': False},
    {'postprocessor': lambda path, key, value: (key.upper(), value)},
    {'postprocessor': lambda path, key, value: None if key == 'b' else (key, value)},
])
def test_all_mapping_options(options):
    expected = xmltodict.parse(DOCUMENT, **options)
    actual = parse(DOCUMENT, **options)
    assert actual == expected
    assert type(actual) is type(expected)


@pytest.mark.parametrize('separator', [':', '|', '', None])
@pytest.mark.parametrize('mapping', [None, {'urn:root': None, 'urn:p': 'short'}])
@pytest.mark.parametrize('xml_attribs', [True, False])
def test_namespace_scopes(separator, mapping, xml_attribs):
    doc = '<r xmlns="urn:root" xmlns:p="urn:p" p:a="v"><p:x/><x xmlns=""/><x xmlns:p="urn:q"><p:y/></x><p:z xml:lang="en"/></r>'
    options = dict(process_namespaces=True, namespace_separator=separator,
                   namespaces=mapping, xml_attribs=xml_attribs)
    # xmltodict's optional name shortening itself rejects an empty/None separator.
    try:
        expected = xmltodict.parse(doc, **options)
    except (TypeError, ValueError) as error:
        with pytest.raises(type(error)):
            parse(doc, **options)
    else:
        assert parse(doc, **options) == expected


@pytest.mark.parametrize('doc', [
    '<p:r/>', '<r xmlns:p=""/>', '<r xmlns:xml="wrong"/>',
    '<r xmlns:xmlns="wrong"/>',
    '<r xmlns:p="http://www.w3.org/XML/1998/namespace"/>',
    '<r xmlns="http://www.w3.org/2000/xmlns/"/>',
    '<r xmlns:a="u" xmlns:b="u" a:x="1" b:x="2"/>',
    '<a:b:c xmlns:a="u"/>', '<:r/>', '<r:/>',
])
def test_namespace_errors(doc):
    with pytest.raises(Exception):
        xmltodict.parse(doc, process_namespaces=True)
    with pytest.raises(rapidxmltodict.ParseError):
        parse(doc, process_namespaces=True)


@pytest.mark.parametrize('encoding,declared', [
    ('utf-8', 'UTF-8'), ('utf-8-sig', 'UTF-8'), ('utf-16', 'UTF-16'),
    ('utf-16-le', 'UTF-16LE'), ('utf-16-be', 'UTF-16BE'),
    ('iso-8859-1', 'ISO-8859-1'), ('cp1252', 'windows-1252'),
])
@pytest.mark.parametrize('chunk_size', [1, 2, 7, 4096])
def test_incremental_encoding_detection(encoding, declared, chunk_size):
    doc = ('<?xml version="1.0" encoding="%s"?><r a="café">élève</r>' % declared).encode(encoding)
    def chunks():
        yield from (doc[i:i + chunk_size] for i in range(0, len(doc), chunk_size))
    assert parse(chunks()) == xmltodict.parse(chunks())


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'iso-8859-1', 'windows-1252'])
def test_explicit_encodings(encoding):
    doc = '<r a="café">élève</r>'
    assert parse(doc, encoding=encoding) == xmltodict.parse(doc, encoding=encoding)
    assert parse(doc.encode(encoding), encoding=encoding) == xmltodict.parse(doc.encode(encoding), encoding=encoding)


def test_unicode_declaration_is_overridden():
    doc = '<?xml version="1.0" encoding="ISO-8859-1"?><r>日本語</r>'
    assert parse(doc) == xmltodict.parse(doc)
    assert parse(iter_unicode_chunks(doc)) == xmltodict.parse(iter_unicode_chunks(doc))


def iter_unicode_chunks(doc):
    for char in doc:
        yield char


@pytest.mark.parametrize('depth', [0, 1, 2, 3, 4])
def test_streaming_paths_and_value_semantics(depth):
    doc = '<r a="x"><i n="1"> first </i><i n="2"><v>two</v> tail </i><i/></r>'
    def run(parse_function):
        calls = []
        def callback(path, item):
            calls.append(deepcopy((path, item)))
            return True
        result = parse_function(doc, item_depth=depth, item_callback=callback)
        return result, calls
    assert run(parse) == run(xmltodict.parse)


def test_interruption_stops_generator_consumption():
    consumed = []
    def chunks():
        consumed.append(1)
        yield '<r><i>one</i>'
        consumed.append(2)
        raise AssertionError('The generator must not resume after interruption')
    with pytest.raises(rapidxmltodict.ParsingInterrupted):
        parse(chunks(), item_depth=2, item_callback=lambda path, item: False)
    assert consumed == [1]


def test_callback_runs_before_generator_resumes():
    calls = []
    def chunks():
        yield '<r><i>one</i>'
        assert calls == ['one']
        yield '<i>two</i>'
        assert calls == ['one', 'two']
        yield '</r>'
    assert parse(chunks(), item_depth=2,
                 item_callback=lambda path, item: calls.append(item) or True) is None


def test_file_callback_stops_before_next_read():
    class BinarySource:
        def __init__(self):
            self.reads = 0
        def read(self, size):
            assert size == 2048
            self.reads += 1
            if self.reads == 1:
                return b'<r><i>one</i>'
            raise AssertionError('The file must not be read after interruption')
    source = BinarySource()
    with pytest.raises(rapidxmltodict.ParsingInterrupted):
        parse(source, item_depth=2, item_callback=lambda path, item: False)
    assert source.reads == 1


def test_interruption_precedes_invalid_trailing_bytes():
    with pytest.raises(rapidxmltodict.ParsingInterrupted):
        parse(b'<r><i>one</i>\xff', item_depth=2, item_callback=lambda path, item: False)


def test_callbacks_propagate_original_error():
    marker = RuntimeError('callback failure')
    def callback(path, item):
        raise marker
    with pytest.raises(RuntimeError) as error:
        parse('<r><i/></r>', item_depth=2, item_callback=callback)
    assert error.value is marker


@pytest.mark.parametrize('doc', [
    '<r>a<![CDATA[b]]>c&amp;d</r>',
    '<r>a<!-- ignored or retained -->b</r>', '<r>a<?pi ignored?>b</r>',
])
@pytest.mark.parametrize('comments', [False, True])
def test_character_coalescing(doc, comments):
    options = dict(cdata_separator='|', process_comments=comments)
    assert parse(doc, **options) == xmltodict.parse(doc, **options)


def test_generator_feed_boundaries_are_observable():
    def chunks():
        yield '<r>one'
        yield 'two'
        yield 'three</r>'
    assert parse(chunks(), cdata_separator='|') == xmltodict.parse(chunks(), cdata_separator='|')


@pytest.mark.parametrize('document', [
    '<!DOCTYPE r [<!ATTLIST r a CDATA "default">]><r/>',
    '<!DOCTYPE r [<!ATTLIST r a NMTOKENS #IMPLIED>]><r a=" a   b "/>',
    '<!DOCTYPE r [<!ENTITY a "hello"><!ENTITY b "&a; world">]><r>&b;</r>',
    '<!DOCTYPE r [<!ENTITY a "hello">]><r a="&a;"/>',
    '<!DOCTYPE r [<!ENTITY a "<i>nested</i>">]><r>&a;</r>',
])
def test_dtd_and_internal_entities(document):
    assert parse(document, disable_entities=False) == xmltodict.parse(document, disable_entities=False)


def test_entity_declarations_disabled_by_default():
    with pytest.raises(ValueError, match='^entities are disabled$'):
        parse('<!DOCTYPE r [<!ENTITY a "hello">]><r>&a;</r>')


@pytest.mark.parametrize('source', [StringIO('<r/>'), ['<r/>'], iter(['<r/>'])])
def test_invalid_input_types(source):
    with pytest.raises(TypeError):
        parse(source)


@pytest.mark.parametrize('source', [bytearray(b'<r/>'), memoryview(b'<r/>'), BytesIO(b'<r/>')])
def test_buffer_and_binary_inputs(source):
    assert parse(source) == {'r': None}


def test_parser_injection_is_removed():
    with pytest.raises(TypeError):
        parse('<r/>', expat=object())


@pytest.mark.parametrize('encoding', ['utf8', 'UTF8', 'utf_8'])
@pytest.mark.parametrize('explicit', [True, False])
def test_encoding_aliases_use_single_byte_character_maps(encoding, explicit):
    # These Python aliases are not built-in XML encoding labels. The oracle's
    # unknown-encoding callback maps single bytes and rejects multibyte text.
    if explicit:
        doc, options = b'<r>\xc3\xa9</r>', {'encoding': encoding}
    else:
        doc = ('<?xml version="1.0" encoding="%s"?><r>é</r>' % encoding).encode()
        options = {}
    with pytest.raises(Exception):
        xmltodict.parse(doc, **options)
    with pytest.raises(rapidxmltodict.ParseError):
        parse(doc, **options)


@pytest.mark.parametrize('document', [
    '<root>hello</root>',
    '<root><child/>tail</root>',
    '<root><![CDATA[hello & <world>]]></root>',
    '<root><![CDATA[a]]> <![CDATA[b]]></root>',
    '<root>&#9;&#10;&#13;text&#xA0;&#x2003;</root>',
    '<root>café 日本語 Ελληνικά Кириллица 😀 𝄞</root>',
    '<root z="last" a="first" m="middle">text</root>',
    '<r>a<![CDATA[b]]>c</r>', '<r>a&amp;b&#10;c</r>',
    '<r>a\r\nb\rc\nd</r>', '<r>a<!--comment-->b<?pi x?>c</r>',
    '<?xml version="1.0" encoding="UTF-8"?><root>hello</root>',
])
@pytest.mark.parametrize('chunk_size', [1, 2, 7, 2048])
@pytest.mark.parametrize('as_bytes', [False, True])
def test_partial_tokens_preserve_text_feed_coalescing(document, chunk_size, as_bytes):
    data = document.encode() if as_bytes else document
    def chunks():
        yield from (data[i:i + chunk_size] for i in range(0, len(data), chunk_size))
    options = {'cdata_separator': '|', 'process_comments': True, 'strip_whitespace': False}
    assert parse(chunks(), **options) == xmltodict.parse(chunks(), **options)


@pytest.mark.parametrize('encoding', [None, 'latin1', 'unknown', 'shift_jis'])
def test_first_unicode_generator_chunk_selects_utf8(encoding):
    def chunks():
        yield '<r>'
        yield b'\xc3\xa9'
        yield '</r>'
    assert parse(chunks(), encoding=encoding) == xmltodict.parse(chunks(), encoding=encoding)


def test_byte_generator_encoding_applies_to_later_unicode_chunks():
    def chunks():
        yield b'<?xml version="1.0" encoding="latin1"?><r>'
        yield 'é'
        yield '</r>'
    assert parse(chunks()) == xmltodict.parse(chunks()) == {'r': 'Ã©'}


def test_empty_explicit_byte_encoding_is_not_default_encoding():
    with pytest.raises(LookupError):
        parse(b'<r/>', encoding='')


@pytest.mark.parametrize('label', [b'\xc3\xa9', b'', b'123'])
def test_malformed_encoding_labels_are_xml_errors(label):
    doc = b'<?xml version="1.0" encoding="' + label + b'"?><r/>'
    with pytest.raises(rapidxmltodict.ParseError):
        parse(doc)


@pytest.mark.parametrize('encoding', ['cp037', 'cp500', 'cp875'])
def test_non_ascii_compatible_encodings_are_not_silently_enabled(encoding):
    with pytest.raises(rapidxmltodict.ParseError) as error:
        parse('<r>abc</r>', encoding=encoding)
    assert error.value.code == 18


@pytest.mark.parametrize('source_encoding', ['utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be'])
@pytest.mark.parametrize('override', ['UTF-8', 'UTF-16', 'UTF-16LE', 'UTF-16BE', 'ISO-8859-1', 'US-ASCII'])
def test_builtin_encoding_overrides_preserve_signature_detection(source_encoding, override):
    document = '<r>é</r>'.encode(source_encoding)
    assert parse(document, encoding=override) == xmltodict.parse(document, encoding=override)


@pytest.mark.parametrize('source_encoding,declared', [
    ('utf-16', 'UTF-8'), ('utf-16-le', 'UTF-16BE'),
    ('utf-16-be', 'UTF-16LE'), ('utf-16', 'ISO-8859-1'),
    ('utf-8', 'UTF-16'), ('utf-8-sig', 'UTF-16'),
])
def test_incompatible_builtin_declarations_are_rejected(source_encoding, declared):
    document = ('<?xml version="1.0" encoding="%s"?><r/>' % declared).encode(source_encoding)
    with pytest.raises(rapidxmltodict.ParseError) as error:
        parse(document)
    assert error.value.code == 19


@pytest.mark.parametrize('encoding', ['latin1', 'ASCII', 'utf16', 'unknown'])
def test_utf16_declarations_honor_unknown_encoding_callback(encoding):
    document = ('<?xml version="1.0" encoding="%s"?><r/>' % encoding).encode('utf-16')
    try:
        xmltodict.parse(document)
    except (ValueError, LookupError) as expected:
        with pytest.raises(type(expected)):
            parse(document)
    except Exception:
        with pytest.raises(rapidxmltodict.ParseError):
            parse(document)
    else:
        pytest.fail('Fixture must be rejected by the oracle')


def test_utf16_declaration_can_switch_to_unknown_single_byte_codec():
    # A legacy parser quirk: the unknown-encoding callback takes effect at the
    # end of the declaration, so subsequent bytes use the declared mapping.
    document = '<?xml version="1.0" encoding="latin1"?>'.encode('utf-16') + '<r>café</r>'.encode('latin1')
    assert parse(document) == xmltodict.parse(document) == {'r': 'café'}


@pytest.mark.parametrize('encoding,label', [
    ('utf-16', 'utf-16'), ('utf-16-le', 'UTF-16LE'), ('utf-16-be', 'UTF-16BE'),
])
@pytest.mark.parametrize('chunk_size', [1, 2, 3, 7, 11])
def test_utf16_partial_bytes_use_original_deferral_units(encoding, label, chunk_size):
    data = ('<?xml version="1.0" encoding="%s"?><root><child/>text</root>' % label).encode(encoding)
    def chunks():
        yield from (data[i:i + chunk_size] for i in range(0, len(data), chunk_size))
    assert parse(chunks(), cdata_separator='|') == xmltodict.parse(chunks(), cdata_separator='|')


@pytest.mark.parametrize('case', [
    'success', 'streaming_success', 'malformed', 'namespace_error',
    'interrupted', 'callback_error', 'encoding_error', 'encoding_type_error',
    'reader_error', 'generator_error',
])
def test_event_parser_lifetime_does_not_require_cyclic_gc(monkeypatch, case):
    import gc
    import importlib
    import weakref

    implementation = importlib.import_module('rapidxmltodict._parse')
    sinks = []
    class TrackedSink(implementation._NamespaceSink):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sinks.append(weakref.ref(self))
    monkeypatch.setattr(implementation, '_NamespaceSink', TrackedSink)

    def callback_error(path, item):
        raise RuntimeError('callback failure')

    class BrokenReader:
        def read(self, size):
            raise OSError('reader failure')

    def broken_generator():
        yield '<r><item>one</item>'
        raise RuntimeError('generator failure')

    def run():
        # Do not keep an exception traceback alive after returning: it would
        # intentionally keep the parse frame and its local references alive.
        options = {'process_comments': True}  # Exercise the event parser.
        document = '<r><item>one</item></r>'
        expected_error = None
        if case == 'streaming_success':
            options.update(item_depth=2, item_callback=lambda path, item: True)
        elif case == 'malformed':
            document = '<r><item>one</wrong></r>'
            expected_error = rapidxmltodict.ParseError
        elif case == 'namespace_error':
            document = '<p:r/>'
            options['process_namespaces'] = True
            expected_error = rapidxmltodict.ParseError
        elif case == 'interrupted':
            options.update(item_depth=2, item_callback=lambda path, item: False)
            expected_error = rapidxmltodict.ParsingInterrupted
        elif case == 'callback_error':
            options.update(item_depth=2, item_callback=callback_error)
            expected_error = RuntimeError
        elif case == 'encoding_error':
            document = '<r>é</r>'
            options['encoding'] = 'ascii'
            expected_error = UnicodeEncodeError
        elif case == 'encoding_type_error':
            document = b'<r/>'
            options['encoding'] = 42
            expected_error = TypeError
        elif case == 'reader_error':
            document = BrokenReader()
            expected_error = OSError
        elif case == 'generator_error':
            document = broken_generator()
            expected_error = RuntimeError
        try:
            result = parse(document, **options)
        except Exception as error:
            assert expected_error is not None
            assert isinstance(error, expected_error)
        else:
            assert expected_error is None
            if case == 'success':
                assert result == {'r': {'item': 'one'}}
            else:
                assert result is None

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        run()
        assert len(sinks) == 1
        # NativeParser strongly owns this sink, so its immediate destruction
        # also proves the owning native parser has released it.
        assert sinks[0]() is None
    finally:
        if was_enabled:
            gc.enable()


def test_parser_back_reference_is_cleared_even_with_retained_traceback(monkeypatch):
    import importlib
    import weakref

    implementation = importlib.import_module('rapidxmltodict._parse')
    sinks = []
    class TrackedSink(implementation._NamespaceSink):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sinks.append(weakref.ref(self))
    monkeypatch.setattr(implementation, '_NamespaceSink', TrackedSink)
    with pytest.raises(rapidxmltodict.ParseError) as captured:
        parse('<r/>tail', process_comments=True)
    assert captured.value.__traceback__ is not None
    assert sinks[0]() is not None
    assert sinks[0]().parser is None
