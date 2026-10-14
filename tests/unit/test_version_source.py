"""The package has one version: the one `pyproject.toml` declares (the release stamps it there)."""
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest

import ravel

ROOT = Path(__file__).resolve().parents[2]


def declared():
    return tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']


def test_the_package_reports_the_declared_version():
    assert ravel.__version__ == declared()


@pytest.mark.parametrize('module', ['ravel', 'ravel.cli'])
def test_the_command_line_reports_the_declared_version(module):
    out = subprocess.run([sys.executable, '-m', module, '--version'], capture_output=True, text=True,
                         check=True, cwd=ROOT)
    assert out.stdout.split() == ['ravel-hep', declared()]


def test_the_package_imports_where_the_file_above_src_cannot_be_read(monkeypatch):
    """A sandboxed worker reads src/ only; the refused stat leaves the installed metadata's answer."""
    real = Path.is_file
    def refused(self):
        if self.name == 'pyproject.toml':
            raise PermissionError(1, 'Operation not permitted', str(self))
        return real(self)
    monkeypatch.setattr(Path, 'is_file', refused)
    assert type(ravel._declared_version()) is str


def test_the_citation_record_carries_the_declared_version():
    citation = ROOT / 'CITATION.cff'
    if citation.exists():
        assert re.findall(r'(?m)^version: (.+)$', citation.read_text()) == [declared()]


def test_no_user_document_names_a_wheel_of_another_version():
    for document in [ROOT / 'README.md', *sorted((ROOT / 'docs').rglob('*.md'))]:
        if document.exists():
            for version in re.findall(r'ravel_hep-(\d[^-\s]*)-py3', document.read_text()):
                assert version == declared(), (document.relative_to(ROOT), version)


def test_every_source_distribution_entry_names_a_path_of_this_tree():
    builds = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['hatch']['build']['targets']
    missing = [entry for entry in builds['sdist']['include'] if not (ROOT / entry).exists()]
    assert missing == []
