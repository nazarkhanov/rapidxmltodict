"""Standalone sanitizer workload; no pytest/plugin allocations at shutdown."""
import ctypes
import gc
import os
from pathlib import Path
import sys
from xml.parsers.expat import ExpatError

import rapidxmltodict as rapid
import rapidxmltodict._native as native
import xmltodict


def exercise():
    documents = [
        '<root/>',
        '<root a="1"><item>one</item><item><![CDATA[two]]></item></root>',
        '<root xmlns="urn:default" xmlns:p="urn:p"><p:item p:a="v">text</p:item></root>',
        '<root:/>',  # Native ValueError -> successful reference fallback.
        '<r>before<a/> after <b/>tail</r>',  # NotImplemented mixed-content fallback.
        '<n>' * 300 + 'deep' + '</n>' * 300,  # Depth fallback, partial DOM cleanup.
        '<r>' + ''.join(f'<item id="{i}">value {i}</item>' for i in range(1000)) + '</r>',
    ]
    malformed = ['<root>', '<r><a></r>', '<r a="1" a="2"/>', '<r>&missing;</r>',
                 '<r>\x00</r>', '<r>' + '<a>value</a>' * 1000 + '</wrong>']
    cases = [(document, {}) for document in documents]
    cases += [(documents[2], {"process_namespaces": True}),
              (documents[1], {"force_list": ("item",)})]
    expected = [xmltodict.parse(document, **options) for document, options in cases]
    for _ in range(1000):
        for (document, options), reference in zip(cases, expected):
            result = rapid.parse(document, **options)
            assert result == reference
            del result
        for document in malformed:
            try:
                rapid.parse(document)
            except ExpatError:
                pass
            else:
                raise AssertionError("Malformed XML accepted")
        # Exercise native error cleanup directly, rather than stopping at Expat.
        for data in (b'<root:/>', b'<r a="\xff"/>', b'<r>\xff</r>'):
            try:
                native.convert(data)
            except (ValueError, UnicodeDecodeError):
                pass
            else:
                raise AssertionError("Expected native conversion exception")
        try:
            rapid.parse('<r><a>v</a></r>', postprocessor=raise_callback)
        except RuntimeError as error:
            assert str(error) == 'callback failure'
        else:
            raise AssertionError("Expected reference callback exception")
    # All result trees, exception tracebacks and reference fixtures die on return.
    print("PASS: 9000 valid/fallback parses, 6000 malformed, 3000 native errors, 1000 callback errors")


def raise_callback(path, key, value):
    raise RuntimeError('callback failure')


def main():
    directory = Path(os.environ['SAN_ROOT']).resolve()
    assert Path(rapid.__file__).resolve().is_relative_to(directory)
    assert Path(native.__file__).resolve().is_relative_to(directory)
    print('Instrumented native extension:', native.__file__, flush=True)
    exercise()
    gc.collect()
    if sys.argv[1:] == ['--intentional-leak']:
        probe = ctypes.CDLL(str(directory / 'leak_probe.so'))
        probe.intentional_leak.restype = ctypes.c_void_p
        probe.intentional_leak()  # Deliberately discard pointer in this process only.
        del probe
        gc.collect()
    elif sys.argv[1:]:
        raise SystemExit('Unexpected arguments')


if __name__ == '__main__':
    main()
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
