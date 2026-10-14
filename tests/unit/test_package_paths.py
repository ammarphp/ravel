"""Path relocation must preserve real workflow discovery and published certification lookup."""
from pathlib import Path

from ravel.workflow import result_pack, scan_babysitter, scan_orchestrator

ROOT = Path(__file__).resolve().parents[2]


def test_scan_tools_resolve_the_checkout_instead_of_the_package_parent():
    assert Path(scan_orchestrator.REPO) == ROOT
    assert Path(scan_babysitter.REPO) == ROOT


def test_certification_lookup_reads_only_the_run_directory(tmp_path):
    (tmp_path / "DIRECTORY.md").write_text("# Directory map\n")
    run = tmp_path / "trial-runs" / "example"
    run.mkdir(parents=True)
    # A certificate outside the run directory is never adopted by name.
    elsewhere = tmp_path / "evidence" / "validation" / "studies"
    elsewhere.mkdir(parents=True)
    (elsewhere / "example-routine.json").write_text('{"verdict": "FAIL"}')
    assert result_pack.find_cert(str(run), "EXAMPLE_ROUTINE", "ins0000000") is None
    (run / "outputs").mkdir()
    own = run / "outputs" / "cutflow_cert.json"
    own.write_text('{"verdict": "WARN"}')
    assert result_pack.find_cert(str(run), "EXAMPLE_ROUTINE", "ins0000000") == str(own)
