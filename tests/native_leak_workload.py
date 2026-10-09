"""Standalone sanitizer workload; no pytest/plugin allocations at shutdown."""
import ctypes
import gc
import os
from pathlib import Path
import sys

import rapidxmltodict as rapid
import rapidxmltodict._native as native
import xmltodict


def exercise(iterations=1000):
    documents = [
        '<root/>',
        '<root a="1"><item>one</item><item><![CDATA[two]]></item></root>',
        '<root xmlns="urn:default" xmlns:p="urn:p"><p:item p:a="v">text</p:item></root>',
        '<root:/>',  # Valid general XML name, supported directly by upstream.
        '<r>before<a/> after <b/>tail</r>',  # NotImplemented mixed-content fallback.
        '<n>' * 300 + 'deep' + '</n>' * 300,  # Depth guard fallback.
        '<r>' + ''.join(f'<item id="{i}">value {i}</item>' for i in range(1000)) + '</r>',
    ]
    malformed = ['<root>', '<r><a></r>', '<r a="1" a="2"/>', '<r>&missing;</r>',
                 '<r>\x00</r>', '<r>' + '<a>value</a>' * 1000 + '</wrong>']
    cases = [(document, {}) for document in documents]
    cases += [(documents[2], {"process_namespaces": True}),
              (documents[1], {"force_list": ("item",)})]
    expected = [xmltodict.parse(document, **options) for document, options in cases]
    for _ in range(iterations):
        for (document, options), reference in zip(cases, expected):
            result = rapid.parse(document, **options)
            assert result == reference
            del result
        for document in malformed:
            try:
                rapid.parse(document)
            except rapid.ParseError:
                pass
            else:
                raise AssertionError("Malformed XML accepted")
        # Exercise integrated native error cleanup, including a partially built DOM.
        for data in (b'<r>\xff</r>', b'<r a="\xff"/>', b'<r><item>one</item><item>two</item><bad>\xff</bad></r>'):
            try:
                native.convert(data)
            except rapid.ParseError:
                pass
            else:
                raise AssertionError("Expected native conversion exception")
        try:
            rapid.parse('<r><a>v</a></r>', postprocessor=raise_callback)
        except RuntimeError as error:
            assert str(error) == 'callback failure'
        else:
            raise AssertionError("Expected native callback exception")
    # All result trees, exception tracebacks and reference fixtures die on return.



def raise_callback(path, key, value):
    raise RuntimeError('callback failure')


def container_counts():
    gc.collect()
    lists = dictionaries = 0
    for obj in gc.get_objects():
        lists += type(obj) is list
        dictionaries += type(obj) is dict
    return lists, dictionaries


def main():
    directory = Path(os.environ['SAN_ROOT']).resolve()
    assert Path(rapid.__file__).resolve().is_relative_to(directory)
    assert Path(native.__file__).resolve().is_relative_to(directory)
    print('Instrumented native extension:', native.__file__, flush=True)
    probe = ctypes.PyDLL(str(directory / 'leak_probe.so'))
    probe.intentional_python_leak.restype = None
    probe.intentional_leak.restype = ctypes.c_void_p
    exercise(10)  # Warm lazy interpreter/reference caches before measuring.
    before = container_counts()
    exercise()
    if sys.argv[1:] == ['--intentional-python-leak']:
        probe.intentional_python_leak()
    after = container_counts()
    print('PASS: 9000 valid/fallback parses, 6000 malformed, 3000 native errors, 1000 callback errors', flush=True)
    print('GC-tracked (lists, dicts) before/after:', before, after, flush=True)
    if any(end > start for start, end in zip(before, after)):
        print('ERROR: retained Python containers after cleanup', flush=True)
        return 24
    if sys.argv[1:] == ['--intentional-python-leak']:
        raise SystemExit('Python-reference positive control was not detected')
    gc.collect()
    if sys.argv[1:] == ['--intentional-leak']:
        probe.intentional_leak()  # Deliberately discard pointer in this process only.
        gc.collect()
    elif sys.argv[1:]:
        raise SystemExit('Unexpected arguments')
    return 0


if __name__ == '__main__':
    status = main()
    # CPython 3.12 immortal/interned strings can be orphaned during interpreter
    # shutdown. Check after our frames/results are gone, before that teardown.
    # This is LSan's supported early exit checkpoint, not a suppression: it
    # scans all tracked allocations and replaces the later automatic check.
    gc.collect()
    check = ctypes.CDLL(None).__lsan_do_leak_check
    check.argtypes = []
    check.restype = None
    check()
    print('PASS: explicit LSan cleanup checkpoint completed', flush=True)
    raise SystemExit(status)
