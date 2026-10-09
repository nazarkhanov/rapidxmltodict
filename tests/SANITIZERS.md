# Native sanitizer and differential checks

These commands were exercised on Linux x86-64 with GCC 14, CPython 3.12 and
xmltodict 0.14.2. They build a separate extension in a temporary directory;
the normal build in `src/rapidxmltodict` is not replaced. Other compilers and
operating systems may require different sanitizer/runtime flags.

Run from the repository root, with a virtual environment containing the test
dependencies. A C++17 compiler and Python development headers are required.
Set `PYTHON` if the desired interpreter is not the active `python`.

## AddressSanitizer and UndefinedBehaviorSanitizer

```sh
export ROOT="$PWD"
export PYTHON="${PYTHON:-python}"
export CXX="${CXX:-g++}"
export SAN_ROOT="$(mktemp -d -t rapidxmltodict-sanitizers.XXXXXX)"

mkdir -p "$SAN_ROOT/rapidxmltodict"
cp src/rapidxmltodict/__init__.py "$SAN_ROOT/rapidxmltodict/"
# Generate/install the package first so its SCM version module exists.
cp src/rapidxmltodict/_version.py "$SAN_ROOT/rapidxmltodict/"

"$PYTHON" - <<'PY'
import os
from pathlib import Path
import subprocess
import sysconfig

root = Path(os.environ['ROOT'])
output = Path(os.environ['SAN_ROOT']) / 'rapidxmltodict'
extension = output / ('_native' + sysconfig.get_config_var('EXT_SUFFIX'))
command = [
    os.environ['CXX'], '-O1', '-g',
    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
    '-shared', '-fPIC', '-std=c++17',
    '-I' + sysconfig.get_path('include'), '-I' + str(root / 'vendor'),
    str(root / 'src/native.cpp'), '-o', str(extension),
]
print(' '.join(command), flush=True)
subprocess.check_call(command)
PY

export LD_PRELOAD="$($CXX -print-file-name=libasan.so):$($CXX -print-file-name=libstdc++.so)"
export ASAN_OPTIONS=detect_leaks=0:halt_on_error=1
export UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1
export PYTHONMALLOC=malloc
export PYTHONPATH="$SAN_ROOT"

# Verify that Python imports the isolated, instrumented package.
"$PYTHON" - <<'PY'
import os
from pathlib import Path
import rapidxmltodict
import rapidxmltodict._native as native

directory = Path(os.environ['SAN_ROOT']).resolve()
assert Path(rapidxmltodict.__file__).resolve().is_relative_to(directory)
assert Path(native.__file__).resolve().is_relative_to(directory)
print(native.__file__)
PY

"$PYTHON" -m pytest "$ROOT/tests" -q
```

The tested source passed all **527 tests** with this instrumented build, with no
ASan or UBSan diagnostics. The isolated malformed-input and deep-nesting tests
inherit the sanitizer environment too. The exact test count may increase.

Loading both ASan and `libstdc++` before Python matters here: loading only ASan
caused its C++ exception interceptor to fail with
`real___cxa_throw != 0` when exercising the intentional fallback for unusual
XML names. That was a sanitizer/runtime initialization issue, rather than an
XML parsing failure.

`PYTHONMALLOC=malloc` makes ordinary Python object allocations use the system
allocator rather than pymalloc, improving allocator visibility to ASan.
**`detect_leaks=0` disables LeakSanitizer. This run does not establish freedom
from memory leaks.** It checks the exercised paths for the address and undefined
behavior errors detected by these sanitizers; passing tests do not prove the
absence of every possible native-code defect.

In the same shell, clear the test-specific variables before ordinary work
(restore prior values instead if your shell already used these variables):

```sh
unset LD_PRELOAD ASAN_OPTIONS UBSAN_OPTIONS PYTHONMALLOC PYTHONPATH
```

## Larger deterministic differential corpus

This uses the same valid-XML generator as the checked-in test suite. It checks
nested structure, scalar types and dictionary insertion order against the
installed xmltodict. The audited run used version 0.14.2 and compared 100,000
generated documents with zero mismatches.

Run against the normal build from the repository root:

```sh
PYTHONPATH="$PWD/src:$PWD/tests" "${PYTHON:-python}" - <<'PY'
import xmltodict
import rapidxmltodict
from test_compatibility import _ordered_shape, _random_document

print('xmltodict:', getattr(xmltodict, '__version__', 'unknown'))
print('rapidxmltodict:', rapidxmltodict.__file__)
for seed in range(100_000):
    document = _random_document(seed)
    expected = xmltodict.parse(document)
    actual = rapidxmltodict.parse(document)
    assert _ordered_shape(actual) == _ordered_shape(expected), (seed, document)
print('100,000 generated documents matched')
PY
```

To run that corpus under sanitizers instead, keep the sanitizer environment
enabled and replace the command's `PYTHONPATH` with
`"$SAN_ROOT:$ROOT/tests"`.

## Repeated-parse RSS smoke check

A local Linux smoke check parsed a 1,000-record document 100 times to warm up,
then another 3,000 times, collecting garbage before each RSS reading. RSS grew
by 8 KiB in that run. This is **not formal leak detection**: allocator caching,
OS accounting and process activity affect RSS, and some leaks need other inputs
or longer runs to become visible. Do not turn this observation into a strict
cross-platform assertion or a claim that memory cannot grow.

For peak-memory comparisons, use the benchmark's fresh-process RSS results.
Python-only `tracemalloc` does not account for the native RapidXML DOM and
input buffers.

## Required Linux leak gate

The `Linux ASan / LSan` job in `tests.yml` is a required dependency of the
fail-closed `CI passed` aggregate. It runs on GitHub-hosted Ubuntu 24.04 with
CPython 3.12 and GCC. It also runs in the tag-release test pipeline.

After installing the project, run `python scripts/check_native_leaks.py`.
The script compiles `src/native.cpp` into a temporary package with
`-fsanitize=address,undefined`, preloads GCC's ASan and C++ runtimes, and uses
`PYTHONMALLOC=malloc`. `ASAN_OPTIONS=detect_leaks=1:halt_on_error=1` and
`LSAN_OPTIONS=exitcode=23:print_suppressions=1` enable real leak
checking. There are **no suppressions**. RapidXML and the shipped extension are
not modified; the instrumented extension and intentional-leak probe are temporary.

A positive control first runs the same Python workload and deliberately loses
one 4,096-byte allocation in a separate, test-only shared library. The runner
must return 23 and report the expected LeakSanitizer diagnostic, byte count and
`intentional_leak` function. A crash or unsupported detector is not success.
The clean process then must exit zero. After the workload returns and GC runs,
`__lsan_do_leak_check()` checks all tracked allocations before interpreter
finalization, replacing LSan's automatic exit check. This documented checkpoint
avoids CPython 3.12 interned/immortal strings becoming orphaned during shutdown;
the first hosted trial reported those Unicode allocations at finalization.
There is no allocation-stack suppression or disabled tracking. Objects still
reachable at the checkpoint, and leaks created later by interpreter finalization,
are outside this check; ASan remains active through shutdown.

A second positive control loses a `PyList_New` owned reference. Python GC
keeps such containers reachable to LSan, so a separate exact list/dict count
guard compares warmed, garbage-collected snapshots after the scoped workload.
The leaked-list control must fail with code 24; clean counts must not increase.
No tolerances are used. Balanced unrelated allocation/deallocation could conceal
a count change, so this complements LSan rather than proving all refcounts.

After a 10-iteration warmup, each process exercises 9,000 successful parses (including namespace, large
1,000-record input, unusual XML name, depth/mixed-content and option
fallbacks), 6,000 malformed inputs, 3,000 direct native exceptions (including
Unicode decoding failure after partial dictionary/list construction), and 1,000 failing reference callbacks. Results and
exception objects are released; fixtures leave scope and garbage collection
runs before process exit. The regular pytest suite remains a separate gate.

This checks the exercised Linux/compiler/interpreter paths, not all inputs,
architectures, out-of-memory paths, or every possible retained/global allocation.
LSan treats reachable allocations as live. RSS stability is not a substitute.
Some traced/sandboxed development environments cannot run LSan (`ptrace` fatal
error); this script fails rather than silently skipping or disabling detection.
Use the hosted CI result for the actual leak verdict in those environments.

Detector behavior: [LLVM LeakSanitizer documentation](https://clang.llvm.org/docs/LeakSanitizer.html).
