"""A small command surface over the existing intake, validation and audit engines."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from . import __version__, validate_task_contract
from .validation.validate_task_contract import SCHEMA, load_contract
from .paths import repository_root


# Focused modules own their complete subcommands and error messages. Scientific
# execution remains in plan/approve/run; these commands inspect evidence or
# preserve explicitly requested advisory artifacts.
FOCUSED_COMMANDS = {
    'study-grid': ('workflow.study_grid', 'submit, observe, resume and harvest finite prepared-study grids'),
    'doctor': ('setup.doctor', 'check that every required tool is installed and give the exact fix for each problem'),
    'research-orchestrate': ('workflow.research_orchestrator', 'durable default design/review/evidence/ordinary-execution research coordination'),
    'agentrivet-construction': ('workflow.agentrivet_construction', 'connect original source-bound paper roles, ordinary build/event feedback and independent whole-task closure'),
    'rivet-hepdata-map': ('physics.hepdata_table_map', 'build a HEPData table map and reference YODA from a record, or check a routine source\'s bookings against it'),
    'intake-plan': ('workflow.intake_planner', 'prepare original-goal bounded designer Graph and unapproved ordinary study or reviewed source work'),
    'site-workflow': ('workflow.site_workflow', 'source-bound site reproducibility export; existing ordinary approvals and research-cycle authority remain required'),
    'backend': ('workflow.execution_backend', 'execution backends (native, container, HTCondor/SLURM): doctor, plans, handles, recovery, images'),
    'partitions': ('workflow.partitioned_execution', 'split an input population into partitions, run them through a backend and merge additive outputs'),
    'site': ('workflow.site_doctor', 'Linux analysis-site readiness checks and no-root install plan'),
    'ntuples': ('physics.dataset_resolution', 'expand container datasets, resolve file members and normalize MC from declared inputs'),
    'root-stream': ('physics.root_stream', 'inspect explicit complete ROOT member/DSID/weight/blinding contracts; execution uses ordinary science'),
    'tree-array-export': ('physics.tree_array_export', 'inspect the source-bound mini-tree array export with its fixed inputs and handoff (not a general exporter); execution uses ordinary science'),
    'parameter-space-sampling': ('physics.parameter_space_sampling', 'inspect supplied scan contracts; execution uses ordinary science'),
    'figure': ('physics.figure_comparison', 'digitise published figures and draw parameter-plane and measurement overlays with natural-language labels'),
    'compare': ('validation.fidelity', 'compare a result with a reference under declared transformations, metrics and tolerances'),
    'dataset-query-quantities': ('physics.dataset_query_quantities', 'inspect the source-bound columnar adapter for its stored released questions (general columnar work: columnar-analysis); execution uses ordinary science'),
    'columnar-analysis': ('physics.columnar_analysis', 'check event files and recipes for reconstructed-event analysis, run partitions and draw control plots; studies use ordinary science'),
    'event-production': ('physics.event_production', 'check a shower and detector production task, read an LHE header and check a production receipt; production runs through ordinary science'),
    'detector-card': ('physics.detector_card', 'check a Delphes card against the model\'s invisible states and write a managed derived or skimmed card'),
    'output-gate': ('workflow.output_gate', 'check a finished stage\'s outputs against their contracts and its log against error markers'),
    'root-schema': ('physics.root_schema', 'inspect ROOT trees and branches read-only and draft a branch and weight contract'),
    'authored-analysis': ('physics.authored_analysis', 'lint, pin, run in a sandbox and repair attempts of an approved authored analysis step'),
    'mssm-physical-map': ('physics.mssm_observable_map', 'inspect full source-bound MSSM spectrum/lifetime grids or prepare an ordinary supplied LLP recipe'),
    'model-conventions': ('physics.nmssm_yukawa_map', 'show finite released NMSSM spectrum convention context; execution uses ordinary plan/run'),
    "resonance-study": ("workflow.resonance_study", "compile whole resonance hypotheses into ordinary search studies and preserve separate constraints"),
    'research-tools': ('workflow.research_tools', 'connect source API context, concrete experiment planning and ordinary tool recovery'),
    'research-protocol': ('workflow.research_protocol', 'bind staged research protocols and prepare scoped ordinary comparison studies'),
    'chargino-decay-table': ('physics.chargino_decay_table', 'prepare exact released pure-limit decay table with complete row and daughter census'),
    'model-spectrum': ('workflow.model_spectrum_plan', 'prepare released named-model spectrum or explicit accepted-spectrum UFO/card handoff'),
    'model-events': ('workflow.model_event_plan', 'prepare an explicit source-bound generation/decay/matching/multiweight ordinary plan'),
    'generation-efficiency': ('workflow.generation_efficiency', 'prepare bounded same-process pilots, inspect failed costs, and create current empirical forecasts'),
    'pilot-cost': ('workflow.pilot_cost', 'measure completed approved pilots and forecast a larger run; the record approval accepts comes from cost_preflight --from-forecast'),
    'lhe-transform': ('physics.lhe_transform', 'check LHE particle-rewrite rules and count their matches; applying them is a science study or part of approved generation'),
    'spec-reconcile': ('workflow.spec_reconciliation', 'compare a declared physics intent with MadGraph proc, run and parameter cards (read only)'),
    'research-cycle': ('workflow.research_cycle', 'connect bounded hypotheses, ordinary studies, reviews and reproducible synthesis'),
    'backend-provider': ('physics.backend_provider', 'discover backend source catalogues and prepare native input contracts'),
    'checkmate-events': ('physics.checkmate_events', 'prepare a source-bound supplied-HepMC2 ordinary study'),
    'task-completion': ('workflow.task_completion', 'inspect original-task coverage or require bound whole-parent acceptance'),
    'fill-template': ('workflow.result_templates', 'fill a supplied numeric result template from an accepted result without changing its bins'),
    'contur-yoda': ('physics.contur_yoda', 'prepare a source-bound fresh Contur single-YODA ordinary study'),
    'contur-companion': ('physics.contur_companion', 'prepare released SM tests, Herwig extraction and native Contur plots'),
    'review': ('workflow.physics_review', 'open, critique, correct and recheck a bounded physics decision'),
    'judgment': ('workflow.scientific_judgment', 'dispatch fresh scoped physics roles, audit justification and return controlled repairs to work'),
    'diagnose': ('workflow.diagnostic_plan', 'evaluate a frozen controlled-experiment contract'),
    'decision-case': ('workflow.decision_case', 'check an evidence-linked scientific decision graph'),
    'review-context': ('workflow.review_context', 'prepare and read role-specific evidence packets'),
    'failed-review': ('workflow.failed_stage_review', 'retain actual failed-stage diagnostic premises without acceptance'),
    'hypothesis-board': ('workflow.hypothesis_board', 'preserve blind advisory hypotheses and falsifiers'),
    'experiment-allocator': ('workflow.experiment_allocator', 'recommend a bounded advisory experiment allocation'),
    'evidence-independence': ('workflow.evidence_independence', 'inspect evidence lineage without assuming independent support'),
    'numerical-witness': ('validation.numerical_witness', 'derive or independently check supplied numerical evidence'),
    'analysis-witness': ('validation.analysis_witness', 'independently check a retained typed-analysis bundle'),
    'sfitter-observed-events': ('physics.sfitter_observed_events', 'acquire complete source-joined event/bin observations and explicit sampling covariance for SFitter'),
    'sfitter-workflow': ('workflow.sfitter_workflow', 'prepare source-bound SFitter specialist phases and exact scientific handoffs'),
    'sfitter-review': ('workflow.sfitter_review_protocol', 'recompute SFitter concern evidence, prepare actual judgment roles and return send-back to its owning phase'),
    'agent-graph': ('workflow.agent_graph', 'run bounded hosted research tasks with retained scheduling and custody'),
    'model-portfolio': ('physics.reinterpret_db', 'prepare a source-bound simplified-model portfolio study'),
    'model-tool-bridge': ('physics.model_tool_bridge', 'prepare a bounded supplied-UFO matrix-element study'),
    'symbolic-evaluation': ('physics.symbolic_evaluation', 'inspect source-bound symbolic execution inputs'),
    'feyn-graph': ('physics.feyn_graph', 'inspect complete model-bound diagram enumeration'),
    'diagram-analysis': ('physics.diagram_analysis', 'inspect source-matched NDA/EDA diagram consumers'),
    'feynarts-amplitude': ('physics.feynarts_amplitude', 'prepare explicit FeynArts/FeynCalc amplitude source'),
    'model-provider-bridge': ('physics.model_provider_bridge', 'prepare a bounded native scientific-provider qualification'),
    'model-derivation-bridge': ('physics.model_derivation_bridge', 'prepare a source-bound model derivation or qualify accepted output reuse'),
    'inference': ('physics.inference.cli', 'check inference documents (prescribed statistics, morphing, formulas, search and measurement likelihoods) and write their study specification'),
    'model': ('physics.model_authoring', 'author a FeynRules model from a ModelSpec or template, lint it, run two-gauge checks and check the UFO'),
    'xsec': ('physics.cross_sections', 'look up a published cross section under an explicit order, PDF and scale convention'),
    'simplified-spectrum': ('physics.simplified_spectrum', 'write an SLHA2 card from a declared simplified-model spectrum and check decay closure'),
    'lineshape': ('physics.resonance_lineshape', 'evaluate leading-order partial widths, propagator schemes and width consistency'),
    'normalization': ('physics.native_normalization', 'reconcile generator cross sections, or derive branching and filter factors (factors)'),
    'normalization-ledger': ('physics.normalization_ledger', 'check every normalization factor and recompute delivered yields'),
    'amplitudes': ('physics.amplitude_cli', 'check amplitude-basis documents (integration, predictions, weighted events, cross-checks) and write their study specification'),
    'export-submission': ('workflow.submission_export', 'write and verify a relocatable submission package of an accepted analysis'),
    'agent-audit': ('workflow.agent_audit', 'build per-prompt audit logs from named agent transcripts and session hooks'),
    'agent-surface': ('workflow.agent_surface', "install RAVEL's skills, hooks and rules into another project and write software skills"),
    'agent-cli': ('workflow.cli_agent_host', 'answer RAVEL model requests with a fresh Claude Code or Codex CLI session'),
    'note-profile': ('workflow.note_profile', 'check a page-limited note rule pack and write its formatting contract'),
    'reco-ntuple': ('physics.reco_ntuple_routine', 'check a reconstructed-ntuple format descriptor for native routine runs; studies use ordinary science'),
    "knowledge": ("workflow.knowledge", "Query and check the generated knowledge atlas"),
    "modes": ("workflow.knowledge", "List, show and retrieve examples for registered science modes"),
    'transport': ('workflow.transport_registry', 'list, show and probe the declared model transports (CLI, HTTP, RAVEL loop, relay)'),
    'rdj': ('workflow.rdj_loop', 'decision justification for gated actions: next challenges, answers, status, cases, authorization by code'),
    'procedure': ('workflow.procedure_export', 'export a source-bound procedure note and Snakemake workflow'),
    'env': ('workflow.env_snapshot', 'capture a content-addressed environment or compare snapshots'),
    'graph': ('workflow.graph_substrate', 'run, observe, answer and drain registered agent graphs (graph run|status|stop|respond|events|list)'),
    'check:event_accounting': ('validation.event_accounting', 'reconcile event counts and signed moments under declared transformations'),
    'gate': ('workflow.host_gate', 'host-neutral gate verdict for a run and an action or tool call (hosts without hooks)'),
    'stage': ('workflow.stage_supervisor', 'run one approved pipeline stage under supervision'),
    'cost': ('workflow.cost_preflight', 'size compute before spending it and write the cost preflight record'),
    'trap-sweep': ('workflow.trap_sweep', 'write or check the physics trap sweep of a run'),
    'work': ('workflow.work_dispatch', 'check complete work-order obligations and adopt exact nonempty output bytes'),
    'lease': ('workflow.machine_lease', 'the machine lease: holder, read-only preflight of earlier jobs\' live processes, operator fence clearing'),
}

# Supplied-contract inspection command block.
FOCUSED_COMMANDS['tree-array-export'] = ('physics.tree_array_export', 'inspect supplied tree branches, shapes, padding and array destinations; execution uses ordinary science')
FOCUSED_COMMANDS['dataset-query-quantities'] = ('physics.dataset_query_quantities', 'inspect supplied datasets, queries, observables and presentation contracts; execution uses ordinary science')


# Lifecycle governance commands over modules whose entry points need an adapter: a required
# sub-command word, a main() that reads sys.argv, or a module error class. (command:
# (module, required sub-command or None, error class name or None, description))
LIFECYCLE_COMMANDS = {
    'lifecycle': ('validation.validate_run_state', 'check', None, 'check a run against the lifecycle state machine and invariants'),
    'checkin': ('validation.validate_checkin', 'validate', None, 'validate a CHECK-IN deck'),
    'result-pack': ('workflow.result_pack', None, 'PackError', 'assemble result.json and figures.json; refuses raw launches and failed delivery checks'),
    'scan': ('workflow.scan_orchestrator', None, None, 'plan, launch, monitor and assemble a parameter scan'),
    'certify': ('validation.certify_acceptance', None, None, 'certify acceptance times efficiency against published values'),
}



# Worker lifecycle registration (module owns its subcommands).
FOCUSED_COMMANDS['work'] = ('workflow.agent_worker', 'dispatch sandboxed workers and inspect broker receipts, recovery and stop state')
# G8 agent call-site conformance.
FOCUSED_COMMANDS['release'] = ('validation.check_agent_paths', 'release gate records (release check --gate G8)')

def released_commands():
    """Keep development dispatch intact while showing the released commands."""
    for name, entry in FOCUSED_COMMANDS.items():
        if not (isinstance(entry, tuple) and len(entry) == 2 and all(isinstance(part, str) for part in entry)):
            raise ValueError(f"malformed focused command registry entry: {name}")
    from ravel.setup import manifest as mf
    if mf.manifest_path().is_file():
        manifest = mf.load()[0]
        return {name: entry for name, entry in FOCUSED_COMMANDS.items()
                if not mf.release_mentions(manifest, [name, entry[1]])}
    from ravel.workflow.knowledge import load_atlas
    ids = {row['id'] for row in load_atlas()['entries']}
    return {name: entry for name, entry in FOCUSED_COMMANDS.items() if 'cmd:' + name in ids}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ravel", description=__doc__)
    ap.add_argument("--version", action="version", version=f"ravel-hep {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    for command, (_, description) in released_commands().items():
        sub.add_parser(command, help=description)
    correction = sub.add_parser('science-correct', help='materialize and admit a prospectively bounded scientific correction')
    correction.add_argument('--rundir', type=Path, required=True)
    correction.add_argument('--request', type=Path, required=True,
                            help='explicit decider correction request JSON; never launches computation')
    initiate = sub.add_parser("initiate", help="draft an intake contract and empty run ledger; never runs compute")
    request = initiate.add_mutually_exclusive_group()
    request.add_argument("--prompt", help="physics request to interpret as a draft")
    request.add_argument("--prompt-file", type=Path, help="UTF-8 file containing the physics request")
    request.add_argument("--resolve", type=Path, metavar="HELD_RUN",
                         help="resolve a held or pre-CHECK-IN 1 draft intake in place; requires --interpretation")
    initiate.add_argument("--out", type=Path,
                          help="new run directory; existing paths are never overwritten")
    initiate.add_argument("--interpretation", type=Path,
                          help="host-agent interpretation JSON with exact request hash and evidence spans")
    initiate.add_argument("--session-id", default=None,
                          help="host session id to record and register (default: RAVEL_SESSION_ID or the host's variable)")
    status = sub.add_parser("status", help="derive a compact current-state packet from live artifacts")
    status.add_argument("--rundir", type=Path, required=True)
    status.add_argument("--write", action="store_true", help="also refresh current_state.json")
    status.add_argument("--notification-command", type=json.loads, help="Optional JSON argv for wait notifications; receives only run path and one-line reason")
    status.add_argument("--retained-study", action="store_true", help="inspect an immutable initial study using its original commitments and the current review reader; never grants computation")
    plan = sub.add_parser("plan", help="prepare a concrete scoped or supplied-data scientific CHECK-IN 1; no compute")
    plan.add_argument("--rundir", type=Path, required=True)
    plan.add_argument("--spec", type=Path, required=True, help="strict scoped specification JSON")
    approve = sub.add_parser("approve", help="record assent bound to a concrete scoped CHECK-IN 1")
    approve.add_argument("--rundir", type=Path, required=True)
    assent=approve.add_mutually_exclusive_group(required=True)
    assent.add_argument("--quote", help="actual assent, or the authorized experimental YES policy")
    assent.add_argument("--delegated", action="store_true", help="record exact machine CI1 decision under source-bound initial-prompt/CI1 user delegation; no execution")
    approve.add_argument("--scripted", action="store_true", help="record experimental scripted assent, never expert review")
    approve.add_argument("--plan", choices=("none", "dry", "smoke", "full", "scan"),
                         help="native runs: the approved compute plan (default: the contract's compute_plan)")
    go = sub.add_parser("go", help="record the CHECK-IN 2 GO of a native run, bound to its evidence; no compute")
    go.add_argument("--rundir", type=Path, required=True)
    go.add_argument("--quote", required=True, help="the physicist's CHECK-IN 2 GO reply, quoted verbatim")
    advance = sub.add_parser("advance", help="advance a native run's lifecycle stage after its gate passes; no compute")
    advance.add_argument("--rundir", type=Path, required=True)
    advance.add_argument("--to", required=True, help="the lifecycle stage to advance to")
    advance.add_argument("--json", action="store_true")
    run = sub.add_parser("run", help="execute one approved scoped attempt with scientific postconditions")
    run.add_argument("--rundir", type=Path, required=True)
    run.add_argument("--resume", action="store_true", help="verify/reuse a valid completed attempt without additional compute")
    for operation in (approve, run):
        operation.add_argument("--replay-runtime", action="store_true", help="explicitly restore the eight prepared environment values before ordinary admission")
        operation.add_argument("--runtime-capsule", type=Path, help="explicit exact-hash capsule for a legacy plan; requires --replay-runtime")
    capsule = sub.add_parser("runtime-capsule", help="inspect prepared values or create an exact-hash legacy capsule; no assent or execution")
    capsule.add_argument("--rundir", type=Path, required=True)
    capsule.add_argument("--environment", type=Path, help="explicit eight-key historical values/removals JSON; must match the planned digest")
    capsule.add_argument("--out", type=Path, help="new file; default prints capsule JSON")
    compare = sub.add_parser("compare-recipes", help="gate comparisons on verified executed physics recipes")
    compare.add_argument("--left", type=Path, required=True)
    compare.add_argument("--right", type=Path, required=True)
    compare.add_argument("--out", type=Path, help="new comparison receipt, never overwrite an existing file")
    validate = sub.add_parser("validate", help="validate a task contract; never authorizes compute")
    choice = validate.add_mutually_exclusive_group(required=True)
    choice.add_argument("contract", type=Path, nargs="?", help="task_contract.json")
    choice.add_argument("--schema", action="store_true", help="print the existing validator schema")
    validate.add_argument("--json", action="store_true", help="emit machine-readable validation")
    audit = sub.add_parser("audit", help="inspect a source checkout with the existing R1-R8 audit")
    audit.add_argument("--root", type=Path, help="Ravel source checkout (otherwise search cwd parents)")
    audit.add_argument("--out", type=Path, help="write the audit report to this explicit path")
    analyses = sub.add_parser("analyses", help="search the pinned public routine census and inspect adaptation requirements; no compute")
    commands = analyses.add_subparsers(dest="analysis_command", required=True)
    listing = commands.add_parser("list", help="filter routines without implying validated support")
    listing.add_argument("--query", default="")
    listing.add_argument("--experiment")
    listing.add_argument("--framework", choices=("rivet", "simpleanalysis"))
    from .analysis_catalog import FAMILIES
    listing.add_argument("--family", choices=tuple(FAMILIES))
    listing.add_argument("--json", action="store_true")
    show = commands.add_parser("show", help="derive an adaptation packet for one unambiguous routine")
    show.add_argument("identity")
    check = commands.add_parser("check-source", help="verify selected source/asset bytes in an existing upstream checkout")
    check.add_argument("identity")
    check.add_argument("--source", type=Path, required=True)
    commands.add_parser("summary", help="report census denominators and scientific boundaries")
    assess = commands.add_parser('assess', help='assess source-bound build, event, response and reference evidence')
    assess.add_argument('--specification', type=Path, required=True)
    assess.add_argument('--out', type=Path)
    adapt = commands.add_parser('adapt', help='derive exact source obligations from a pinned external coverage landscape')
    adapt.add_argument('identity')
    adapt.add_argument('--landscape', type=Path, required=True)
    adapt.add_argument('--manifest-sha256', required=True, help='externally retained landscape manifest digest')
    adapt.add_argument('--objective', choices=('prediction', 'measurement', 'exclusion'), default='prediction')
    adapt.add_argument('--out', type=Path, help='new adaptation packet; otherwise print to stdout')
    adapt.add_argument('--source-root', type=Path, help='exact source tree for a requested capsule seed')
    adapt.add_argument('--capsule', type=Path, help='new unresolved source capsule; requires --source-root')
    return ap


def _analyses(args) -> int:
    if args.analysis_command == 'adapt':
        from .coverage_landscape import load_landscape
        if bool(args.source_root) != bool(args.capsule):
            raise ValueError('--source-root and --capsule must be supplied together')
        landscape = load_landscape(args.landscape, expected_sha256=args.manifest_sha256)
        result = landscape.intake(args.identity, objective=args.objective)
        outputs = []
        if args.capsule:
            outputs.append((args.capsule, landscape.capsule(args.identity, args.source_root)))
        if args.out:
            outputs.append((args.out, result))
        paths = [p.expanduser().absolute() for p, _ in outputs]
        if len(set(paths)) != len(paths):
            raise ValueError('adaptation packet and capsule must have distinct output paths')
        for path in paths:
            if path.exists() or any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError('adaptation output must be new and must not traverse symlinks: ' + str(path))
        for path, (_, value) in zip(paths, outputs):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as stream:
                json.dump(value, stream, indent=2, allow_nan=False)
                stream.write('\n')
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    if args.analysis_command == 'assess':
        from .workflow.analysis_admission import main as assess
        arguments = ['--specification', str(args.specification)]
        if args.out:
            arguments.extend(['--out', str(args.out)])
        return assess(arguments)
    from .analysis_catalog import load_catalog, search, resolve, adaptation_packet, verify_source
    catalog = load_catalog()
    if args.analysis_command == "summary":
        result = {"date": catalog["retrieved_at_utc"], "scope": catalog["scope"],
                  **catalog["summary"], "compute_authorized": False}
    elif args.analysis_command == "list":
        rows = search(catalog, args.query, args.experiment, args.framework, args.family)
        result = {"matches": len(rows), "entries": rows, "compute_authorized": False}
        if not args.json:
            print(f"{len(rows)} catalogue entries; discovery only, compute_authorized=false")
            for row in rows:
                print(f"{row['id']} | {row['experiment']} | {row['family']} | {row['title']}")
            return 0
    else:
        row = resolve(catalog, args.identity)
        if args.analysis_command == "show":
            result = adaptation_packet(catalog, row)
        else:
            result = verify_source(catalog, row, args.source)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if result.get("status") == "FAIL" else 0


def _check_initiate(ap, args):
    if args.resolve is not None:
        if args.out is not None or args.interpretation is None:
            ap.error("initiate --resolve takes the held run and --interpretation, without --out")
    elif args.out is None or (args.prompt is None and args.prompt_file is None):
        ap.error("initiate requires one of --prompt/--prompt-file and --out")


# Artifacts that show a run has reached CHECK-IN 1 or later; an intake is a draft before them.
CHECKIN1_ARTIFACTS = ("inputs/checkin1.json", "inputs/checkin1_approval.json", "CHECKIN1.md",
                      "inputs/checkin1-response.txt", "inputs/checkin1-delegation.json",
                      "inputs/science-plan.json", "inputs/science-approval.json", "execution_state.json")
# Intake-owned files that a resolution replaces; the previous versions move to inputs/history/.
INTAKE_FILES = ("inputs/task_contract.json", "inputs/capability_recovery.json", "inputs/intake_handoff.json",
                "inputs/interpretation.json", "inputs/reading.json", "inputs/plan.json",
                "current_state.json", "method_proposal.md")
READING_KINDS = ("request-reading-additions", "request-reading")


def _split_interpretation(document):
    """(intent, reading additions): a host interpretation is either an intent or reading additions."""
    if type(document) is dict and document.get("kind") in READING_KINDS:
        return None, document
    return document, None


def _draft_route(prompt, interpretation, additions=None):
    """(contract, reading, label) for a request; the reading is the floor plus any host additions."""
    from .workflow import route_prompt
    return route_prompt.route_records(prompt, interpretation=interpretation, additions=additions)


def _draft_plan(reading, contract):
    """Build the mandatory request plan before creating or revising an epoch-two run."""
    import importlib
    try:
        # A blocked module must not be recovered from a stale package attribute.
        request_plan = importlib.import_module("ravel.workflow.request_plan")
        plan = request_plan.draft(reading, contract)
    except (ImportError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"epoch-two intake requires a request plan: {exc}") from exc
    if not isinstance(plan, dict):
        raise ValueError("epoch-two intake requires a request plan object")
    return plan, None


def _write_json_file(path, value):
    data = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(data)
    if path.read_bytes() != data:
        raise ValueError(f"{path.name} changed while it was written")
    return data


def _write_intake(output, prompt, contract, recovery, *, replace_state=False, interpretation_bytes=None,
                  reading=None, plan=None, session_id=""):
    """Write the intake-owned files of a run and return the written contract bytes."""
    from .workflow import intake, workflow_state
    if reading is None or plan is None:
        raise ValueError("epoch-two intake requires a reading and request plan")
    inputs = output / "inputs"
    inputs.mkdir(exist_ok=True)
    contract = dict(contract)
    if reading is not None:
        raw = _write_json_file(inputs / "reading.json", reading)
        contract["reading"] = {"path": "inputs/reading.json", "sha256": hashlib.sha256(raw).hexdigest()}
    if plan is not None:
        if reading is None:
            raise ValueError("a request plan requires its reading")
        raw = _write_json_file(inputs / "plan.json", plan)
        contract["request_plan"] = {"path": "inputs/plan.json", "sha256": hashlib.sha256(raw).hexdigest()}
    contract["agent_layer_epoch"] = 2
    contract_path = inputs / "task_contract.json"
    intended_contract = (json.dumps(contract, indent=2, allow_nan=False) + "\n").encode("utf-8")
    contract_path.write_bytes(intended_contract)
    if not (output / "request.txt").exists():
        (output / "request.txt").write_text(prompt, encoding="utf-8")
    if interpretation_bytes is not None:
        (inputs / "interpretation.json").write_bytes(interpretation_bytes)
    (inputs / "capability_recovery.json").write_text(json.dumps(recovery, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    # Read the persisted bytes through the same strict reader used by validate.
    if contract_path.read_bytes() != intended_contract:
        raise ValueError("written intake contract differs from intended request")
    persisted = load_contract(contract_path)
    if persisted != contract:
        raise ValueError("persisted intake changed before validation")
    errors = validate_task_contract(persisted)
    if errors:
        raise ValueError("persisted task contract is invalid: " + "; ".join(errors))
    from .workflow.research_admission import admission
    protocol_errors = admission(output, 'plan', contract=persisted, bind=True)
    if protocol_errors:
        raise ValueError('; '.join(protocol_errors))
    # KV-7: record the host session so session-scoped guards find this run.
    state = workflow_state.new_state(str(output), persisted, str(contract_path), session_id)
    if replace_state:
        workflow_state.write_state(str(output), state, replace=True)
    else:
        workflow_state.write_state(str(output), state)
    if contract.get("intake", {}).get("kind") == "method_study":
        intent = contract["intake"]
        (output / "method_proposal.md").write_text(
            "# Draft method study\n\n" + intent["objective"] +
            "\n\nRequested outputs:\n\n" + "\n".join("- " + x for x in intent["requested_outputs"]) +
            "\n\nResolve before designing an execution plan:\n\n" +
            "\n".join("- " + x for x in intent["unresolved"]) +
            "\n\nNo model training, data access, statistical claim, or compute approval is implied.\n",
            encoding="utf-8")
    handoff_path = intended_handoff = None
    if intake.handoff_applicable(contract):
        parent_pin = {"path": str(contract_path), "sha256": hashlib.sha256(intended_contract).hexdigest(),
                      "size": len(intended_contract)}
        handoff = intake.execution_handoff(parent_pin, base_dir=output)
        intended_handoff = (json.dumps(handoff, indent=2, allow_nan=False) + "\n").encode("utf-8")
        handoff_path = inputs / "intake_handoff.json"
        handoff_path.write_bytes(intended_handoff)
        if handoff_path.read_bytes() != intended_handoff or contract_path.read_bytes() != intended_contract:
            raise ValueError("intake handoff or parent contract changed during preparation")
    from .workflow.current_state import write_packet
    write_packet(output)
    if contract_path.read_bytes() != intended_contract:
        raise ValueError("intake contract changed during status preparation")
    if handoff_path is not None and handoff_path.read_bytes() != intended_handoff:
        raise ValueError("intake handoff changed during status preparation")


def _coverage_summary(output, contract, reading, label, plan, plan_note):
    """Label, obligation coverage, gaps, open ambiguity rows and boundaries of a fresh intake."""
    obligations = contract["task_requirements"]["obligations"]
    finer = obligations[1:]
    rule = f"label={label['task_mode']} rule={label['rule']}" if label else ""
    if label and label.get("open"):
        rule += " (open parent: composed from the operation catalogue)"
    if rule:
        print(rule)
    covered = set()
    for row in (plan or {}).get("coverage", []):
        if type(row) is dict and row.get("by"):
            covered.add(row.get("obligation_id"))
    gaps = [row for row in finer if row["id"] not in covered]
    print(f"Coverage: {len(obligations)} obligation(s): the whole request verbatim plus {len(finer)} finer; "
          + (f"{len(finer) - len(gaps)} covered by the draft plan" if plan is not None
             else f"no draft plan ({plan_note}); CHECK-IN 1 covers each"))
    for row in gaps[:16]:
        print(f"  gap {row['id']} ({row['kind']}): {row['statement'][:110]}")
    if len(gaps) > 16:
        print(f"  ... {len(gaps) - 16} more in inputs/task_contract.json")
    rows = [a for a in reading["ambiguities"] if a["status"] == "open"]
    for a in rows:
        print(f"  open {a['id']}{' [physics-critical]' if a['physics_critical'] else ''}: {a['issue'][:110]}")
    for b in reading["boundaries"]:
        print(f"  boundary {b['id']} {b['class']}: would make it possible: {b['would_make_possible'][:140]}")
    print(f"Reading: {output / 'inputs/reading.json'}" + (f"; plan: {output / 'inputs/plan.json'}" if plan else ""))


def _summary(output, contract, recovery, *, resolved=False, reading=None, label=None, plan=None, plan_note=None):
    """A short terminal summary; the complete packets stay in the run directory."""
    from .workflow import intake
    route = intake.handoff_route(contract, reading)
    candidates = [c["mode"] for c in recovery["candidates"]][:8]
    if contract["task_mode"] == "unsupported":
        print(f"Held intake retained: {output}")
        print(f"classification={recovery['classification_status']} task_mode=unsupported compute_authorized=false")
    else:
        print(("Intake resolved in place: " if resolved else "Draft intake created: ") + str(output))
        print(f"task_mode={contract['task_mode']} compute_plan={contract['compute_plan']} "
              "compute_authorized=false")
        operation = contract.get("intake", {}).get("operation")
        print(f"next_route={route or 'scoped-workflow'}" + (f" operation={operation}" if operation else ""))
    if candidates:
        print("Candidate modes (provisional, review each adapter): " + ", ".join(candidates))
    if reading is not None:
        _coverage_summary(output, contract, reading, label, plan, plan_note)
    print(f"Recovery packet: {output / 'inputs/capability_recovery.json'}")
    if contract["task_mode"] == "unsupported":
        print("Next: inspect the recovery packet, then resolve the intent in place with "
              f"`ravel initiate --resolve {output} --interpretation intent.json`. No compute was launched.")
        return
    print("Intake uses a deterministic action parser or a grounded host-agent interpretation. "
          "The contract is a draft; current_state.json records the next required step.")
    print("Next: resolve required inputs and flagged assumptions, then present and obtain approval "
          "for the CHECK-IN 1 plan before generation or scans. No compute was launched.")


def _resolve(args) -> int:
    """Replace a held or pre-CHECK-IN 1 draft intake with a grounded interpretation, in place."""
    from .workflow import intake
    from .workflow.state_io import read_json
    from .workflow.capability_routing import plan as recovery_plan
    from .workflow.execution import utc_now
    output = args.resolve.expanduser().absolute()
    if any(p.is_symlink() for p in (output, *output.parents)) or not output.is_dir():
        raise ValueError(f"held run must be an existing directory without symlinks: {output}")
    contract_path = output / "inputs/task_contract.json"
    if not (output / "request.txt").is_file() or not contract_path.is_file():
        raise ValueError("held run requires request.txt and inputs/task_contract.json from ravel initiate")
    prompt = (output / "request.txt").read_bytes().decode("utf-8")
    previous = load_contract(contract_path)
    if previous.get("prompt") != prompt:
        raise ValueError("held contract does not belong to the retained request.txt")
    reached = [name for name in CHECKIN1_ARTIFACTS if (output / name).exists()]
    if reached:
        raise ValueError("intake has reached CHECK-IN 1 (" + ", ".join(reached) + "); "
                         "start a new run instead of rewriting its intake")
    state = read_json(output / "run_state.json") if (output / "run_state.json").is_file() else {}
    if state.get("routed") or state.get("compute_launched") or state.get("checkins"):
        raise ValueError("run ledger records routing, check-ins or compute; the intake is no longer a draft")
    interpretation_bytes = args.interpretation.expanduser().read_bytes()
    interpretation = read_json(args.interpretation.expanduser())
    if type(interpretation) is not dict or interpretation.get("prompt_sha256") != intake.prompt_hash(prompt):
        raise ValueError("interpretation prompt_sha256 does not match the held request")
    interpretation, additions = _split_interpretation(interpretation)
    if additions is None and (output / "inputs/reading.json").is_file():
        # An intent resolution keeps the reading the run already holds, including host additions.
        retained = read_json(output / "inputs/reading.json")
        if retained.get("authors", [{}])[1:]:
            additions = retained
    contract, reading, label = _draft_route(prompt, interpretation, additions)
    errors = validate_task_contract(contract)
    if errors:
        print("ravel: invalid resolved route; compute_authorized=false:\n" +
              "\n".join(f"  - {error}" for error in errors), file=sys.stderr)
        return 1
    if contract["task_mode"] == "unsupported":
        print("ravel: the interpretation does not resolve the held intake; it remains unchanged; "
              "compute_authorized=false:\n" + "\n".join(f"  - {reason}" for reason in contract["blocking"]),
              file=sys.stderr)
        return 1
    recovery = recovery_plan(prompt, contract=contract, reading=reading)
    plan, plan_note = _draft_plan(reading, contract)
    from .workflow import gate_wiring
    gate_wiring.check_resolution(output)  # never resolve a draft custody did not record
    history_root = output / "inputs/history"
    revision = 1 + sum(1 for p in history_root.iterdir() if p.is_dir()) if history_root.is_dir() else 1
    history = history_root / f"revision-{revision}"
    history.mkdir(parents=True, exist_ok=False)
    try:
        moved = []
        for name in INTAKE_FILES:
            source = output / name
            if source.is_file():
                target = history / name
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
                moved.append(name)
        if (output / "run_state.json").is_file():
            (history / "run_state.json").write_bytes((output / "run_state.json").read_bytes())
            moved.append("run_state.json")
        previous_bytes = (history / "inputs/task_contract.json").read_bytes()
        (history / "resolution.json").write_text(json.dumps({
            "schema_version": 1, "kind": "intake-resolution", "resolved_utc": utc_now(),
            "request_sha256": intake.prompt_hash(prompt),
            "previous_contract_sha256": hashlib.sha256(previous_bytes).hexdigest(),
            "previous_task_mode": previous["task_mode"], "task_mode": contract["task_mode"],
            "interpretation_sha256": hashlib.sha256(interpretation_bytes).hexdigest(),
            "retained": moved, "compute_authorized": False}, indent=2) + "\n", encoding="utf-8")
        session_id = _session_id(args) or state.get("session_id") or ""
        _write_intake(output, prompt, contract, recovery, replace_state=True,
                      interpretation_bytes=interpretation_bytes, reading=reading, plan=plan,
                      session_id=session_id)
        gate_wiring.record_intake_resolution(output, hashlib.sha256(previous_bytes).hexdigest())
        _register(output, session_id, "initiate --resolve")
    except (OSError, ValueError) as exc:
        raise ValueError(f"intake resolution did not complete; previous draft retained at {history}; "
                         f"compute_authorized=false: {exc}") from exc
    _summary(output, contract, recovery, resolved=True, reading=reading, label=label, plan=plan, plan_note=plan_note)
    print(f"Previous draft retained: {history}")
    return 0


def _session_id(args):
    """The host session id: --session-id, else RAVEL_SESSION_ID or the host's own variable."""
    from .workflow import active_run
    explicit = getattr(args, "session_id", None)
    return explicit.strip() if explicit else active_run.session_from_env()


def _register(rundir, session_id, by):
    """Bind the host session to the run in the R-50 registry; a lookup aid, never an authorization."""
    from .workflow import active_run
    if session_id and (Path(rundir) / "run_state.json").is_file():
        active_run.register(rundir, session_id, by=by)


def _run_kind(rundir):
    """science | scoped | native | unplanned: which lifecycle a run follows."""
    if (rundir / "inputs/science-plan.json").exists():
        return "science"
    from .workflow import scoped
    if (rundir / scoped.PLAN).exists():
        return "scoped"
    if (rundir / "inputs/checkin1.json").exists():
        return "native"
    return "unplanned"


def _initiate(args) -> int:
    if args.resolve is not None:
        return _resolve(args)
    prompt = (args.prompt if args.prompt is not None else
              args.prompt_file.expanduser().read_bytes().decode("utf-8"))
    if not prompt.strip():
        raise ValueError("the request must not be blank; compute_authorized=false")
    interpretation_bytes = interpretation = additions = None
    if args.interpretation:
        from .workflow.state_io import read_json
        interpretation_bytes = args.interpretation.expanduser().read_bytes()
        interpretation, additions = _split_interpretation(read_json(args.interpretation.expanduser()))
    contract, reading, label = _draft_route(prompt, interpretation, additions)
    errors = validate_task_contract(contract)
    if errors:
        print("ravel: invalid draft route; compute_authorized=false:\n" +
              "\n".join(f"  - {error}" for error in errors), file=sys.stderr)
        return 1
    from .workflow.capability_routing import plan as recovery_plan
    recovery = recovery_plan(prompt, contract=contract, reading=reading)
    plan, plan_note = _draft_plan(reading, contract)
    # Do not resolve the final path before mkdir: even a dangling symlink is an
    # existing destination and must not silently redirect a new run elsewhere.
    output = args.out.expanduser().absolute()
    output.mkdir(parents=True, exist_ok=False)
    try:
        from .workflow import gate_wiring
        # The steering journal and the run identity exist from run creation, before the directory
        # holds anything: dispatch needs the initialization record, and a later copy of the
        # directory is recognized by the identity bound here.
        gate_wiring.initialize_steering(output, route='run-initialization')
        (output / "inputs").mkdir(exist_ok=True)
        (output / "request.txt").write_text(prompt, encoding="utf-8")
        session_id = _session_id(args)
        _write_intake(output, prompt, contract, recovery, interpretation_bytes=interpretation_bytes,
                      reading=reading, plan=plan, session_id=session_id)
        # the prompt and the run_init snapshot bind the epoch before any agent session acts.
        gate_wiring.record_run_init(output)
        _register(output, session_id, "initiate")
    except (OSError, ValueError) as exc:
        raise ValueError(f"intake did not complete; partial output retained at {output}; "
                         f"compute_authorized=false: {exc}") from exc

    _summary(output, contract, recovery, reading=reading, label=label, plan=plan, plan_note=plan_note)
    if contract["task_mode"] == "unsupported":
        print("ravel: " + recovery["classification_status"] + "; compute_authorized=false; "
              f"original request and recovery retained at {output}:\n" +
              "\n".join(f"  - {reason}" for reason in contract["blocking"]), file=sys.stderr)
        return 1
    return 0


def _status(args) -> int:
    retained = getattr(args, 'retained_study', False)
    command = getattr(args, 'notification_command', None)
    if retained:
        if command is not None:
            raise ValueError('wait notifications require an active review run')
        from .workflow.retained_science_review import packet
        result = packet(args.rundir, write=args.write)
        failures = ('invalid', 'failed')
    elif (args.rundir / "inputs/science-plan.json").exists():
        from .workflow.science import packet
        result = packet(args.rundir, write=args.write)
        failures = ('invalid', 'failed')
    else:
        from .workflow.current_state import build_packet, write_packet
        result = (write_packet if args.write else build_packet)(args.rundir)
        failures = ('invalid',)
    if not retained:
        from .workflow import physics_review, scientific_autonomy
        if physics_review.registered(args.rundir):
            review = result.get('physics_review') or physics_review.status(args.rundir)
            result['physics_review'] = review
            waiting = review.get('waiting_for_human')
            if waiting:
                result['waiting_for_human'] = waiting
                result['next_required'] = waiting['message']
            if command is not None:
                result['notification'] = scientific_autonomy.notify_waiting(args.rundir, command=command)
            if args.write:
                from .workflow.state_io import atomic_json
                atomic_json(args.rundir / 'current_state.json', result)
        elif command is not None:
            raise ValueError('wait notifications require an active registered review')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if result["execution"]["status"] in failures else 0


def _validate(args) -> int:
    if args.schema:
        print(json.dumps(SCHEMA, indent=2))
        return 0
    try:
        contract = load_contract(args.contract)
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        errors = [f"cannot read contract: {exc}"]
        code = 2
    else:
        errors = validate_task_contract(contract)
        code = 1 if errors else 0
    result = {"valid": code == 0, "errors": errors, "compute_authorized": False}
    if args.json:
        print(json.dumps(result, indent=2))
    elif errors:
        print("INVALID task contract:\n" + "\n".join(f"  - {error}" for error in errors))
    else:
        print("Valid task contract. This does not authorize compute or certify a physics result.")
    return code


def _plan(args) -> int:
    from .workflow.state_io import read_json
    from .workflow.science import MODES
    if read_json(args.spec).get("mode") in MODES:
        from .workflow.science import plan
    else:
        from .workflow.scoped import plan
    result = plan(args.rundir, args.spec)
    from .workflow import active_run
    _register(args.rundir, active_run.session_from_env(), "plan")
    if result.get("status") == "held":
        print(f"Held {result['mode']} CHECK-IN 1: {args.rundir / 'CHECKIN1.md'} lists "
              f"{len(result['unmet'])} unmet item(s):")
        for item in result["unmet"]:
            print(f"  - {item.get('path') or item.get('item')} ({item['kind']}, {item['reason']})")
        print("Supply them, then run this plan command again with the same --rundir. No compute launched.")
        return 0
    print(f"Concrete {result['mode']} CHECK-IN 1: {args.rundir / 'inputs/checkin1.json'}")
    print("Review the recipe, assumptions and hard ceiling, then record approval. No compute launched.")
    return 0


def _approve(args) -> int:
    """R-51 item 1: dispatch by run kind (science, scoped or native)."""
    result = _approve_by_kind(args)
    if result == 0:
        # HOOKLESS: the enforcement surface the approval was given under, fingerprinted at CHECK-IN 1.
        from .workflow import host_governance
        host_governance.record_checkin1_surface(args.rundir)
        # the CHECK-IN 1 response as custody user text and the checkin1 input snapshot.
        from .workflow import gate_wiring
        gate_wiring.record_checkin1(args.rundir, quote=getattr(args, "quote", None),
                                    scripted=bool(getattr(args, "scripted", False)))
    return result


def _approve_by_kind(args) -> int:
    kind = _run_kind(args.rundir)
    if kind == "native" and not getattr(args, "delegated", False):
        return _native_approve(args)
    if kind == "science":
        from .workflow.science import approve
    else:
        from .workflow.scoped import approve
    from .workflow.prepared_runtime import selected_context
    with selected_context(args.rundir, enabled=getattr(args, "replay_runtime", False), capsule_path=getattr(args, "runtime_capsule", None)):
        if getattr(args,'delegated',False):
            if kind != "science":
                return _approve_delegated_plan(args.rundir)
            from .workflow.science import approve_delegated
            return approve_delegated(args.rundir)
        return approve(args.rundir, args.quote, scripted=args.scripted)


def _native_approve_without_scripted(args) -> int:
    """A native run's CHECK-IN 1 approval: workflow_state approve over checkin1.json and the budget."""
    from .workflow import workflow_state
    from .validation.validate_task_contract import load_contract
    plan = args.plan
    if plan is None:
        contract_path = args.rundir / "inputs/task_contract.json"
        plan = load_contract(contract_path)["compute_plan"] if contract_path.is_file() else None
    if plan not in workflow_state.APPROVAL_PLANS:
        raise ValueError(f"native approval needs --plan (one of {', '.join(workflow_state.APPROVAL_PLANS)}); "
                         f"the contract's compute_plan is {plan!r}")
    return workflow_state.main(["approve", "--rundir", str(args.rundir), "--quote", args.quote, "--plan", plan])


def _go(args) -> int:
    """R-51 item 1: CHECK-IN 2 GO exists for native runs; scoped and science runs carry no waypoint."""
    kind = _run_kind(args.rundir)
    if kind in ("science", "scoped"):
        raise ValueError(f"a {kind} run has no CHECK-IN 2 GO; its approved plan covers execution (`ravel run`)")
    from .workflow import workflow_state
    return workflow_state.main(["go", "--rundir", str(args.rundir), "--quote", args.quote])


def _advance(args) -> int:
    """R-51 item 1: lifecycle advance exists for native runs; scoped and science runs advance by `ravel run`."""
    kind = _run_kind(args.rundir)
    if kind in ("science", "scoped"):
        raise ValueError(f"a {kind} run advances through `ravel run` and its review, not `ravel advance`")
    from .workflow import workflow_state
    return workflow_state.main(["advance", "--rundir", str(args.rundir), "--to", args.to,
                                *(["--json"] if args.json else [])])


def _lifecycle_command(command, arguments) -> int:
    """Dispatch a LIFECYCLE_COMMANDS entry: check its sub-command word, adapt its entry point."""
    from importlib import import_module
    import inspect
    name, word, error_class, _ = LIFECYCLE_COMMANDS[command]
    if word is not None:
        if not arguments or arguments[0] != word:
            print(f"usage: ravel {command} {word} [arguments]", file=sys.stderr)
            return 2
        arguments = arguments[1:]
    module = import_module("ravel." + name)
    errors = (getattr(module, error_class),) if error_class else ()
    try:
        if inspect.signature(module.main).parameters:
            result = module.main(arguments)
        else:
            saved = sys.argv
            sys.argv = [f"ravel {command}", *arguments]
            try:
                result = module.main()
            finally:
                sys.argv = saved
    except errors as exc:
        print(f"ERROR ({command}): {exc}", file=sys.stderr)
        return 1
    return 0 if result is None else result


def _approve_delegated_plan(rundir) -> int:
    """Machine CHECK-IN 1 decision over a pinned request plan, after plan-level pre-authorization."""
    import json
    from .validation.validate_task_contract import load_contract
    path = rundir / "inputs/task_contract.json"
    contract = load_contract(path) if path.is_file() else None
    if not isinstance(contract, dict) or "request_plan" not in contract:
        raise ValueError("delegated approval requires the prospective science/v2 route or a pinned request plan")
    from .workflow.workflow_state import record_delegated_approval
    record = record_delegated_approval(rundir, contract["compute_plan"])
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


def _run(args) -> int:
    from .workflow import wms_policy
    wms_policy.require_dispatch(args.rundir)
    if (args.rundir / "inputs/science-plan.json").exists():
        from .workflow.science import run
    else:
        from .workflow.scoped import run
    from .workflow.prepared_runtime import selected_context
    with selected_context(args.rundir, enabled=getattr(args, "replay_runtime", False), capsule_path=getattr(args, "runtime_capsule", None)):
        return run(args.rundir, resume=args.resume)


def _runtime_capsule(args):
    from .workflow.prepared_runtime import for_plan, read_capsule, _ordinary
    import json
    environment = read_capsule(args.environment) if args.environment else None
    result = for_plan(args.rundir, environment=environment)
    text = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.out:
        path = args.out.expanduser().absolute()
        _ordinary(path)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text, end="")
    return 0


def _science_correct(args) -> int:
    from .workflow.science import correct
    from .workflow.state_io import read_json
    request = read_json(args.request)
    required = {'actor_id', 'changed_paths', 'recheck_checks'}
    if (not isinstance(request, dict) or not required <= set(request)
            or set(request) - required - {'max_seconds'}):
        raise ValueError('science correction request requires actor_id, changed_paths and recheck_checks; max_seconds is optional')
    result = correct(args.rundir, **request)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


def _compare_recipes(args) -> int:
    from .workflow.scoped import compare
    result = compare(args.left, args.right)
    if args.out:
        with args.out.expanduser().open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["comparable"] else 1


def _audit(args) -> int:
    candidates = ([args.root.expanduser().resolve()] if args.root else
                  [Path.cwd(), *Path.cwd().parents])
    root = next((candidate for candidate in candidates
                 if (candidate / "scripts/audit.py").is_file()
                 and (candidate / "distribution.json").is_file()
                 and (candidate / "docs/workflow").is_dir()), None)
    if root is None:
        raise ValueError("The R1-R8 audit needs a Ravel source checkout. Clone "
                         "https://github.com/ammarphp/ravel and run 'ravel audit --root PATH'. "
                         "The wheel does not contain the source checkout.")
    cmd = [sys.executable, str(root / "scripts/audit.py")]
    if args.out:
        target = args.out.expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"audit output already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--write", "--out", str(target)])
    print("Audit scores the files available in this checkout; completion is not a physics certification.", flush=True)
    return subprocess.call(cmd, cwd=root)


def _register_prepared(arguments):
    """R-50 item 1: `research-orchestrate prepare --out <dir>` registers a prepared run."""
    from .workflow import active_run
    out = next((arguments[i + 1] for i, a in enumerate(arguments[:-1]) if a == "--out"), None)
    if out is not None:
        _register(Path(out), active_run.session_from_env(), "research-orchestrate prepare")


def _ordinary_main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        # These focused modules own their subcommands. Early dispatch preserves
        # their complete --help and error messages in installed distributions.
        if arguments and arguments[0] in FOCUSED_COMMANDS:
            from importlib import import_module
            name, _ = FOCUSED_COMMANDS[arguments[0]]
            result = import_module("ravel." + name).main(arguments[1:])
            if arguments[0] == "research-orchestrate" and arguments[1:2] == ["prepare"] and result == 0:
                _register_prepared(arguments[1:])
            return result
        if arguments and arguments[0] in LIFECYCLE_COMMANDS:
            return _lifecycle_command(arguments[0], arguments[1:])
        ap = parser()
        args = ap.parse_args(arguments)
        if args.command == "initiate":
            _check_initiate(ap, args)
        return {"initiate": _initiate, "status": _status, "validate": _validate,
                "audit": _audit, "plan": _plan, "approve": _approve,
                "run": _run, "runtime-capsule": _runtime_capsule, "science-correct": _science_correct,
                "go": _go, "advance": _advance,
                "compare-recipes": _compare_recipes, "analyses": _analyses}[args.command](args)
    except (OSError, ValueError) as exc:
        print(f"ravel: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ravel: interrupted", file=sys.stderr)
        return 130


# Epoch-two review inspection extends the existing command; legacy subcommands delegate unchanged.
FOCUSED_COMMANDS['review'] = ('workflow.review_points', 'inspect mandatory review points and receipt-backed deliveries')

# the trusted CHECK-IN response path, the steering recorder and the T13 RDJ cost report.
FOCUSED_COMMANDS['gate-wiring'] = ('workflow.gate_wiring', 'record CHECK-IN responses (approve, reopen, withdraw) and steering in custody; RDJ cost report')

# Research preregistration derived in code from an approved CHECK-IN 1 plan.
FOCUSED_COMMANDS['research-preregister'] = ('workflow.research_launch', 'derive and record the research preregistration from an approved CHECK-IN 1 plan')
# `ravel work mcp` (the broker's MCP face); other work subcommands delegate to agent_worker unchanged.
FOCUSED_COMMANDS['work'] = ('workflow.work_cli', 'dispatch sandboxed workers, inspect broker receipts, recovery and stop state, and serve the toolbelt over MCP (work mcp)')

# Broker-bound literal literature cards and citation/code following.
FOCUSED_COMMANDS['literature'] = ('workflow.literature', 'check evidence cards, follow located citations and code commits, and resolve publication titles')

# `ravel review run|dispatch` executes the review.points graph; other review subcommands delegate unchanged.
FOCUSED_COMMANDS['review'] = ('workflow.graphs.review', 'run review points on the review.points graph; inspect mandatory review points and receipt-backed deliveries')

# the production executors (`ravel work next|seal|dispatch --node|waive|host-authored`; other work
# subcommands delegate unchanged) and the lifecycle graph (`ravel drive`, `ravel drive respond`).
FOCUSED_COMMANDS['work'] = ('workflow.production_executor', 'production work orders (next, seal, dispatch --node, waive, host-authored), sandboxed workers, broker receipts, recovery and stop state, and the toolbelt over MCP (work mcp)')
FOCUSED_COMMANDS['drive'] = ('workflow.graphs.lifecycle', 'drive a run through the lifecycle graph; it stops at every human CHECK-IN and resumes on drive respond')

# The package ships a pinned catalogue snapshot; this command rebuilds one from the user's own checkouts.
FOCUSED_COMMANDS['catalogue'] = ('workflow.analysis_catalog_build', 'build the local analysis catalogue from your Rivet and SimpleAnalysis checkouts')

# Public steering names retain the existing gate-wiring producers and custody.
FOCUSED_COMMANDS['steer'] = ('workflow.steer_cli', 'record steering through gate-wiring')
FOCUSED_COMMANDS['respond'] = ('workflow.respond_cli', 'record responses through gate-wiring')

# Preserve scripted authority on the native path as well as the scientific path.
def _native_approve(args) -> int:
    if not getattr(args, 'scripted', False):
        return _native_approve_without_scripted(args)
    from .workflow import workflow_state
    from .validation.validate_task_contract import load_contract
    plan = args.plan
    if plan is None:
        path = args.rundir / 'inputs/task_contract.json'
        plan = load_contract(path)['compute_plan'] if path.is_file() else None
    if plan not in workflow_state.APPROVAL_PLANS:
        raise ValueError('native approval needs an explicit or contracted compute plan')
    return workflow_state.main(['approve', '--rundir', str(args.rundir), '--quote', args.quote,
                                '--plan', plan, '--scripted'])

FOCUSED_COMMANDS['method-decision'] = ('workflow.method_selection', 'validate and render the cheapest sufficient method in CHECK-IN 1')

# Workflow-manager-first launch; each approved stage becomes a Snakemake rule before it runs.
# The launch module also routes `adopt|adopt-run|adopt-status` to external Snakefile adoption.
FOCUSED_COMMANDS['wms'] = ('workflow.wms_launch', 'workflow-manager-first projects: init, add an approved run as a Snakemake rule, launch it through run-step, status; adopt an external Snakefile')

# Review rubrics as data and their pinned overlays.
FOCUSED_COMMANDS['review-rubric'] = ('workflow.review_rubric', 'show a review rubric, record the rubric and pinned overlay of a run, and apply it to a review packet')

FOCUSED_COMMANDS['deliver-workspace'] = ('workflow.requester_delivery', 'copy accepted study artifacts into a supplied requester layout and verify provenance')

# Conformance policy is supplied by the requester; checks only inspect records.
FOCUSED_COMMANDS['conformance'] = ('workflow.submission_conformance', 'check a git working tree and declared run records against a supplied rule pack')

# Supplied document sources; native compilation stays in ordinary manuscript-build.
FOCUSED_COMMANDS['manuscript'] = ('physics.manuscript_slides', 'pin supplied class bundles and prepare source-bound slides')

# One declared project instruction document per run, delivered to every session the run starts.
FOCUSED_COMMANDS['project-instructions'] = ('workflow.project_instructions', 'pin one project instruction document for a run; every worker and reviewer session receives it, and a changed document needs an approved re-pin')

# Command blocks outside the ordinary parser: prompt exports extend the checkout audit, and
# `ravel replay prepare|approval-gate|run|compare|template` is the governed replay of a completed
# run (workflow.replay). Any other replay call reaches the ordinary parser and is refused.
REPLAY_OPERATIONS = ('prepare', 'approval-gate', 'run', 'compare', 'template')
def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:2] == ['audit', 'prompt-log']:
        from .workflow import prompt_log
        return prompt_log.main(arguments[2:])
    if arguments[:1] == ['replay'] and arguments[1:2] and arguments[1] in REPLAY_OPERATIONS:
        from .workflow.replay import main as replay
        try:
            return replay(arguments[1:])
        except (OSError, ValueError) as exc:
            print(f"ravel: {exc}", file=sys.stderr)
            return 2
    return _ordinary_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
