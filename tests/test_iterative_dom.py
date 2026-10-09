"""Deep strict DOM parsing and conversion must consume input without restarting."""
from xml.parsers import expat

import pytest
import xmltodict

import rapidxmltodict
from rapidxmltodict import _native, _parse


def _reject_event_fallback(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('deep XML restarted through a validator or event parser')

    monkeypatch.setattr(_native, 'validate', unexpected, raising=False)
    monkeypatch.setattr(_parse, 'NativeParser', unexpected)


def _leaf(result, depth, name='node'):
    # Recursive equality would test Python's recursion limit, not the parser.
    for _ in range(depth):
        assert isinstance(result, dict)
        assert list(result) == [name]
        result = result[name]
    return result


@pytest.mark.parametrize('depth', [257, 2048, 12000])
def test_deep_private_converter_and_public_parser_stay_on_dom(monkeypatch, depth):
    _reject_event_fallback(monkeypatch)
    document = b'<node>' * depth + b'leaf' + b'</node>' * depth
    assert _leaf(_native.convert(document), depth) == 'leaf'
    assert _leaf(rapidxmltodict.parse(document), depth) == 'leaf'


def test_late_deep_branch_does_not_restart_completed_prefix(monkeypatch):
    _reject_event_fallback(monkeypatch)
    depth = 4096
    document = (b'<root>' + b'<item a="1">value</item>' * 3000
                + b'<node>' * depth + b'leaf' + b'</node>' * depth
                + b'<item a="2">last</item></root>')
    conversions = []
    original_convert = _native.convert

    def convert(data):
        conversions.append(len(data))
        return original_convert(data)

    monkeypatch.setattr(_native, 'convert', convert)
    result = rapidxmltodict.parse(document)['root']
    assert conversions == [len(document)]
    assert list(result) == ['item', 'node']
    assert result['item'] == [{'@a': '1', '#text': 'value'}] * 3000 + [
        {'@a': '2', '#text': 'last'}]
    assert _leaf({'node': result['node']}, depth) == 'leaf'


def test_deep_parent_frames_preserve_attributes_text_and_sibling_order(monkeypatch):
    _reject_event_fallback(monkeypatch)
    depth = 1024
    opening = b'<node a="x&#13;y">before<item>first</item>'
    closing = b'<item>last</item>after<![CDATA[ & ]]><!--gap--><?pi ok?></node>'
    document = opening * depth + b'<leaf/>middle' + closing * depth
    result = _native.convert(document)
    assert result is not NotImplemented
    node = result['node']
    for level in range(depth):
        assert node['@a'] == 'x\ry'
        assert node['item'] == ['first', 'last']
        if level + 1 < depth:
            assert list(node) == ['@a', 'item', 'node', '#text']
            assert node['#text'] == 'beforeafter &'
            node = node['node']
        else:
            assert list(node) == ['@a', 'item', 'leaf', '#text']
            assert node['leaf'] is None
            assert node['#text'] == 'beforemiddleafter &'


@pytest.mark.parametrize('tail', [
    b'</wrong>',
    b'<leaf a="1" a="2"/>',
    b'<leaf>undefined &missing;</leaf>',
    b'<leaf>invalid &#0;</leaf>',
    b'<leaf><!-- invalid--x --></leaf>',
    b'<leaf><![CDATA[unclosed',
    b'<leaf>\x00</leaf>',
    b'<leaf>',
    b'<',
    b'',
])
def test_deep_errors_keep_oracle_diagnostics_without_fallback(monkeypatch, tail):
    _reject_event_fallback(monkeypatch)
    depth = 1024
    document = (b'\xef\xbb\xbf<root>one&amp;two\r\n'
                + b'<node a="x&#13;y">\xc3\xa9\r\n' * depth + tail)
    with pytest.raises(expat.ExpatError) as expected:
        xmltodict.parse(document)
    for convert in (_native.convert, rapidxmltodict.parse):
        with pytest.raises(rapidxmltodict.ParseError) as actual:
            convert(document)
        assert (actual.value.code, actual.value.lineno, actual.value.offset) == (
            expected.value.code, expected.value.lineno, expected.value.offset)
        assert str(actual.value) == str(expected.value)
    parser = expat.ParserCreate()
    with pytest.raises(expat.ExpatError):
        parser.Parse(document, True)
    assert actual.value.byte_index == parser.ErrorByteIndex


def test_repeated_deep_parse_failures_release_partial_documents():
    # This also runs under ASan/LSan. Each failure owns a large partial DOM;
    # subsequent successful parses verify that no parser/frame state survives.
    depth = 2048
    prefix = b'<node a="value">text<item/>' * depth
    invalid = prefix + b'</wrong>'
    valid = prefix + b'</node>' * depth
    for _ in range(20):
        with pytest.raises(rapidxmltodict.ParseError) as error:
            _native.convert(invalid)
        assert error.value.code == 7
        result = _native.convert(valid)
        node = result['node']
        for level in range(depth):
            assert node['@a'] == 'value'
            assert node['item'] is None
            assert node['#text'] == 'text'
            if level + 1 < depth:
                node = node['node']
        del result, node
        assert _native.convert(b'<r>ok</r>') == {'r': 'ok'}
