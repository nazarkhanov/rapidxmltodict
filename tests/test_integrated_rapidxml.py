"""The strict RapidXML parse must be the parser, not a validated conversion.

These checks intentionally call the private converter and disable both older
validation and event fallbacks on the common path. Public result equality alone
would also pass with a separate validator in front of an unchanged RapidXML.
"""
import pytest
import xmltodict

import rapidxmltodict
from rapidxmltodict import _native, _parse
from test_security import MALFORMED


COMMON_DOCUMENTS = [
    '<r/>',
    '<r a="value"><item>one</item><item>two</item></r>',
    '<?xml version="1.0" encoding="UTF-8"?><r>café 日本語</r>',
    '\ufeff<r a="é">日</r>',
    '<日本 属性="value"><子>text</子></日本>',
    '<p:r xmlns:p="urn:r"><p:item p:a="v"/></p:r>',
    '<r>left<x/> middle <y/>right</r>',
    '<r>left<![CDATA[ middle ]]><!-- gap --><?work done?>right</r>',
    '<r> <x/>text<y/> </r>',
    '<r a="literal\t\r\nspace &#9;&#10;&#13;">a\r\nb\rc&#13;d</r>',
]


@pytest.mark.parametrize('document', COMMON_DOCUMENTS)
@pytest.mark.parametrize('as_bytes', [False, True])
def test_common_parse_does_not_run_validator_or_event_fallback(monkeypatch, document, as_bytes):
    if as_bytes:
        document = document.encode('utf-8')
    expected = xmltodict.parse(document)
    conversions = []
    original_convert = _native.convert

    def unexpected(*args, **kwargs):
        raise AssertionError('common input ran a separate validator or event fallback')

    def convert(data):
        conversions.append(data)
        return original_convert(data)

    # The old helper may be removed entirely; a spy still catches a future
    # accidental reintroduction of this prevalidation call.
    monkeypatch.setattr(_native, 'validate', unexpected, raising=False)
    monkeypatch.setattr(_parse, 'NativeParser', unexpected)
    monkeypatch.setattr(_native, 'convert', convert)
    assert rapidxmltodict.parse(document) == expected
    assert len(conversions) == 1


@pytest.mark.parametrize('document', [value for value in MALFORMED if b'<!DOCTYPE' not in value])
def test_private_converter_rejects_unvalidated_malformed_input(document):
    # Reuse only the project's ordinary malformed-XML regression corpus.
    # DOCTYPE is deliberately an event-parser capability fallback.
    with pytest.raises(rapidxmltodict.ParseError):
        _native.convert(document)


@pytest.mark.parametrize('document', COMMON_DOCUMENTS + [
    '<r><![CDATA[first]]>second<![CDATA[third]]></r>',
    '<r>first<!-- comment -->second<?pi value?>third</r>',
    '<r>first<x>child</x>second<y>child</y>third</r>',
    '<r>\r\n<x/>\r\ntext\r\n<y/>\r\n</r>',
    '<r a="&lt;&amp;&quot;&apos;&gt;">&lt;&amp;&quot;&apos;&gt;</r>',
    '<r a="\r\n\r\n&#13;&#10;&#9;">\r\n\r\n&#13;&#10;&#9;x</r>',
    '<r><![CDATA[a\r\nb\rc\td]]></r>',
    '<r>\u2003text\u00a0</r>',
])
def test_private_converter_preserves_compact_text_and_normalization(document):
    assert _native.convert(document.encode('utf-8')) == xmltodict.parse(document)


@pytest.mark.parametrize('depth', [255, 256])
def test_private_converter_handles_supported_depth_without_prescan(depth):
    document = b'<node>' * depth + b'leaf' + b'</node>' * depth
    result = _native.convert(document)
    assert result is not NotImplemented
    for _ in range(depth):
        result = result['node']
    assert result == 'leaf'


def test_depth_fallback_preserves_public_result():
    depth = 257
    document = b'<node>' * depth + b'leaf' + b'</node>' * depth
    assert _native.convert(document) is NotImplemented
    result = rapidxmltodict.parse(document)
    for _ in range(depth):
        result = result['node']
    assert result == 'leaf'


@pytest.mark.parametrize('document', [
    b'<!DOCTYPE r><r/>',
    b'<!DOCTYPE r [<!ATTLIST r a CDATA "default">]><r/>',
])
def test_doctype_fallback_preserves_public_result(document):
    assert _native.convert(document) is NotImplemented
    assert rapidxmltodict.parse(document) == xmltodict.parse(document)


def test_error_after_utf8_bom_preserves_original_byte_index():
    document = b'\xef\xbb\xbf<r><i></r>'
    with pytest.raises(rapidxmltodict.ParseError) as direct:
        _native.convert(document)
    with pytest.raises(rapidxmltodict.ParseError) as public:
        rapidxmltodict.parse(document)
    assert direct.value.byte_index == public.value.byte_index == document.index(b'</r>') + 2
    assert (direct.value.code, direct.value.lineno, direct.value.offset) == (
        public.value.code, public.value.lineno, public.value.offset)


@pytest.mark.parametrize('chunk_size', [1, 2, 7, 2048])
def test_resumable_header_keeps_progress_across_buffer_growth(chunk_size):
    # A completed parent prefix can be discarded while its child's header is
    # incomplete. Long values also force buffer reallocations. Neither operation
    # may invalidate header offsets or repeat already-delivered value fragments.
    value = ('plain text café 日本語 &amp; &#13;&#10;&#9;\r\n' * 240)
    attributes = ' '.join('a%d="v%d"' % (i, i) for i in range(12))
    document = ('<r><item %s value="%s"/></r>' % (attributes, value)).encode('utf-8')
    expected = xmltodict.parse(document)['r']['item']
    expected_attributes = [(key[1:], text) for key, text in expected.items()]
    events = []

    class Sink:
        def start(self, name, attrs):
            events.append(('start', name, attrs))

        def end(self, name):
            events.append(('end', name))

        def text(self, text):
            events.append(('text', text))

        def comment(self, text):
            events.append(('comment', text))

    parser = _native.NativeParser(Sink())
    for start in range(0, len(document), chunk_size):
        parser.feed(document[start:start + chunk_size])
    parser.feed(b'', final=True)
    assert events == [
        ('start', 'r', []),
        ('start', 'item', expected_attributes),
        ('end', 'item'),
        ('end', 'r'),
    ]
