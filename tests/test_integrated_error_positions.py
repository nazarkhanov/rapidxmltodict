"""Ordinary syntax diagnostics share original-source positions across parsers."""
from xml.parsers import expat

import pytest
import rapidxmltodict
from rapidxmltodict import _native


# Each expected tuple is code, line, column, UTF-8 byte index. Check the ordinary
# reference parser too so a platform-oracle difference cannot silently pass.
CASES = [
    (b'\xef', (5, 1, 0, 0)),
    (b'\xef\xbb', (5, 1, 0, 0)),
    (b'\xc2', (6, 1, 0, 0)),
    (b'<?xml?><root/>', (30, 1, 5, 5)),
    (b'<?xml?', (5, 1, 0, 0)),
    (b'<?pi?', (5, 1, 0, 0)),
    (b'<?xml?x>', (4, 1, 6, 6)),
    (b'<?pi?x>', (4, 1, 5, 5)),
    (b'<?xml version="1.0"?', (5, 1, 0, 0)),
    (b'<?xml version="1.0"?<r/>', (5, 1, 0, 0)),
    (b'<?xml version="1.0"?x?>', (30, 1, 19, 19)),
    (b'<r><!-- note--', (5, 1, 3, 3)),
    (b'<r><!-- note---', (4, 1, 14, 14)),
    (b'<?xml ?><root/>', (30, 1, 5, 5)),
    (b'<?xml version="1.0"', (5, 1, 0, 0)),
    (b'<root>&</root>', (4, 1, 7, 7)),
    (b'<root>\xe2\x82</root>', (4, 1, 6, 6)),
    (b'<r>ab\xc3(</r>', (4, 1, 5, 5)),
    (b'<r a="ab\xc3("/>', (4, 1, 8, 8)),
    (b'<root><!-- invalid -- comment --></root>', (4, 1, 21, 21)),
    (b'<r><!-- note--x --></r>', (4, 1, 14, 14)),
    (b'<root><?unfinished</root>', (4, 1, 18, 18)),
    (b'<r>plain &amp', (5, 1, 9, 9)),
    (b'<r>plain &#12', (5, 1, 9, 9)),
    (b'<r>plain ]]></r>', (4, 1, 11, 11)),
    ('<r>é\r\nplain ]]></r>'.encode(), (4, 2, 8, 15)),
]


@pytest.mark.parametrize('document,expected', CASES)
def test_reference_error_positions(document, expected):
    parser = expat.ParserCreate()
    with pytest.raises(expat.ExpatError) as caught:
        parser.Parse(document, True)
    error = caught.value
    assert (error.code, error.lineno, error.offset, parser.ErrorByteIndex) == expected


@pytest.mark.parametrize('document,expected', CASES)
@pytest.mark.parametrize('path', ['dom', 'events', 'chunks'])
def test_integrated_error_positions(document, expected, path):
    if path == 'dom':
        parse = _native.convert
    elif path == 'events':
        parse = lambda data: rapidxmltodict.parse(data, strip_whitespace=True)
    else:
        parse = lambda data: rapidxmltodict.parse((data[i:i + 2] for i in range(0, len(data), 2)))
    with pytest.raises(rapidxmltodict.ParseError) as caught:
        parse(document)
    error = caught.value
    assert (error.code, error.lineno, error.offset, error.byte_index) == expected
