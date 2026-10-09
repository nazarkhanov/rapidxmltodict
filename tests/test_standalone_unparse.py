"""Differential serializer coverage against the pinned xmltodict 1.0.4 oracle.

Compare emitted bytes/text and exact errors, including partially written output.
The serializer is also exercised in a fresh interpreter that refuses imports of
the reference implementation and every standard-library Expat entry point.
"""

import codecs
from collections import OrderedDict, UserDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import importlib.metadata
import inspect
from io import BytesIO, StringIO
from pathlib import Path
import random
import subprocess
import sys

import pytest
import xmltodict

from rapidxmltodict import _serialize


def _outcome(function, data, **options):
    try:
        return ("return", function(data, **options))
    except Exception as exc:
        return ("raise", type(exc), exc.args)


def assert_same(data, **options):
    """Use immutable/reusable inputs here; use factories for iterators below."""
    expected = _outcome(xmltodict.unparse, data, **options)
    actual = _outcome(_serialize.unparse, data, **options)
    assert actual == expected
    return actual


def test_oracle_and_public_signature():
    assert importlib.metadata.version("xmltodict") == "1.0.4"
    assert inspect.signature(_serialize.unparse) == inspect.signature(xmltodict.unparse)
    assert inspect.signature(_serialize._emit) == inspect.signature(xmltodict._emit)


SCALARS = [
    None, "", "plain", " a\r\nb\tc ", "& < > \" '", "é日本😀",
    True, False, 0, -12, 1.5, float("inf"), Decimal("3.25"),
    b"bytes", b"caf\xc3\xa9", b"\xff", bytearray(b"bytes"), memoryview(b"bytes"),
]


@pytest.mark.parametrize("value", SCALARS)
@pytest.mark.parametrize("location", ["element", "attribute", "text", "comment"])
@pytest.mark.parametrize("short_empty_elements", [False, True])
def test_scalar_conversion(value, location, short_empty_elements):
    if location == "element":
        data = {"root": value}
    else:
        key = {"attribute": "@value", "text": "#text", "comment": "#comment"}[location]
        data = {"root": {key: value}}
    assert_same(data, short_empty_elements=short_empty_elements)


DOCUMENTS = [
    {}, {"root": None}, {"root": {}}, {"root": ""}, {"root": []},
    {"root": [None]}, {"root": [None, None]}, {"first": None, "second": None},
    {"root": {"empty": [], "present": [""]}},
    {"root": {"@id": 1, "child": ["one", "two"], "empty": None}},
    {"root": {"child": {"grandchild": "text"}, "#text": "tail"}},
    OrderedDict([("root", OrderedDict([("@z", "last"), ("@a", "first"), ("b", "2"), ("a", "1")]))]),
    UserDict({"root": "top-level mapping"}),
    {"root": UserDict({"one": 1, "two": 2})},
    {"日本": {"@属性": "値", "子": ["内容", None]}},
    {"root": {"#comment": ["first", None, "", "last"], "child": "text"}},
    OrderedDict([("#comment", "before"), ("root", {"#comment": "inside"})]),
    OrderedDict([("root", None), ("#comment", "after")]),
    {"#comment": "without a root"}, {"#comment": []},
    {"root": {"#text": ["one", "two"], "@list": [1, 2]}},
    {"root": {"@tuple": (1, 2), "@mapping": {"a": "b"}}},
    {"root": {"item": (1, None, True)}},
    {"root": {"item": range(3)}},
    {"root": {"item": [[1, 2], [], [3]]}},
]


@pytest.mark.parametrize("data", DOCUMENTS)
@pytest.mark.parametrize("full_document", [False, True])
@pytest.mark.parametrize("short_empty_elements", [False, True])
@pytest.mark.parametrize("pretty", [False, True])
def test_document_shapes(data, full_document, short_empty_elements, pretty):
    assert_same(data, full_document=full_document,
                short_empty_elements=short_empty_elements, pretty=pretty)


@pytest.mark.parametrize("indent", ["\t", "  ", "", 0, 1, 3, -1, True])
@pytest.mark.parametrize("newl", ["\n", "\r\n", "", b"\n"])
@pytest.mark.parametrize("depth", [0, 1, 3])
def test_pretty_print_parameters(indent, newl, depth):
    data = {"root": {"@id": "1", "child": [{"nested": "a"}, "b"], "#comment": "note"}}
    assert_same(data, pretty=True, indent=indent, newl=newl, depth=depth)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le", "utf-16-be",
                                      "utf-32", "iso-8859-1", "ascii", "windows-1252"])
@pytest.mark.parametrize("full_document", [False, True])
@pytest.mark.parametrize("output_kind", ["return", "text", "binary", "minimal", "codecs"])
def test_output_encoding_and_streams(encoding, full_document, output_kind):
    data = {"root": {"@attr": "café 日本", "item": "é Ελληνικά 😀"}}

    class Writer:
        def __init__(self):
            self.data = bytearray()

        def write(self, value):
            self.data.extend(value)
            return len(value)

        def getvalue(self):
            return bytes(self.data)

    def run(function):
        if output_kind == "return":
            return function(data, encoding=encoding, full_document=full_document)
        if output_kind == "text":
            output = StringIO()
        elif output_kind == "binary":
            output = BytesIO()
        elif output_kind == "minimal":
            output = Writer()
        else:
            output = codecs.getwriter(encoding)(BytesIO(), errors="xmlcharrefreplace")
        result = function(data, output=output, encoding=encoding, full_document=full_document)
        assert result is None
        assert not getattr(output, "closed", False)
        return output.getvalue()

    assert run(_serialize.unparse) == run(xmltodict.unparse)


@pytest.mark.parametrize("mode", ["wb", "w"])
def test_real_file_is_left_open(tmp_path, mode):
    outputs = []
    for name, function in [("reference", xmltodict.unparse), ("standalone", _serialize.unparse)]:
        path = tmp_path / name
        options = {"encoding": "utf-8"} if mode == "w" else {"buffering": 0}
        with path.open(mode, **options) as output:
            assert function({"root": "é"}, output=output) is None
            assert not output.closed
            output.write("\n" if mode == "w" else b"\n")
        outputs.append(path.read_bytes())
    assert outputs[0] == outputs[1]


def test_binary_writer_position_controls_bom():
    def run(function):
        output = BytesIO()
        function({"first": "é"}, output=output, encoding="utf-16", full_document=False)
        function({"second": "é"}, output=output, encoding="utf-16", full_document=False)
        return output.getvalue()
    assert run(_serialize.unparse) == run(xmltodict.unparse)


@pytest.mark.parametrize("encoding", ["utf-8", "latin-1", "ascii"])
@pytest.mark.parametrize("bytes_errors", ["strict", "replace", "ignore", "backslashreplace",
                                         "surrogateescape", "unknown-handler", None, 3])
@pytest.mark.parametrize("location", ["element", "attribute", "text", "comment"])
def test_bytes_decoding_and_error_handlers(encoding, bytes_errors, location):
    key = {"element": "child", "attribute": "@attr", "text": "#text", "comment": "#comment"}[location]
    assert_same({"root": {key: b"caf\xe9\xff"}}, encoding=encoding, bytes_errors=bytes_errors)


NAMESPACE_CASES = [
    ({"urn:example:root": {"@urn:example:id": "1", "urn:other:child": "v"}},
     {"urn:example": "ex", "urn:other": "other"}, ":", "@"),
    ({"urn:example:root": {"@urn:example:id": "1", "urn:other:child": "v"}},
     {"urn:example": None}, ":", "@"),
    ({"urn:example|root": {"@urn:example|id": "1", "urn:other|child": "v"}},
     {"urn:example": "ex", "urn:other": None}, "|", "@"),
    ({"root": {"@xmlns": {"": "urn:default", "p": "urn:p", "q": None}, "p:child": "v"}},
     None, ":", "@"),
    ({"root": {"@xmlns": {"": None, "p": b"urn:p", "q": 3, "b": True}}},
     {}, ":", "@"),
    ({"ns:root": {"$ns:id": "1", "$xmlns": {"p": "urn:p"}}},
     {"ns": "p"}, ":", "$"),
    ({"root": {"@@ns:id": "1", "@plain": "2"}}, {"ns": "p"}, ":", "@"),
    ({"root": {"@ns:id": "1", "@other:id": "2"}}, {"ns": None, "other": None}, ":", "@"),
]


@pytest.mark.parametrize("data,namespaces,separator,attr_prefix", NAMESPACE_CASES)
@pytest.mark.parametrize("pretty", [False, True])
def test_namespace_processing(data, namespaces, separator, attr_prefix, pretty):
    assert_same(data, namespaces=namespaces, namespace_separator=separator,
                attr_prefix=attr_prefix, pretty=pretty)


@pytest.mark.parametrize("attr_prefix", ["@", "$", "", "attr:"])
@pytest.mark.parametrize("cdata_key", ["#text", "$text", "text"])
@pytest.mark.parametrize("comment_key", ["#comment", "!comment", "comment"])
def test_custom_representation_keys(attr_prefix, cdata_key, comment_key):
    assert_same({"root": {attr_prefix + "id": True, cdata_key: "tail",
                          comment_key: "note", "child": "value"}},
                attr_prefix=attr_prefix, cdata_key=cdata_key, comment_key=comment_key)


@pytest.mark.parametrize("expand_iter", [None, "item", "entry", ""])
@pytest.mark.parametrize("factory", [
    lambda: {"root": {"child": (value for value in [1, 2, 3])}},
    lambda: {"root": {"child": iter([1, None, False])}},
    lambda: {"root": {"child": [[1, 2], [], [3]]}},
    lambda: {"root": {"child": [(1, 2), (3,)]}},
    lambda: {"root": (value for value in ["one", "two"])},
    lambda: {"root": []},
    lambda: {"root": {"child": [bytearray(b"abc"), memoryview(b"def")]}},
])
@pytest.mark.parametrize("full_document", [False, True])
def test_iterables_and_expansion(factory, expand_iter, full_document):
    options = {"expand_iter": expand_iter, "full_document": full_document}
    assert _outcome(_serialize.unparse, factory(), **options) == \
        _outcome(xmltodict.unparse, factory(), **options)


@pytest.mark.parametrize("expand_iter", ["item", "entry"])
def test_nested_generators_expand(expand_iter):
    def data():
        return {"root": {"child": [(value for value in [1, 2])]}}
    assert _serialize.unparse(data(), expand_iter=expand_iter) == \
        xmltodict.unparse(data(), expand_iter=expand_iter)


def test_unexpanded_nested_generator_is_stringified_without_consumption():
    values = (value for value in [1, 2])
    data = {"root": {"child": [values]}}
    assert_same(data)
    assert list(values) == [1, 2]


def test_registered_bytes_error_handler():
    def replacement(error):
        return "[invalid byte]", error.end
    codecs.register_error("rapidxmltodict_test_handler", replacement)
    assert_same({"root": b"caf\xff"}, bytes_errors="rapidxmltodict_test_handler")


@pytest.mark.parametrize("action", ["rename", "drop_child", "drop_root", "change_value", "bad_result", "raise"])
def test_preprocessor_order_values_and_errors(action):
    def run(function):
        calls = []
        def preprocessor(key, value):
            calls.append(deepcopy((key, value)))
            if action == "rename":
                return key.upper(), value
            if action == "drop_child" and key == "child":
                return None
            if action == "drop_root" and key == "p:root":
                return None
            if action == "change_value" and key == "child":
                return "replacement", {"@new": 1, "#text": "changed"}
            if action == "bad_result":
                return (key,)
            if action == "raise" and key == "child":
                raise RuntimeError("callback stopped")
            return key, value
        data = {"ns:root": {"@id": "1", "child": ["one", "two"], "#comment": "note", "#text": "tail"}}
        output = StringIO()
        result = _outcome(function, data, output=output, preprocessor=preprocessor,
                          namespaces={"ns": "p"}, pretty=True)
        return result, calls, output.getvalue()
    assert run(_serialize.unparse) == run(xmltodict.unparse)


@pytest.mark.parametrize("data,options", [
    (None, {}), ([], {}), ("not a mapping", {}),
    ({17: "value"}, {}), ({b"root": "value"}, {}),
    ({"root": {17: "value"}}, {}),
    ({"two words": "value"}, {}), ({"root": {"@two words": "value"}}, {}),
    ({"root": {"@xmlns": {None: "urn:p"}}}, {}),
    ({"root": {"@xmlns": {"two words": "urn:p"}}}, {}),
    ({"root": {"#comment": "two--dashes"}}, {}),
    ({"root": {"#comment": "trailing-"}}, {}),
    ({"root": None}, {"dict_constructor": OrderedDict}),
    ({"root": None}, {"unknown_option": True}),
    ({"root": None}, {"process_namespaces": True}),
    ({"root": None}, {"attr_prefix": None}),
    ({"root": {"child": "value"}}, {"pretty": True, "indent": None}),
    ({"root": None}, {"pretty": True, "newl": 17}),
    ({"ns:root": None}, {"namespaces": {"ns": "p"}, "namespace_separator": ""}),
    ({"root": None}, {"namespaces": {"ns": "p"}, "namespace_separator": 17}),
    ({"root": None}, {"encoding": "unknown-encoding"}),
    ({"root": b"bytes"}, {"encoding": "unknown-encoding"}),
    ({"root": None}, {"bytes_errors": "unknown-handler"}),
])
@pytest.mark.parametrize("output_kind", ["return", "text", "binary"])
def test_errors_and_partial_output(data, options, output_kind):
    def run(function):
        output = None if output_kind == "return" else (StringIO() if output_kind == "text" else BytesIO())
        result = _outcome(function, data, output=output, **options)
        return result, output.getvalue() if output is not None else None
    assert run(_serialize.unparse) == run(xmltodict.unparse)


@pytest.mark.parametrize("data", [
    {}, {"root": ["one", "two"]}, {"first": None, "second": None},
    {"#comment": "no root"}, {"root": {"child": "ok", "bad name": "value"}},
])
def test_partial_writes_match_reference(data):
    for output_factory in [StringIO, BytesIO]:
        expected_output, actual_output = output_factory(), output_factory()
        expected = _outcome(xmltodict.unparse, data, output=expected_output)
        actual = _outcome(_serialize.unparse, data, output=actual_output)
        assert actual == expected
        assert actual_output.getvalue() == expected_output.getvalue()


def test_sixth_positional_comment_key():
    args = ({"root": {"note": "comment", "item": b"caf\xc3\xa9"}},
            None, "utf-8", True, False, "note")
    assert _serialize.unparse(*args, bytes_errors="strict") == \
        xmltodict.unparse(*args, bytes_errors="strict")


def _generated_document(seed):
    rng = random.Random(seed)
    values = [None, "", "text", "é日本😀", "a & b < c", 17, True, b"bytes"]
    def node(depth):
        if depth == 3 or rng.randrange(4) == 0:
            return rng.choice(values)
        result = {}
        if rng.randrange(2):
            result["@id"] = rng.choice(values)
        for index in range(rng.randrange(4)):
            value = node(depth + 1)
            result["child" + str(index)] = [value, node(depth + 1)] if rng.randrange(3) == 0 else value
        if rng.randrange(3) == 0:
            result["#text"] = rng.choice(values)
        if rng.randrange(3) == 0:
            result["#comment"] = "note & more"
        return result
    return {"root": node(0)}


@pytest.mark.parametrize("seed", range(100))
def test_generated_serialization(seed):
    data = _generated_document(seed)
    assert_same(data, pretty=bool(seed % 2), short_empty_elements=bool(seed % 3),
                full_document=bool(seed % 5))


def test_repeated_and_concurrent_calls_do_not_share_state():
    documents = [_generated_document(seed) for seed in range(24)]
    expected = [xmltodict.unparse(data) for data in documents]
    def run(index):
        selected = index % len(documents)
        assert _serialize.unparse(documents[selected]) == expected[selected]
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(run, range(120)))


def test_serializer_has_no_reference_or_expat_import_dependency():
    # Load this exact module independently so a different parser implementation
    # cannot hide or create the serializer's runtime dependencies.
    script = r'''
import importlib.abc
import importlib.util
import sys
import os
# -I deliberately ignores PYTHONPATH; explicitly retain sanitizer isolation.
if os.environ.get("SAN_ROOT"):
    sys.path.insert(0, os.environ["SAN_ROOT"])
    import sitecustomize
    assert sitecustomize.LSAN_CHECKPOINT_ACTIVE
from io import BytesIO

class BlockReferenceAndExpat(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "xmltodict" or "expat" in fullname:
            raise AssertionError("forbidden serializer import: " + fullname)

sys.meta_path.insert(0, BlockReferenceAndExpat())
spec = importlib.util.spec_from_file_location("standalone_serializer", sys.argv[1])
serializer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serializer)
data = {"root": {"@id": 1, "child": b"caf\xc3\xa9", "#comment": "note"}}
result = serializer.unparse(data)
assert "<child>café</child>" in result
output = BytesIO()
serializer.unparse(data, output=output, encoding="latin-1", bytes_errors="replace")
assert b"<root" in output.getvalue()
assert not any(name == "xmltodict" or "expat" in name for name in sys.modules)
'''
    completed = subprocess.run([sys.executable, "-I", "-c", script, str(Path(_serialize.__file__).resolve())],
                               text=True, capture_output=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
