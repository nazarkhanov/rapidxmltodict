"""Strict UTF-8 literals in the allocation-light native validator."""
from xml.parsers import expat

import pytest
import xmltodict
import rapidxmltodict
from rapidxmltodict import _native


CONTEXTS = [
    (b'<root>', b'</root>'),
    (b'<root value="', b'"/>'),
    (b'<root><!--', b'--></root>'),
    (b'<root><![CDATA[', b']]></root>'),
    (b'<root><?work ', b'?></root>'),
]


@pytest.mark.parametrize('prefix,suffix', CONTEXTS)
@pytest.mark.parametrize('text', ['café', '東京', '🙂', 'é日😀', '\u0080\u07ff\u0800',
                                  '\ud7ff\ue000\ufffd', '\U00010000\U0010ffff', '\ufdd0\U0001fffe'])
def test_valid_utf8_literals_match_oracle(prefix, suffix, text):
    document = prefix + text.encode('utf-8') + suffix
    assert _native.validate(document) is None
    assert rapidxmltodict.parse(document) == xmltodict.parse(document)


@pytest.mark.parametrize('prefix,suffix', CONTEXTS)
@pytest.mark.parametrize('invalid', [
    b'\x80', b'\xbf', b'\xc0\xaf', b'\xc1\xbf', b'\xc2', b'\xc2A',
    b'\xe0\x80\xaf', b'\xe0\x9f\xbf', b'\xe2\x82', b'\xed\xa0\x80',
    b'\xed\xbf\xbf', b'\xef\xbf\xbe', b'\xef\xbf\xbf',
    b'\xf0\x80\x80\x80', b'\xf0\x8f\xbf\xbf', b'\xf0\x9f\x99',
    b'\xf4\x90\x80\x80', b'\xf5\x80\x80\x80', b'\xff', b'\x00', b'\x01',
])
def test_invalid_utf8_literals_never_bypass_full_validation(prefix, suffix, invalid):
    document = prefix + invalid + suffix
    with pytest.raises(expat.ExpatError):
        xmltodict.parse(document)
    with pytest.raises(rapidxmltodict.ParseError):
        _native.validate(document)
    with pytest.raises(rapidxmltodict.ParseError):
        rapidxmltodict.parse(document)


@pytest.mark.parametrize('document', [
    '<日本 属性="café"><子>🙂</子></日本>',
    '<?日本 café?><root/>',
    '<root 日本="café"/>',
])
def test_unicode_names_keep_complete_validator_fallback(document):
    assert rapidxmltodict.parse(document) == xmltodict.parse(document)
