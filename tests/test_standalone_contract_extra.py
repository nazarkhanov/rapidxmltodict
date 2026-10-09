"""Focused 1.0.4 contracts for normal streaming and mapping use.

xmltodict is only the test oracle. The standalone package deliberately owns its
parse/interruption exceptions, so comparisons translate those two identities.
"""
from collections import OrderedDict
from copy import deepcopy
from xml.parsers.expat import ExpatError

import pytest
import xmltodict

import rapidxmltodict


def _shape(value):
    if isinstance(value, dict):
        return type(value), tuple((key, _shape(item)) for key, item in value.items())
    if isinstance(value, list):
        return type(value), tuple(_shape(item) for item in value)
    return type(value), value


def _compare(document, **options):
    try:
        expected = xmltodict.parse(document, **options)
    except Exception as expected_error:
        error_type = (rapidxmltodict.ParseError if isinstance(expected_error, ExpatError)
                      else type(expected_error))
        with pytest.raises(error_type) as caught:
            rapidxmltodict.parse(document, **options)
        if isinstance(expected_error, ExpatError):
            assert caught.value.code == expected_error.code
        return
    assert _shape(rapidxmltodict.parse(document, **options)) == _shape(expected)


@pytest.mark.parametrize('encoding', [
    'utf-8', 'UTF-8', 'utf8', 'UTF8', 'latin-1', 'latin1',
    'iso-8859-1', 'ISO8859-1', 'windows-1252', 'cp1252',
    'UTF-16LE', 'utf-16-le', 'UTF-16BE', 'utf-16-be',
])
@pytest.mark.parametrize('as_bytes', [False, True])
def test_encoding_name_aliases_follow_oracle(encoding, as_bytes):
    document = '<r a="café">élève</r>'
    if as_bytes:
        document = document.encode(encoding)
    _compare(document, encoding=encoding)


@pytest.mark.parametrize('encoding', ['utf-8', 'UTF8', 'latin1', 'ISO8859-1', 'windows-1252'])
def test_declared_encoding_names_follow_oracle(encoding):
    document = ('<?xml version="1.0" encoding="%s"?><r>café</r>' % encoding).encode(encoding)
    _compare(document)
    _compare(document, force_list=('r',))


@pytest.mark.parametrize('document,options', [
    ('<r xmlns:a="urn:a" xmlns:b="urn:b" a:x="first" b:x="last"><a:x>A</a:x><b:x>B</b:x></r>',
     {'namespaces': {'urn:a': None, 'urn:b': None}}),
    ('<r xmlns:a="urn:a" xmlns:b="urn:b" a:x="first" b:x="last"><a:x>A</a:x><b:x>B</b:x></r>',
     {'namespaces': {'urn:a': 'same', 'urn:b': 'same'}, 'attr_prefix': ''}),
    ('<r xmlns="urn:r" xmlns:a="urn:a"><a:x xmlns:a="urn:b"/><a:x/><x xmlns=""/></r>',
     {'xml_attribs': False, 'force_list': True}),
    ('<r xmlns:a="ab" xmlns:b="a" a:c="first" b:bc="last"/>',
     {'namespace_separator': ''}),
    ('<r xmlns:a="urn:a" a:x="first"><a:x>A</a:x></r>',
     {'namespace_separator': None}),
])
def test_namespace_collisions_and_option_interactions(document, options):
    _compare(document, process_namespaces=True, dict_constructor=OrderedDict, **options)


def test_mapping_callback_order_and_paths():
    document = '<r a="x"> head <!-- note --><x> one </x><x>two</x><skip/><y a="v">tail</y></r>'

    def run(module):
        events = []
        def postprocess(path, key, value):
            events.append(('postprocess', deepcopy((path, key, value))))
            return None if key == 'skip' else (key.upper(), value)
        def force_cdata(path, key, value):
            events.append(('force_cdata', deepcopy((path, key, value))))
            return key == 'x'
        def force_list(path, key, value):
            events.append(('force_list', deepcopy((path, key, value))))
            return key == 'X'
        result = module.parse(document, postprocessor=postprocess,
                              force_cdata=force_cdata, force_list=force_list,
                              process_comments=True, dict_constructor=OrderedDict)
        return _shape(result), events
    assert run(rapidxmltodict) == run(xmltodict)


@pytest.mark.parametrize('source_kind', ['generator', 'file'])
def test_input_failure_preserves_prior_callbacks_and_exception(source_kind):
    marker = OSError('input interrupted')
    def run(module):
        events = []
        def chunks():
            events.append('first input')
            yield b'<r><i>one</i>'
            events.append('next input')
            raise marker
        if source_kind == 'generator':
            source = chunks()
        else:
            class Source:
                def __init__(self):
                    self.parts = chunks()
                def read(self, size):
                    assert size == 2048
                    return next(self.parts)
            source = Source()
        def callback(path, item):
            events.append(('callback', deepcopy((path, item))))
            return True
        with pytest.raises(OSError) as caught:
            module.parse(source, item_depth=2, item_callback=callback)
        assert caught.value is marker
        return events
    assert run(rapidxmltodict) == run(xmltodict)


@pytest.mark.parametrize('false_value', [False, None, 0, '', []])
def test_false_callback_results_stop_before_consuming_next_chunk(false_value):
    def run(module):
        events = []
        def chunks():
            yield '<r><i>one</i>'
            events.append('unexpected next input')
            yield '</r>'
        def callback(path, item):
            events.append(('callback', deepcopy((path, item))))
            return false_value
        with pytest.raises(module.ParsingInterrupted):
            module.parse(chunks(), item_depth=2, item_callback=callback)
        return events
    assert run(rapidxmltodict) == run(xmltodict)


def test_postprocessor_exception_is_not_replaced_or_followed_by_more_input():
    marker = LookupError('postprocessor interrupted')
    def run(module):
        events = []
        def chunks():
            yield '<r><i>one</i>'
            events.append('unexpected next input')
            yield '</r>'
        def postprocess(path, key, value):
            events.append((key, value))
            raise marker
        with pytest.raises(LookupError) as caught:
            module.parse(chunks(), postprocessor=postprocess)
        assert caught.value is marker
        return events
    assert run(rapidxmltodict) == run(xmltodict)


def test_nested_public_parse_calls_from_callback_are_independent():
    def run(module):
        items = []
        def callback(path, item):
            items.append((deepcopy(path), item, module.parse('<nested a="ok"/>')))
            return True
        result = module.parse('<r><i>one</i><i>two</i></r>', item_depth=2, item_callback=callback)
        return result, items
    assert run(rapidxmltodict) == run(xmltodict)


@pytest.mark.parametrize('size', [8191, 8192, 8193, 16385])
@pytest.mark.parametrize('character', ['x', 'é'])
def test_character_separator_at_text_buffer_boundaries(size, character):
    document = '<r>%s<!-- gap -->%s</r>' % (character * size, character * size)
    _compare(document, cdata_separator='|')
    _compare(document, cdata_separator='|', process_comments=True)


@pytest.mark.parametrize('document,options', [
    ('<r>', {}), ('<r><i></r>', {}), ('<r>é\n<i></r>', {}),
    ('<r a="1" a="2"/>', {}), ('<r>\n text', {}),
    ('<p:r/>', {'process_namespaces': True}),
    ('<r xmlns:p="u"><p:x></r>', {'process_namespaces': True}),
])
@pytest.mark.parametrize('as_bytes', [False, True])
def test_owned_parse_error_preserves_diagnostic_metadata(document, options, as_bytes):
    if as_bytes:
        document = document.encode('utf-8')
    with pytest.raises(ExpatError) as expected:
        xmltodict.parse(document, **options)
    with pytest.raises(rapidxmltodict.ParseError) as actual:
        rapidxmltodict.parse(document, **options)
    assert type(actual.value) is rapidxmltodict.ParseError
    assert (actual.value.code, actual.value.lineno, actual.value.offset) == (
        expected.value.code, expected.value.lineno, expected.value.offset)
    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize('encoding,declared', [
    ('utf-8', 'UTF-8'), ('utf-8-sig', 'UTF-8'), ('utf-16', 'UTF-16'),
    ('utf-16-le', 'UTF-16LE'), ('utf-16-be', 'UTF-16BE'),
    ('iso-8859-1', 'ISO-8859-1'), ('cp1252', 'windows-1252'),
])
@pytest.mark.parametrize('body', ['<r>café\r\n<i></r>', '<r a="é" a="x"/>', '<r>élève'])
@pytest.mark.parametrize('chunk_size', [None, 1, 3, 11])
def test_encoded_incremental_error_positions(encoding, declared, body, chunk_size):
    document = ('<?xml version="1.0" encoding="%s"?>%s' % (declared, body)).encode(encoding)
    def source():
        if chunk_size is None:
            return document
        return (document[i:i + chunk_size] for i in range(0, len(document), chunk_size))
    with pytest.raises(ExpatError) as expected:
        xmltodict.parse(source())
    with pytest.raises(rapidxmltodict.ParseError) as actual:
        rapidxmltodict.parse(source())
    assert (actual.value.code, actual.value.lineno, actual.value.offset) == (
        expected.value.code, expected.value.lineno, expected.value.offset)
    assert str(actual.value) == str(expected.value)


def test_extended_features_with_parser_dependencies_blocked():
    import subprocess
    import sys

    program = r'''
import importlib.abc
import io
import sys
import os
# -I deliberately ignores PYTHONPATH; explicitly retain sanitizer isolation.
if os.environ.get("SAN_ROOT"):
    sys.path.insert(0, os.environ["SAN_ROOT"])
    import sitecustomize
    assert sitecustomize.LSAN_CHECKPOINT_ACTIVE
blocked = {'xmltodict', 'pyexpat', 'xml.parsers.expat', 'xml.sax.expatreader'}
class RejectParserDependency(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise ImportError('blocked runtime ' + fullname)
sys.meta_path.insert(0, RejectParserDependency())
import rapidxmltodict as xml
for encoding in ['utf-8', 'utf-16', 'iso-8859-1']:
    document = ('<?xml version="1.0" encoding="%s"?><r><!-- note --><i>café</i><i>two</i></r>' % encoding).encode(encoding)
    expected = {'r': {'#comment': 'note', 'i': ['café', 'two']}}
    assert xml.parse(io.BytesIO(document), process_comments=True) == expected
    chunks = (document[i:i + 3] for i in range(0, len(document), 3))
    assert xml.parse(chunks, process_comments=True) == expected
assert xml.parse('<!DOCTYPE r [<!ENTITY v "text">]><r>&v;</r>', disable_entities=False) == {'r': 'text'}
value = {'r': {'i': ['one', 'two']}}
assert xml.parse(xml.unparse(value, pretty=True)) == value
assert not blocked & sys.modules.keys()
'''
    result = subprocess.run([sys.executable, '-I', '-c', program],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


_ASCII_VALIDATION_CASES = [
    # Declarations, including grammar accepted by the 1.0.4 reference parser.
    '<?xml version="1.0"?><r/>',
    "<?xml version = '1.1' ?><r/>",
    '<?xml\nversion="1.0"\nencoding="UTF-8"\nstandalone="yes"?><r/>',
    '<?xml version="1.0" standalone="no"?><r/>',
    '<?xml version="release_1-0"?><r/>',
    '<?xml?><r/>', '<?xml encoding="UTF-8"?><r/>',
    '<?xml version="1.0"version="1.0"?><r/>',
    '<?xml version="1.0" version="1.0"?><r/>',
    '<?xml version="1.0" standalone="maybe"?><r/>',
    '<?xml version="1.0" standalone="yes" encoding="UTF-8"?><r/>',
    ' <?xml version="1.0"?><r/>', '<?XML version="1.0"?><r/>',
    '<?xml version="1.0"?><?xml version="1.0"?><r/>',
    # Ordinary processing instructions in each legal document position.
    '<?work?><r/><?work done?>', '<?work one > two?><r/>',
    '<?xml-stylesheet href="style.xsl"?><r/>', '<?a:b data?><r/>',
    '<r>a<?work ignored?>b<?work?>c</r>',
    '<r><?xml version="1.0"?></r>', '<?work/data?><r/>',
    # Comments and CDATA. Their contents must not be parsed as element markup.
    '<!-- before --><r><!-- inside -->a<!-- middle -->b</r><!-- after -->',
    '<!----><r/>', '<r><!-- - --></r>', '<r><!-- -- bad --></r>',
    '<r><!-- unfinished</r>', '<r><!-- trailing---></r>',
    '<r><![CDATA[<item a="v">&amp;</item>]]></r>',
    '<r>a<![CDATA[b]]>c<![CDATA[d]]>e</r>', '<r><![CDATA[]]></r>',
    '<r><![CDATA[]]]></r>', '<r><![CDATA[unfinished</r>',
    '<![CDATA[text]]><r/>', '<r/> <![CDATA[text]]>', '<r>text]]>tail</r>',
    # Literal and referenced text/attribute characters.
    '<r>&lt;&gt;&amp;&apos;&quot;</r>',
    '<r>&#65;&#x41;&#xE9;&#128512;</r>', '<r>&#9;&#10;&#13;</r>',
    '<r a="&lt;&gt;&amp;&apos;&quot;&#9;&#10;&#13;"/>',
    '<r>&unknown;</r>', '<r>&amp</r>', '<r>&#;</r>', '<r>&#x;</r>',
    '<r a="<"/>', '<r a="&unknown;"/>', '<r a="&amp"/>',
    '<r a="one\ttwo\r\nthree">one\rtwo\r\nthree</r>',
    "<r a='double \" quote' b=\"single ' quote\"/>",
    '<r a="one" b="two" c="three" d="four" e="five" f="six" g="seven" h="eight"/>',
    '<r a="one" b="two" c="three" d="four" e="five" f="six" g="seven" h="eight" i="nine"/>',
    '<r a="one" b="two" a="repeat"/>',
    '<r a="one" b="two" c="three" d="four" e="five" f="six" g="seven" h="eight" a="repeat"/>',
    '<r a="one"b="two"/>', '<r a=one/>', '<r a="unfinished/>',
    # XML names, root shape, and explicitly unsupported fast-path features.
    '<r:_x a:b:c="v"><child-name/><child.name/><_child/></r:_x>',
    '<r><child>one</child><child>two</child></r>',
    ' \t\r\n<r/> \t\r\n', '<r/>tail', 'head<r/>', '<r/><second/>',
    '<r>', '<r><child></r>', '<r / >', '<1root/>', '<r bad?="v"/>',
    '<!DOCTYPE r><r/>', '<!DOCTYPE r [<!ATTLIST r a CDATA "default">]><r/>',
    '<!DOCTYPE r [<!ENTITY word "hello">]><r>&word;</r>',
    '<r a="café">élève</r>', '<日本 属性="値"><子/></日本>',
]


@pytest.mark.parametrize('document', _ASCII_VALIDATION_CASES)
@pytest.mark.parametrize('as_bytes', [False, True])
def test_ascii_validation_subset_matches_full_engine_and_oracle(document, as_bytes):
    if as_bytes:
        document = document.encode('utf-8')
    try:
        expected = xmltodict.parse(document)
    except ExpatError:
        for options in ({}, {'force_list': False}):
            with pytest.raises(rapidxmltodict.ParseError):
                rapidxmltodict.parse(document, **options)
    except ValueError as expected_error:
        for options in ({}, {'force_list': False}):
            with pytest.raises(ValueError) as actual_error:
                rapidxmltodict.parse(document, **options)
            assert actual_error.value.args == expected_error.args
    else:
        for options in ({}, {'force_list': False}):
            assert _shape(rapidxmltodict.parse(document, **options)) == _shape(expected)
