"""Runtime evidence for the bundled public typing contract.

Run against both the minimum and current supported xmltodict versions.  The
stub covers their combined API, while behavior follows the installed version.
"""

import ast
from collections import OrderedDict, UserDict
from copy import deepcopy
import inspect
from io import BytesIO, StringIO
from pathlib import Path

import pytest
import xmltodict

import rapidxmltodict


def _stub_overloads(name):
    path = Path(rapidxmltodict.__file__).with_suffix('.pyi')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return [node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name]


def _runtime_parameters(function):
    return {name: parameter
            for name, parameter in inspect.signature(function).parameters.items()
            if parameter.kind != inspect.Parameter.VAR_KEYWORD}


def test_parse_stub_covers_all_runtime_options():
    public = _runtime_parameters(rapidxmltodict.parse)
    handler = _runtime_parameters(xmltodict._DictSAXHandler)
    expected = set(public) | set(handler)
    overloads = _stub_overloads('parse')
    assert overloads
    for node in overloads:
        assert [arg.arg for arg in node.args.args] == list(public)
        assert {arg.arg for arg in node.args.args + node.args.kwonlyargs} == expected
        assert node.args.vararg is None
        assert node.args.kwarg is None


def test_unparse_stub_covers_version_dependent_runtime_options():
    public = _runtime_parameters(xmltodict.unparse)
    emit = set(_runtime_parameters(xmltodict._emit))
    emit -= {'key', 'value', 'content_handler'}
    expected = set(public) | emit
    # 1.0.4 adds a sixth positional comment_key and bytes_errors keyword.
    newer_options = {'comment_key', 'bytes_errors'}
    overloads = _stub_overloads('unparse')
    assert overloads
    for node in overloads:
        positional = [arg.arg for arg in node.args.args]
        names = set(positional) | {arg.arg for arg in node.args.kwonlyargs}
        assert positional[:len(public)] == list(public)
        assert names == expected | newer_options
        assert node.args.vararg is None
        assert node.args.kwarg is None


@pytest.mark.parametrize('chunk_type', [str, bytes, bytearray, memoryview])
def test_generator_chunks_and_non_none_return(chunk_type):
    def chunks():
        for chunk in ('<root>', 'value', '</root>'):
            yield chunk if chunk_type is str else chunk_type(chunk.encode())
        return 17  # The generator return type has no effect on XML parsing.

    assert rapidxmltodict.parse(chunks()) == {'root': 'value'}


def test_minimal_binary_reader():
    class Reader:
        def __init__(self):
            self.source = BytesIO(b'<root>value</root>')

        def read(self, size):
            return self.source.read(size)

    assert rapidxmltodict.parse(Reader()) == {'root': 'value'}


def test_plain_iterators_are_not_generator_inputs():
    with pytest.raises(TypeError):
        rapidxmltodict.parse(iter([b'<root/>']))


@pytest.mark.parametrize('constructor', [OrderedDict, UserDict,
                                         lambda *args: UserDict(*args)])
def test_custom_mapping_constructors_and_factories(constructor):
    result = rapidxmltodict.parse('<root><item>value</item></root>',
                                dict_constructor=constructor)
    assert type(result) is type(constructor())
    assert type(result['root']) is type(constructor())
    assert result == {'root': {'item': 'value'}}


def test_postprocessor_can_drop_root_or_change_key_type():
    assert rapidxmltodict.parse('<root/>', postprocessor=lambda *args: None) is None
    assert rapidxmltodict.parse('<root>value</root>',
                               postprocessor=lambda path, key, value: (17, value)) == {17: 'value'}


def test_force_list_sees_postprocessed_key_and_value():
    seen = []

    def predicate(path, key, value):
        seen.append((deepcopy(path), key, value))
        return True

    result = rapidxmltodict.parse(
        '<root>value</root>',
        postprocessor=lambda path, key, value: (17, 23),
        force_list=predicate,
    )
    assert result == {17: [23]}
    assert seen == [([], 17, 23)]


def test_force_list_container_can_match_postprocessed_non_string_keys():
    assert rapidxmltodict.parse(
        '<root>value</root>',
        postprocessor=lambda path, key, value: (17, value),
        force_list=(17,),
    ) == {17: ['value']}


def test_callback_path_attributes_include_namespace_mappings():
    seen = []

    def callback(path, item):
        seen.append(deepcopy((path, item)))
        return 1  # Any truthy value keeps streaming, not only bool.

    rapidxmltodict.parse('<root xmlns:p="urn:p" a="x"/>',
                        process_namespaces=True,
                        item_depth=1, item_callback=callback)
    assert seen[0][0] == [('root', {'a': 'x', 'xmlns': {'p': 'urn:p'}})]


@pytest.mark.parametrize('item_depth', [1, 2, 3])
def test_streaming_with_trailing_comment_can_return_mapping(item_depth):
    document = '<root><item>value</item></root><!-- trailing -->'
    result = rapidxmltodict.parse(document, item_depth=item_depth,
                                 process_comments=True)
    assert result == xmltodict.parse(document, item_depth=item_depth,
                                    process_comments=True)
    assert result['#comment'] == 'trailing'


def test_selective_force_cdata_matches_installed_version():
    document = '<root><a>one</a><b>two</b></root>'
    for option in [('a',), lambda path, key, value: key == 'a']:
        assert rapidxmltodict.parse(document, force_cdata=option) == \
            xmltodict.parse(document, force_cdata=option)


@pytest.mark.parametrize('output_factory', [BytesIO, StringIO])
def test_unparse_file_output_returns_none(output_factory):
    output = output_factory()
    assert rapidxmltodict.unparse({'root': 'value'}, output=output) is None
    value = output.getvalue()
    if isinstance(value, bytes):
        value = value.decode()
    assert '<root>value</root>' in value


def test_unparse_minimal_binary_writer_returns_none():
    class Writer:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data)
            return len(data)

    output = Writer()
    assert rapidxmltodict.unparse({'root': 'value'}, output=output) is None
    assert b'<root>value</root>' in output.data


def test_unparse_preprocessor_can_drop_items():
    def preprocess(key, value):
        return None if key == 'omit' else (key, value)

    assert rapidxmltodict.unparse({'root': {'keep': 'x', 'omit': 'y'}},
                                 full_document=False,
                                 preprocessor=preprocess) == \
        '<root><keep>x</keep></root>'


def test_unparse_new_options_follow_installed_version():
    if 'comment_key' in inspect.signature(xmltodict.unparse).parameters:
        result = rapidxmltodict.unparse(
            {'root': {'!comment': 'note', 'item': b'caf\xc3\xa9'}},
            None, 'utf-8', True, False, '!comment', bytes_errors='strict',
        )
        assert '<!--note-->' in result
        assert '<item>caf\xe9</item>' in result
    else:
        with pytest.raises(TypeError):
            rapidxmltodict.unparse({'root': 'value'}, comment_key='!comment')
        with pytest.raises(TypeError):
            rapidxmltodict.unparse({'root': 'value'}, bytes_errors='strict')
