# tests/unit/test_validate_checkin.py
import importlib.util, subprocess, sys
import pytest
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


# ---------------------------------------------------- A6: gallery integrity
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


def test_gallery_preserves_absolute_path(tmp_path):
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")
    run = tmp_path / "run"
    run.mkdir()
    assert _mod().validate(_valid_checkin1(str(reference)), base_dir=str(run)) == []


def test_gallery_preserves_parent_relative_path(tmp_path):
    (tmp_path / "reference.pdf").write_bytes(b"reference")
    run = tmp_path / "run"
    run.mkdir()
    assert _mod().validate(_valid_checkin1("../reference.pdf"), base_dir=str(run)) == []


def test_gallery_does_not_substitute_same_named_local_file(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "missing.pdf").write_bytes(b"wrong reference")
    errors = _mod().validate(_valid_checkin1("../missing.pdf"), base_dir=str(run))
    assert any("../missing.pdf" in error for error in errors)


def test_backcompat_no_base_dir():
    vc = _mod()
    c = _valid_checkin1("cites plots/whatever.png but schema-only mode skips existence")
    assert vc.validate(c) == []


def _checkin2(options):
    return {"schema_version": 1, "kind": "checkin2", "sections": {
        "waypoint": "comparison", "expectation": "smoke", "ask": {"options": options}}}


@pytest.mark.parametrize("options", [
    ["GO", "ADJUST", "OTHER"], ["GO", "ADJUST", "GO"], ["GO", "GO"],
    [{"name": ["GO"]}, {"name": "ADJUST"}], [{"name": {}}, "ADJUST"],
    [True, "ADJUST"], {"GO": 1, "ADJUST": 2}, None,
])
def test_exact_options_and_malformed_names(options):
    assert _mod().validate(_checkin2(options))


@pytest.mark.parametrize("options", [["GO", "ADJUST"], ["ADJUST", "GO"],
                                      [{"name": "GO"}, {"name": "ADJUST"}]])
def test_equivalent_valid_option_forms(options):
    assert _mod().validate(_checkin2(options)) == []


@pytest.mark.parametrize("version", [True, False, 1.0, "1", [], {}])
def test_version_requires_integer(version):
    checkin = _checkin2(["GO", "ADJUST"])
    checkin["schema_version"] = version
    assert _mod().validate(checkin)


def test_missing_waypoint_file(tmp_path):
    checkin = _checkin2(["GO", "ADJUST"])
    checkin["sections"]["waypoint"] = "missing-waypoint.png"
    assert any("missing" in error for error in _mod().validate(checkin, base_dir=tmp_path))


def test_malformed_sibling_contract_is_a_validation_result(tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs/task_contract.json").write_text("[]")
    assert _mod().validate(_good_checkin1(), base_dir=tmp_path) == []


def test_cli_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "checkin.json"
    path.write_text('{"schema_version":true,"schema_version":1,"kind":"checkin2"}')
    result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
    assert result.returncode == 2 and "duplicate JSON key" in result.stderr
