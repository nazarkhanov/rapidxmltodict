"""The native event mapper builds Python objects without a Python tag handler."""
from collections import OrderedDict
from copy import deepcopy
from io import BytesIO
import sys

import pytest
import xmltodict

import rapidxmltodict
from rapidxmltodict import _native, _parse
from oracle_contract_cases import MAPPING_CHUNK_CASE, assert_chunk_contract


DOCUMENT = ('<!--before--><r a="1"> before <x>one</x><x/><y> two </y>'
            '<![CDATA[ tail ]]><!--after--></r>')


@pytest.mark.parametrize('options', [
    {}, {'xml_attribs': False}, {'attr_prefix': ''}, {'attr_prefix': '$'},
    {'cdata_key': 'text'}, {'force_cdata': True}, {'force_cdata': ('x',)},
    {'force_cdata': lambda path, key, value: key == 'y'},
    {'force_list': True}, {'force_list': ('x',)},
    {'force_list': lambda path, key, value: key == 'y'},
    {'strip_whitespace': False}, {'cdata_separator': '|'},
    {'dict_constructor': OrderedDict}, {'process_comments': True},
    {'process_comments': True, 'comment_key': 'comments'},
    {'postprocessor': lambda path, key, value: (key.upper(), value)},
    {'postprocessor': lambda path, key, value: None if key == 'y' else (key, value)},
])
@pytest.mark.parametrize('kind', ['text', 'bytes', 'file', 'chunks'])
def test_mapping_option_matrix(options, kind):
    def source():
        if kind == 'text':
            return DOCUMENT
        raw = DOCUMENT.encode()
        if kind == 'bytes':
            return raw
        if kind == 'file':
            return BytesIO(raw)
        return (raw[i:i + 7] for i in range(0, len(raw), 7))
    if kind == 'chunks' and options.get('cdata_separator') == '|':
        # Old Expat builds emit an extra text boundary here. Enforce the
        # approved exact modern oracle, plus live empty-separator semantics.
        assert MAPPING_CHUNK_CASE.document == DOCUMENT.encode()
        assert_chunk_contract(MAPPING_CHUNK_CASE, _parse._parse_native_events,
                              xmltodict.parse)
        return
    expected = xmltodict.parse(source(), **options)
    actual = _parse._parse_native_events(source(), **options)
    assert actual == expected
    assert type(actual) is type(expected)


@pytest.mark.parametrize('separator', [':', '|', '', None])
@pytest.mark.parametrize('mapping', [None, {'urn:root': None, 'urn:p': 'short'}])
def test_native_namespace_scopes(separator, mapping):
    xml = ('<r xmlns="urn:root" xmlns:p="urn:p" p:a="1">'
           '<p:x/><x xmlns=""/><x xmlns:p="urn:other"><p:y/></x>'
           '<p:z xml:lang="en"/></r>')
    options = dict(process_namespaces=True, namespace_separator=separator,
                   namespaces=mapping)
    try:
        expected = xmltodict.parse(xml, **options)
    except (ValueError, TypeError) as error:
        with pytest.raises(type(error)):
            _parse._parse_native_events(xml, **options)
    else:
        assert _parse._parse_native_events(xml, **options) == expected


@pytest.mark.parametrize('depth', [-1, 0, 1, 2, 3, 4, 1.0, 2.0, 10**100])
def test_native_item_depth(depth):
    xml = '<r a="v"><i> one </i><i n="2"><x>two</x> tail </i><i/></r>'
    def run(parse):
        seen = []
        result = parse(xml, item_depth=depth,
                       item_callback=lambda path, item: seen.append(deepcopy((path, item))) or True)
        return result, seen
    assert run(_parse._parse_native_events) == run(xmltodict.parse)


@pytest.mark.parametrize('encoded', [False, True])
def test_early_stop_precedes_invalid_trailing_input(encoded):
    consumed = []
    def source():
        consumed.append(1)
        yield b'<r><i>one</i>\xff' if encoded else '<r><i>one</i><invalid'
        consumed.append(2)
        raise AssertionError('The generator resumed after the stopping item')
    with pytest.raises(rapidxmltodict.ParsingInterrupted):
        _parse._parse_native_events(source(), item_depth=2,
                                    item_callback=lambda path, item: False)
    assert consumed == [1]


@pytest.mark.parametrize('xml,options', [
    ('<r>é\n<wrong></r>', {}),
    ('<r xmlns:a="u" xmlns:b="u" a:x="1" b:x="2"/>', {'process_namespaces': True}),
    ('<p:r/>', {'process_namespaces': True}),
    ('<r xmlns:xml="bad"/>', {'process_namespaces': True}),
    ('<r xmlns:p=""/>', {'process_namespaces': True}),
    ('<a:b:c/>', {'process_namespaces': True}),
    ('<r xmlns:p="urn|p"/>', {'process_namespaces': True, 'namespace_separator': '|'}),
])
@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'iso-8859-1'])
def test_source_byte_error_fields_match_existing_event_engine(xml, options, encoding):
    raw = xml.encode(encoding)
    errors = []
    for parse in (_parse.parse, _parse._parse_native_events):
        with pytest.raises(rapidxmltodict.ParseError) as caught:
            # Explicit encoding forces the old public entry through its event
            # engine rather than using the separate integrated-DOM comparator.
            parse(raw, encoding=encoding, **options)
        error = caught.value
        errors.append((str(error), error.code, error.lineno, error.offset, error.byte_index))
    assert errors[0] == errors[1]


def test_no_dom_or_python_tag_handler_is_used(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('A DOM or Python SAX handler was constructed')
    monkeypatch.setattr(_parse, '_DictSAXHandler', forbidden, raising=False)
    monkeypatch.setattr(_parse, '_NamespaceSink', forbidden, raising=False)
    monkeypatch.setattr(_parse, 'NativeParser', forbidden)
    monkeypatch.setattr(_native, 'convert', forbidden)
    monkeypatch.setattr(_native, 'validate', forbidden)
    assert _parse._parse_native_events('<r a="1"><x>one</x><x>two</x></r>') == {
        'r': {'@a': '1', 'x': ['one', 'two']}}
    assert _parse._parse_native_events(
        '<r xmlns:p="urn:p"><p:x/></r>', process_namespaces=True) == {
            'r': {'@xmlns': {'p': 'urn:p'}, 'urn:p:x': None}}


def test_default_mapping_never_calls_python_per_tag():
    calls = []
    def profile(frame, event, arg):
        if event == 'call':
            calls.append((frame.f_code.co_filename, frame.f_code.co_name))
    old_profile = sys.getprofile()
    try:
        sys.setprofile(profile)
        parser = _native.NativeMappingParser()
        parser.feed('<r>' + '<x a="1">value</x>' * 100 + '</r>', final=True)
        result = parser.result
        parser.close()
    finally:
        sys.setprofile(old_profile)
    assert result['r']['x'] == [{'@a': '1', '#text': 'value'}] * 100
    assert calls == []


def test_deep_nesting_builds_without_cpp_or_python_recursion():
    depth = 12000
    result = _parse._parse_native_events('<x>' * depth + 'value' + '</x>' * depth)
    for _ in range(depth):
        assert type(result) is dict
        result = result['x']
    assert result == 'value'


def test_reinitialize_and_uninitialized_protocol():
    parser = _native.NativeMappingParser.__new__(_native.NativeMappingParser)
    assert parser.result is None
    with pytest.raises(RuntimeError, match='not initialized'):
        parser.feed('<r/>', final=True)
    parser.__init__()
    parser.feed('<r>one</r>', final=True)
    assert parser.result == {'r': 'one'}
    with pytest.raises(rapidxmltodict.ParseError) as caught:
        parser.feed('', final=True)
    assert caught.value.code == 36
    parser.__init__(force_list=True)
    parser.feed('<s/>', final=True)
    assert parser.result == {'s': [None]}
    parser.close()
    assert parser.result is None


def test_input_validation_and_unknown_options():
    with pytest.raises(TypeError, match='expat'):
        _native.NativeMappingParser(expat=object())
    parser = _native.NativeMappingParser()
    with pytest.raises(TypeError, match='UTF-8 bytes or text'):
        parser.feed(bytearray(b'<r/>'))
    with pytest.raises(ValueError, match='nonnegative'):
        parser.feed('', undecoded_bytes=-1)
    with pytest.raises(ValueError, match='unknown source encoding'):
        parser.set_source_encoding('rot13')
    parser.feed(b'<r/>', final=True)
    assert parser.result == {'r': None}


def test_fast_mapper_partial_result_custom_key_preserves_exception_scope():
    events = []

    class Key:
        def __hash__(self):
            return hash('second')

        def __eq__(self, other):
            if other == 'second':
                events.append(sys.exc_info()[0])
            return False

    parser = _native.NativeMappingParser()
    parser.feed('<r a="v"><first>one</first>')
    partial = parser.result
    key = Key()
    partial[key] = partial.pop('first')
    parser.feed('<second>two</second></r>', final=True)
    # Dictionary probe sequences may compare the same colliding key more than
    # once under different hash seeds; lookup and insertion still have distinct
    # exception scopes in that order.
    assert None in events and KeyError in events
    boundary = events.index(KeyError)
    assert all(event is None for event in events[:boundary])
    assert all(event is KeyError for event in events[boundary:])
    result = parser.result
    assert result['r'] is partial
    assert partial[key] == 'one'
    assert partial['second'] == 'two'
    parser.close()


def test_fast_mapper_partial_result_list_override_is_observed():
    calls = []

    class List(list):
        def append(self, value):
            calls.append(value)
            raise KeyError('retry as missing')

    parser = _native.NativeMappingParser()
    parser.feed('<r a="v"><x>one</x>')
    partial = parser.result
    partial['x'] = List([partial['x']])
    parser.feed('<x>two</x></r>', final=True)
    assert parser.result == {'r': {'@a': 'v', 'x': 'two'}}
    assert calls == ['two']
    parser.close()


def test_missing_key_handler_does_not_retry_keyerror_from_force_hook():
    marker = KeyError('force hook failure')
    calls = []

    def force(path, key, value):
        calls.append(key)
        raise marker

    with pytest.raises(KeyError) as caught:
        _parse._parse_native_events('<r/>', force_list=force)
    assert caught.value is marker
    assert calls == ['r']
