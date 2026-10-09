#!/usr/bin/env python3
"""Bounded same-host large-XML comparison with fresh-process native-aware RSS.

Generate fixtures outside measured workers; compare old/new rapidxmltodict and
xmltodict using complete output structural SHA-256 fingerprints. See the report
for interpretation. This is a benign performance benchmark, not a stress test.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time

MIB = 1024**2
VERSIONS = ('before', 'after', 'xmltodict')


def current_rss():
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1])*1024
    return None


def peak_rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)


def available_memory():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1])*1024
    return None


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(MIB), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    """Canonical typed traversal; chunk string encoding to bound extra memory."""
    h = hashlib.sha256()
    counts = {'dict': 0, 'list': 0, 'str': 0, 'none': 0}
    def walk(x):
        if isinstance(x, dict):
            counts['dict'] += 1
            h.update(f'd{len(x)}:'.encode())
            for k in sorted(x):
                walk(k)
                walk(x[k])
        elif isinstance(x, list):
            counts['list'] += 1
            h.update(f'l{len(x)}:'.encode())
            for item in x:
                walk(item)
        elif isinstance(x, str):
            counts['str'] += 1
            h.update(f's{len(x)}:'.encode())
            for offset in range(0, len(x), 65536):
                h.update(x[offset:offset+65536].encode('utf-8'))
        elif x is None:
            counts['none'] += 1
            h.update(b'n:')
        else:
            raise TypeError(type(x))
        h.update(b';')
    walk(value)
    return {'sha256': h.hexdigest(), 'type_counts': counts}


def worker(args):
    # Reserve a hard upper bound on virtual address space. Allocation failure is
    # reported instead of retrying with an expanded limit or risking host OOM.
    resource.setrlimit(resource.RLIMIT_AS, (args.limit_mib*MIB, args.limit_mib*MIB))
    if hasattr(os, 'sched_setaffinity'):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    if args.version == 'xmltodict':
        import xmltodict as parser
    else:
        import rapidxmltodict as parser
    # The same UTF-8 str input path is used for every parser. Loading's transient
    # bytes/string copies can raise baseline peak; current RSS is also retained.
    xml = Path(args.fixture).read_bytes().decode('utf-8')
    gc.enable()
    gc.collect()
    baseline_current, baseline_peak = current_rss(), peak_rss()
    start = time.perf_counter_ns()
    output = parser.parse(xml)
    elapsed = time.perf_counter_ns()-start
    # Take memory readings BEFORE fingerprinting and keep input and output alive.
    peak, retained = peak_rss(), current_rss()
    return {'elapsed_ns': elapsed, 'baseline_current_rss_bytes': baseline_current,
            'baseline_peak_rss_bytes': baseline_peak, 'peak_rss_bytes': peak,
            'incremental_peak_rss_bytes': max(0, peak-baseline_peak),
            'retained_output_current_rss_bytes': retained,
            'retained_current_increase_bytes': retained-baseline_current,
            'output_fingerprint': fingerprint(output), 'parser_module': parser.__file__,
            'xmltodict_version': importlib.metadata.version('xmltodict'),
            'cpu_affinity': sorted(os.sched_getaffinity(0)), 'gc_enabled': gc.isenabled()}


def create_fixture(folder, shape, size):
    target = size*MIB
    path = folder/f'{shape}-{size}mib.xml'
    start, end = ((b'<catalog region="us">', b'</catalog>') if shape == 'records'
                  else (b'<document><payload>', b'</payload></document>'))
    count = 0
    with path.open('wb') as f:
        f.write(start)
        written = len(start)
        if shape == 'records':
            while True:
                i = count
                record = (f'<item id="{i:06d}" active="{"true" if i % 3 else "false"}">'
                          f'<name>Widget-{i % 97:02d} &amp; spare</name>'
                          f'<price currency="USD">{10+i%80}.{i%100:02d}</price>'
                          '<details><tag>alpha</tag><tag>beta</tag>'
                          f'<stock>{i%250}</stock></details></item>').encode()
                if written+len(record)+len(end)>target:
                    break
                f.write(record)
                written += len(record)
                count += 1
            f.write(b' '*(target-written-len(end)))
        else:
            remaining = target-written-len(end)
            block = (b'abcdefgh01234567'*(MIB//16))
            while remaining:
                n = min(len(block), remaining)
                f.write(block[:n])
                remaining -= n
        f.write(end)
    assert path.stat().st_size == target
    return {'path': str(path.resolve()), 'shape': shape, 'size_mib': size,
            'bytes': target, 'records': count if shape == 'records' else None,
            'sha256': sha(path), 'input_type': 'str'}


def main(args):
    before, after = Path(args.before).resolve(), Path(args.after).resolve()
    output = Path(args.output).resolve()
    fixtures = Path(args.fixtures).resolve()
    fixtures.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    source_files = ('src/native.cpp','src/rapidxmltodict/__init__.py','vendor/rapidxml/rapidxml.hpp')
    sources = {v:{p:sha(root/p) for p in source_files} for v,root in [('before',before),('after',after)]}
    binaries = {v:{p.name:sha(p) for p in (root/'src/rapidxmltodict').glob('_native*.so')}
                for v,root in [('before',before),('after',after)]}
    data = {'schema_version':1, 'metadata':{'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'python':sys.version, 'platform':platform.platform(), 'argv':sys.argv,
            'script_sha256':sha(__file__), 'source_hashes':sources, 'native_binary_hashes':binaries,
            'xmltodict_version':importlib.metadata.version('xmltodict'),
            'initial_available_memory_bytes':available_memory(),
            'method':{'repetitions':args.repetitions, 'input_type':'str', 'gc_enabled':True,
                'fresh_process_per_sample':True,'one_parse_per_process':True,'output_destruction_timed':False,
                'memory_sample_before_fingerprint':True,'max_address_space_mib':args.limit_mib,
                'fingerprint':'Typed SHA-256 recursive traversal, sorted dictionary keys, preserved list order, all string values; not a sampled checksum.',
                'resource_guard':'Each process limited by RLIMIT_AS; skip if estimated peak exceeds 40% of available memory or 80% of address-space cap; no automatic retries after allocation failure.'}},
            'workloads':{},'run_order':[]}
    # Generate all inputs here, never in a measured child. Streaming generation
    # prevents a large orchestrator heap from inflating inherited peak RSS.
    specs=[create_fixture(fixtures,shape,size) for size in args.sizes for shape in ['records','large_text']]
    def save():
        output.write_text(json.dumps(data,indent=2)+'\n')
    for spec in specs:
        name=f'{spec["shape"]}_{spec["size_mib"]}mib'
        entry={**spec,'samples':{v:[] for v in VERSIONS},'skipped':{}}
        data['workloads'][name]=entry
        for rep in range(args.repetitions):
            # Rotate order across independent repetitions.
            order=VERSIONS[rep%3:]+VERSIONS[:rep%3]
            for version in order:
                available=available_memory()
                # Conservative starting estimate from the existing 1 MiB suite;
                # update with measured 10/50 MiB growth for the same shape/parser.
                estimate=spec['bytes']*(24 if spec['shape']=='records' else 8)+64*MIB
                prior=[w for w in data['workloads'].values() if w['shape']==spec['shape'] and w['size_mib']<spec['size_mib'] and w['samples'][version]]
                if prior:
                    w=max(prior,key=lambda w:w['size_mib'])
                    ratio=max(s['peak_rss_bytes'] for s in w['samples'][version])/w['bytes']
                    estimate=spec['bytes']*ratio*1.25+64*MIB
                if estimate > min(available*0.4, args.limit_mib*MIB*0.8):
                    entry['skipped'][version]={'reason':'Conservative memory budget exceeded','estimated_peak_bytes':estimate,'available_memory_bytes':available}
                    save()
                    continue
                command=[sys.executable,str(Path(__file__).resolve()),'--worker','--version',version,
                         '--fixture',spec['path'],'--limit-mib',str(args.limit_mib)]
                env=os.environ.copy()
                if version!='xmltodict':
                    env['PYTHONPATH']=str((before if version=='before' else after)/'src')
                else:
                    env.pop('PYTHONPATH',None)
                run=subprocess.run(command,env=env,text=True,capture_output=True,close_fds=False,timeout=600)
                data['run_order'].append({'workload':name,'repetition':rep,'version':version,'available_memory_bytes':available})
                if run.returncode:
                    entry['skipped'][version]={'reason':'Worker failed; no automatic retry','returncode':run.returncode,'stderr':run.stderr[-4000:]}
                    save()
                    raise SystemExit(f'{name}/{version}: worker failed; results saved')
                sample=json.loads(run.stdout)
                assert sample['xmltodict_version']=='0.14.2'
                entry['samples'][version].append(sample)
                save()
                print(f'{name} {version} #{rep+1}: {sample["elapsed_ns"]/1e9:.3f}s; peak {sample["peak_rss_bytes"]/MIB:.1f} MiB; retained {sample["retained_output_current_rss_bytes"]/MIB:.1f} MiB',flush=True)
        fingerprints={s['output_fingerprint']['sha256'] for samples in entry['samples'].values() for s in samples}
        entry['all_available_output_fingerprints_equal']=len(fingerprints)==1
        assert len(fingerprints)<=1, f'Output mismatch for {name}'
        keys=['elapsed_ns','baseline_current_rss_bytes','baseline_peak_rss_bytes','peak_rss_bytes',
              'incremental_peak_rss_bytes','retained_output_current_rss_bytes','retained_current_increase_bytes']
        entry['medians']={v:{k:statistics.median(s[k] for s in samples) for k in keys} for v,samples in entry['samples'].items() if samples}
        save()
    data['metadata']['source_and_binary_hashes_unchanged']=all(
        sha(root/p)==sources[v][p] for v,root in [('before',before),('after',after)] for p in source_files)
    data['metadata']['source_and_binary_hashes_unchanged'] &= all(
        sha(root/'src/rapidxmltodict'/p)==digest for v,root in [('before',before),('after',after)] for p,digest in binaries[v].items())
    assert data['metadata']['source_and_binary_hashes_unchanged']
    save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before')
    parser.add_argument('--after')
    parser.add_argument('--output',default='benchmarks/upstream-large-memory.json')
    parser.add_argument('--fixtures',default='benchmarks/fixtures/upstream-large')
    parser.add_argument('--sizes',nargs='+',type=int,default=[10,50,100])
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--limit-mib',type=int,default=3072)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--version',choices=VERSIONS)
    parser.add_argument('--fixture')
    args=parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args)))
    else:
        main(args)
