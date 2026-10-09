"""Ordinary XML/DTD oracle cases for the independent incremental event engine."""
from xml.parsers import expat

import pytest
import xmltodict
import rapidxmltodict


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


@pytest.mark.parametrize('version', ['104', 'abc', '1.1', '2.0', '1_0'])
def test_reference_version_token_permissiveness(version):
    assert_oracle('<?xml version="%s"?><r/>' % version)


@pytest.mark.parametrize('doctype', [
    '<!DOCTYPE r [<!ELEMENT r (#PCDATA)>]>',
    '<!DOCTYPE r [<!ENTITY e "word"><!ENTITY f "a&e;b">]>',
    '<!DOCTYPE r [<!ATTLIST r a CDATA "default">]>',
    '<!DOCTYPE r [<!--comment--><!ELEMENT r (#PCDATA)>]>',
    '<!DOCTYPE r SYSTEM "not-fetched">',
    '<!DOCTYPE r PUBLIC "id" "not-fetched">',
])
@pytest.mark.parametrize('chunk_size', [1, 2, 3, 4, 5, 7, 11])
@pytest.mark.parametrize('process_comments', [False, True])
def test_dtd_lexical_feed_boundaries(doctype, chunk_size, process_comments):
    document = doctype + '<r>text</r>'
    def chunks():
        return (document[i:i + chunk_size] for i in range(0, len(document), chunk_size))
    options = dict(disable_entities=False, process_comments=process_comments,
                   cdata_separator='|', strip_whitespace=False)
    assert rapidxmltodict.parse(chunks(), **options) == xmltodict.parse(chunks(), **options)


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
