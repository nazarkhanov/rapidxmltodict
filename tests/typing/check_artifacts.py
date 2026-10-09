"""Confirm PEP 561 assets survive sdist and wheel packaging."""
from pathlib import Path
import tarfile
import zipfile

root = Path(__file__).resolve().parents[2]
stub = (root / 'src/rapidxmltodict/__init__.pyi').read_bytes()
for suffix in ('*.whl', '*.tar.gz'):
    artifacts = list((root / 'dist').glob(suffix))
    assert artifacts, suffix
    for path in artifacts:
        if path.suffix == '.whl':
            with zipfile.ZipFile(path) as archive:
                assert archive.read('rapidxmltodict/__init__.pyi') == stub
                assert archive.read('rapidxmltodict/py.typed') == b''
        else:
            with tarfile.open(path) as archive:
                prefix = path.name[:-7] + '/src/rapidxmltodict/'
                assert archive.extractfile(prefix + '__init__.pyi').read() == stub
                assert archive.extractfile(prefix + 'py.typed').read() == b''
        print(path.name, 'contains matching stubs and py.typed')
