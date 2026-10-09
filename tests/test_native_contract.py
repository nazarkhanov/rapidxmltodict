import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import rapidxmltodict
import rapidxmltodict._native as native
import xmltodict
import pytest


def test_vendor_header_unchanged():
    header = Path(__file__).parents[1] / 'vendor/rapidxml/rapidxml.hpp'
    assert hashlib.sha256(header.read_bytes()).hexdigest() == 'd61c53fd63f11aef0e18d253746ee800903dc82e4ad3cc533d0fdca69f07c4f9'


def test_default_uses_native(monkeypatch):
    calls = []
    original = native.convert
    def convert(data):
        calls.append(data)
        return original(data)
    monkeypatch.setattr(native, 'convert', convert)
    assert rapidxmltodict.parse('<r a="1"><x>yes</x><x/></r>') == {'r': {'@a':'1', 'x':['yes',None]}}
    assert len(calls) == 1


@pytest.mark.parametrize('xml,kwargs', [
    ('<r/>', {'force_list': True}),
    ('<!DOCTYPE r><r/>', {}),
    ('<?xml version="1.0" encoding="ISO-8859-1"?><r/>', {}),
    ('<r>' * 257 + '</r>' * 257, {}),
])
def test_documented_options_are_native(xml, kwargs):
    assert rapidxmltodict.parse(xml, **kwargs) == xmltodict.parse(xml, **kwargs)


def test_returned_values_own_memory():
    result = rapidxmltodict.parse(b'<r><x a="value">content</x><x>other</x></r>')
    for _ in range(1000):
        rapidxmltodict.parse(b'<r><y>overwrite</y></r>')
    assert result == {'r': {'x': [{'@a': 'value', '#text':'content'}, 'other']}}


def test_parallel_calls():
    # No global mutable cache or shared document. Native conversion holds GIL.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(rapidxmltodict.parse, ['<r>ok</r>'] * 200))
    assert all(x == {'r': 'ok'} for x in results)


def test_utf8_declaration_uses_native(monkeypatch):
    calls = []
    original = native.convert
    def convert(data):
        calls.append(data)
        return original(data)
    monkeypatch.setattr(native, 'convert', convert)
    assert rapidxmltodict.parse('<?xml version="1.0" encoding="UTF-8"?><r>é</r>') == {'r': 'é'}
    assert len(calls) == 1


@pytest.mark.parametrize('document', [
    '<p:root xmlns:p="urn:p"><p:item p:attr="v">one</p:item><p:item>two</p:item></p:root>',
    '<root xmlns="urn:default" xmlns:a="urn:a" xmlns:b="urn:b"><a:item/><b:item/><item/></root>',
    '<a:root xmlns:a="urn:one"><a:item xmlns:a="urn:two">value</a:item></a:root>',
    '<root:/>',
])
def test_upstream_preserves_qualified_names_on_native_path(monkeypatch, document):
    # Upstream name()/name_size() contain the whole qualified name. Comparing
    # before patching the reference proves prefixes are neither lost nor doubled.
    expected = xmltodict.parse(document)
    calls = []
    original = native.convert
    def convert(data):
        calls.append(data)
        return original(data)
    monkeypatch.setattr(native, 'convert', convert)
    assert rapidxmltodict.parse(document) == expected
    assert len(calls) == 1
