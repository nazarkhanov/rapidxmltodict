"""Build an isolated ASan/UBSan extension and run real exit-time LSan checks.

Linux/GCC only. Requires the project installed in the active interpreter.
No suppressions or sanitizer disabling: an unsupported LSan host fails closed.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    import rapidxmltodict

    compiler = os.environ.get("CXX", "g++")
    with tempfile.TemporaryDirectory(prefix="rapidxml-leaks-") as temporary:
        directory = Path(temporary)
        package = directory / "rapidxmltodict"
        package.mkdir()
        installed = Path(rapidxmltodict.__file__).parent
        for name in ("__init__.py", "_version.py"):
            shutil.copy2(installed / name, package / name)
        flags = [compiler, "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-omit-frame-pointer", "-shared", "-fPIC", "-std=c++17"]
        subprocess.run(flags + ["-I" + sysconfig.get_path("include"),
                       "-I" + str(ROOT / "vendor"), str(ROOT / "src/native.cpp"),
                       "-o", str(package / ("_native" + sysconfig.get_config_var("EXT_SUFFIX")))],
                       check=True)
        # Test-only shared library, never linked into or shipped with the package.
        # A volatile write and escaped return prevent allocation elimination.
        probe = directory / "leak_probe.cpp"
        probe.write_text('''#include <cstdlib>
extern "C" __attribute__((noinline)) void* intentional_leak() {
    void* p = std::malloc(4096);
    if (!p) std::abort();
    static_cast<volatile char*>(p)[0] = 42;
    return p;
}
''')
        subprocess.run(flags + [str(probe), "-o", str(directory / "leak_probe.so")], check=True)
        libraries = [subprocess.check_output([compiler, "-print-file-name=" + name],
                     text=True).strip() for name in ("libasan.so", "libstdc++.so")]
        if not all(Path(name).is_file() for name in libraries):
            raise SystemExit("GCC sanitizer runtime libraries not found")
        env = dict(os.environ, LD_PRELOAD=":".join(libraries),
                   ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                   LSAN_OPTIONS="exitcode=23:print_suppressions=1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
                   PYTHONMALLOC="malloc", PYTHONPATH=str(directory),
                   SAN_ROOT=str(directory))
        command = [sys.executable, str(ROOT / "tests/native_leak_workload.py")]
        # First prove the identical Python/runtime configuration detects a known
        # leak. A crash, unavailable LSan, or unrelated error is NOT a pass.
        result = subprocess.run(command + ["--intentional-leak"], env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout, flush=True)
        if (result.returncode != 23 or "LeakSanitizer: detected memory leaks" not in result.stdout
                or "4096 byte(s)" not in result.stdout or "intentional_leak" not in result.stdout):
            raise SystemExit("LSan positive control did not detect the intentional 4096-byte leak")
        print("PASS: LSan detected intentional leak and returned exit code 23", flush=True)
        subprocess.run(command, env=env, check=True)
        print("PASS: native workload exited cleanly with ASan/UBSan/LSan enabled", flush=True)


if __name__ == "__main__":
    main()
