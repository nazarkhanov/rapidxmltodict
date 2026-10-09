"""Malformed XML, entity safety, and crash-regression checks.

These checks establish compatibility with xmltodict, not that arbitrary XML is
safe without application-level input-size and resource limits.
"""

import os
from pathlib import Path
import subprocess
import sys
from xml.parsers.expat import ExpatError

import pytest
import xmltodict

import rapidxmltodict


MALFORMED = [
    b'', b' ', b'text', b'<', b'>', b'<>', b'</root>',
    b'<root>', b'<root></wrong>', b'<root><child></root></child>',
    b'<root/><second/>', b'<root/>trailing', b'leading<root/>',
    b'<root a="x" a="y"/>', b'<root a=x/>', b'<root a="unterminated/>',
    b'<root a="<"/>', b'<root a/>', b'<root a="x"b="y"/>',
    b'<1root/>', b'<root a?="x"/>', b'<root/ >', b'<root /x>',
    b'<root>&unknown;</root>', b'<root>&amp</root>', b'<root>&</root>',
    b'<root>&#;</root>', b'<root>&#x;</root>', b'<root>&#xGG;</root>',
    b'<root>&#0;</root>', b'<root>&#1;</root>', b'<root>&#xD800;</root>',
    b'<root>&#x110000;</root>', b'<root>&#999999999999999999999999999999999;</root>',
    b'<root>\x00</root>', b'<root/>\x00<other/>', b'<root>\x01</root>',
    b'<root>\xff</root>', b'<root>\xc0\xaf</root>', b'<root>\xed\xa0\x80</root>',
    b'<root>\xf4\x90\x80\x80</root>', b'<root>\xe2\x82</root>',
    b'\xef\xbb\xbf\xef\xbb\xbf<root/>',
    b'<root><![CDATA[unfinished</root>', b'<root>]]></root>',
    b'<root><!-- unfinished</root>', b'<root><!-- invalid -- comment --></root>',
    b'<root><?unfinished</root>', b'<root><?xml version="1.0"?></root>',
    b'<?xml?><root/>', b'<?xml version="1.0"?><?xml version="1.0"?><root/>',
    b' <!DOCTYPE', b'<!DOCTYPE root [><root/>',
]


@pytest.mark.parametrize('document', MALFORMED)
def test_malformed_xml_is_rejected(document):
    with pytest.raises(ExpatError):
        xmltodict.parse(document)
    with pytest.raises(ExpatError):
        rapidxmltodict.parse(document)


@pytest.mark.parametrize('disable_entities', [True, False])
def test_internal_entity_policy_matches_reference(disable_entities):
    document = '<!DOCTYPE root [<!ENTITY word "hello"><!ENTITY twice "&word; &word;">]><root a="&word;">before &twice; after</root>'
    assert rapidxmltodict.parse(document, disable_entities=disable_entities) == xmltodict.parse(document, disable_entities=disable_entities)


@pytest.mark.parametrize('disable_entities', [True, False])
def test_external_file_entities_are_not_loaded(tmp_path, disable_entities):
    secret = tmp_path / 'external-entity.txt'
    secret.write_text('ENTITY_FILE_CONTENT_MUST_NOT_APPEAR', encoding='utf-8')
    document = '<!DOCTYPE root [<!ENTITY secret SYSTEM "%s">]><root>before&secret;after</root>' % secret.as_uri()
    actual = rapidxmltodict.parse(document, disable_entities=disable_entities)
    assert actual == xmltodict.parse(document, disable_entities=disable_entities)
    assert 'ENTITY_FILE_CONTENT_MUST_NOT_APPEAR' not in repr(actual)


def test_entity_expansion_disabled_by_default():
    declarations = ['<!ENTITY a "literal">']
    previous = 'a'
    for index in range(6):
        name = 'e%d' % index
        declarations.append('<!ENTITY %s "%s">' % (name, ('&%s;' % previous) * 10))
        previous = name
    document = '<!DOCTYPE root [%s]><root>&%s;</root>' % (''.join(declarations), previous)
    assert rapidxmltodict.parse(document) == {'root': None}


def _run_isolated(program):
    env = os.environ.copy()
    root = str(Path(__file__).resolve().parents[1])
    env['PYTHONPATH'] = root + os.pathsep + env.get('PYTHONPATH', '')
    result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', program], capture_output=True, text=True, timeout=30, env=env)
    assert result.returncode == 0, 'Isolated parse failed:\n%s\n%s' % (result.stdout, result.stderr)


def test_deep_document_does_not_crash_process():
    _run_isolated('''
import rapidxmltodict
import xmltodict
depth = 2000
document = '<node>' * depth + 'leaf' + '</node>' * depth
actual = rapidxmltodict.parse(document)
expected = xmltodict.parse(document)
for index in range(depth):
    actual = actual['node']
    expected = expected['node']
assert actual == expected == 'leaf'
''')


def test_deterministic_mutation_corpus_does_not_crash_or_accept_invalid_xml():
    _run_isolated(r'''
import random
import rapidxmltodict
import xmltodict

rng = random.Random(739201)
base = b'<?xml version="1.0"?><root a="value"><item>one&amp;two</item><item><![CDATA[text]]></item></root>'
alphabet = b'<>/&;=\x00\xff\x01\r\n\t\"\' abc0123456789'
cases = [base[:position] for position in range(len(base))]
for iteration in range(600):
    document = bytearray(base)
    for mutation in range(rng.randrange(1, 5)):
        position = rng.randrange(len(document) + 1)
        operation = rng.randrange(3)
        if operation == 0:
            document[position:position] = bytes([rng.choice(alphabet)])
        elif operation == 1:
            del document[position:position + 1]
        elif position < len(document):
            document[position] = rng.choice(alphabet)
    cases.append(bytes(document))
for document in cases:
    try:
        expected = xmltodict.parse(document)
    except Exception as expected_error:
        try:
            rapidxmltodict.parse(document)
        except Exception as actual_error:
            assert type(actual_error) is type(expected_error), (document, type(actual_error), type(expected_error))
        else:
            raise AssertionError(('accepted invalid XML', document))
    else:
        assert rapidxmltodict.parse(document) == expected, document
''')
