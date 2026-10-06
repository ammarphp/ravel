"""Path relocation must preserve real workflow discovery and published certification lookup."""
from pathlib import Path

from ravel.workflow import result_pack, scan_babysitter, scan_orchestrator

ROOT = Path(__file__).resolve().parents[2]


def test_scan_tools_resolve_the_checkout_instead_of_the_package_parent():
    assert Path(scan_orchestrator.REPO) == ROOT
    assert Path(scan_babysitter.REPO) == ROOT


def test_certification_lookup_follows_canonical_evidence_names(tmp_path):
    (tmp_path / "DIRECTORY.md").write_text("# Directory map\n")
    run = tmp_path / "trial-runs" / "example"
    run.mkdir(parents=True)
    evidence = tmp_path / "evidence" / "validation" / "studies"
    evidence.mkdir(parents=True)
    cert = evidence / "atlas-2018-i1676551-c1n2.json"
    cert.write_text('{"verdict": "FAIL"}')
    assert result_pack.find_cert(str(run), "ATLAS_2018_I1676551", "ins1676551") == str(cert)
    # A run-local certificate has precedence over a generic study.
    (run / "outputs").mkdir()
    own = run / "outputs" / "cutflow_cert.json"
    own.write_text('{"verdict": "WARN"}')
    assert result_pack.find_cert(str(run), "ATLAS_2018_I1676551", "ins1676551") == str(own)
