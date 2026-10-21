"""Typed CHECK-INs of the analysis route rendered from run state (A06, C03, C04, C14, C10, C36)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from test_p06_support import operator_home  # noqa: F401

from ravel.controller.routes import analysis
from ravel.controller.routes.analysis import checkins
from p09_support import (Store, adopt, adopt_prepare, compile_plan, context, contract, grant, reading,
                              record_outcome, route_analysis)

VIEW_FIELDS = {"run_id", "pins", "sections", "flags", "items", "options", "required_sections", "summary"}


def _ready(tmp_path, *, task_mode="reproduce", **adopt_options):
    store = Store()
    read, con = reading(scan=task_mode == "scan"), contract(task_mode)
    plan = compile_plan("analysis.scan" if task_mode == "scan" else "analysis", read, con)
    plan = analysis.bind(plan, context(store, tmp_path, plan, read, con, adopt_prepare(store, tmp_path, plan,
                                                                                      **adopt_options))) or plan
    states = {s["id"]: {"status": "completed"} for s in plan["steps"] if s["parameters"].get("phase") == "prepare"}
    return store, plan, read, con, states


def _codes(view):
    return {e["code"] for e in view["errors"]}


def test_a06_c03_complete_checkin1_view_renders_every_route_section(tmp_path):
    store, plan, read, con, states = _ready(tmp_path)
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    assert view["errors"] == []
    assert view["variant"] == "reproduction"
    assert view["required_sections"] == ["preamble", "resource_census", "gallery", "figure_target", "method"]
    assert all(s["lines"] for s in view["sections"])
    assert view["pins"]["plan_sha256"] == plan["sha256"]
    assert any(k.startswith("evidence:inputs.census:") for k in view["pins"])
    assert view["bounds"]["rung"] == "full"
    assert view["flags"][0]["text"].startswith("F1:") and view["flags"][0]["kind"] == "assumption"
    # the authority service's checkin.v1 view takes exactly these fields from the route part
    rendered = {"run_id": store.run_id, **{k: view[k] for k in ("pins", "sections", "flags", "items",
                                                                "required_sections", "summary")}}
    assert set(rendered) <= VIEW_FIELDS
    assert not {s["id"] for s in view["sections"]} & {"plan", "flags", "options", "respond"}


def test_a06_c03_checkin1_with_an_empty_required_section_is_refused(tmp_path):
    """A06, C03: the figure gallery and target are empty, so CHECK-IN 1 is not presented."""
    store, plan, read, con, states = _ready(tmp_path, empty="figure_target.json")
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    assert "checkin_content" in _codes(view) or "checkin_section_empty" in _codes(view)
    assert any("(iii)" in e["message"] or "figure_target" in e["message"] for e in view["errors"])


def test_a06_c03_checkin1_with_a_hollow_preamble_is_refused(tmp_path):
    """A06: the plan section carries the cost record; a hollow route analysis empties the preamble."""
    store, plan, read, con, states = _ready(tmp_path, empty="route_analysis.json")
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    assert any("(i)" in e["message"] or "preamble" in e["message"] for e in view["errors"])


def test_a06_checkin1_missing_prepare_evidence_is_refused(tmp_path):
    store, plan, read, con, _ = _ready(tmp_path, skip=("inputs.cost",))
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, {}))
    assert "checkin_evidence_missing" in _codes(view)


def test_c04_c10_checkin1_variant_follows_the_pinned_request(tmp_path):
    """C04: a restricted comparison reference selects reference_withheld; reproduction is refused for it."""
    store = Store()
    read = reading()
    restriction = {"kind": "blinded", "identifiers": {"inspire": ["4242"]}, "origin": "request",
                   "statement": "the published limits of record 4242 stay withheld until delivery",
                   "evidence": [{"start": 0, "end": 8, "text": "withheld"}]}
    con = contract("reproduce", targets={"inspire": ["4242"]}, forbidden_sources=[restriction])
    plan = compile_plan("analysis", read, con)
    states = adopt_prepare(store, tmp_path, plan, withheld=True)
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    assert view["variant"] == "reference_withheld"
    assert "withheld_waypoints" in view["required_sections"] and "gallery" not in view["required_sections"]
    assert not [e for e in view["errors"] if e["row"] in ("C04", "C10")], view["errors"]
    # the same request with published figure material in its waypoint evidence is refused (C10)
    adopt(store, tmp_path, "inputs.figures", "outputs/figure_target.json", {"targets": [
        {"figure_id": "Figure 3", "axes": {"x": "linear", "y": "log"}, "source": "paper-inspection"}]})
    from ravel.controller.routes.analysis import evidence
    figures_step = next(s for s in plan["steps"] if s["id"] == "inputs.figures")
    problems = evidence.figures(figures_step, None, context(store, tmp_path, plan, read, con, states))
    assert "figure_target_withheld" in {e["code"] for e in problems}


def test_c04_invalid_source_restriction_census_holds_checkin1(tmp_path):
    """C04: a variant cannot be selected from a restriction census that does not validate."""
    store = Store()
    read = reading()
    con = contract("reproduce", forbidden_sources=[{"kind": "blinded", "reason": "no statement or evidence"}])
    plan = compile_plan("analysis", read, con)
    states = adopt_prepare(store, tmp_path, plan, withheld=True)
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    assert "source_restrictions_invalid" in _codes(view)


def test_c14_result_sensitive_assumption_without_alternatives_is_refused(tmp_path):
    """C14: a result-sensitive assumption must be a numbered flag with its reason and alternatives."""
    store = Store()
    read, con = reading(), contract("reproduce")
    plan = compile_plan("analysis", read, con)
    states = adopt_prepare(store, tmp_path, plan)
    bad = route_analysis(assumptions=[{"id": "A1", "statement": "The widget decays promptly.", "reason": "",
                                       "alternatives": [], "result_sensitive": True}])
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json", bad)
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    assert "flag_incomplete" in _codes(view)
    assert next(e for e in view["errors"] if e["code"] == "flag_incomplete")["row"] == "C14"


def test_c14_trap_hit_is_carried_as_a_numbered_flag(tmp_path):
    store, plan, read, con, states = _ready(tmp_path)
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    assert any("Trap T8 applies" in f["text"] for f in view["flags"])


def test_a06_scan_checkin1_shows_the_grid(tmp_path):
    store, plan, read, con, states = _ready(tmp_path, task_mode="scan", cost_mode="scan")
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    assert view["errors"] == []
    assert view["required_sections"][-1] == "scan_grid"
    assert view["pins"]["scan_grid_sha256"] == plan["parameters"]["grid"]["sha256"]


def test_c10_checkin2_binds_the_executed_waypoint_evidence(tmp_path):
    store, plan, read, con, states = _ready(tmp_path)
    grant(store, "approve_plan", plan=plan)
    waypoint = next(s for s in plan["steps"] if s["waypoint"])
    adopt(store, tmp_path, waypoint["id"], "outputs/waypoint.json",
          {"summary": "The smoke cutflow agrees.", "element": "first three cutflow rows",
           "expectation": "within ten percent", "evidence": "rows agree within six percent"})
    record_outcome(store, waypoint)
    view = checkins.go(context(store, tmp_path, plan, read, con, states))
    assert view["errors"] == []
    assert any(k.startswith("waypoint_document:") for k in view["pins"]) and "approve_plan" in view["pins"]


def test_c10_checkin2_without_the_ci1_record_or_waypoint_is_refused(tmp_path):
    store, plan, read, con, states = _ready(tmp_path)
    view = checkins.go(context(store, tmp_path, plan, read, con, states))
    assert {"waypoint_evidence_missing", "checkin1_record_missing"} <= _codes(view)


def test_c36_final_checkin_refuses_a_deck_that_drops_unknown_recipe_rows(tmp_path, monkeypatch):
    """C36: the final check-in keeps every unknown recipe ledger row unchanged."""
    store, plan, read, con, states = _ready(tmp_path)
    grant(store, "approve_plan", plan=plan)
    current = {"unknown": [{"id": "R1", "layer": "cards", "status": "unknown"},
                           {"id": "R2", "layer": "run", "status": "unknown"}], "deviated": [], "matched_count": 3}
    monkeypatch.setattr(checkins, "recipe_rows", lambda run_dir: current)
    deck = next(s for s in plan["steps"] if s["id"] == "synthesize")
    adopt(store, tmp_path, deck["id"], "outputs/results.json",
          {"headline": "limit recorded", "numbers": [], "recipe_ledger": {"unknown": current["unknown"][:1]}})
    view = checkins.final(context(store, tmp_path, plan, read, con, states))
    assert "recipe_rows_dropped" in _codes(view)
    adopt(store, tmp_path, deck["id"], "outputs/results.json",
          {"headline": "limit recorded", "numbers": [], "recipe_ledger": current})
    view = checkins.final(context(store, tmp_path, plan, read, con, states))
    assert "recipe_rows_dropped" not in _codes(view)
    assert any("unknown: R2" in line for s in view["sections"] if s["id"] == "recipe_ledger" for line in s["lines"])


def test_a06_checkin1_shows_every_bound_launch_command(tmp_path):
    """A06: a native command bound into the plan before CHECK-IN 1 is shown to the approver, not only pinned."""
    from ravel.controller.routes.analysis import execution
    store, plan, read, con, states = _ready(tmp_path)
    launch = {"argv": ["fictional-native", "--events", "100"], "reads": []}
    bound = execution.bind_launches(plan, {"launches": {"run.full": launch}})
    view = checkins.approve_plan(context(store, tmp_path, bound, read, con, states))
    assert any("fictional-native --events 100" in line for line in view["items"]["steps"])
    assert any("fictional-native --events 100" in line for line in view["legacy"]["sections"]["iv"]["steps"])


def test_a06_figure_target_section_states_no_absent_waypoint(tmp_path):
    """An absent waypoint proposal is not rendered as a 'None' line that fills the figure-target section."""
    store, plan, read, con, states = _ready(tmp_path, empty="waypoint.json")
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    section = next(s for s in view["sections"] if s["id"] == "figure_target")
    assert not any("None" in line for line in section["lines"])
    assert view["errors"]


@pytest.mark.parametrize('body_id', [None, 'body-id-is-not-the-store-id'])
def test_latest_authority_selects_actual_envelope_id_over_signed_body_uid(tmp_path, body_id):
    store, plan, _, _, _ = _ready(tmp_path)
    extra = {'uid': 'signed-body-uid-distinct-from-envelope'}
    if body_id is not None:
        extra['id'] = body_id
    canonical = grant(store, 'approve_plan', plan=plan, **extra)
    assert canonical != extra['uid'] and canonical != body_id
    assert checkins.latest_authority(store, 'approve_plan', plan=plan) == canonical
    assert checkins.latest_authority(store, 'approve_plan') == canonical


def test_latest_authority_retains_canonical_id_through_approved_deviation_chain(tmp_path):
    store, plan, _, _, _ = _ready(tmp_path)
    canonical = grant(store, 'approve_plan', plan=plan, uid='original-body-uid')
    preceding = plan
    for index in (1, 2):
        changed = deepcopy(plan)
        changed['sha256'] = str(index) * 64
        grant(store, 'deviation', plan=changed, uid=f'deviation-body-uid-{index}', subject={'pins': {
            'plan_sha256': changed['sha256'], 'previous_plan_sha256': preceding['sha256'],
            'approve_plan': canonical}})
        assert checkins.latest_authority(store, 'approve_plan', plan=changed) == canonical
        preceding = changed


class _BareAuthorityStore(Store):
    """Exercise the supported body-only scan shape without inventing envelope identity."""
    def scan(self, kind):
        return [entry['record'] for entry in super().scan(kind)]


def test_latest_authority_body_only_scan_uses_canonical_id_when_present(tmp_path):
    _, plan, _, _, _ = _ready(tmp_path)
    store = _BareAuthorityStore()
    canonical = grant(store, 'approve_plan', plan=plan, uid='body-uid')
    store.entries[-1]['record']['id'] = canonical
    assert checkins.latest_authority(store, 'approve_plan', plan=plan) == canonical


def test_latest_authority_body_uid_without_canonical_store_id_grants_no_reference(tmp_path):
    _, plan, _, _, _ = _ready(tmp_path)
    store = _BareAuthorityStore()
    grant(store, 'approve_plan', plan=plan, uid='body-uid-is-not-a-canonical-reference')
    assert checkins.latest_authority(store, 'approve_plan', plan=plan) is None
    assert checkins.latest_authority(store, 'approve_plan') is None


def test_selected_real_store_authority_reference_is_accepted_by_authority_service(tmp_path, operator_home):
    from ravel.controller import authority
    from ravel.controller.store import RunStore
    from test_p06_support import autonomous, view

    _, plan, _, con, _ = _ready(tmp_path / 'plan')
    autonomous()
    store = RunStore.create(tmp_path / 'authority-run', root=tmp_path / 'authority-store',
                            run_id='route-authority-reference')
    authority.freeze_mode(store, con)
    approved = authority.request(store, 'approve_plan', {'view': view(
        store, 'approve_plan', plan_sha256=plan['sha256'])}, {'rung': 'full'})
    assert approved['decision'] == 'approve' and approved['authorizes_effects'] is True
    assert approved['uid'] != approved['id']
    canonical = checkins.latest_authority(store, 'approve_plan', plan=plan)
    verified = authority.verify(store, canonical, kind='approve_plan', subject={'plan_sha256': plan['sha256']})
    assert canonical == approved['id'] == verified['id']
    assert verified['uid'] == approved['uid']


def test_go_document_digest_does_not_replace_the_complete_waypoint_output_subject(tmp_path):
    from ravel.controller import graph
    store, plan, read, con, states = _ready(tmp_path)
    grant(store, "approve_plan", plan=plan)
    waypoint = next(s for s in plan["steps"] if s.get("waypoint"))
    document_sha = adopt(store, tmp_path, waypoint["id"], "outputs/waypoint.json",
          {"summary": "The toy rows agree.", "element": "selected rows",
           "expectation": "one half", "evidence": "50 of 100 unit-weight rows"})
    outputs = [{"artifact": f"{waypoint['id']}:outputs/waypoint.json",
                "path": "outputs/waypoint.json", "sha256": document_sha}]
    observed = record_outcome(store, waypoint, outputs=outputs)
    view = checkins.go(context(store, tmp_path, plan, read, con, states))
    canonical = graph.waypoint_pins(plan["waypoints"], {waypoint["id"]: observed})
    assert view["errors"] == []
    assert not set(canonical).intersection(view["pins"])
    assert view["pins"][f"waypoint_document:{waypoint['id']}"] == document_sha
    assert graph._merge_checkin_pins(canonical, view["pins"])[f"waypoint:{waypoint['id']}"] == canonical[f"waypoint:{waypoint['id']}"]
