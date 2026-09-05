"""Retained CR004 failure: partial detector files must never receive full rate."""
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("detector_count", [221, 206, 19999, 20001])
def test_partial_or_duplicated_detector_exposure_stops_before_conversion(tmp_path, monkeypatch, detector_count):
    from ravel.physics import delphes2sa_native as driver
    marker = tmp_path / "converter-ran"
    script = tmp_path / "converter.py"
    script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    fake = SimpleNamespace(gSystem=SimpleNamespace(Load=lambda _: 0),
        gInterpreter=SimpleNamespace(Declare=lambda _: True, AddIncludePath=lambda _: None))
    monkeypatch.setitem(sys.modules, "ROOT", fake)
    monkeypatch.setattr(driver, "read_weights", lambda *_a, **_k: [1.0] * detector_count)
    monkeypatch.setattr(driver, "load_normalization", lambda _: {
        "applied_cross_section_pb": 1.0,
        "generation": {"n_events": 20000, "negative_weights": 0, "sumw": 20000., "sumw2": 20000.}})
    with pytest.raises(ValueError, match="detector event count"):
        driver.main(["--input", "partial.root", "--output", str(tmp_path / "out.root"),
                     "--lumi", "139000", "--normalization", "verified-normalization.json",
                     "--converter-script", str(script), "--recast-env", str(tmp_path)])
    assert not marker.exists()
    assert not (tmp_path / "out.root.normalization.json").exists()
