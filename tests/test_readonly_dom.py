"""Read-only DOM spans and final Unicode values must own the right memory.

xmltodict/Expat are test-only references. These in-memory default-option cases
avoid the version-sensitive chunk boundaries covered by the golden oracle suite.
"""
import gc
import sys
from xml.parsers import expat

import pytest
import xmltodict

import rapidxmltodict
from rapidxmltodict import _native


@pytest.fixture(params=['public', 'native'])
def parse(request):
    return rapidxmltodict.parse if request.param == 'public' else _native.convert


def _source(text, as_bytes):
    # Always make a distinct immutable object, including for ASCII strings.
    data = text.encode('utf-8', 'surrogatepass')
    return data if as_bytes else data.decode('utf-8', 'surrogatepass')


def _snapshot(source):
    # bytes(source) and a full string slice can return source itself, which
    # would let accidental in-place native writes mutate the expected value too.
    if isinstance(source, bytes):
        return memoryview(source).tobytes()
    # Check both the Unicode value and its UTF-8 representation: non-ASCII
    # input can have a separate UTF-8 cache borrowed by the native parser.
    return tuple(map(ord, source)), source.encode('utf-8', 'surrogatepass')


NORMALIZATION_CASES = [
    ('<r a="\t\r\n&#9;&#10;&#13;">L\r\nM\rN\t&#9;&#10;&#13;R</r>',
     {'r': {'@a': '  \t\n\r', '#text': 'L\nM\nN\t\t\n\rR'}}),
    ('<r a="&amp;lt;&lt;&gt;&quot;&apos;">&amp;lt;&lt;&gt;&quot;&apos;</r>',
     {'r': {'@a': '&lt;<>"\'', '#text': '&lt;<>"\''}}),
    ('<r a="&#65;&#xE9;&#x6771;&#x1F642;">&#65;&#xE9;&#x6771;&#x1F642;</r>',
     {'r': {'@a': 'Aé東🙂', '#text': 'Aé東🙂'}}),
    ('<r>L&#13;\n<![CDATA[\r]]>\nR</r>', {'r': 'L\r\n\n\nR'}),
    ('<r a="\u00a0\u2003">\u00a0<![CDATA[\u2003]]>&#9;&#10;&#13;</r>',
     {'r': {'@a': '\u00a0\u2003'}}),
    ('<r> &#xA0;<![CDATA[\u2003]]>a<!--ignored--> b<?pi &amp;?>c<x/>'
     'd<![CDATA[&amp;\r\n]]>&amp;e&#x2003; </r>',
     {'r': {'x': None, '#text': 'a bcd&amp;\n&e'}}),
    ('<r><![CDATA[]]><!--ignored--><?pi ignored?><![CDATA[]]></r>',
     {'r': None}),
    ('<r a="">before<x/> between <x/>after</r>',
     {'r': {'@a': '', 'x': [None, None], '#text': 'before between after'}}),
]


@pytest.mark.parametrize('document,expected', NORMALIZATION_CASES)
@pytest.mark.parametrize('as_bytes', [False, True], ids=['str', 'bytes'])
def test_normalized_spans_leave_successful_input_unchanged(parse, as_bytes, document, expected):
    source = _source(document, as_bytes)
    before = _snapshot(source)
    assert xmltodict.parse(source) == expected
    # Parsing twice also catches terminators/entity normalization written into
    # a borrowed buffer after the first otherwise-correct conversion.
    assert parse(source) == expected
    assert _snapshot(source) == before
    assert parse(source) == expected
    assert _snapshot(source) == before


@pytest.mark.parametrize('literal', ['ASCII', 'caféÿ', '東京\u0800', '🙂\U0010ffff'])
@pytest.mark.parametrize('as_bytes', [False, True], ids=['str', 'bytes'])
def test_unicode_width_is_chosen_after_all_spans_are_normalized(parse, as_bytes, literal):
    # The source's Unicode width and the widest decoded reference need not
    # match. A later span can require widening even when the first is ASCII.
    document = ('<root plain="%s" ref="&#x1F642;" narrow="&#65;">'
                '<value>start<![CDATA[%s]]>&#x1F642;end</value>'
                '<value>&#x1F642;<![CDATA[%s]]>tail</value>'
                '<value>\u2003&#65;\u2003</value></root>') % (literal, literal, literal)
    source = _source(document, as_bytes)
    before = _snapshot(source)
    expected = {'root': {
        '@plain': literal, '@ref': '🙂', '@narrow': 'A',
        'value': ['start' + literal + '🙂end', '🙂' + literal + 'tail', 'A'],
    }}
    assert xmltodict.parse(source) == expected
    assert parse(source) == expected
    assert _snapshot(source) == before


@pytest.mark.parametrize('name', ['plain_name', 'élève', '東京', 'Ω_имя'])
@pytest.mark.parametrize('as_bytes', [False, True], ids=['str', 'bytes'])
def test_borrowed_name_spans_preserve_non_ascii_keys(parse, as_bytes, name):
    source = _source('<%s %s="first&amp;second"><%s>value</%s></%s>' %
                     (name, name, name, name, name), as_bytes)
    before = _snapshot(source)
    expected = {name: {'@' + name: 'first&second', name: 'value'}}
    assert xmltodict.parse(source) == expected
    assert parse(source) == expected
    assert _snapshot(source) == before


FAILURE_TAILS = [
    '</wrong>',
    '<x duplicate="one&#13;two" duplicate="other"/>',
    '<x a="valid&amp;prefix &unknown;"/>',
    '<x>valid&amp;prefix &#x110000;</x>',
    '<x><![CDATA[unfinished\r\n',
    '<x><!-- valid\r\nthen--invalid --></x>',
    '<x>literal ]]></x>',
    '<x>literal\x00</x>',
    '<x>',
]


@pytest.mark.parametrize('tail', FAILURE_TAILS)
@pytest.mark.parametrize('as_bytes', [False, True], ids=['str', 'bytes'])
def test_error_positions_use_unchanged_source_after_normalized_prefix(parse, as_bytes, tail):
    document = ('\ufeff<root a="é&#13;\r\n🙂">one&amp;two\r\n'
                '<![CDATA[東京\r\nthree]]><!--gap--><?pi ignored?>' + tail)
    source = _source(document, as_bytes)
    before = _snapshot(source)
    with pytest.raises(expat.ExpatError) as expected:
        xmltodict.parse(source)
    reference = expat.ParserCreate()
    with pytest.raises(expat.ExpatError):
        reference.Parse(source, True)
    for _ in range(2):
        with pytest.raises(rapidxmltodict.ParseError) as actual:
            parse(source)
        assert (actual.value.code, actual.value.lineno, actual.value.offset,
                actual.value.byte_index) == (
                    expected.value.code, expected.value.lineno,
                    expected.value.offset, reference.ErrorByteIndex)
        assert str(actual.value) == str(expected.value)
        assert _snapshot(source) == before


@pytest.mark.parametrize('document', [
    '<r>\ud800</r>',
    '<r a="é\udfff"/>',
    '<r><![CDATA[\ud800\udc00]]></r>',
    '<r><!--\ud800--></r>',
    '<r><?pi \udfff?></r>',
    '<\ud800/>',
])
def test_surrogate_strings_keep_reference_encoding_errors_and_input(parse, document):
    source = _source(document, False)
    before = _snapshot(source)
    with pytest.raises(UnicodeEncodeError) as expected:
        xmltodict.parse(source)
    with pytest.raises(UnicodeEncodeError) as actual:
        parse(source)
    assert actual.value.args == expected.value.args
    assert _snapshot(source) == before


@pytest.mark.parametrize('as_bytes', [False, True], ids=['str', 'bytes'])
def test_results_survive_input_release_and_later_successes_and_failures(parse, as_bytes):
    retained = []
    expected = []
    for index in range(40):
        # Unique names/attributes exercise the borrowed name cache too; values
        # include direct literals, decoded references and joined CDATA spans.
        name = 'record_%d_東京' % index
        source = _source(
            '<root><%s unique_%d="é&#13;🙂">left&amp;<![CDATA[東京\r\n]]>'
            '&#x1F642;<leaf/>right</%s></root>' % (name, index, name), as_bytes)
        expected.append(xmltodict.parse(source))
        retained.append(parse(source))
        del source
        with pytest.raises(rapidxmltodict.ParseError):
            parse(_source('<root a="&amp;">overwritten\r\n</wrong>', as_bytes))
        assert parse(_source('<root><other>replacement</other></root>', as_bytes)) == {
            'root': {'other': 'replacement'}}
    gc.collect()
    # Allocate similarly sized objects after freeing every original input.
    churn = [_source('<discard a="%s">%s</discard>' % ('x' * 40, 'y' * 120), as_bytes)
             for _ in range(1000)]
    assert retained == expected
    assert len(churn) == 1000


@pytest.mark.parametrize('as_bytes', [False, True], ids=['str', 'bytes'])
def test_repeated_success_and_error_calls_do_not_retain_inputs(parse, as_bytes):
    good = _source('<root a="é&#13;🙂">left&amp;<![CDATA[東京\r\n]]>right</root>', as_bytes)
    bad = _source('<root a="é&#13;🙂">left&amp;<![CDATA[東京\r\n]]></wrong>', as_bytes)
    before = sys.getrefcount(good), sys.getrefcount(bad)
    for _ in range(100):
        assert parse(good) == {'root': {'@a': 'é\r🙂', '#text': 'left&東京\nright'}}
        with pytest.raises(rapidxmltodict.ParseError):
            parse(bad)
    gc.collect()
    assert (sys.getrefcount(good), sys.getrefcount(bad)) == before


@pytest.mark.parametrize('as_bytes', [False, True], ids=['str', 'bytes'])
def test_deep_iterative_frames_keep_raw_spans_alive(parse, as_bytes):
    depth = 1536
    source = _source(
        '<node a="&#x1F642;\r\n">left&amp;<![CDATA[東京\r\n]]>' * depth
        + '<leaf>é</leaf>' + '&#xE9;<!--gap--><?pi ignored?>right</node>' * depth,
        as_bytes)
    before = _snapshot(source)
    actual = parse(source)
    expected = xmltodict.parse(source)
    assert _snapshot(source) == before
    del source
    gc.collect()
    # Avoid recursive equality, which would hit Python's recursion limit and
    # obscure whether the native parser/converter itself remains iterative.
    for level in range(depth):
        actual, expected = actual['node'], expected['node']
        assert list(actual) == list(expected)
        assert actual['@a'] == expected['@a'] == '🙂 '
        assert actual['#text'] == expected['#text'] == 'left&東京\néright'
        if level + 1 == depth:
            assert actual['leaf'] == expected['leaf'] == 'é'
