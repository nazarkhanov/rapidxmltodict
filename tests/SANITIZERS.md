# Native sanitizer checks

The required `Linux ASan / LSan` CI job runs on Ubuntu 24.04 with CPython 3.12
and GCC. It is a fail-closed dependency of `CI passed`, including release builds.

## Run

Install the package and test dependencies in a virtual environment, then run:

```sh
python -m pip install '.[test]'
python scripts/check_native_leaks.py
```

The script compiles an isolated native extension using
`-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer`, preloads matching
GCC ASan/C++ runtimes, and sets `PYTHONMALLOC=malloc`. It never replaces the
normal installed extension or changes the vendored header.

`ASAN_OPTIONS=detect_leaks=1:halt_on_error=1`,
`LSAN_OPTIONS=exitcode=23:print_suppressions=1`, and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1` remain enabled.
There are no suppression files or disabled allocation tracking.

## What is checked

1. The same native workload must detect an intentional 4,096-byte allocation
   leak in a separate test-only library, with the expected LSan diagnostic and
   exit code 23. An unrelated crash or unavailable detector cannot pass.
2. A second control deliberately loses a Python list reference. A warmed exact
   list/dict count guard must detect the retained container and exit 24. Python's
   GC lists can keep such objects reachable to LSan, hence the separate guard.
3. The clean workload must pass both checks: 9,000 valid/option/depth/name parses,
   6,000 malformed inputs, 3,000 direct native exceptions, and 1,000 callback
   exceptions after a 10-iteration warmup. Partial dictionary/list construction,
   namespace handling, large records and object cleanup are included.
4. The complete differential pytest suite runs with the instrumented extension.
   Its child Python processes inherit a startup hook for a real LSan checkpoint.
   This includes standalone validation, streaming, DTD/encoding and serialization
   regression tests. xmltodict 1.0.4 is a test oracle only.
   Import-block subprocesses omit `-I` only in this instrumented job because
   isolated mode ignores `PYTHONMALLOC=malloc` and `PYTHONPATH`; they explicitly
   check the hook and allocator environment, and still reject parser imports.
   Normal jobs run those subprocesses with `-I`.
5. The same behavior corpus runs again through the forced direct-native event
   mapper, including custom-object protocols, retained-traceback cleanup, deep
   results and partial-result mutation. This second process uses the same real
   LSan startup hook; it is not a skipped or unsanitized comparison.

The separate runtime-independence tests block xmltodict, pyexpat and Expat parser
imports. Normal distribution/typing jobs also remain required.

## Interpretation and limits

After results and exception frames leave scope and garbage collection runs,
`__lsan_do_leak_check()` scans tracked allocations before CPython finalization.
This documented checkpoint replaces the automatic exit check, avoiding orphaned
interpreter shutdown allocations without suppressing Python allocator stacks.
ASan stays active through shutdown. Allocations still reachable at the checkpoint
and leaks introduced later during interpreter finalization are outside that scan.

The exact container-count guard complements LSan; balanced unrelated growth and
shrinkage could conceal a count change. Passing tests cover exercised paths,
compiler/interpreter builds and inputs, not every possible allocation failure,
platform or XML document. Stable RSS is not proof of absence of leaks.

Some traced/sandboxed environments cannot execute LSan (`ptrace` fatal error).
The script fails rather than skipping detection; use the GitHub-hosted run for
its actual result in those environments.

See the [official LeakSanitizer documentation](https://clang.llvm.org/docs/LeakSanitizer.html).

The Linux job also compiles `native_readonly_input.cpp` with ASan/UBSan/LSan.
It places XML in read-only pages immediately before an inaccessible page, checks
raw normalization metadata and unchanged node sizes, and parses 12,000 levels
without recursion. The Python suite checks unchanged str/bytes values, Unicode
cache integrity, result/input lifetimes and mixed normalization.

Five isolated `RLIMIT_AS` allocation-failure cases run in ordinary Linux tests.
They check DOM allocation, final ASCII/UTF-8/entity-decoded strings and a Unicode
input UTF-8 cache, with recovery after each `MemoryError`. Only those probes skip
inside ASan/LSan, whose large virtual address mappings conflict with address caps;
no sanitizer is disabled. Two additional bounded Python-allocation fault sweeps
run when CPython provides `_testcapi` hooks. Missing hooks are explicit skips.
