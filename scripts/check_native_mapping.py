"""Exercise the existing public behavior corpus with direct native mapping forced.

Run the normal suite separately as well. Native lifetime/cleanup tests run for
both the public dispatcher and this forced direct-event entry point.
"""
from pathlib import Path

import pytest
import rapidxmltodict
from rapidxmltodict import _parse

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'test_standalone_parse.py', 'test_standalone_xml_engine.py',
    'test_standalone_contract_extra.py', 'test_compatibility.py',
    'test_security.py', 'test_native_mapping.py', 'test_native_mapping_callbacks.py',
]


def main():
    rapidxmltodict.parse = _parse._parse_native_events
    _parse.parse = _parse._parse_native_events
    return pytest.main([*(str(ROOT / 'tests' / name) for name in FILES), '-q'])


if __name__ == '__main__':
    raise SystemExit(main())
