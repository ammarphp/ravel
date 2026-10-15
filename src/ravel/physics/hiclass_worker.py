"""Isolated hi_class CMB worker.

This module is executed only by the interpreter installed in ``.venv-hiclass``.
It deliberately imports ``classy`` after validating the supplied identity, so
the host interpreter's CLASS binding cannot be selected by accident.
"""
from __future__ import annotations

import importlib
import json
import math
from pathlib import Path
import sys


def _number(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("finite " + label + " required")
    return float(value)


def _request(value: object) -> dict:
    if type(value) is not dict or set(value) != {"expected_version", "parameters", "spectra", "ell_max"}:
        raise ValueError("closed hi_class worker request required")
    if type(value["expected_version"]) is not str or not value["expected_version"]:
        raise ValueError("expected hi_class version required")
    if type(value["parameters"]) is not dict or not value["parameters"]:
        raise ValueError("hi_class parameters required")
    if type(value["spectra"]) is not list or not value["spectra"] or any(x not in {"tt", "ee", "bb", "te"} for x in value["spectra"]):
        raise ValueError("known hi_class spectra required")
    if type(value["ell_max"]) is not int or not 2 <= value["ell_max"] <= 5000:
        raise ValueError("bounded hi_class ell_max required")
    return value


def _classy(expected_version: str):
    module = importlib.import_module("classy")
    actual = str(getattr(module, "__version__", "")).lstrip("v")
    if actual != expected_version:
        raise ValueError("hi_class interpreter version differs from its pinned runtime")
    return module


def run(request: dict) -> dict:
    request = _request(request)
    module = _classy(request["expected_version"])
    solver = module.Class()
    try:
        solver.set(request["parameters"])
        solver.compute()
        raw = solver.lensed_cl(request["ell_max"])
        spectra = {}
        for name in request["spectra"]:
            values = raw[name]
            if len(values) < request["ell_max"] + 1:
                raise ValueError("hi_class returned fewer multipoles than requested")
            spectra[name.upper()] = [_number(values[ell], "hi_class spectrum") for ell in range(2, request["ell_max"] + 1)]
        return {"parameters": request["parameters"], "spectra": spectra}
    finally:
        solver.struct_cleanup()
        solver.empty()


def compare_spectra(reference: dict, candidate: dict, *, tolerance: float) -> None:
    if type(reference) is not dict or type(candidate) is not dict or set(reference) != set(candidate):
        raise ValueError("matching spectrum populations required")
    if type(tolerance) not in (int, float) or not 0 < tolerance < 1:
        raise ValueError("finite relative tolerance required")
    for name, expected in reference.items():
        actual = candidate[name]
        if type(expected) is not list or type(actual) is not list or len(expected) != len(actual):
            raise ValueError("matching spectrum lengths required")
        for left, right in zip(expected, actual):
            baseline = abs(_number(left, "reference spectrum"))
            if baseline == 0 or abs(_number(right, "candidate spectrum") - left) / baseline > tolerance:
                raise ValueError("hi_class spectrum exceeds relative tolerance")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        raise ValueError("request and output paths required")
    request = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    result = run(request)
    Path(argv[1]).write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
