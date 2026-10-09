"""Compose versioned release prose and install instructions without publishing."""
import argparse
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def compose_notes(version, notes_directory):
    if str(Version(version)) != version:
        raise ValueError("Release notes require a canonical PEP 440 version")
    source = Path(notes_directory) / (version + ".md")
    if source.is_file():
        overview = source.read_text(encoding="utf-8").strip()
        if not overview:
            raise ValueError(f"Release notes file is empty: {source}")
    else:
        overview = (
            f"## rapidxmltodict {version}\n\n"
            "See the generated changelog below for the changes in this release."
        )
    return (
        overview + "\n\n## Install\n\n```sh\n"
        f"python -m pip install rapidxmltodict=={version}\n```\n\n"
        f"[Package on PyPI](https://pypi.org/project/rapidxmltodict/{version}/)\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--notes-directory", type=Path,
                        default=ROOT / "docs/release-notes")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(compose_notes(args.version, args.notes_directory),
                           encoding="utf-8")


if __name__ == "__main__":
    main()
