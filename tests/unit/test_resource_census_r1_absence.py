"""R1 rung absence-vs-outage classification (taunu run 2026-08-28, RESULT.md gap G2).

The measured defect: the census reported "Cloudflare-blocked / 503" for CMS ins1684340 when in
fact NO HEPData record exists (the open JSON API 404s and INSPIRE lists no HEPDATA external id).
A physicist decision (drop-CMS vs wait-for-outage) hinges on the distinction, so the rung must
return a first-class ABSENT verdict for a definitive API 404 and an outage-or-block ERROR for
5xx/403/network trouble -- never conflate the two.
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/workflow/resource_census.py"


def _mod():
    spec = importlib.util.spec_from_file_location("rc_r1", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_404_with_inspire_confirming_none_is_definitive_absent():
    rc = _mod()
    v = rc.hepdata_absence_verdict(
        "1684340", 404, {"status": "OK", "hepdata_listed": False, "ids": []})
    assert v["status"] == "ABSENT"
    assert v["http_status"] == 404
    assert v["corroborated_by_inspire"] is True
    assert "definitive" in v["meaning"].lower()
    assert "outage" not in v["status"].lower()


def test_404_but_inspire_lists_hepdata_id_is_inconsistent_error():
    rc = _mod()
    v = rc.hepdata_absence_verdict(
        "1649273", 404,
        {"status": "OK", "hepdata_listed": True,
         "ids": [{"schema": "HEPDATA", "value": "ins1649273"}]})
    assert v["status"] == "ERROR"
    assert v["classification"] == "inconsistent"
    # an inconsistent state must never be reported as a definitive absence
    assert "absen" in v["reason"].lower() and "not" in v["reason"].lower()


def test_5xx_is_outage_or_block_not_absence():
    rc = _mod()
    v = rc.hepdata_absence_verdict("1684340", 503, None)
    assert v["status"] == "ERROR"
    assert v["classification"] == "outage-or-block"
    assert "not evidence" in v["meaning"].lower()


def test_network_error_no_http_code_is_outage_or_block():
    rc = _mod()
    v = rc.hepdata_absence_verdict("1684340", None, None)
    assert v["status"] == "ERROR"
    assert v["classification"] == "outage-or-block"


def test_404_with_inspire_unreachable_stays_absent_uncorroborated():
    # the open API's 404 is a served, definitive response (a block manifests as 403/5xx),
    # so an unreachable INSPIRE cross-check downgrades corroboration, not the verdict
    rc = _mod()
    v = rc.hepdata_absence_verdict(
        "1684340", 404, {"status": "ERROR", "reason": "timeout"})
    assert v["status"] == "ABSENT"
    assert v["corroborated_by_inspire"] is False


def test_absent_counts_as_a_walked_rung():
    rc = _mod()
    assert rc._rung_ok({"status": "OK"}) is True
    assert rc._rung_ok({"status": "ABSENT"}) is True
    assert rc._rung_ok({"status": "ERROR", "classification": "outage-or-block"}) is False


def test_markdown_line_distinguishes_absent_from_outage():
    rc = _mod()
    absent = rc._r1_markdown_line({"status": "ABSENT", "http_status": 404,
                                   "corroborated_by_inspire": True,
                                   "url": "https://www.hepdata.net/record/ins1684340"})
    assert "no hepdata record" in absent.lower()
    assert "404" in absent
    outage = rc._r1_markdown_line({"status": "ERROR", "classification": "outage-or-block",
                                   "reason": "HTTPError: HTTP Error 503"})
    assert "not evidence" in outage.lower()
    ok = rc._r1_markdown_line({"status": "OK", "n_tables": 8, "url": "u",
                               "likelihood_candidates": [], "efficiency_map_candidates": []})
    assert "8 tables" in ok
