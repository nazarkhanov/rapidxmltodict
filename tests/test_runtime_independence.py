"""Verify the installed package works when both former runtimes are unavailable."""
import os
import subprocess
import sys
from importlib.metadata import requires


def test_no_runtime_dependency():
    dependencies = requires('rapidxmltodict') or []
    assert not any('xmltodict' in value.lower() and 'extra ==' not in value
                   for value in dependencies)


def test_parse_streaming_and_unparse_without_expat_or_xmltodict():
    code = r'''
import importlib.abc
import io
import sys
class BlockFormerRuntimes(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('xmltodict', 'pyexpat', 'xml.parsers.expat'):
            raise ImportError('blocked runtime: ' + fullname)
sys.meta_path.insert(0, BlockFormerRuntimes())
import rapidxmltodict as xml
assert xml.parse('<r a="v"><x>A</x><x>B</x></r>') == {'r': {'@a': 'v', 'x': ['A', 'B']}}
assert xml.parse('<r xmlns="urn:r"><x>A</x></r>', process_namespaces=True,
                 namespaces={'urn:r': None}) == {'r': {'@xmlns': {'': 'urn:r'}, 'x': 'A'}}
seen = []
def callback(path, item):
    seen.append(item)
    return True
assert xml.parse(iter_chunks := (chunk for chunk in [b'<r><x>A</x>', b'<x>B</x></r>']),
                 item_depth=2, item_callback=callback) is None
assert seen == ['A', 'B']
assert xml.parse(xml.unparse({'r': {'x': ['A', 'B']}})) == {'r': {'x': ['A', 'B']}}
assert not {'xmltodict', 'pyexpat', 'xml.parsers.expat'} & sys.modules.keys()
'''
    environment = os.environ.copy()
    result = subprocess.run([sys.executable, '-c', code], env=environment,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
