"""Real allocation failures, separate from the instrumented sanitizer suite.

Address-space limits conflict with ASan/LSan's large virtual-memory mappings.
These optional Linux subprocess checks run in normal jobs; sanitizer jobs keep
their own lifetime/cleanup checks enabled and skip only this OS-limit probe.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from rapidxmltodict import _native


def _address_limit_unavailable():
    if not sys.platform.startswith('linux'):
        return 'real OOM probe requires Linux /proc and RLIMIT_AS'
    try:
        import resource
    except ImportError:
        return 'resource module is unavailable'
    if not hasattr(resource, 'RLIMIT_AS'):
        return 'RLIMIT_AS is unavailable'
    if any(os.environ.get(name) for name in
           ('SAN_ROOT', 'ASAN_OPTIONS', 'LSAN_OPTIONS')):
        return 'RLIMIT_AS is incompatible with the active sanitizer run'
    try:
        mappings = Path('/proc/self/maps').read_text().lower()
        Path('/proc/self/statm').read_text()
    except OSError:
        return 'Linux process memory information is unavailable'
    if any(name in mappings for name in ('libasan', 'liblsan', 'clang_rt.asan')):
        return 'RLIMIT_AS is incompatible with the loaded sanitizer runtime'
    return None


_UNAVAILABLE = _address_limit_unavailable()

_PROGRAM = r'''
import gc
import os
from pathlib import Path
import resource
import sys

# Test the exact package selected by the parent, including isolated test builds.
sys.path.insert(0, sys.argv[2])
from rapidxmltodict import _native

mode = sys.argv[1]
if mode == 'ascii_final':
    source = b'<r>' + b'x' * (12 * 1024 * 1024) + b'</r>'
elif mode == 'utf8_final':
    source = b'<r>' + ('\U0001f600' * (4 * 1024 * 1024)).encode() + b'</r>'
elif mode == 'reference_final':
    source = b'<r>' + b'&#x1F600;' * (3 * 1024 * 1024) + b'</r>'
elif mode == 'many_nodes':
    source = b'<r>' + b'<n/>' * (1024 * 1024) + b'</r>'
elif mode == 'unicode_cache':
    # Do not create this string's UTF-8 cache before imposing the limit.
    source = '<r>' + '\U0001f600' * (4 * 1024 * 1024) + '</r>'
else:
    raise AssertionError(mode)

gc.collect()
virtual_size = (int(Path('/proc/self/statm').read_text().split()[0])
                * os.sysconf('SC_PAGE_SIZE'))
original = resource.getrlimit(resource.RLIMIT_AS)
limit = virtual_size + 1024 * 1024
if any(bound != resource.RLIM_INFINITY and bound < limit for bound in original):
    print('existing address-space limit is too restrictive for this probe')
    raise SystemExit(77)
try:
    resource.setrlimit(resource.RLIMIT_AS, (limit, original[1]))
except (OSError, ValueError) as error:
    print('cannot set the address-space limit:', error)
    raise SystemExit(77)

failures = 0
try:
    for attempt in range(4):
        try:
            _native.convert(source)
        except MemoryError:
            failures += 1
        else:
            raise AssertionError('large parse unexpectedly fit the memory cap')
        # Exercise cleanup and reuse without removing the cap. No exception
        # traceback or partially constructed result is retained between calls.
        result = _native.convert(b'<r a="v"><n>ok</n><n>again</n></r>')
        assert result == {'r': {'@a': 'v', 'n': ['ok', 'again']}}
finally:
    resource.setrlimit(resource.RLIMIT_AS, original)
assert failures == 4
print('MemoryError and recovery verified four times')
'''


@pytest.mark.skipif(_UNAVAILABLE is not None, reason=_UNAVAILABLE or '')
@pytest.mark.parametrize('mode', [
    'ascii_final', 'utf8_final', 'reference_final', 'many_nodes', 'unicode_cache',
])
def test_readonly_allocation_failure_recovers_in_subprocess(mode):
    package_root = str(Path(_native.__file__).resolve().parent.parent)
    completed = subprocess.run(
        [sys.executable, '-c', _PROGRAM, mode, package_root],
        text=True, capture_output=True, timeout=60,
    )
    if completed.returncode == 77:
        pytest.skip(completed.stdout.strip())
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert 'MemoryError and recovery verified four times' in completed.stdout
