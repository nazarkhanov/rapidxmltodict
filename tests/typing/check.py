"""Validate installed-package types outside the checkout (mypy + Pyright)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

source = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='rapidxml-types-') as directory:
    work = Path(directory)
    for name in ('positive.py', 'negative.py'):
        shutil.copyfile(source / name, work / name)
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    def run(*args):
        result = subprocess.run([sys.executable, '-m', *args], cwd=work,
                                env=environment, text=True, capture_output=True)
        print(result.stdout, result.stderr)
        return result
    # Jedi uses the current interpreter and installed stubs, not checkout sources.
    import jedi
    jedi.settings.cache_directory = str(work / "jedi-cache")
    for function, expected in (
        ('parse', {'force_list', 'item_callback', 'postprocessor', 'dict_constructor', 'comment_key'}),
        ('unparse', {'pretty', 'indent', 'preprocessor', 'comment_key', 'bytes_errors'}),
    ):
        script = jedi.Script('import rapidxmltodict as xml\nxml.' + function + '(',
                             path=str(work / 'editor.py'))
        signatures = script.get_signatures(2, len('xml.' + function + '('))
        assert signatures, function
        parameters = {parameter.name for signature in signatures for parameter in signature.params}
        assert expected <= parameters, (function, parameters)
        completions = {item.name.rstrip('=') for item in script.complete(2, len('xml.' + function + '('))}
        assert expected <= completions, (function, completions)
        assert all(str(signature.module_path).endswith('__init__.pyi') for signature in signatures)
        print(function, 'installed-stub signatures and keyword completion verified')
    installed = run('pip', 'show', 'rapidxmltodict')
    assert installed.returncode == 0
    for target in ('3.9', '3.12'):
        result = run('mypy', '--strict', '--no-incremental', '--python-version', target, 'positive.py')
        assert result.returncode == 0
        result = run('pyright', '--pythonversion', target, '--pythonpath', sys.executable, 'positive.py')
        assert result.returncode == 0
    bad_lines = {5, 6, 7, 8, 9, 10, 11, 12, 13}
    result = run('mypy', '--strict', '--no-incremental', 'negative.py')
    assert result.returncode == 1
    found = {int(line.split(':')[1]) for line in result.stdout.splitlines()
             if line.startswith('negative.py:') and ': error:' in line}
    assert found == bad_lines, (found, bad_lines)
    result = run('pyright', '--outputjson', '--pythonpath', sys.executable, 'negative.py')
    assert result.returncode == 1
    report = json.loads(result.stdout)
    found = {x['range']['start']['line'] + 1 for x in report['generalDiagnostics'] if x['severity'] == 'error'}
    assert found == bad_lines, (found, bad_lines)
print('Installed-package typing checks passed.')
