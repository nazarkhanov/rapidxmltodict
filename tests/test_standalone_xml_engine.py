"""Ordinary XML/DTD oracle cases for the independent incremental event engine."""
from xml.parsers import expat

import pytest
import xmltodict
import rapidxmltodict
from oracle_contract_cases import DTD_CHUNK_CASES, assert_chunk_contract


def assert_oracle(document, **options):
    try:
        expected = xmltodict.parse(document, **options)
    except expat.ExpatError:
        with pytest.raises(rapidxmltodict.ParseError):
            rapidxmltodict.parse(document, **options)
    except ValueError as error:
        with pytest.raises(ValueError) as actual:
            rapidxmltodict.parse(document, **options)
        assert actual.value.args == error.args
    else:
        assert rapidxmltodict.parse(document, **options) == expected


DTD_DECLARATIONS = [
    '<!ENTITY e "a&#13;b">',
    '<!ENTITY e "a\rb">',
    '<!ENTITY e "&#13;\n">',
    '<!ENTITY e "<a/>text<b/>">',
    '<!ENTITY e "x"><!ENTITY f "&e; &e;">',
    '<!ENTITY e SYSTEM "not-fetched">',
    '<!ENTITY e SYSTEM "not-fetched" NDATA binary>',
    '<!ENTITY % p "unused">',
    '<!ENTITY % p ""><!ENTITY e "x">%p;<!ENTITY f "y">',
    '<!ATTLIST r a CDATA "yes">',
    '<!ATTLIST r a NMTOKENS " x  y ">',
    '<!ELEMENT r (a,(b|c)*,d?)>',
    '<!ELEMENT r (#PCDATA|a)*>',
    '<!NOTATION image SYSTEM "image/gif">',
    '<!NOTATION image PUBLIC "name">',
    '<!ENTITY amp "ignored">',
    '<!ENTITY e "</r><r>">',
    '<!ENTITY e "<r>">',
]


@pytest.mark.parametrize('declaration', DTD_DECLARATIONS)
@pytest.mark.parametrize('body', ['<r/>', '<r>&e;</r>', '<r a="&e;"/>', '<r>&f;</r>'])
@pytest.mark.parametrize('standalone', ['', '<?xml version="1.0" standalone="yes"?>'])
@pytest.mark.parametrize('disable_entities', [False, True])
def test_dtd_declarations_match_reference(declaration, body, standalone, disable_entities):
    assert_oracle(standalone + '<!DOCTYPE r [' + declaration + ']>' + body,
                  disable_entities=disable_entities, strip_whitespace=False)


@pytest.mark.parametrize('attribute', [False, True])
def test_long_nonexpanding_entity_chain_is_iterative(attribute):
    count = 500
    declarations = '<!ENTITY e0 "x">' + ''.join(
        '<!ENTITY e%d "&e%d;">' % (i, i - 1) for i in range(1, count))
    reference = '&e%d;' % (count - 1)
    body = '<r a="%s"/>' % reference if attribute else '<r>%s</r>' % reference
    assert_oracle('<!DOCTYPE r [' + declarations + ']>' + body, disable_entities=False)


@pytest.mark.parametrize('character', ['é', '日', '\u3007', '\u212e', '\u037f', '\u200c', '\u2c00', '\u3001', '\u00aa', '😀'])
@pytest.mark.parametrize('prefix', ['', 'a'])
def test_xml_name_character_repertoire(character, prefix):
    assert_oracle('<%s%s/>' % (prefix, character))


@pytest.mark.parametrize('version', ['1.0', '1.1', '1.00', '1.1234567890'])
@pytest.mark.parametrize('quote', ['"', "'"])
@pytest.mark.parametrize('event_mode', [False, True])
def test_xml_declaration_accepts_version_num_grammar(version, quote, event_mode):
    document = '<?xml version=%s%s%s?><r/>' % (quote, version, quote)
    options = {'strip_whitespace': True} if event_mode else {}
    assert_oracle(document, **options)


@pytest.mark.parametrize('version', ['', '104', 'abc', '2.0', '1_0', '1.',
                                     '1.a', '01.0', '1.0.1', '1.0e2', '1.-1'])
@pytest.mark.parametrize('input_kind', ['text', 'bytes', 'chunks'])
@pytest.mark.parametrize('event_mode', [False, True])
def test_xml_declaration_rejects_non_version_num_values(version, input_kind, event_mode):
    # The canonical modern reference rejects these values. Older platform
    # parsers can accept them, so the package contract is asserted directly.
    document = '<?xml version="%s"?><r/>' % version
    if input_kind != 'text':
        document = document.encode()
    if input_kind == 'chunks':
        raw = document
        document = (raw[i:i + 2] for i in range(0, len(raw), 2))
    options = {'strip_whitespace': True} if event_mode else {}
    with pytest.raises(rapidxmltodict.ParseError) as caught:
        rapidxmltodict.parse(document, **options)
    error = caught.value
    assert (error.code, error.lineno, error.offset, error.byte_index) == (30, 1, 15, 15)
    assert str(error) == 'XML declaration not well-formed: line 1, column 15'


@pytest.mark.parametrize('version', ['1. 0', '1.&0', '1.☃', '1.١'])
def test_xml_declaration_invalid_value_character_position(version):
    with pytest.raises(rapidxmltodict.ParseError) as caught:
        rapidxmltodict.parse('<?xml version="%s"?><r/>' % version)
    error = caught.value
    assert (error.code, error.lineno, error.offset, error.byte_index) == (30, 1, 17, 17)


def test_xml_declaration_version_position_with_line_break_and_single_quotes():
    prefix = "<?xml\n version = '"
    with pytest.raises(rapidxmltodict.ParseError) as caught:
        rapidxmltodict.parse(prefix + "abc'?><r/>")
    error = caught.value
    assert error.code == 30
    assert error.lineno == 2
    assert error.offset == len(prefix.rsplit('\n', 1)[1])
    assert error.byte_index == len(prefix.encode())


@pytest.mark.parametrize('case', DTD_CHUNK_CASES, ids=lambda case: case.id)
def test_dtd_lexical_feed_boundaries(case):
    assert_chunk_contract(case, rapidxmltodict.parse, xmltodict.parse)


@pytest.mark.parametrize('encoding', ['utf-8', 'iso-8859-1', 'utf-16'])
@pytest.mark.parametrize('character', ['a', 'é'])
@pytest.mark.parametrize('middle', ['\n', '\r', '\r\n', '<![CDATA[\n]]>'])
@pytest.mark.parametrize('size', [8191, 8192, 9000])
def test_large_literal_text_buffer_boundaries(encoding, character, middle, size):
    document = ('<?xml version="1.0" encoding="%s"?><r>%s%s%s</r>' %
                (encoding, character * size, middle, character * size)).encode(encoding)
    assert_oracle(document, cdata_separator='|', strip_whitespace=False)


@pytest.mark.parametrize('encoding', ['utf-8', 'iso-8859-1', 'utf-16'])
@pytest.mark.parametrize('prefix_size', [1, 123, 1000, 1100, 2000, 4000, 8000])
def test_transcoded_literal_buffer_after_character_reference(encoding, prefix_size):
    document = ('<?xml version="1.0" encoding="%s"?><r>%s&#65;%s</r>' %
                (encoding, 'p' * prefix_size, 'x' * 10000)).encode(encoding)
    assert_oracle(document, cdata_separator='|')


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
@pytest.mark.parametrize('middle', ['\n', '&#13;', '&#13;\n'])
def test_entity_literal_and_referenced_carriage_returns_keep_buffer_semantics(encoding, middle):
    document = ('<?xml version="1.0" encoding="%s"?><!DOCTYPE r [<!ENTITY e "%s%s%s">]><r>&e;</r>' %
                (encoding, 'a' * 8191, middle, 'b' * 8191)).encode(encoding)
    assert_oracle(document, cdata_separator='|', disable_entities=False)
