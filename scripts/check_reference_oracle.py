#!/usr/bin/env python3
"""Generate/verify exact-oracle fixtures without importing the implementation.

The default verify mode requires CPython 3.12.15, xmltodict 1.0.4 and Expat 2.8.5
with reparse deferral enabled. It does not modify fixtures. --generate requires
the same environment. --generate-provisional is an explicit one-time bootstrap
using CPython 3.12.14/Expat 2.8.3; passing its output locally does not verify the
canonical contract. The required canonical CI job must reproduce every byte.

Provenance is printed separately from the deterministic fixture payload:
"target_oracle" describes the intended contract, not the generation runtime.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
from xml.parsers import expat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from oracle_contract_cases import CANONICAL_ORACLE, CHUNK_CASES, FIXTURE_PATH, ordered_shape


def runtime_identity():
    parser = expat.ParserCreate()
    return {
        'python': platform.python_version(),
        'xmltodict': version('xmltodict'),
        'expat': expat.EXPAT_VERSION,
        'reparse_deferral': getattr(parser, 'GetReparseDeferralEnabled', lambda: False)(),
    }


def fixture_bytes():
    import xmltodict

    records = []
    for case in CHUNK_CASES:
        record = case.specification()
        record['expected'] = ordered_shape(xmltodict.parse(case.chunks(), **case.options))
        records.append(record)
    fixture = {'schema_version': 1, 'target_oracle': CANONICAL_ORACLE, 'cases': records}
    return (json.dumps(fixture, ensure_ascii=True, indent=2, sort_keys=True) + '\n').encode('utf-8')


def verify_strict_declaration_contract():
    import xmltodict

    versions = ('104', 'abc', '2.0', '1_0', 'release_1-0')
    documents = ['<?xml version="%s"?><r/>' % value for value in versions]
    documents += [document.encode('ascii') for document in documents]
    documents.append(b'<?xml version="104"?><root a="value"><item>one&amp;two</item><item><![CDATA[text]]></item></root>')
    for document in documents:
        try:
            xmltodict.parse(document)
        except expat.ExpatError as error:
            if (error.code, error.lineno, error.offset) != (30, 1, 15):
                raise SystemExit('Unexpected strict-declaration diagnostic: %r: %s' % (document, error))
        else:
            raise SystemExit('Canonical oracle accepted an invalid version: %r' % document)
    print('Verified %d strict XML-declaration rejection cases.' % len(documents))


def report_difference(saved_bytes, actual_bytes):
    saved = json.loads(saved_bytes)
    actual = json.loads(actual_bytes)
    expected_cases = {case['id']: case for case in saved['cases']}
    actual_cases = {case['id']: case for case in actual['cases']}
    differences = []
    for case_id in sorted(set(expected_cases) | set(actual_cases)):
        expected, observed = expected_cases.get(case_id), actual_cases.get(case_id)
        if expected != observed:
            differences.append({'id': case_id, 'checked_in': expected, 'canonical': observed})
    print('ORACLE_DIFFERENCES_BEGIN')
    print(json.dumps(differences, ensure_ascii=True, indent=2, sort_keys=True))
    print('ORACLE_DIFFERENCES_END')
    if not differences:
        print('Case results match, but fixture metadata or byte formatting differs.')


def main():
    argument_parser = argparse.ArgumentParser(description=__doc__)
    mode = argument_parser.add_mutually_exclusive_group()
    mode.add_argument('--generate', action='store_true')
    mode.add_argument('--generate-provisional', action='store_true')
    arguments = argument_parser.parse_args()
    actual_runtime = runtime_identity()
    print('Oracle runtime: ' + json.dumps(actual_runtime, sort_keys=True), flush=True)
    print('Expat build features: ' + json.dumps(expat.features), flush=True)
    if platform.python_implementation() != 'CPython':
        raise SystemExit('The reference oracle must be CPython.')
    required = dict(CANONICAL_ORACLE)
    if arguments.generate_provisional:
        required.update(python='3.12.14', expat='expat_2.8.3')
    if actual_runtime != required:
        raise SystemExit('Wrong oracle runtime; required ' + json.dumps(required, sort_keys=True))
    features = dict(expat.features)
    if features.get('XML_CONTEXT_BYTES') != 1024:
        raise SystemExit('Canonical input buffering requires XML_CONTEXT_BYTES=1024.')
    if 'rapidxmltodict' in sys.modules:
        raise SystemExit('Fixture generation must not import rapidxmltodict.')
    if not arguments.generate_provisional:
        verify_strict_declaration_contract()
    produced = fixture_bytes()
    if 'rapidxmltodict' in sys.modules:
        raise SystemExit('The implementation was imported during fixture generation.')
    digest = hashlib.sha256(produced).hexdigest()
    if arguments.generate or arguments.generate_provisional:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_bytes(produced)
        qualifier = 'PROVISIONAL; canonical verification still required' if arguments.generate_provisional else 'canonical'
        print('Generated %d cases (%s), SHA256=%s' % (len(CHUNK_CASES), qualifier, digest))
        return
    saved = FIXTURE_PATH.read_bytes()
    if saved != produced:
        report_difference(saved, produced)
        raise SystemExit('Canonical oracle differs from checked-in fixture; no file was modified.')
    print('Verified %d canonical oracle cases byte-for-byte, SHA256=%s' % (len(CHUNK_CASES), digest))


if __name__ == '__main__':
    main()
