"""Build stable/prerelease fixtures, then rebuild wheels without .git.

Runs only in the packaging CI job, not for users installing the package.
All tags/commits are made in a temporary local fixture; none are pushed.
"""
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from release_checks import check_distributions, check_tag

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True)


def check_fixture(tag):
    with tempfile.TemporaryDirectory(prefix="rapidxml-release-") as temp:
        base = Path(temp)
        source = base / "checkout"
        source.mkdir()
        snapshot = subprocess.check_output(
            ["git", "archive", "--format=tar", "HEAD"], cwd=ROOT
        )
        with tarfile.open(fileobj=io.BytesIO(snapshot)) as archive:
            archive.extractall(source, filter="data")
        run("git", "init", cwd=source)
        run("git", "config", "user.name", "Packaging Test", cwd=source)
        run("git", "config", "user.email", "packaging-test@example.invalid", cwd=source)
        run("git", "add", ".", cwd=source)
        run("git", "commit", "-m", "Temporary packaging fixture", cwd=source)
        run("git", "tag", tag, cwd=source)
        run(sys.executable, "scripts/release_checks.py", tag, cwd=source)
        dist = base / "dist"
        run(sys.executable, "-m", "build", "--sdist", "--outdir", str(dist), cwd=source)
        unpacked = base / "unpacked"
        with tarfile.open(next(dist.glob("*.tar.gz"))) as archive:
            archive.extractall(unpacked, filter="data")
        extracted = next(unpacked.iterdir())
        assert not (extracted / ".git").exists()
        run(sys.executable, "-m", "build", "--wheel", "--outdir", str(dist), cwd=extracted)
        expected = tag[1:]
        check_distributions(dist, expected)
        try:
            check_distributions(dist, "999.999.999")
        except ValueError:
            pass
        else:
            raise AssertionError("Wrong artifact versions must be rejected")
        wheel = next(dist.glob("*.whl"))
        run(sys.executable, "-m", "pip", "install", "--force-reinstall", str(wheel), cwd=base)
        code = (
            "import rapidxmltodict as r; from importlib.metadata import version; "
            f"assert r.__version__ == version('rapidxmltodict') == {expected!r}; "
            "assert r.parse('<root>ok</root>') == {'root': 'ok'}"
        )
        run(sys.executable, "-I", "-c", code, cwd=base)
        print(f"Verified tagged checkout -> sdist -> wheel -> installed runtime: {tag}")


if __name__ == "__main__":
    for fixture_tag in ("v9.8.7", "v9.8.8rc1"):
        check_fixture(fixture_tag)
