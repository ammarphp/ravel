"""--tables fallback via the OPEN internal endpoint (taunu run 2026-08-28, RESULT.md gap G3).

The measured fact: /download/table/... is Cloudflare-403 from this host, but
/record/data/<recid>/<table_id>/<version> is open and serves the identical table content
(verified 2026-08-28: all 8 tables of ins1649273 fetched this way; recid+table ids come from
the open record JSON). The fallback must honor the same verify-after-download integrity
contract as the hepdata-cli route: every listed table lands, parses, and carries non-empty
values[] -- anything less raises (-> the CLI's loud nonzero exit).
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/workflow/hepdata_fetch.py"

# minimal synthetic record in the verified live shape (ins1649273, 2026-08-28):
# recid/version at top level (mirrored under record.*), data_tables[].{id,name,description}
REC = {
    "recid": 80812, "version": 3,
    "record": {"recid": 80812, "version": 3, "inspire_id": "1649273"},
    "data_tables": [
        {"id": 229547, "name": "Table 1",
         "description": "Observed and predicted mT distributions"},
        {"id": 229548, "name": "Table 4",
         "description": "Cutflow of selected events"},
    ],
}


def _mod():
    spec = importlib.util.spec_from_file_location("hf_fallback", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_record_data_index_derives_recid_version_and_table_ids():
    hf = _mod()
    recid, version, idx = hf.record_data_index(REC)
    assert (recid, version) == (80812, 3)
    assert idx == [(229547, "Table 1"), (229548, "Table 4")]


def test_record_data_index_rejects_record_without_recid_or_tables():
    hf = _mod()
    with pytest.raises(ValueError):
        hf.record_data_index({"data_tables": [{"id": 1, "name": "Table 1"}]})
    with pytest.raises(ValueError):
        hf.record_data_index({"recid": 80812, "data_tables": []})
    with pytest.raises(ValueError):
        hf.record_data_index({"recid": 80812, "data_tables": [{"name": "no id"}]})


def test_fallback_downloads_verifies_and_classifies(tmp_path):
    hf = _mod()
    served = {
        "https://www.hepdata.net/record/data/80812/229547/3":
            {"name": "Table 1", "doi": "10.17182/hepdata.80812.v3/t1",
             "description": "Observed and predicted mT distributions",
             "values": [{"x": [{"value": 1}], "y": [{"value": 2}]}]},
        "https://www.hepdata.net/record/data/80812/229548/3":
            {"name": "Table 4", "doi": "10.17182/hepdata.80812.v3/t4",
             "description": "Cutflow of selected events",
             "values": [{"x": [{"value": 1}], "y": [{"value": 3}]}]},
    }
    manifest = {"table_files": [], "errors": []}
    hf.fetch_tables_via_record_data(REC, str(tmp_path), manifest,
                                    get_json_fn=lambda u: served[u])
    assert len(manifest["table_files"]) == 2
    kinds = {t["name"]: t["kind"] for t in manifest["table_files"]}
    assert kinds["Table 4"] == "cutflow"
    # every table file landed on disk, is valid JSON, and carries the served values
    for t in manifest["table_files"]:
        p = tmp_path / t["file"]
        assert p.is_file() and p.stat().st_size > 0
        assert json.load(open(p))["values"]
    assert manifest["table_kinds"]["cutflow"] == 1


def test_fallback_empty_values_is_corrupt_and_raises(tmp_path):
    hf = _mod()
    manifest = {"table_files": [], "errors": []}
    with pytest.raises(RuntimeError, match="(?i)corrupt|partial"):
        hf.fetch_tables_via_record_data(
            REC, str(tmp_path), manifest,
            get_json_fn=lambda u: {"name": "Table 1", "values": []})


def test_fallback_download_failure_raises_partial(tmp_path):
    hf = _mod()

    def flaky(url):
        if "229548" in url:
            raise OSError("connection reset")
        return {"name": "Table 1", "description": "d",
                "values": [{"x": [], "y": []}]}

    manifest = {"table_files": [], "errors": []}
    with pytest.raises(RuntimeError, match="(?i)partial"):
        hf.fetch_tables_via_record_data(REC, str(tmp_path), manifest, get_json_fn=flaky)


def test_classify_is_module_level_and_shared():
    # the fallback reuses the SAME classifier as the hepdata-cli route
    hf = _mod()
    assert hf.classify("Cutflow of selected events", "Table 4") == "cutflow"
    assert hf.classify("Upper limit on the cross-section", "Table 3") == "limit"


def test_verified_ctx_is_defined():
    # regression: _open()'s TLS retry referenced _VERIFIED_CTX without defining it (NameError)
    hf = _mod()
    assert hasattr(hf, "_VERIFIED_CTX")
