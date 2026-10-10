"""Differential coverage of the public xmltodict-compatible parse interface.

The reference implementation is intentionally used as the oracle. Fixtures are
small, deterministic, and include XML rules that RapidXML does not implement.
"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO, StringIO
from itertools import product
import random
from xml.parsers import expat
from xml.sax.saxutils import escape, quoteattr

import pytest
import xmltodict

import rapidxmltodict


def _ordered_shape(value):
    """Check insertion order and scalar types as well as dictionary equality."""
    if isinstance(value, dict):
        return (type(value), tuple((key, _ordered_shape(item)) for key, item in value.items()))
    if isinstance(value, list):
        return (list, tuple(_ordered_shape(item) for item in value))
    return (type(value), value)


def assert_same(document, **kwargs):
    try:
        expected = xmltodict.parse(document, **kwargs)
    except ValueError as expected_error:
        # xmltodict 1.x rejects entity declarations with disable_entities=True;
        # 0.14.2 accepts the document without expanding its text entities.
        # Match the installed reference's exact rejection, not any exception.
        with pytest.raises(type(expected_error)) as actual_error:
            rapidxmltodict.parse(document, **kwargs)
        assert type(actual_error.value) is type(expected_error)
        assert actual_error.value.args == expected_error.args
        return None
    actual = rapidxmltodict.parse(document, **kwargs)
    assert _ordered_shape(actual) == _ordered_shape(expected)
    return actual


def test_differential_helper_matches_exact_reference_rejection(monkeypatch):
    def reject(*args, **kwargs):
        raise ValueError('entities are disabled')
    monkeypatch.setattr(xmltodict, 'parse', reject)
    monkeypatch.setattr(rapidxmltodict, 'parse', reject)
    assert assert_same('<root/>') is None


def test_differential_helper_does_not_accept_a_different_rejection(monkeypatch):
    def reference_reject(*args, **kwargs):
        raise ValueError('entities are disabled')
    def different_reject(*args, **kwargs):
        raise ValueError('an unrelated error')
    monkeypatch.setattr(xmltodict, 'parse', reference_reject)
    monkeypatch.setattr(rapidxmltodict, 'parse', different_reject)
    with pytest.raises(AssertionError):
        assert_same('<root/>')


def test_differential_helper_does_not_swallow_unexpected_errors(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('unexpected reference failure')
    monkeypatch.setattr(xmltodict, 'parse', fail)
    with pytest.raises(RuntimeError, match='unexpected reference failure'):
        assert_same('<root/>')


DEFAULT_CASES = [
    '<root/>',
    '<root></root>',
    '<root> </root>',
    '<root>\t\r\n </root>',
    '<root>hello</root>',
    '<root>  hello world  </root>',
    '<root>first\nsecond\tthird</root>',
    '<root><child/></root>',
    '<root><child></child><child/><child> </child></root>',
    '<root><a>1</a><b>2</b><a>3</a><c>4</c></root>',
    '<root><a/><b/><a><nested/></a><a>text</a></root>',
    '<root a=""/>',
    '<root z="last" a="first" m="middle">text</root>',
    '<root a="value"><a>child</a></root>',
    '<root a="value">text<a/>more<b/>tail</root>',
    '<root>before<child>inside</child>after</root>',
    '<root> before <child/> after </root>',
    '<root><child/>tail</root>',
    '<root>head<child/></root>',
    '<root>one<child>discard from parent text</child>two<child/>three</root>',
    '<root><![CDATA[]]></root>',
    '<root><![CDATA[hello & <world>]]></root>',
    '<root>before<![CDATA[middle]]>after</root>',
    '<root><![CDATA[a]]><![CDATA[b]]><![CDATA[c]]></root>',
    '<root><![CDATA[a]]> <![CDATA[b]]></root>',
    '<root>a<!-- first --> <!-- second -->b</root>',
    '<root>a<child/> <child/>b</root>',
    '<root>a<?work first?>\t\r\n<?work second?>b</root>',
    '<root> <![CDATA[ ]]><child/><![CDATA[ ]]></root>',
    '<root><![CDATA[ \u00a0\u2003text\u3000 ]]></root>',
    '<root><!-- ignore me --></root>',
    '<!-- before --><root><!-- inside -->a<!-- middle -->b</root><!-- after -->',
    '<root>a<?work ignored?>b</root>',
    '<?work before?><root/><?work after?>',
    '<?xml version="1.0"?><root/>',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><root/>',
    '\ufeff<root>text</root>',
    '<root>&lt;&gt;&amp;&quot;&apos;</root>',
    '<root a="&lt;&gt;&amp;&quot;&apos;">&amp;lt;</root>',
    '<root>&#65;&#x41;&#x1F680;&#128640;</root>',
    '<root>&#9;&#10;&#13;text&#xA0;&#x2003;</root>',
    '<root>a&#13;b&#xD;c</root>',
    '<root a="&#9;&#10;&#13;&#xA0;"/>',
    '<root>a\rb\r\nc\nd</root>',
    '<root><![CDATA[a\rb\r\nc\nd]]></root>',
    '<root a="a\tb\nc\rd\r\ne"/>',
    '<root a=" \t\r\n " b="&#9;&#10;&#13;"/>',
    '<root a="a\r\n&#10;b">a\r\n&#13;b</root>',
    '<root>\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000</root>',
    '<root>\u200btext\ufeff</root>',
    '<root>café 日本語 Ελληνικά Кириллица 😀 𝄞</root>',
    '<日本 属性="値"><子>内容</子><子/></日本>',
    '<root xmlns="urn:default"><child/></root>',
    '<p:root xmlns:p="urn:p" p:a="x"><p:child/></p:root>',
    '<root xmlns:p="urn:p"><p:child xmlns:p="urn:q"/></root>',
    '<root xml:space="preserve">  still stripped  </root>',
    '<root xml:lang="en"><_:child a.b="x" a-b="y"/></root>',
    '<:root/>',
    '<root:/>',
    '<a:b:c/>',
    '<:root></:root>',
    '<root:></root:>',
    '<root a:b:c="x"><:child:/></root>',
    '<!DOCTYPE root><root/>',
    '<!DOCTYPE root [<!ELEMENT root (#PCDATA)>]><root>ok</root>',
    '<!DOCTYPE root [<!ENTITY value "hidden">]><root>before&value;after</root>',
    '<!DOCTYPE root [<!ATTLIST root a CDATA "default">]><root/>',
    '<!DOCTYPE root [<!ATTLIST root a NMTOKENS #IMPLIED>]><root a=" a   b "/>',
    '<!DOCTYPE root [<!ENTITY value "expanded in attribute">]><root a="&value;"/>',
    '<!DOCTYPE root [<!ENTITY value "hidden">]><root><![CDATA[&value;]]></root>',
]


@pytest.mark.parametrize('document', DEFAULT_CASES)
@pytest.mark.parametrize('as_bytes', [False, True], ids=['str', 'bytes'])
def test_default_corpus(document, as_bytes):
    assert_same(document.encode('utf-8') if as_bytes else document)


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'iso-8859-1', 'windows-1252'])
def test_declared_byte_encodings(encoding):
    declared = {'utf-8-sig': 'UTF-8', 'utf-16-le': 'UTF-16LE', 'utf-16-be': 'UTF-16BE'}.get(encoding, encoding)
    document = ('<?xml version="1.0" encoding="%s"?><root a="café">élève</root>' % declared).encode(encoding)
    assert_same(document)


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'iso-8859-1', 'windows-1252'])
def test_explicit_encoding(encoding):
    document = '<root a="café">élève</root>'
    assert_same(document, encoding=encoding)
    assert_same(document.encode(encoding), encoding=encoding)


def test_unicode_input_overrides_encoding_declaration_like_xmltodict():
    assert_same('<?xml version="1.0" encoding="ISO-8859-1"?><r>日本語</r>')


@pytest.mark.parametrize('input_type', [bytearray, memoryview])
def test_buffer_inputs_are_accepted_without_mutating_source(input_type):
    source = bytearray('<r a="é">a&amp;b<child/></r>'.encode())
    original = bytes(source)
    assert_same(input_type(source))
    assert bytes(source) == original


def test_binary_file():
    document = b'<root a="x"><child>one</child><child>two</child></root>'
    assert rapidxmltodict.parse(BytesIO(document)) == xmltodict.parse(BytesIO(document))


def test_text_file_rejected_like_reference():
    for module in (xmltodict, rapidxmltodict):
        with pytest.raises(TypeError):
            module.parse(StringIO('<root/>'))


@pytest.mark.parametrize('chunk_size', [1, 2, 3, 8, 31])
def test_byte_generator_split_inside_utf8_and_markup(chunk_size):
    document = '<root a="é">日本<![CDATA[😀]]><child>one</child><child/></root>'.encode()
    def chunks():
        for index in range(0, len(document), chunk_size):
            yield document[index:index + chunk_size]
    assert rapidxmltodict.parse(chunks()) == xmltodict.parse(chunks())


def test_string_generator():
    def chunks():
        yield '<root>'
        yield '日本'
        yield '<child>one</child>'
        yield '</root>'
    assert rapidxmltodict.parse(chunks()) == xmltodict.parse(chunks())


OPTION_DOCUMENT = '<root z="x" a="y"> head <!-- comment --><child a="1">one</child><child/><other>  two  </other><![CDATA[ tail ]]></root>'
OPTION_CASES = [
    {'xml_attribs': False},
    {'attr_prefix': ''},
    {'attr_prefix': '$'},
    {'cdata_key': '$text'},
    {'strip_whitespace': False},
    {'force_cdata': True},
    {'force_list': True},
    {'force_list': ('child', 'other')},
    {'force_list': lambda path, key, value: key == 'other'},
    {'dict_constructor': OrderedDict},
    {'process_comments': True},
    {'process_comments': True, 'comment_key': '$comment'},
    {'process_comments': True, 'strip_whitespace': False},
    {'cdata_separator': '|'},
    {'postprocessor': lambda path, key, value: (key.upper(), value)},
    {'postprocessor': lambda path, key, value: None if key == 'child' else (key, value)},
    {'xml_attribs': False, 'force_list': ('child',), 'force_cdata': True, 'strip_whitespace': False},
]


@pytest.mark.parametrize('options', OPTION_CASES)
def test_advanced_option_fallbacks(options):
    assert_same(OPTION_DOCUMENT, **options)


@pytest.mark.parametrize('options', [
    {'process_namespaces': True},
    {'process_namespaces': True, 'namespace_separator': '|'},
    {'process_namespaces': True, 'namespaces': {'urn:r': None, 'urn:p': 'p'}},
    {'process_namespaces': True, 'namespaces': {'urn:r': 'r', 'urn:p': None}},
    {'namespaces': {'p': 'q'}},
])
def test_namespace_fallbacks(options):
    assert_same('<r xmlns="urn:r" xmlns:p="urn:p" p:a="x"><p:c>value</p:c><c xmlns="urn:q"/></r>', **options)


@pytest.mark.parametrize('depth', [0, 1, 2, 3])
def test_streaming_callbacks(depth):
    document = '<root a="x"><item n="1"><name>one</name></item><item n="2"><name>two</name></item></root>'
    def run(module):
        seen = []
        def callback(path, item):
            seen.append(deepcopy((path, item)))
            return True
        result = module.parse(document, item_depth=depth, item_callback=callback)
        return result, seen
    assert run(rapidxmltodict) == run(xmltodict)


def test_streaming_callback_can_interrupt():
    calls = []
    def stop(path, item):
        calls.append(deepcopy((path, item)))
        return False
    with pytest.raises(rapidxmltodict.ParsingInterrupted):
        rapidxmltodict.parse('<root><item>one</item><item>two</item></root>', item_depth=2, item_callback=stop)
    assert len(calls) == 1
    assert calls[0][1] == 'one'


def test_removed_expat_parameter_is_rejected():
    with pytest.raises(TypeError):
        rapidxmltodict.parse('<root/>', expat=expat)


def test_unknown_keyword_rejected():
    for module in (xmltodict, rapidxmltodict):
        with pytest.raises(TypeError):
            module.parse('<root/>', not_a_real_option=True)


def _random_document(seed):
    rng = random.Random(seed)
    names = ['a', 'b', 'c', 'item', '_name', 'tag.name', 'tag-name', '日本', 'p:item']
    texts = ['', 'plain', ' two words ', '\t\r\n', 'é日本😀', '\u00a0 x \u2003', 'a\rb\r\nc', 'a & b < c > d', '\u200b']
    references = ['&amp;', '&lt;', '&#65;', '&#x1F680;', '&#9;', '&#10;', '&#13;', '&#xA0;']
    def node(depth):
        name = rng.choice(names)
        attributes = ''.join(' %s=%s' % (attr, quoteattr(rng.choice(texts))) for attr in ['x', 'y', 'z'][:rng.randrange(4)])
        if rng.randrange(5) == 0:
            return '<%s%s/>' % (name, attributes)
        parts = []
        for _ in range(rng.randrange(6)):
            kind = rng.randrange(6)
            if kind == 0 and depth < 3:
                parts.append(node(depth + 1))
            elif kind == 1:
                parts.append('<![CDATA[%s]]>' % rng.choice(texts))
            elif kind == 2:
                parts.append(rng.choice(references))
            elif kind == 3:
                parts.append('<!-- comment -->')
            elif kind == 4:
                parts.append('<?work ignored?>')
            else:
                parts.append(escape(rng.choice(texts)))
        return '<%s%s>%s</%s>' % (name, attributes, ''.join(parts), name)
    return node(0)


@pytest.mark.parametrize('seed', list(range(250)) + [810, 2363, 3774, 3829, 4312, 5661, 5934, 6814, 7083, 7219])
def test_deterministic_generated_documents(seed):
    document = _random_document(seed)
    assert_same(document)
    assert_same(document.encode())


def test_parse_results_own_their_values():
    source = bytearray(b'<root a="value"><child>one</child><child>two</child></root>')
    first = rapidxmltodict.parse(source)
    second = rapidxmltodict.parse(source)
    source[:] = b'x' * len(source)
    first['root']['child'].append('modified')
    assert second == {'root': {'@a': 'value', 'child': ['one', 'two']}}


def test_repeated_calls_and_threads_do_not_share_parser_state():
    documents = [_random_document(seed) for seed in range(32)]
    expected = [xmltodict.parse(document) for document in documents]
    def run(index):
        selected = index % len(documents)
        assert rapidxmltodict.parse(documents[selected]) == expected[selected]
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(run, range(320)))


def test_mixed_content_gap_combinations():
    # Whitespace-only text between separate markup nodes is significant in
    # mixed content even though purely formatting whitespace normally vanishes.
    segments = ['a', ' ', '\t\r\n', '<![CDATA[b]]>', '<![CDATA[ ]]>',
                '<child/>', '<!-- comment -->', '<?work ignored?>', '&#13;', '\u00a0']
    for parts in product(segments, repeat=3):
        assert_same('<root>left%sright</root>' % ''.join(parts))


@pytest.mark.parametrize('size', [8191, 8192, 8193, 65536])
def test_text_and_attributes_across_expat_buffer_boundaries(size):
    assert_same('<root>%s</root>' % ('é' * size))
    assert_same('<root a="%s"/>' % ('é&amp;' * size))
