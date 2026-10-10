"""Version-sensitive test inputs and platform-independent oracle expectations.

Only standard-library modules are imported here. Expectations are produced by
xmltodict alone in scripts/check_reference_oracle.py, never by rapidxmltodict.
The exact target environment is a test oracle, not a runtime dependency.
"""
import codecs
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


CANONICAL_ORACLE = {
    'python': '3.12.15',
    'xmltodict': '1.0.4',
    'expat': 'expat_2.8.5',
    'reparse_deferral': True,
}
FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'oracle_104_chunking.json'


@dataclass(frozen=True)
class ChunkCase:
    id: str
    document: object
    chunk_size: int
    options: dict

    def chunks(self):
        data = self.document
        return (data[i:i + self.chunk_size]
                for i in range(0, len(data), self.chunk_size))

    def specification(self):
        document = ({'kind': 'bytes', 'hex': self.document.hex()}
                    if isinstance(self.document, bytes)
                    else {'kind': 'text', 'text': self.document})
        return {'id': self.id, 'document': document,
                'chunk_size': self.chunk_size, 'options': self.options}


_PARTIAL_DOCUMENTS = [
    '<root>hello</root>',
    '<root><child/>tail</root>',
    '<root><![CDATA[hello & <world>]]></root>',
    '<root><![CDATA[a]]> <![CDATA[b]]></root>',
    '<root>&#9;&#10;&#13;text&#xA0;&#x2003;</root>',
    '<root>café 日本語 Ελληνικά Кириллица 😀 𝄞</root>',
    '<root z="last" a="first" m="middle">text</root>',
    '<r>a<![CDATA[b]]>c</r>', '<r>a&amp;b&#10;c</r>',
    '<r>a\r\nb\rc\nd</r>', '<r>a<!--comment-->b<?pi x?>c</r>',
    '<?xml version="1.0" encoding="UTF-8"?><root>hello</root>',
]
_DTD_DECLARATIONS = [
    '<!DOCTYPE r [<!ELEMENT r (#PCDATA)>]>',
    '<!DOCTYPE r [<!ENTITY e "word"><!ENTITY f "a&e;b">]>',
    '<!DOCTYPE r [<!ATTLIST r a CDATA "default">]>',
    '<!DOCTYPE r [<!--comment--><!ELEMENT r (#PCDATA)>]>',
    '<!DOCTYPE r SYSTEM "not-fetched">',
    '<!DOCTYPE r PUBLIC "id" "not-fetched">',
]


def _cases():
    cases = []
    for as_bytes in (False, True):
        for chunk_size in (1, 2, 7, 2048):
            for index, document in enumerate(_PARTIAL_DOCUMENTS):
                kind = 'bytes' if as_bytes else 'text'
                cases.append(ChunkCase(
                    'partial-%s-%s-%02d' % (kind, chunk_size, index),
                    document.encode('utf-8') if as_bytes else document,
                    chunk_size, {'cdata_separator': '|', 'process_comments': True,
                                 'strip_whitespace': False}))
    for chunk_size in (1, 2, 3, 7, 11):
        for encoding, label in (('utf-16', 'utf-16'),
                                ('utf-16-le', 'UTF-16LE'),
                                ('utf-16-be', 'UTF-16BE')):
            text = ('<?xml version="1.0" encoding="%s"?>'
                    '<root><child/>text</root>') % label
            # Fix the BOM/input byte order in the fixture, independently of the
            # host's native endianness. UTF-16 autodetection still runs normally.
            data = (codecs.BOM_UTF16_LE + text.encode('utf-16-le')
                    if encoding == 'utf-16' else text.encode(encoding))
            cases.append(ChunkCase('utf16-%s-%s' % (encoding, chunk_size),
                                   data, chunk_size, {'cdata_separator': '|'}))
    for comments in (False, True):
        for chunk_size in (1, 2, 3, 4, 5, 7, 11):
            for index, declaration in enumerate(_DTD_DECLARATIONS):
                cases.append(ChunkCase(
                    'dtd-%s-%s-%02d' % (int(comments), chunk_size, index),
                    declaration + '<r>text</r>', chunk_size,
                    {'disable_entities': False, 'process_comments': comments,
                     'cdata_separator': '|', 'strip_whitespace': False}))
    cases.append(ChunkCase(
        'native-mapping-comments-seven-byte',
        ('<!--before--><r a="1"> before <x>one</x><x/><y> two </y>'
         '<![CDATA[ tail ]]><!--after--></r>').encode('utf-8'),
        7, {'cdata_separator': '|'}))
    assert len(cases) == 196
    assert len({case.id for case in cases}) == len(cases)
    return tuple(cases)


CHUNK_CASES = _cases()
MAPPING_CHUNK_CASE = next(case for case in CHUNK_CASES
                          if case.id == 'native-mapping-comments-seven-byte')
PARTIAL_TOKEN_CASES = tuple(case for case in CHUNK_CASES if case.id.startswith('partial-'))
UTF16_CHUNK_CASES = tuple(case for case in CHUNK_CASES if case.id.startswith('utf16-'))
DTD_CHUNK_CASES = tuple(case for case in CHUNK_CASES if case.id.startswith('dtd-'))


def ordered_shape(value):
    """JSON-safe result shape, preserving dictionary order and scalar types."""
    if type(value) is dict:
        return ['dict', [[key, ordered_shape(item)] for key, item in value.items()]]
    if type(value) is list:
        return ['list', [ordered_shape(item) for item in value]]
    if value is None:
        return ['none']
    if type(value) is str:
        return ['str', value]
    raise TypeError('Unexpected oracle result type: %s' % type(value).__name__)


@lru_cache(maxsize=1)
def _expected_cases():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    assert fixture['schema_version'] == 1
    assert fixture['target_oracle'] == CANONICAL_ORACLE
    records = fixture['cases']
    by_id = {record['id']: record for record in records}
    assert len(records) == len(by_id) == len(CHUNK_CASES)
    assert set(by_id) == {case.id for case in CHUNK_CASES}
    for case in CHUNK_CASES:
        specification = dict(by_id[case.id])
        specification.pop('expected')
        assert specification == case.specification(), case.id
    return by_id


def assert_chunk_contract(case, candidate_parse, live_oracle_parse):
    """Always enforce canonical chunking plus a live semantic comparison."""
    expected = _expected_cases()[case.id]['expected']
    assert ordered_shape(candidate_parse(case.chunks(), **case.options)) == expected, case.id
    options = dict(case.options, cdata_separator='')
    assert ordered_shape(candidate_parse(case.chunks(), **options)) == ordered_shape(
        live_oracle_parse(case.chunks(), **options)), case.id
