"""S1-11: every read of a legacy contract label under src/ravel is classified before schema v2.

Schema-v2 contracts omit ``task_mode``, ``stat_mode``, ``compute_plan`` and ``detector_mode``.
Code that indexes a missing key raises, which fails closed. Code that reads it with ``.get`` sees
``None``, and some of those reads then pass a gate silently. This test enumerates every read site
by AST (``label_read_sites.py``) and requires each to carry one class:

``unreachable-for-v2``
    The site sits behind the version-1 schema or operates only on version-1 text: the v1 contract
    reader that is kept permanently, the router's own v1 output and self-tests.
``fail-closed``
    With the key absent, the site raises, refuses, demands the stricter branch, or only formats
    text. No gate can pass because the label is missing.
``port-before-v2``
    With the key absent, a gate's trigger, requirement or check is skipped. The site must be
    rekeyed on the plan, claims or artifacts before a v2 contract reaches it.

Sites inside ``validate_run_state.evaluate`` are shielded today: ``evaluate`` validates the
contract against the v1 schema before dispatch, so a v2 contract fails there. They are classified
by what they do if the evaluator is reused with the label keys absent, which is the Stage 2 plan.

A new site, or one whose identity changed, fails until a row is added here. A row whose site no
longer exists also fails, so the registry stays exact.
"""
from collections import Counter

from label_read_sites import enumerate_sites

UNREACHABLE, FAIL_CLOSED, PORT = "unreachable-for-v2", "fail-closed", "port-before-v2"
CLASSES = (UNREACHABLE, FAIL_CLOSED, PORT)

REASONS = {
    # unreachable-for-v2
    "v1-schema": "names a required key of the version-1 schema, which a v2 contract never validates against",
    "after-v1-schema": "runs only after the version-1 schema accepted the contract; the v1 reader stays permanently",
    "selftest": "a self-test over fixture v1 contracts",
    "router-v1-output": "reads the v1 contract the router itself just built; the cutover rewrites the router",
    # fail-closed
    "subscript": "indexes the key directly; an absent key raises before any decision",
    "matrix-keyerror": "STAGE_MATRIX[None] raises KeyError when no intake kind supplies the row",
    "report-field": "copies the value into a report or status line; no decision depends on it",
    "message": "formats an error or PASS message only",
    "equality-required": "the gate requires an exact label value, so None refuses",
    "go-required": "None is not a no-CHECK-IN-2 label, so the stricter GO requirement applies",
    "delegation-bound": "None is outside the delegated compute plans, so the machine GO is refused",
    "scan-shortcut": "None loses only the scan attestation shortcut; the per-run artifacts stay required",
    "deviation-overtrigger": "None differs from any artifact stat_mode, so DEVIATIONS.md becomes required (over-triggers; precise port later)",
    "hint-only": "selects suggestion ranking or a status word that still requires admission; no gate",
    "no-handoff": "None yields no handoff step, so the run stops rather than proceeds (S1-04 reads the reading sidecar instead)",
    "cli-enum": "result-pack command-line arguments, validated against the enums; anything else exits",
    "shortcut-denied": "None denies the reviewed finite-calculation shortcut; the general path applies",
    "derived-label": "reads the derived label dict (derived_label.derive or the plan's label), which every reading "
                     "and plan yields in v1 and v2; it is not a contract key",
    # port-before-v2
    "stat-artifact": "selects the statistics artifact and the must-be-absent check; None silently requires exclusion.json and skips the forbidden-statistics check",
    "c2-generation": "None makes the conditional generation stage N/A",
    "c9-statistics": "None makes the no-routine statistics stage optional",
    "route-tbd": "None skips the TBD-judgment escalation FAIL and the uncertified-detector WARN",
    "unsupported-no-compute": "None skips the no-compute check for held intakes (v2 uses boundary rows)",
    "side-by-side": "None drops the reproduce side-by-side requirement on figure targets",
    "mode-consistency": "None skips the artifact/contract statistic consistency check",
    "result-pack-kind": "None skips calculation and research completion and changes the expected deliverables",
    "trigger-lost": "None removes one trigger of the gate (summary, shape fit, scan), so the gate can PASS untriggered",
    "absent-pass": "None returns PASS (not applicable) for the whole gate",
    "variant-open": "None admits every CHECK-IN 1 variant instead of the task's own",
    "uncertified-surface": "None skips the requirement to surface an uncertified detector route at CHECK-IN 1",
    "certificate-not-requested": "None requests no R5 or acceptance certificate for the delivered limit",
    "pilot-not-required": "None reads as not a production parent, so the measured-pilot requirement is skipped",
    "run-scan-skill": "None skips the run-scan skill requirement at the statistics step",
    "stricter-route": "None is not a plain-route label, so the route with the fuller stage and protocol set applies",
    "run-state-copy": "copies the labels into run_state.json, whose None feeds the Stop hook's fail-open run-scan check",
}

# Every site, by identity (see label_read_sites.py), with its class and reason code.
REGISTRY = {
    # Intake Stage 1 (reading, plan, derived label, plan-level pre-authorization)
    'src/ravel/cli.py::_coverage_summary::label.subscript[task_mode]#0': ('fail-closed', 'derived-label'),
    'src/ravel/cli.py::_approve_delegated_plan::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/capability_routing.py::plan::contract.get[task_mode]#2': ('fail-closed', 'hint-only'),
    'src/ravel/workflow/derived_label.py::_refine::structural.subscript[task_mode]#0': ('fail-closed', 'derived-label'),
    'src/ravel/workflow/derived_label.py::floor_row::label.subscript[task_mode]#0': ('fail-closed', 'derived-label'),
    'src/ravel/workflow/derived_label.py::floor_row::label.subscript[task_mode]#1': ('fail-closed', 'derived-label'),
    'src/ravel/workflow/derived_label.py::floor_row::label.subscript[task_mode]#2': ('fail-closed', 'derived-label'),
    'src/ravel/workflow/derived_label.py::derive::label.subscript[task_mode]#0': ('fail-closed', 'derived-label'),
    'src/ravel/workflow/derived_label.py::plan_label::<literal>.literal[task_mode]#0': ('fail-closed', 'derived-label'),
    'src/ravel/workflow/intake.py::open_parent::contract.get[task_mode]#0': ('fail-closed', 'no-handoff'),
    'src/ravel/workflow/route_prompt.py::_decide::label.subscript[task_mode]#0': ('fail-closed', 'derived-label'),
    'src/ravel/workflow/route_prompt.py::_finish::contract.subscript[task_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::_route::decision.subscript[task_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::_selftest_extra::herwig.subscript[task_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/scientific_autonomy.py::_plan_pinned_contract::<literal>.literal[task_mode]#0': ('unreachable-for-v2', 'v1-schema'),
    'src/ravel/cli.py::_summary::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/cli.py::_summary::contract.subscript[task_mode]#1': ('fail-closed', 'subscript'),
    'src/ravel/cli.py::_summary::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/cli.py::_summary::contract.subscript[task_mode]#2': ('fail-closed', 'subscript'),
    'src/ravel/cli.py::_resolve::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/cli.py::_resolve::previous.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/cli.py::_resolve::contract.subscript[task_mode]#1': ('fail-closed', 'subscript'),
    'src/ravel/cli.py::_initiate::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/physics/literal_calculation.py::_capture::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/physics/native_pipeline.py::verify_execution_approval::contract.get[detector_mode]#0': ('fail-closed', 'equality-required'),
    'src/ravel/physics/native_pipeline.py::verify_execution_approval::contract.get[stat_mode]#0': ('fail-closed', 'equality-required'),
    'src/ravel/physics/published_summary.py::validate_requested_summary::parent.get[task_mode]#0': ('fail-closed', 'equality-required'),
    'src/ravel/validation/certificates.py::validate_pack_certificates::contract.get[stat_mode]#0': ('port-before-v2', 'certificate-not-requested'),
    'src/ravel/validation/certificates.py::validate_pack_certificates::contract.get[stat_mode]#1': ('port-before-v2', 'certificate-not-requested'),
    'src/ravel/validation/validate_checkin.py::checkin_variant::contract.get[task_mode]#0': ('port-before-v2', 'variant-open'),
    'src/ravel/validation/validate_checkin.py::validate::contract.get[task_mode]#0': ('fail-closed', 'message'),
    'src/ravel/validation/validate_checkin.py::validate::contract.get[task_mode]#1': ('fail-closed', 'message'),
    'src/ravel/validation/validate_checkin.py::validate::contract.get[task_mode]#2': ('fail-closed', 'message'),
    'src/ravel/validation/validate_checkin.py::validate::contract.get[detector_mode]#0': ('port-before-v2', 'uncertified-surface'),
    'src/ravel/validation/validate_run_state.py::discover_facts::contract.get[task_mode]#0': ('port-before-v2', 'stat-artifact'),
    'src/ravel/validation/validate_run_state.py::discover_facts::contract.get[stat_mode]#0': ('port-before-v2', 'stat-artifact'),
    'src/ravel/validation/validate_run_state.py::required_stages::contract.get[task_mode]#0': ('fail-closed', 'matrix-keyerror'),
    'src/ravel/validation/validate_run_state.py::resolve_level::contract.get[compute_plan]#0': ('port-before-v2', 'c2-generation'),
    'src/ravel/validation/validate_run_state.py::resolve_level::contract.get[stat_mode]#0': ('port-before-v2', 'c9-statistics'),
    'src/ravel/validation/validate_run_state.py::<module>::<literal>.literal[detector_mode]#0': ('port-before-v2', 'route-tbd'),
    'src/ravel/validation/validate_run_state.py::<module>::<literal>.literal[stat_mode]#0': ('port-before-v2', 'route-tbd'),
    'src/ravel/validation/validate_run_state.py::check_route::contract.get[detector_mode]#0': ('port-before-v2', 'route-tbd'),
    'src/ravel/validation/validate_run_state.py::check_route::contract.get[stat_mode]#0': ('port-before-v2', 'route-tbd'),
    'src/ravel/validation/validate_run_state.py::check_route::<literal>.literal[detector_mode]#0': ('port-before-v2', 'route-tbd'),
    'src/ravel/validation/validate_run_state.py::check_route::<literal>.literal[stat_mode]#0': ('port-before-v2', 'route-tbd'),
    'src/ravel/validation/validate_run_state.py::check_route::<literal>.literal[detector_mode]#1': ('port-before-v2', 'route-tbd'),
    'src/ravel/validation/validate_run_state.py::check_route::contract.get[task_mode]#0': ('port-before-v2', 'unsupported-no-compute'),
    'src/ravel/validation/validate_run_state.py::check_figure_contract::contract.get[task_mode]#0': ('port-before-v2', 'side-by-side'),
    'src/ravel/validation/validate_run_state.py::check_figure_contract::contract.get[task_mode]#1': ('fail-closed', 'message'),
    'src/ravel/validation/validate_run_state.py::check_generation::contract.get[task_mode]#0': ('fail-closed', 'scan-shortcut'),
    'src/ravel/validation/validate_run_state.py::check_generation::contract.get[task_mode]#1': ('fail-closed', 'scan-shortcut'),
    'src/ravel/validation/validate_run_state.py::check_analysis::contract.get[task_mode]#0': ('fail-closed', 'scan-shortcut'),
    'src/ravel/validation/validate_run_state.py::check_statistics::contract.get[stat_mode]#0': ('port-before-v2', 'mode-consistency'),
    'src/ravel/validation/validate_run_state.py::check_statistics::doc.get[stat_mode]#0': ('port-before-v2', 'mode-consistency'),
    'src/ravel/validation/validate_run_state.py::check_result_pack::contract.get[task_mode]#0': ('port-before-v2', 'result-pack-kind'),
    'src/ravel/validation/validate_run_state.py::check_result_pack::contract.get[task_mode]#1': ('port-before-v2', 'result-pack-kind'),
    'src/ravel/validation/validate_run_state.py::check_result_pack::contract.get[task_mode]#2': ('port-before-v2', 'result-pack-kind'),
    'src/ravel/validation/validate_run_state.py::inv_resource_census_before_route::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/validation/validate_run_state.py::inv_trap_sweep_recorded::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/validation/validate_run_state.py::inv_basis_manifest_before_comparison::contract.get[task_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/validation/validate_run_state.py::inv_figure_contract_fulfilled::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/validation/validate_run_state.py::inv_r5_before_limit::contract.get[stat_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/validation/validate_run_state.py::inv_likelihood_pairing::contract.get[stat_mode]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_blocked_shape_fit_refusal_recorded::contract.get[stat_mode]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_deviations_on_change::doc.get[stat_mode]#0': ('fail-closed', 'deviation-overtrigger'),
    'src/ravel/validation/validate_run_state.py::inv_deviations_on_change::doc.get[stat_mode]#1': ('fail-closed', 'deviation-overtrigger'),
    'src/ravel/validation/validate_run_state.py::inv_deviations_on_change::contract.get[stat_mode]#0': ('fail-closed', 'deviation-overtrigger'),
    'src/ravel/validation/validate_run_state.py::inv_param_validated_before_scan::contract.get[task_mode]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_ladder_order::contract.get[compute_plan]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_ladder_order::contract.get[compute_plan]#1': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_ladder_order::contract.get[task_mode]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_certify_before_limit::contract.get[stat_mode]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_certify_before_limit::contract.get[stat_mode]#1': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_certify_before_limit::contract.get[task_mode]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_trap_obligations::contract.get[task_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/validation/validate_run_state.py::inv_approval_before_compute::contract.get[compute_plan]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_approval_before_compute::contract.get[compute_plan]#1': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_checkin2_go_before_bulk_compute::contract.get[task_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/validation/validate_run_state.py::inv_checkin2_go_before_bulk_compute::contract.get[task_mode]#1': ('port-before-v2', 'trigger-lost'),
    'src/ravel/validation/validate_run_state.py::inv_cost_preflight_recorded::contract.get[compute_plan]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::inv_cost_preflight_recorded::contract.get[compute_plan]#1': ('port-before-v2', 'absent-pass'),
    'src/ravel/validation/validate_run_state.py::evaluate::fields.get[task_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/validation/validate_run_state.py::evaluate::fields.get[stat_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/validation/validate_run_state.py::evaluate::fields.get[compute_plan]#0': ('fail-closed', 'report-field'),
    'src/ravel/validation/validate_run_state.py::evaluate::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/validation/validate_run_state.py::evaluate::contract.subscript[task_mode]#1': ('fail-closed', 'subscript'),
    'src/ravel/validation/validate_run_state.py::evaluate::contract.subscript[task_mode]#2': ('fail-closed', 'subscript'),
    'src/ravel/validation/validate_run_state.py::evaluate::contract.get[stat_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/validation/validate_run_state.py::evaluate::contract.get[compute_plan]#0': ('fail-closed', 'report-field'),
    'src/ravel/validation/validate_run_state.py::backfill_plan::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/validation/validate_run_state.py::print_human::result.subscript[task_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/validation/validate_run_state.py::print_human::result.subscript[stat_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/validation/validate_run_state.py::print_human::result.subscript[compute_plan]#0': ('fail-closed', 'report-field'),
    'src/ravel/validation/validate_task_contract.py::<module>::<literal>.literal[task_mode]#0': ('unreachable-for-v2', 'v1-schema'),
    'src/ravel/validation/validate_task_contract.py::<module>::<literal>.literal[detector_mode]#0': ('unreachable-for-v2', 'v1-schema'),
    'src/ravel/validation/validate_task_contract.py::<module>::<literal>.literal[stat_mode]#0': ('unreachable-for-v2', 'v1-schema'),
    'src/ravel/validation/validate_task_contract.py::<module>::<literal>.literal[compute_plan]#0': ('unreachable-for-v2', 'v1-schema'),
    'src/ravel/validation/validate_task_contract.py::validate::c.subscript[task_mode]#0': ('unreachable-for-v2', 'after-v1-schema'),
    'src/ravel/validation/validate_task_contract.py::validate::c.subscript[stat_mode]#0': ('unreachable-for-v2', 'after-v1-schema'),
    'src/ravel/validation/validate_task_contract.py::validate::c.subscript[compute_plan]#0': ('unreachable-for-v2', 'after-v1-schema'),
    'src/ravel/validation/validate_task_contract.py::validate::c.subscript[detector_mode]#0': ('unreachable-for-v2', 'after-v1-schema'),
    'src/ravel/validation/validate_task_contract.py::validate::c.subscript[detector_mode]#1': ('unreachable-for-v2', 'after-v1-schema'),
    'src/ravel/validation/validate_task_contract.py::selftest::<literal>.literal[task_mode]#0': ('unreachable-for-v2', 'selftest'),
    'src/ravel/validation/validate_task_contract.py::main::contract.subscript[task_mode]#0': ('unreachable-for-v2', 'after-v1-schema'),
    'src/ravel/validation/validate_task_contract.py::main::contract.subscript[detector_mode]#0': ('unreachable-for-v2', 'after-v1-schema'),
    'src/ravel/validation/validate_task_contract.py::main::contract.subscript[stat_mode]#0': ('unreachable-for-v2', 'after-v1-schema'),
    'src/ravel/validation/validate_task_contract.py::main::contract.subscript[compute_plan]#0': ('unreachable-for-v2', 'after-v1-schema'),
    'src/ravel/workflow/calculation_completion.py::completion_route::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/calculation_completion.py::_evaluate_scientific_parent::current.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/calculation_completion.py::_evaluate_scientific_parent::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/calculation_completion.py::_evaluate_scientific_parent::contract.subscript[stat_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/calculation_completion.py::collect::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/calculation_completion.py::evaluate_parent::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/calculation_completion.py::evaluate_parent::contract.subscript[stat_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/calculation_completion.py::evaluate_parent::contract.subscript[compute_plan]#1': ('fail-closed', 'subscript'),
    'src/ravel/workflow/calculation_completion.py::evaluate_parent::contract.subscript[stat_mode]#1': ('fail-closed', 'subscript'),
    'src/ravel/workflow/capability_routing.py::plan::contract.get[task_mode]#0': ('fail-closed', 'hint-only'),
    'src/ravel/workflow/capability_routing.py::plan::contract.get[task_mode]#1': ('fail-closed', 'hint-only'),
    'src/ravel/workflow/current_state.py::build_packet::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/current_state.py::build_packet::contract.subscript[task_mode]#1': ('fail-closed', 'subscript'),
    'src/ravel/workflow/current_state.py::build_packet::contract.subscript[stat_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/current_state.py::build_packet::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/current_state.py::build_packet::contract.subscript[task_mode]#2': ('fail-closed', 'subscript'),
    'src/ravel/workflow/generation_efficiency.py::_production_parent::contract.get[compute_plan]#0': ('port-before-v2', 'pilot-not-required'),
    'src/ravel/workflow/intake.py::handoff_applicable::contract.get[task_mode]#0': ('fail-closed', 'no-handoff'),
    'src/ravel/workflow/intake.py::handoff_route::contract.get[task_mode]#0': ('fail-closed', 'no-handoff'),
    'src/ravel/workflow/intake.py::execution_handoff::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/intake.py::execution_handoff::contract.subscript[task_mode]#1': ('fail-closed', 'subscript'),
    'src/ravel/workflow/launch_authorization.py::_capture::contract.get[task_mode]#0': ('fail-closed', 'go-required'),
    'src/ravel/workflow/launch_authorization.py::_historical_scoped::contract.get[task_mode]#0': ('fail-closed', 'equality-required'),
    'src/ravel/workflow/launch_authorization.py::_historical_errors::contract.get[task_mode]#0': ('fail-closed', 'go-required'),
    'src/ravel/workflow/launch_authorization.py::_historical_errors::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/result_pack.py::build_result::args.attribute[stat_mode]#0': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::build_result::args.attribute[detector_mode]#0': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::build_result::args.attribute[detector_mode]#1': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::main::result.subscript[stat_mode]#0': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::main::result.subscript[stat_mode]#1': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::main::result.subscript[detector_mode]#0': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::main::result.subscript[detector_mode]#1': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::main::result.subscript[stat_mode]#2': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::main::result.subscript[detector_mode]#2': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/route_prompt.py::_selftest_extra::c.subscript[stat_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::_selftest_extra::hinted.subscript[stat_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::_selftest_extra::c.subscript[stat_mode]#1': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::selftest::c.subscript[task_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::selftest::c.subscript[compute_plan]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::selftest::c.subscript[task_mode]#1': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::selftest::c.subscript[compute_plan]#1': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::selftest::c.subscript[stat_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::selftest::c.subscript[task_mode]#2': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::selftest::c.subscript[compute_plan]#2': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::main::contract.subscript[task_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::main::contract.subscript[detector_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::main::contract.subscript[stat_mode]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/route_prompt.py::main::contract.subscript[compute_plan]#0': ('unreachable-for-v2', 'router-v1-output'),
    'src/ravel/workflow/scoped.py::plan::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/scoped.py::verify_plan::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/scoped.py::verify_plan::contract.subscript[task_mode]#1': ('fail-closed', 'subscript'),
    'src/ravel/workflow/scoped.py::evaluate::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/scoped.py::evaluate::contract.subscript[task_mode]#1': ('fail-closed', 'subscript'),
    'src/ravel/workflow/scoped.py::evaluate::contract.subscript[task_mode]#2': ('fail-closed', 'subscript'),
    'src/ravel/workflow/scoped.py::evaluate::contract.subscript[task_mode]#3': ('fail-closed', 'subscript'),
    'src/ravel/workflow/scoped.py::evaluate::contract.subscript[task_mode]#4': ('fail-closed', 'subscript'),
    'src/ravel/workflow/scoped.py::evaluate::contract.subscript[stat_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/scoped.py::evaluate::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/stop_dispatch.py::branch_skill_coverage::rs.get[task_mode]#0': ('port-before-v2', 'run-scan-skill'),
    'src/ravel/workflow/task_completion.py::_reviewed_finite_calculation::contract.get[task_mode]#0': ('fail-closed', 'shortcut-denied'),
    'src/ravel/workflow/workflow_state.py::new_state::contract.get[task_mode]#0': ('port-before-v2', 'run-state-copy'),
    'src/ravel/workflow/workflow_state.py::new_state::contract.get[stat_mode]#0': ('port-before-v2', 'run-state-copy'),
    'src/ravel/workflow/workflow_state.py::new_state::contract.get[detector_mode]#0': ('port-before-v2', 'run-state-copy'),
    'src/ravel/workflow/workflow_state.py::new_state::contract.get[compute_plan]#0': ('port-before-v2', 'run-state-copy'),
    'src/ravel/workflow/workflow_state.py::cmd_init::state.subscript[task_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/workflow/workflow_state.py::cmd_init::state.subscript[compute_plan]#0': ('fail-closed', 'report-field'),
    'src/ravel/workflow/workflow_state.py::_verify_approval_record::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/workflow_state.py::_verify_approval_record::contract.subscript[compute_plan]#1': ('fail-closed', 'subscript'),
    'src/ravel/workflow/workflow_state.py::_verify_approval_record::contract.get[task_mode]#0': ('fail-closed', 'go-required'),
    'src/ravel/workflow/workflow_state.py::record_delegated_go::contract.get[compute_plan]#0': ('fail-closed', 'delegation-bound'),
    'src/ravel/workflow/workflow_state.py::cmd_status::state.get[task_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/workflow/workflow_state.py::cmd_status::state.get[compute_plan]#0': ('fail-closed', 'report-field'),
    'src/ravel/workflow/workflow_state.py::selftest::state.subscript[task_mode]#0': ('unreachable-for-v2', 'selftest'),
    # Sites added after the first classification (reading-plan, completion, research launch and protocol)
    'src/ravel/cli.py::_native_approve::load_contract(contract_path).subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/cli.py::_native_approve::load_contract(path).subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/physics/native_pipeline.py::require_claim_inputs::record.get[task_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/validation/certification_tolerances.py::_requires_section::contract.get[stat_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/validation/validate_run_state.py::evaluate::contract.subscript[task_mode]#3': ('fail-closed', 'subscript'),
    'src/ravel/workflow/completion_children.py::specification::doc.get[task_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/workflow/completion_children.py::specification::doc.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/completion_lifecycle.py::evaluate_parent::contract.get[task_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/workflow/completion_lifecycle.py::evaluate_parent::contract.subscript[task_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/completion_lifecycle.py::evaluate_parent::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/completion_lifecycle.py::evaluate_parent::contract.subscript[stat_mode]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/completion_lifecycle.py::summary_invariant::contract.get[task_mode]#0': ('port-before-v2', 'absent-pass'),
    'src/ravel/workflow/host_gate.py::launch_errors::contract.subscript[compute_plan]#0': ('fail-closed', 'subscript'),
    'src/ravel/workflow/method_selection.py::scientific_plan::document.get[compute_plan]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/workflow/research_launch.py::_evaluators::contract.get[stat_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/workflow/research_launch.py::_evaluators::contract.get[detector_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/workflow/research_launch.py::_evaluators::contract.get[task_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/workflow/research_launch.py::derive::contract.get[task_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/workflow/research_launch.py::derive_campaign::original.get[task_mode]#0': ('fail-closed', 'report-field'),
    'src/ravel/workflow/research_protocol.py::precision_required::<literal>.literal[task_mode]#0': ('port-before-v2', 'trigger-lost'),
    'src/ravel/workflow/research_protocol.py::_route::contract.get[task_mode]#0': ('fail-closed', 'stricter-route'),
    'src/ravel/workflow/research_protocol.py::route_applicability::run_contract(root).get[compute_plan]#0': ('fail-closed', 'stricter-route'),
    'src/ravel/workflow/result_pack.py::main::args.attribute[detector_mode]#0': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::main::args.attribute[detector_mode]#1': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::main::args.attribute[detector_mode]#2': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/result_pack.py::main::args.attribute[detector_mode]#3': ('fail-closed', 'cli-enum'),
    'src/ravel/workflow/stage_supervisor.py::supervise::authorization_plan.get[compute_plan]#0': ('port-before-v2', 'trigger-lost'),
}

# Sites the intake architecture names as fail-open; they must stay marked for porting.
NAMED_FAIL_OPEN = (
    "src/ravel/validation/validate_run_state.py::inv_certify_before_limit::contract.get[stat_mode]#0",
    "src/ravel/validation/certificates.py::validate_pack_certificates::contract.get[stat_mode]#1",
    "src/ravel/workflow/stop_dispatch.py::branch_skill_coverage::rs.get[task_mode]#0",
)


def test_every_label_read_site_is_classified():
    sites = enumerate_sites()
    current = {s["id"]: s for s in sites}
    unclassified = [f"{sid} (line {current[sid]['line']})" for sid in current if sid not in REGISTRY]
    stale = sorted(set(REGISTRY) - set(current))
    assert not unclassified, (
        "label reads with no v2 classification; add a REGISTRY row (unreachable-for-v2, fail-closed "
        "or port-before-v2) with a reason:\n  " + "\n  ".join(unclassified))
    assert not stale, "REGISTRY rows whose site no longer exists:\n  " + "\n  ".join(stale)


def test_registry_rows_are_well_formed():
    bad = [sid for sid, (cls, why) in REGISTRY.items() if cls not in CLASSES or why not in REASONS]
    assert not bad, bad
    unused = set(REASONS) - {why for _, why in REGISTRY.values()}
    assert not unused, f"reason codes used by no row: {sorted(unused)}"


def test_named_fail_open_sites_are_marked_for_porting():
    for sid in NAMED_FAIL_OPEN:
        assert REGISTRY.get(sid, (None,))[0] == PORT, sid
    # Each invariant that returns PASS when its label is absent is a porting obligation.
    absent_pass = {sid.split("::")[1] for sid, (cls, why) in REGISTRY.items() if why == "absent-pass"}
    assert {"inv_certify_before_limit", "inv_likelihood_pairing", "inv_ladder_order",
            "inv_approval_before_compute", "inv_cost_preflight_recorded"} <= absent_pass


def test_enumeration_covers_every_read_form(tmp_path):
    pkg = tmp_path / "src" / "ravel"
    pkg.mkdir(parents=True)
    (pkg / "probe.py").write_text(
        "def f(c, a):\n"
        "    c['task_mode']\n"
        "    c.get('stat_mode')\n"
        "    getattr(a, 'compute_plan')\n"
        "    a.detector_mode\n"
        "    'task_mode' in c\n"
        "    c['stat_mode'] = 1\n"
        "    return {'compute_plan': 1}\n")
    found = sorted((s["accessor"], s["key"]) for s in enumerate_sites(pkg))
    assert found == [("attribute", "detector_mode"), ("get", "stat_mode"), ("getattr", "compute_plan"),
                     ("literal", "task_mode"), ("subscript", "task_mode")]


def test_classification_summary_is_reported(capsys):
    counts = Counter(cls for cls, _ in REGISTRY.values())
    print({cls: counts[cls] for cls in CLASSES})
    assert counts[PORT] >= len(NAMED_FAIL_OPEN)
