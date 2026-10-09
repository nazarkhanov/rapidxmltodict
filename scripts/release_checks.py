"""Release validation helpers; never uploads or creates a tag."""
import argparse
from email.parser import BytesParser
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

from packaging.version import Version

TAG = re.compile(r"v([0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?)")


def tag_version(tag):
    match = TAG.fullmatch(tag)
    if match is None:
        raise ValueError("Use a canonical vX.Y.Z, vX.Y.ZrcN, aN, bN or .postN tag")
    version = match.group(1)
    if str(Version(version)) != version:
        raise ValueError("Tag version must be canonical PEP 440 (no leading zeros)")
    return version


def check_tag(tag):
    from setuptools_scm import get_version
    expected = tag_version(tag)
    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()
    if git("rev-parse", "HEAD") != git("rev-parse", "refs/tags/" + tag + "^{commit}"):
        raise ValueError("The tag does not point at the checked-out commit")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Refusing to release a dirty checkout")
    actual = get_version()
    if actual != expected:
        raise ValueError(f"SCM version {actual!r} does not match tag {expected!r}")
    return expected


def check_distributions(directory, expected):
    paths = sorted(Path(directory).iterdir())
    if not any(p.name.endswith(".tar.gz") for p in paths):
        raise ValueError("Missing source distribution")
    if not any(p.suffix == ".whl" for p in paths):
        raise ValueError("Missing wheels")
    for path in paths:
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                metadata_names = [n for n in names if n.endswith(".dist-info/METADATA")]
                if len(metadata_names) != 1:
                    raise ValueError(f"{path}: expected exactly one wheel METADATA")
                metadata = archive.read(metadata_names[0])
                for asset in ("__init__.pyi", "py.typed", "_version.py"):
                    if "rapidxmltodict/" + asset not in names:
                        raise ValueError(f"{path}: missing {asset}")
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as archive:
                names = archive.getnames()
                root = path.name[:-7]
                member = archive.extractfile(root + "/PKG-INFO")
                if member is None:
                    raise ValueError(f"{path}: missing PKG-INFO")
                metadata = member.read()
                for asset in ("src/rapidxmltodict/_version.py",
                              "src/rapidxmltodict/__init__.pyi",
                              "src/rapidxmltodict/py.typed",
                              "src/native.cpp", "vendor/rapidxml/rapidxml.hpp"):
                    if root + "/" + asset not in names:
                        raise ValueError(f"{path}: missing {asset}")
        else:
            raise ValueError(f"Unexpected release artifact: {path}")
        message = BytesParser().parsebytes(metadata)
        if message["Name"] != "rapidxmltodict" or message["Version"] != expected:
            raise ValueError(f"{path}: unexpected name/version "
                             f"{message['Name']!r}/{message['Version']!r}; wanted {expected}")
        print(f"Verified {path.name}: rapidxmltodict {expected}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    expected = tag_version(args.tag)
    if args.dist:
        check_distributions(args.dist, expected)
    else:
        check_tag(args.tag)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"version={expected}\n")
            stream.write(f"prerelease={str(Version(expected).is_prerelease).lower()}\n")


if __name__ == "__main__":
    main()
