"""Every recorded premise travels with delivered bytes and source identity."""
import hashlib
import json

import pytest

from p07_support import run  # noqa: F401
from ravel.controller import sink


@pytest.mark.parametrize("ending", [False, True])
def test_complete_assumption_appendix_is_delivered_and_verified(run, ending):
    run.complete()
    premises = [
        {"statement": "The supplied scale is exact.", "severity": 1, "controlled": False},
        {"statement": "The selected sample is representative.", "severity": 2, "controlled": True},
        {"statement": "The response law holds across the declared domain.", "severity": 9, "controlled": False}]
    source = run.store.append("assumptions", {"assumptions": premises})
    receipt = sink.bounded_end(run.store, "recorded stopping point") if ending else run.deliver()
    appendix = receipt["assumptions"]
    assert len(appendix) == len(premises)
    report = run.delivered("DELIVERY.md").read_text()
    readable = run.delivered("ASSUMPTIONS.md").read_text()
    structured = json.loads(run.delivered("ASSUMPTIONS.json").read_text())
    assert structured["assumptions"] == appendix
    for index, premise in enumerate(premises):
        row = next(a for a in appendix if a["statement"] == premise["statement"])
        assert row["locator"] == source + "#/assumptions/" + str(index)
        assert row["record_digest"] == run.store.read("assumptions", source)["digest"]
        assert premise["statement"] in report and premise["statement"] in readable
        assert row["locator"] in readable
    for name in ("ASSUMPTIONS.json", "ASSUMPTIONS.md"):
        delivered = next(a for a in receipt["delivery"]["artifacts"] if a["path"] == name)
        assert delivered["sha256"] == hashlib.sha256(run.delivered(name).read_bytes()).hexdigest()
    run.delivered("ASSUMPTIONS.md").write_text("changed appendix")
    assert sink.receipt(run.store)["accepted"] is False


def test_assumptions_travel_with_the_delivered_result_notice(run):
    run.complete()
    run.store.append("assumptions", {"assumptions": ["The declared conversion is exact."]})
    receipt = run.deliver()
    row = next(a for a in receipt["delivery"]["artifacts"] if a["path"].endswith("report.md"))
    notice = run.delivered(row["path"]).read_text()
    assert "The declared conversion is exact." in notice
    assert "ASSUMPTIONS.md" in notice
