# tests/unit/test_validate_checkin.py
import importlib.util, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/validation/validate_checkin.py"

def _mod():
    spec = importlib.util.spec_from_file_location("vc", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

def _good_checkin1():
    return {"schema_version": 1, "kind": "checkin1", "sections": {
        "i": "plain preamble", "i-b": "resource census block", "ii": "gallery",
        "iii": {"figure_id": "Figure 3", "waypoint": "grey QCD-MC line"},
        "iv": "plan", "v": [{"id": "F1", "why": "x"}], "vi": ["answer", "ask", "propose"]}}

def test_selftest_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_good_checkin1_validates():
    assert _mod().validate(_good_checkin1()) == []

def test_missing_section_fails():
    m = _mod(); bad = _good_checkin1(); del bad["sections"]["ii"]
    errs = m.validate(bad)
    assert any("(ii)" in e for e in errs), errs

def test_bad_flag_id_fails():
    m = _mod(); bad = _good_checkin1(); bad["sections"]["v"] = [{"id": "X1"}]
    assert any("F<number>" in e or "F1" in e for e in m.validate(bad))

def test_checkin2_requires_go_adjust():
    m = _mod()
    c2 = {"schema_version": 1, "kind": "checkin2", "sections": {
        "waypoint": "side by side", "expectation": "should match",
        "ask": {"options": [{"name": "GO"}]}}}
    assert any("GO and ADJUST" in e for e in m.validate(c2))


# ---------------------------------------------------- Task 5 (A6): gallery integrity (trial QD.1)
def _valid_checkin1(gallery):
    return {"schema_version": 1, "kind": "checkin1", "sections": {
        "i": "request understood", "i-b": "census summary", "ii": gallery,
        "iii": {"plan": "x", "waypoint": "SR yield shape at 1k events"},
        "iv": "budget: 1h", "v": [{"id": "F1", "text": "assume 139/fb"}],
        "vi": ["answer", "ask", "propose"]}}


def test_gallery_missing_file_invalid(tmp_path):
    vc = _mod()
    c = _valid_checkin1("side-by-side at plots/nope.png awaiting review")
    errs = vc.validate(c, base_dir=str(tmp_path))
    assert any("plots/nope.png" in e for e in errs)


def test_gallery_file_uri_invalid(tmp_path):
    vc = _mod()
    c = _valid_checkin1("deck at file:///private/tmp/deck.html")
    errs = vc.validate(c, base_dir=str(tmp_path))
    assert any("file://" in e for e in errs)


def test_gallery_existing_ok(tmp_path):
    vc = _mod()
    (tmp_path / "plots").mkdir()
    (tmp_path / "plots" / "fig5.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    c = _valid_checkin1("primary side-by-side: plots/fig5.png")
    assert vc.validate(c, base_dir=str(tmp_path)) == []


def test_backcompat_no_base_dir():
    vc = _mod()
    c = _valid_checkin1("cites plots/whatever.png but schema-only mode skips existence")
    assert vc.validate(c) == []
