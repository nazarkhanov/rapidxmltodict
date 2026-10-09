"""Source-position diagnostics from the consuming RapidXML DOM parser."""
from xml.parsers import expat

import pytest
import xmltodict

import rapidxmltodict
from rapidxmltodict import _native


@pytest.mark.parametrize('document', [
    '<?xml?><r/>',
    '<?xml?',
    '<?pi?',
    '<?xml?x>',
    '<?pi?x>',
    '<?xml version="1.0"?',
    '<?xml version="1.0"?<r/>',
    '<?xml version="1.0"?x?>',
    '<r><!-- note--',
    '<r><!-- note---',
    '<?xml version="1.0"',
    '<r><!-- note--x --></r>',
    '<r>plain ]]></r>',
    '<r a="one\r\ntwo" a="duplicate"/>',
    '<r>one&amp;two\r\n<i></r>',
    '<r><![CDATA[one\r\ntwo]]><i></r>',
    '<r><!-- one\r\ntwo --><i></r>',
    '<r><?work one\r\ntwo?><i></r>',
])
@pytest.mark.parametrize('as_bytes', [False, True])
def test_dom_diagnostic_uses_original_source(document, as_bytes):
    if as_bytes:
        document = document.encode('utf-8')
    with pytest.raises(expat.ExpatError) as expected:
        xmltodict.parse(document)
    with pytest.raises(rapidxmltodict.ParseError) as actual:
        rapidxmltodict.parse(document)
    error, reference = actual.value, expected.value
    assert (error.code, error.lineno, error.offset) == (
        reference.code, reference.lineno, reference.offset)
    assert str(error) == str(reference)
    data = document if isinstance(document, bytes) else document.encode('utf-8')
    with pytest.raises(rapidxmltodict.ParseError) as direct:
        _native.convert(data)
    assert direct.value.byte_index == error.byte_index
