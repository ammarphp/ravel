"""Synthetic isolation checks for the separate hi_class interpreter."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.physics import hiclass_worker


def _request(version="hi-class-test"):
    return {
        "expected_version": version,
        "parameters": {"H0": 67.0, "omega_b": 0.02},
        "spectra": ["tt"],
        "ell_max": 3,
    }


def test_class_module_version_is_refused_for_hiclass_engine(monkeypatch):
    monkeypatch.setitem(sys.modules, "classy", type("Module", (), {"__version__": "3.4.1"})())
    with pytest.raises(ValueError, match="hi_class interpreter version differs"):
        hiclass_worker.run(_request())


def _fake_classy(root):
    package = root / "fake-site"
    package.mkdir()
    (package / "classy.py").write_text(
        "__version__ = 'hi-class-test'\n"
        "class Class:\n"
        "    def set(self, parameters):\n"
        "        self.parameters = dict(parameters)\n"
        "    def compute(self):\n"
        "        self.scale = self.parameters['H0']\n"
        "    def lensed_cl(self, ell_max):\n"
        "        return {'tt': [self.scale * ell for ell in range(ell_max + 1)]}\n"
        "    def struct_cleanup(self):\n"
        "        pass\n"
        "    def empty(self):\n"
        "        pass\n"
    )
    return package


def _run_worker(tmp_path, request):
    source = tmp_path / "request.json"
    output = tmp_path / "output.json"
    source.write_text(json.dumps(request) + "\n")
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(_fake_classy(tmp_path)), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-B", str(Path(hiclass_worker.__file__)), str(source), str(output)],
                          env=env, capture_output=True, text=True)
    return done, output


def test_worker_round_trips_parameters_and_spectra_with_fake_interpreter(tmp_path):
    done, output = _run_worker(tmp_path, _request())
    assert done.returncode == 0, done.stderr
    assert json.loads(output.read_text()) == {
        "parameters": _request()["parameters"],
        "spectra": {"TT": [134.0, 201.0]},
    }


def test_worker_process_refuses_version_mismatch_without_writing_output(tmp_path):
    done, output = _run_worker(tmp_path, _request(version="3.4.1"))
    assert done.returncode != 0
    assert "hi_class interpreter version differs" in done.stderr
    assert not output.exists()


def test_qualification_comparator_refuses_planted_wrong_row():
    reference = {"TT": [1.0, 2.0]}
    candidate = {"TT": [1.0, 2.0003]}
    with pytest.raises(ValueError, match="relative tolerance"):
        hiclass_worker.compare_spectra(reference, candidate, tolerance=1e-4)
