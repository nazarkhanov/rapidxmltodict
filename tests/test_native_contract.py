import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import rapidxmltodict
import pytest


def test_vendor_header_unchanged():
    header = Path(__file__).parents[1] / 'vendor/rapidxml/rapidxml.hpp'
    assert hashlib.sha256(header.read_bytes()).hexdigest() == 'ac2ea2d3b0e8c2543b8f70784a157e4976ddee6c0afea5484f63516960d58cdb'


def test_default_uses_native(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('unexpected fallback')
    monkeypatch.setattr(rapidxmltodict._reference, 'parse', forbidden)
    assert rapidxmltodict.parse('<r a="1"><x>yes</x><x/></r>') == {'r': {'@a':'1', 'x':['yes',None]}}


@pytest.mark.parametrize('xml,kwargs', [
    ('<r/>', {'force_list': True}),
    ('<!DOCTYPE r><r/>', {}),
    ('<?xml version="1.0" encoding="ISO-8859-1"?><r/>', {}),
    ('<r>' * 257 + '</r>' * 257, {}),
])
def test_documented_fallback(monkeypatch, xml, kwargs):
    expected = object()
    monkeypatch.setattr(rapidxmltodict._reference, 'parse', lambda *a, **kw: expected)
    assert rapidxmltodict.parse(xml, **kwargs) is expected


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
    def forbidden(*args, **kwargs):
        raise AssertionError('UTF-8 declaration should be accelerated')
    monkeypatch.setattr(rapidxmltodict._reference, 'parse', forbidden)
    assert rapidxmltodict.parse('<?xml version="1.0" encoding="UTF-8"?><r>é</r>') == {'r': 'é'}
