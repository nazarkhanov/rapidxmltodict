"""Build an isolated ASan/UBSan extension and run real LSan cleanup checks.

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
        for source in installed.iterdir():
            if source.suffix in (".py", ".pyi") or source.name == "py.typed":
                shutil.copy2(source, package / source.name)
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
#include <Python.h>
extern "C" __attribute__((noinline)) void* intentional_leak() {
    void* p = std::malloc(4096);
    if (!p) std::abort();
    static_cast<volatile char*>(p)[0] = 42;
    return p;
}
extern "C" void intentional_python_leak() {
    PyObject* p = PyList_New(0);
    if (!p) std::abort();
    // Deliberately lose the owned reference; the GC still sees the live list.
}
''')
        subprocess.run(flags + ["-I" + sysconfig.get_path("include"), str(probe), "-o", str(directory / "leak_probe.so")], check=True)
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
        # A native executable proves the DOM accepts truly read-only, bounded
        # input, including a page boundary with no readable sentinel byte.
        readonly = directory / "readonly_input"
        subprocess.run([compiler, "-O1", "-g", "-std=c++17",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-I" + str(ROOT / "vendor"),
                        str(ROOT / "tests/native_readonly_input.cpp"),
                        "-o", str(readonly)], check=True)
        native_env = dict(env)
        native_env.pop("LD_PRELOAD", None)  # executable already links ASan first
        subprocess.run([str(readonly)], env=native_env, check=True)
        print("PASS: read-only bounded DOM spans with ASan/UBSan/LSan", flush=True)
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
        result = subprocess.run(command + ["--intentional-python-leak"], env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout, flush=True)
        if result.returncode != 24 or "ERROR: retained Python containers after cleanup" not in result.stdout:
            raise SystemExit("Python-reference positive control did not detect the leaked list")
        print("PASS: Python cleanup guard detected intentional leaked reference", flush=True)
        subprocess.run(command, env=env, check=True)
        print("PASS: native workload exited cleanly with ASan/UBSan/LSan enabled", flush=True)
        # Also instrument every differential test and inherited Python subprocess.
        # A startup hook performs the same real pre-finalization LSan checkpoint;
        # pytest itself retains interpreter objects until shutdown, so no broad
        # allocator-stack suppressions are appropriate.
        (directory / "sitecustomize.py").write_text('''import atexit
import ctypes
import gc
import os
LSAN_CHECKPOINT_ACTIVE = True
def _checkpoint():
    try:
        gc.collect()
        check = ctypes.CDLL(None).__lsan_do_leak_check
        check.argtypes = []
        check.restype = None
        check()
    except BaseException:
        os._exit(25)
atexit.register(_checkpoint)
''')
        program = (
            "import sitecustomize; assert sitecustomize.LSAN_CHECKPOINT_ACTIVE; "
            "import pytest; raise SystemExit(pytest.main([" + repr(str(ROOT / "tests")) + ", '-q']))"
        )
        subprocess.run([sys.executable, "-c", program], env=env, check=True)
        print("PASS: complete differential suite under ASan/UBSan/LSan", flush=True)
        subprocess.run([sys.executable, str(ROOT / "scripts/check_native_mapping.py")],
                       env=env, check=True)
        print("PASS: forced native mapping corpus under ASan/UBSan/LSan", flush=True)


if __name__ == "__main__":
    main()
