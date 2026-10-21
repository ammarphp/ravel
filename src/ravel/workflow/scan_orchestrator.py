#!/usr/bin/env python
"""Plan, supervise and aggregate supplied finite named-parameter scans.

Version-2 contracts supply axes, requested quantities, dataset metadata, card
bindings and output format. No dimensionality, mass relation, study population
or physics result is implied. Live dispatch uses existing native admission,
method decisions, CHECK-IN approval and supervised execution.

Commands: plan <contract.json> [--dry-run], launch <scandir> [--write-plans]
[--go], status <scandir>, assemble <scandir> [--out PATH] [--normalization-contract PATH],
rebase <scandir> --transformation PATH. A normalization contract supplies like-for-like
corrections (limits and reference cross sections scale inversely); a transformation supplies
component accounting and response ratios. Historical supplied limit records retain their
numerical status, provenance and review protections.
See docs/workflow/steps/08-scan.md.
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse
import json
import math
import os
import re
import subprocess
import sys

from pathlib import Path
from ravel.paths import repository_root, package_data_path
from ravel.limits import attach_limits, read_limits, rescale_artifact, source_errors, NUMERICAL_METADATA
REPO = str(repository_root() or Path.cwd())
SCHEMA_VERSION = 2


def die(msg):
    sys.exit(f"scan_orchestrator: {msg}")


class MissingInputError(ValueError):
    reason = "missing-input"

    def __init__(self, field):
        self.field = field
        super().__init__(f"{self.reason}: supplied {field} required")


def _required(document, key):
    if key not in document or document[key] is None:
        raise MissingInputError(key)
    return document[key]


def _relative_path(value):
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError("explicit relative artifact path without traversal required")
    return value


def load_spec(path):
    with open(path) as stream:
        spec = json.load(stream)
    if not isinstance(spec, dict):
        raise ValueError("scan contract must be an object")
    for key in ("name", "axes", "max_points", "quantities", "datasets", "output",
                "template_toml", "subst", "run_root", "run_prefix"):
        _required(spec, key)
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("version-2 scan contract required; migrate supplied legacy coordinates explicitly")
    if any(k in spec for k in ("grid", "line", "plane")):
        raise ValueError("named axes required; implicit plane relations are not scan contracts")
    for key in ("name", "template_toml", "run_root"):
        if not isinstance(spec[key], str) or not spec[key]:
            raise ValueError(f"nonempty {key} required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", str(spec["run_prefix"])):
        raise ValueError("filesystem-safe run_prefix required")
    from jsonschema import validate, ValidationError
    schema = json.loads(package_data_path("templates", "scan.schema.json").read_text())
    try:
        validate(spec, schema)
    except ValidationError as exc:
        raise ValueError(f"invalid scan contract: {exc.message}") from exc
    points = enumerate_points(spec)
    names = set(points[0])
    if not isinstance(spec["subst"], dict) or not spec["subst"] or any(v not in names for v in spec["subst"].values()):
        raise ValueError("subst must bind supplied TOML addresses to declared axis names")
    if set(spec["subst"].values()) != names:
        raise ValueError("point input bindings must consume every axis")
    datasets = spec["datasets"]
    if not isinstance(datasets, list) or not datasets or any(not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"] for d in datasets):
        raise ValueError("explicit nonempty dataset population with identifiers required")
    if len({d["id"] for d in datasets}) != len(datasets):
        raise ValueError("duplicate dataset identifier")
    quantities = spec["quantities"]
    if not isinstance(quantities, list) or not quantities:
        raise ValueError("explicit nonempty requested quantities required")
    reserved = {"tag", "parameters", "sources", "inference", "overridden", "regime", "override", "receipt_sha256", "status", *names}
    qnames = []
    for q in quantities:
        if not isinstance(q, dict) or set(q) != {"name", "source", "field"}:
            raise ValueError("quantity requires name/source/field")
        if not isinstance(q["name"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", q["name"]) or q["name"] in reserved:
            raise ValueError("unambiguous quantity name required")
        _relative_path(q["source"])
        if not isinstance(q["field"], str) or not q["field"] or any(not part for part in q["field"].split('.')):
            raise ValueError("explicit dotted JSON quantity field required")
        qnames.append(q["name"])
    if len(set(qnames)) != len(qnames):
        raise ValueError("duplicate requested quantity")
    output = spec["output"]
    if not isinstance(output, dict) or set(output) != {"format", "path"} or output["format"] not in ("json", "csv"):
        raise ValueError("explicit JSON or CSV output specification required")
    _relative_path(output["path"])
    if output["path"] == "scan_manifest.json":
        raise ValueError("result output cannot overwrite the scan manifest")
    return spec


def enumerate_axes(axes, *, maximum=128):
    """Complete ordered Cartesian coordinates for explicitly named finite axes.

    This utility attaches no physics interpretation. Callers own the model's
    kinematic constraints.
    """
    from itertools import product
    if type(axes) is not list or not 1 <= len(axes) <= 8 or type(maximum) is not int or not 1 <= maximum <= 4096:
        raise ValueError('bounded explicit named scan axes required')
    names=[];vectors=[];size=1
    for row in axes:
        if type(row) is not dict or set(row) != {'name','values'} or type(row['name']) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,80}',row['name']):
            raise ValueError('closed named scan axis required')
        xs=row['values']
        if type(xs) is not list or not xs or any(type(x) not in (int,float) or not math.isfinite(x) for x in xs) or len(set(xs)) != len(xs):
            raise ValueError('distinct finite literal scan values required')
        names.append(row['name']);vectors.append(xs);size *= len(xs)
    if len(set(names)) != len(names) or size > maximum:
        raise ValueError('duplicate scan axis or complete grid exceeds resource ceiling')
    return [dict(zip(names,x)) for x in product(*vectors)]


def enumerate_points(spec):
    axes = _required(spec, "axes")
    maximum = _required(spec, "max_points")
    points = enumerate_axes(axes, maximum=maximum)
    if "points" in spec:
        selected = spec["points"]
        domain = {tuple(p.items()) for p in points}
        names = [a["name"] for a in axes]
        if not isinstance(selected, list) or not selected:
            raise ValueError("explicit named point population required")
        points = []
        for p in selected:
            if not isinstance(p, dict) or set(p) != set(names) or any(type(v) not in (int, float) or not math.isfinite(v) for v in p.values()):
                raise ValueError("point must supply every declared finite axis coordinate")
            point = {name: p[name] for name in names}
            if tuple(point.items()) not in domain:
                raise ValueError("selected point outside supplied axis domain")
            points.append(point)
        if len({tuple(p.items()) for p in points}) != len(points):
            raise ValueError("duplicate selected point")
    return points


def population(manifest, scan):
    """Population equality of an assembled scan against its manifest (SW33, G12, E24).

    Returns ``{"holes", "extras", "duplicates", "unconfirmed", "claimed_complete", "not_completed"}``:
    manifest points the scan does not list (in its ``point_population`` when present, else its result
    rows), listed points outside the manifest, points listed twice, result rows the population does not
    mark completed, and whether the scan claims full coverage (``n_missing == 0``, ``missing_tags == []``
    or ``n_done`` equal to the manifest) while a point is not completed. An audit that checks only the
    reported points cannot see a hole; this compares the whole population. It never raises: malformed
    parts count as absent.
    """
    manifest = manifest if isinstance(manifest, dict) else {}
    scan = scan if isinstance(scan, dict) else {}
    points = manifest.get("points") if isinstance(manifest.get("points"), list) else []
    invalid = []

    def tags(rows, label):
        found = []
        for row in rows:
            tag = row.get("tag") if isinstance(row, dict) else None
            if not isinstance(tag, str) or not tag:
                invalid.append(label)
            else:
                found.append(tag)
        return found

    expected = tags(points, "manifest point without a valid tag")
    results = scan.get("points") if isinstance(scan.get("points"), list) else []
    rows = scan.get("point_population")
    if not isinstance(rows, list):
        rows = results
    listed = tags(rows, "population row without a valid tag")
    result_tags = tags(results, "result row without a valid tag")
    completed = {r["tag"] for r in rows if isinstance(r, dict) and isinstance(r.get("tag"), str)
                 and r.get("tag") and r.get("status", "completed") == "completed"}
    seen, duplicates = set(), []
    for tag in listed:
        if tag in seen and tag not in duplicates:
            duplicates.append(tag)
        seen.add(tag)
    holes = [tag for tag in expected if tag not in seen]
    extras = [tag for tag in listed if tag not in set(expected)]
    missing = [tag for tag in expected if tag not in completed]
    unconfirmed = [tag for tag in result_tags if tag not in completed]
    claimed = (scan.get("n_missing") == 0 or scan.get("missing_tags") == []
               or (scan.get("n_done") is not None and scan.get("n_done") == len(expected)))
    return {"holes": holes, "extras": extras, "duplicates": duplicates, "unconfirmed": unconfirmed,
            "claimed_complete": bool(claimed and missing), "not_completed": missing, "invalid": invalid}


def population_errors(manifest, scan):
    """Plain-language refusals of :func:`population` (empty when the scan lists exactly the manifest)."""
    found = population(manifest, scan)
    errors = []
    if found["invalid"]:
        errors.append(f"scan population has {len(found['invalid'])} malformed manifest, population or result row(s)")
    if found["holes"]:
        errors.append(f"scan omits {len(found['holes'])} manifest point(s): {', '.join(map(str, found['holes'][:20]))}")
    if found["extras"]:
        errors.append(f"scan lists unmanifested point(s): {', '.join(map(str, found['extras'][:20]))}")
    if found["duplicates"]:
        errors.append(f"scan lists point(s) twice: {', '.join(map(str, found['duplicates'][:20]))}")
    if found["unconfirmed"]:
        errors.append("scan reports result row(s) its population does not mark completed: "
                      + ", ".join(map(str, found["unconfirmed"][:20])))
    if found["claimed_complete"]:
        errors.append(f"scan claims full coverage with {len(found['not_completed'])} point(s) not completed")
    return errors


def refuse_controller_owned(command, target):
    """Exit through the controller's command policy when ``target`` lies in a controller-owned run.

    Without the controller no run is owned. ``plan`` is also checked at the directories it would write.
    """
    try:
        from ravel.controller import command_policy
    except ImportError:
        return
    reason = command_policy.check(["scan_orchestrator", command, os.path.abspath(target)])
    if reason:
        die(reason)


def point_tag(point):
    from hashlib import sha256
    return "point_"+sha256(json.dumps(point, sort_keys=True, allow_nan=False).encode()).hexdigest()[:20]


def named_live_tags(process_text):
    """Recognize coordinate-independent point tokens at the existing monitor seam."""
    tools = ('native_pipeline', 'run-pipeline-native', 'mg5_aMC', 'DelphesHepMC',
             'pythia_shower', 'native_simpleanalysis', 'rjr_resolve', 'delphes2sa')
    return {tag for line in process_text.splitlines()
            if 'scan_babysitter' not in line and any(tool in line for tool in tools)
            for tag in re.findall(r'(?<![A-Za-z0-9])point_[0-9a-f]{20}(?![0-9a-f])', line)}


def substitute_toml(template_text, spec, point):
    """Exactly one supplied section/key address per binding; no frozen-coordinate fallback."""
    lines = template_text.splitlines()
    section = ""
    locations = {}
    for i, line in enumerate(lines):
        header = re.fullmatch(r"\s*\[([^]\n]+)\]\s*(?:#.*)?", line)
        if header:
            section = header[1].strip()
        assignment = re.match(r"(\s*)([A-Za-z][A-Za-z0-9_-]*)\s*=", line)
        if assignment:
            key = assignment[2]
            locations.setdefault(key, []).append((i, assignment[1]))
            if section:
                locations.setdefault(section+"."+key, []).append((i, assignment[1]))
    edited = set()
    for address, name in spec["subst"].items():
        if name not in point:
            raise MissingInputError(f"parameters.{name}")
        found = locations.get(address, [])
        if len(found) != 1 or found[0][0] in edited:
            raise ValueError(f"template needs exactly one distinct {address} assignment")
        i, indent = found[0]
        key = address.rsplit('.', 1)[-1]
        lines[i] = f"{indent}{key} = {point[name]:g}"
        edited.add(i)
    rendered = "\n".join(lines)+"\n"
    import tomllib
    tomllib.loads(rendered)
    return rendered


def cmd_plan(args):
    spec = load_spec(args.spec)
    points = enumerate_points(spec)
    base = Path(args.spec).resolve().parent
    template = Path(spec["template_toml"])
    template = template.resolve() if template.is_absolute() else (base/template).resolve()
    if not template.is_file():
        raise MissingInputError("template_toml")
    text = template.read_text()
    # Validate all substitutions before creating any run directory.
    rendered = [substitute_toml(text, spec, p) for p in points]
    root = Path(spec["run_root"])
    root = root.resolve() if root.is_absolute() else (base/root).resolve()
    directory = root/(spec["run_prefix"]+"_SCAN")
    if getattr(args, "dry_run", False):
        print(f"[DRY-RUN] {len(points)} supplied points under {directory}")
        for p in points:
            print(f"  {point_tag(p)} {p}")
        return
    for target in [directory] + [root/(spec["run_prefix"]+"_"+point_tag(p)) for p in points]:
        refuse_controller_owned("plan", target)
    if (directory/"scan_manifest.json").exists():
        raise ValueError("scan manifest already exists; inspect/resume rather than overwrite")
    for point in points:
        config = root/(spec["run_prefix"]+"_"+point_tag(point))/"config/point.toml"
        if config.exists():
            raise ValueError("point configuration already exists; refusing to replace")
    manifest_points = []
    for p, card in zip(points, rendered):
        tag = point_tag(p)
        run = root/(spec["run_prefix"]+"_"+tag)
        config = run/"config/point.toml"
        if config.exists():
            raise ValueError("point configuration already exists; refusing to replace")
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(card)
        manifest_points.append({"tag": tag, "parameters": p, "run_dir": str(run),
            "config": "config/point.toml", "quantities": spec["quantities"]})
    manifest = {"schema_version": SCHEMA_VERSION, "name": spec["name"],
        "model": spec.get("model"), "analysis_id": spec.get("analysis_id"),
        "axes": spec["axes"], "quantities": spec["quantities"], "datasets": spec["datasets"],
        "output": spec["output"], "subst": spec["subst"], "template_toml": str(template),
        "n_points": len(points), "points": manifest_points}
    from ravel.workflow.state_io import atomic_json
    atomic_json(directory/"scan_manifest.json", manifest)
    from ravel.workflow import gate_wiring
    # The scan directory owns the steering of its points; each point is bound to it at launch.
    gate_wiring.initialize_steering(directory, route='scan-plan')
    print(f"planned {len(points)} supplied points -> {directory}/scan_manifest.json")


def load_manifest(scandir):
    if not os.path.isabs(scandir):
        scandir = os.path.join(REPO, scandir)
    mpath = os.path.join(scandir, "scan_manifest.json")
    if not os.path.exists(mpath):
        die(f"no scan_manifest.json in {scandir} -- run `plan` first")
    with open(mpath) as fh:
        manifest = json.load(fh)
    if len(manifest['points']) != manifest['n_points'] or len({p['tag'] for p in manifest['points']}) != len(manifest['points']):
        raise ValueError('scan population changed or contains duplicate point identities')
    return scandir, manifest


def override_context(manifest):
    from .point_overrides import digest, pin
    return digest({**{k: manifest[k] for k in ('name', 'axes', 'quantities', 'datasets')},
        'points': [{**{k: p[k] for k in ('tag', 'parameters', 'run_dir')},
                    'config': p.get('base_config', p['config']),
                    'base_input': pin(Path(REPO) / p['run_dir'] / p.get('base_config', p['config']))}
                   for p in manifest['points']]})


def record_override(scandir, point_id, request):
    """Admit one replacement configuration, retaining original cards and receipts."""
    import tomllib
    from . import point_overrides as overrides
    from .state_io import atomic_json, file_lock
    directory = Path(scandir).resolve()
    with file_lock(directory / '.point-overrides.lock'):
        _, manifest = load_manifest(str(directory))
        if manifest.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('point overrides require a current declarative scan manifest')
        population = {p['tag']: p for p in manifest['points']}
        if point_id not in population:
            raise ValueError('override names an unknown point')
        point = population[point_id]
        if point_status(point)[0] == 'running':
            raise ValueError('cannot override a running point')
        root = Path(REPO) / point['run_dir']
        base_config = point.get('base_config', point['config'])
        original = root / base_config
        settings = tomllib.loads(original.read_text())
        def successful_neighbour(p):
            if point_status(p)[0] != 'done':
                return []
            harvested = harvest_point(p)
            if not harvested:
                return []
            pins = [{'path': v['path'], 'sha256': v['sha256']} for v in harvested.get('sources', {}).values()]
            if not pins and harvested.get('source'):
                run = point_attempt_root(p, Path(REPO) / p['run_dir'])
                pins = [overrides.pin(candidate) for candidate in
                        (run / harvested['source'], run / 'output' / harvested['source']) if candidate.is_file()]
            return pins
        record, effective = overrides.admit(point_id, request, settings, point=point,
            population=population, axes=manifest['axes'], successful=successful_neighbour,
            context_sha256=override_context(manifest),
            evidence_directory=root / 'inputs/point-overrides/evidence')
        # Immutable copies, never edits to original input cards or completed results.
        rendered = overrides.toml_text(effective)
        config = 'config/overrides/' + record['receipt_sha256'] + '.toml'
        receipt = root / ('inputs/point-overrides/' + record['receipt_sha256'] + '.json')
        target = root / config
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)
        atomic_json(receipt, record)
        atomic_json(root / 'inputs/active-point-override.json', record)
        attempts = point.setdefault('attempt_history', [])
        if not attempts:
            attempts.append({k: point[k] for k in ('config', 'output_directory', 'override', 'override_receipt') if k in point})
            attempts[0].setdefault('output_directory', 'output')
        output_directory = 'attempts/' + record['receipt_sha256'] + '/output'
        attempt_identity = {'config': config, 'output_directory': output_directory,
                            'override': record, 'override_receipt': str(receipt)}
        if attempt_identity not in attempts:
            attempts.append(attempt_identity)
        history = point.setdefault('override_history', [])
        if point.get('override') and point['override'] != record:
            history.append({k: point[k] for k in ('config', 'output_directory', 'override', 'override_receipt') if k in point})
        point.update(base_config=base_config, **attempt_identity)
        atomic_json(directory / 'scan_manifest.json', manifest)
        return record


def cmd_override(args):
    from .state_io import read_json
    print(json.dumps(record_override(args.scandir, args.point, read_json(Path(args.record))), allow_nan=False))


def sigma_ref_fb(mp):
    """Per-point reference cross-section (fb) the signal was normalized to = σ_LO(MadGraph) × kfactor.
    This bridges mapyde's dimensionless µ95 to an ABSOLUTE σ upper-limit (σ_UL = µ95 × σ_ref), which is
    what the (mapyde−ATLAS)/ATLAS difference map compares against the published per-point σ-UL grid (the
    σ_theory cancels in the relative difference). Reads logs/madgraph.log + the run's TOML kfactor;
    returns None if unavailable (the contour overlay still works, only the difference map needs it)."""
    run_dir = os.path.join(REPO, mp["run_dir"])
    attempt = point_attempt_root(mp, run_dir)
    normalization = str(attempt / "output/normalization.json")
    if os.path.exists(normalization):
        from ravel.physics.native_normalization import load_normalization
        return load_normalization(normalization)["applied_cross_section_pb"] * 1000.0
    log = str(point_log_root(mp, run_dir) / "madgraph.log")
    sigma_pb = None
    if os.path.exists(log):
        try:
            for line in open(log, errors="ignore"):
                m = re.search(r"Cross-section\s*:\s*([0-9.eE+-]+)", line)
                if m:
                    sigma_pb = float(m.group(1))   # last match = the final result
        except OSError:
            sigma_pb = None
    if sigma_pb is None:
        # Fallback for RE-RUN / healed points whose madgraph.log lacks the "Cross-section :" summary
        # line (MadGraph reused a cached refine and did not re-print it): the σ that was actually fed
        # downstream is recorded in analysis.log as "Using cross section X" (pb). Same number, so the
        # σ_ref is faithful. Without this a healed point has sigma_ref_fb=None and BREAKS the rebase.
        alog = str(point_log_root(mp, run_dir) / "analysis.log")
        if os.path.exists(alog):
            try:
                for line in open(alog, errors="ignore"):
                    m = re.search(r"Using cross section\s+([0-9.eE+-]+)", line)
                    if m:
                        applied = float(m.group(1))
                        if math.isfinite(applied) and applied > 0:
                            # The converter logs the cross section it actually
                            # received, including k. Never apply that factor twice.
                            return applied * 1000.0
            except OSError:
                sigma_pb = None
    if sigma_pb is None or not math.isfinite(sigma_pb) or sigma_pb <= 0:
        return None
    kf = point_kfactor(mp)
    return sigma_pb * kf * 1000.0 if kf is not None else None


def point_kfactor(mp):
    """The FLAT k-factor this point's sigma_ref was normalized with (the TOML analysis.kfactor --
    the same value sigma_ref_fb() folded in). None if the TOML is unreadable: the NLO re-norm must
    then fail loud rather than guess what normalization it is replacing."""
    try:
        normalization = str(point_attempt_root(mp, Path(REPO) / mp["run_dir"]) / "output/normalization.json")
        if os.path.exists(normalization):
            from ravel.physics.native_normalization import load_normalization
            return load_normalization(normalization)["kfactor"]
        import tomllib
        cfg = tomllib.load(open(os.path.join(REPO, mp["run_dir"], mp["config"]), "rb"))
        value = cfg.get("analysis", {}).get("kfactor")
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            return None
        return float(value)
    except (ValueError, OSError, KeyError):
        return None


def apply_nlo_renorm(rows, contract, man):
    """Apply an explicitly supplied correction contract; no process defaults."""
    from ravel.physics.production_basis import renormalize
    return renormalize(rows, contract, man, point_kfactor)


def apply_production_transformation(rows, contract, base="."):
    from ravel.physics.production_basis import transform
    return transform(rows, contract, base)


def cmd_rebase(args):
    """Rebase from supplied component accounting and response ratios."""
    from ravel.physics.production_basis import load_contract, write_scan
    contract, base, commitment = load_contract(getattr(args, "transformation", None))
    scan_path = args.scan or os.path.join(args.scandir, "scan.json")
    scan = json.load(open(scan_path))
    if scan.get("model_basis"):
        raise ValueError("scan already carries model_basis; start from its source assembly")
    metadata = apply_production_transformation(scan["points"], contract, base)
    metadata["contract"] = commitment
    scan["model_basis"] = metadata
    write_scan(scan, args.out or scan_path, metadata)
    print(f"rebased {len(scan['points'])} points using the supplied production transformation")


def point_parameters(point):
    coordinates = point.get("parameters")
    if coordinates is None:
        # Supplied older manifests carry their coordinates as scalar fields.
        coordinates = {k: v for k, v in point.items() if type(v) in (int, float)}
    if not isinstance(coordinates, dict) or not coordinates or any(type(v) not in (int, float) or not math.isfinite(v) for v in coordinates.values()):
        raise ValueError("explicit finite point coordinates required")
    return coordinates


def point_attempt_root(point, run):
    """Resolve only the attempt selected by the manifest identity."""
    relative = _relative_path(point.get('output_directory', 'output'))
    expected = 'attempts/' + point['override']['receipt_sha256'] + '/output' if point.get('override') else 'output'
    if relative != expected:
        raise ValueError('point attempt must name its output directory')
    root = (Path(run) / relative).parent.resolve()
    if not root.is_relative_to(Path(run).resolve()):
        raise ValueError('point attempt escapes point directory')
    return root


def point_log_root(point, run):
    if point.get('override'):
        return Path(run) / 'logs/attempts' / point['override']['receipt_sha256']
    return Path(run) / 'logs'


def native_quantity_manifest(point, run):
    witness = point_attempt_root(point, run) / 'output/native_execution_result.json'
    if not witness.is_file():
        if point.get('output_directory') or (Path(run) / 'execution_state.json').exists():
            raise ValueError('native quantity receipt is missing for the selected attempt')
        return None
    try:
        report = json.loads(witness.read_text())
        expected_receipt = point.get('override', {}).get('receipt_sha256')
        if not isinstance(report, dict) or report.get('point_receipt_sha256') != expected_receipt:
            raise ValueError('native quantity lacks the effective point override receipt')
        pins = report.get('quantity_outputs')
        if not isinstance(pins, list) or not pins:
            raise ValueError('native quantity output manifest is missing')
        identities = {}
        for pin in pins:
            if (not isinstance(pin, dict) or not isinstance(pin.get('path'), str)
                    or not Path(pin['path']).is_absolute()
                    or not isinstance(pin.get('sha256'), str)
                    or not re.fullmatch(r'[0-9a-f]{64}', pin['sha256'])):
                raise ValueError('invalid native quantity output manifest entry')
            path = str(Path(pin['path']).resolve())
            if path in identities:
                raise ValueError('duplicate native quantity output manifest entry')
            identities[path] = pin['sha256']
        return identities
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError('invalid native quantity output manifest') from exc


def verify_native_quantity(source, pins, *, identity=None):
    from ravel.physics.native_normalization import fingerprint
    if pins is None:
        return
    if not source.is_file():
        raise ValueError('native quantity output is missing: ' + str(source))
    identity = fingerprint(source) if identity is None else identity
    if pins.get(str(source.resolve())) != identity['sha256']:
        raise ValueError('native quantity output is unlisted or its sha256 mismatches: ' + str(source))


def harvest_quantities(point, run):
    from ravel.physics.native_normalization import fingerprint
    coordinates = point_parameters(point)
    record = point.get('override')
    if record:
        from . import point_overrides as overrides
        overrides.verify(record, Path(run) / point['config'])
    pins = native_quantity_manifest(point, run)
    attempt = point_attempt_root(point, run)
    result = {"parameters": coordinates, "sources": {}}
    for quantity in point["quantities"]:
        source = attempt/_relative_path(quantity["source"])
        if not source.is_file():
            verify_native_quantity(source, pins)
            return None
        if not source.resolve().is_relative_to(attempt):
            raise ValueError("quantity source escapes point directory")
        identity = fingerprint(source)
        verify_native_quantity(source, pins, identity=identity)
        document = json.loads(source.read_text())
        if isinstance(document, dict) and "parameters" in document and document["parameters"] != coordinates:
            raise ValueError("quantity artifact parameters differ from the planned point")
        if quantity["source"] == "result.json" and isinstance(document, dict) and "limits" in document:
            errors = source_errors(document, run, required=True)
            if errors:
                raise ValueError("; ".join(errors))
        if record and pins is None and (not isinstance(document, dict) or document.get('point_receipt_sha256') != record['receipt_sha256']):
            raise ValueError('quantity lacks the effective point override receipt')
        value = document
        try:
            for key in quantity["field"].split('.'):
                value = value[key]
        except (KeyError, TypeError) as exc:
            raise MissingInputError(f"{quantity['source']}:{quantity['field']}") from exc
        if fingerprint(source) != identity:
            raise ValueError("quantity source changed during harvesting")
        json.dumps(value, allow_nan=False)
        # Inference quantities transport typed status and censoring alongside values.
        if isinstance(document, dict) and any(k in document for k in ("limits", "obs_limit", "mu95_obs")):
            result.setdefault("inference", {})[quantity["name"]] = read_limits(document).to_dict()
        result[quantity["name"]] = value
        result["sources"][quantity["name"]] = {**identity, "field": quantity["field"]}
    if record:
        result.update(overrides.metadata(record))
    return result


def point_statistics(document, run_dir):
    """A harvested point's uncertainty statement and recomputed statistics record.

    A full record is recomputed with ``situations.audit``; a result pack's summary is replaced by the
    record of the exclusion it is bound to, which must give the same outcome and labels. A record that
    does not recompute, or a held outcome, makes the point invalid: its limit is never harvested. A point
    written before these records existed carries neither.
    """
    from ravel.physics.inference import situations, uncertainty
    out = {}
    if "uncertainty" in document:
        errors = uncertainty.document_errors(document)
        if errors:
            raise ValueError("the uncertainty statement disagrees with the reported limits: " + "; ".join(errors[:3]))
        out["uncertainty"] = document["uncertainty"]
    block = document.get("statistics")
    if block is None:
        return out
    summary = None
    assessment_document = document
    if not (isinstance(block, dict) and block.get("kind") == situations.BLOCK_KIND):
        summary = block if isinstance(block, dict) else {}
        source = (document.get("limit_source") or {}).get("path") or (document.get("pointers") or {}).get("exclusion")
        path = Path(run_dir) / source if isinstance(source, str) else None
        if path is None or not path.is_file():
            raise ValueError("the statistics summary names no exclusion record to recompute it from")
        assessment_document = json.loads(path.read_text())
        block = assessment_document.get("statistics")
    errors = (situations.audit(block) or situations.result_document_errors(block, assessment_document)
              or situations.result_document_errors(block, document))
    if errors:
        raise ValueError("the statistics record does not recompute: " + "; ".join(errors[:3]))
    errors = uncertainty.document_errors(assessment_document) or uncertainty.document_errors(document)
    if errors:
        raise ValueError("the uncertainty statement disagrees with the reported limits: " + "; ".join(errors[:3]))
    outcome, labels = block["validity"]["outcome"], situations.labels(block)
    if outcome == "held":
        raise ValueError("the statistics outcome is held: " + "; ".join(labels))
    if summary is not None and (summary.get("outcome"), summary.get("labels")) != (outcome, labels):
        raise ValueError("the result's statistics summary differs from its exclusion record")
    out["statistics"] = block
    return out


def harvest_point(mp):
    """Read a finished point's limit -> dict(mu95_obs, mu95_exp, mu95_exp_band, m_parent, m_lsp,
    sigma_ref_fb, source) or None. Prefers result.json (the RESULT-PACK headline); falls back to the
    native driver's output/exclusion.json (obs_limit + the 5-entry exp_limits band), keyed to the
    manifest masses. Lets the scan harvest either the container path (result_pack) or the native
    path (run-pipeline-native.sh ends at pyhf -> exclusion.json)."""
    run_dir = os.path.join(REPO, mp["run_dir"])
    from ravel.workflow.review_enforcement import delivery_errors, required
    review_errors = delivery_errors(run_dir)
    if review_errors:
        raise ValueError("scientific review prevents scan harvesting: " + "; ".join(review_errors))
    if os.path.exists(os.path.join(run_dir, "execution_state.json")):
        from ravel.workflow.execution import validate_execution
        errors = validate_execution(run_dir)
        if errors:
            raise ValueError(f"stale/invalid execution artifacts: {errors}")
    if "quantities" in mp:
        return harvest_quantities(mp, run_dir)
    if mp.get('override'):
        from . import point_overrides as overrides
        overrides.verify(mp['override'], Path(run_dir) / mp['config'])
        witness = point_attempt_root(mp, run_dir) / 'output/native_execution_result.json'
        if not witness.is_file() or json.loads(witness.read_text()).get('point_receipt_sha256') != mp['override']['receipt_sha256']:
            raise ValueError('native output lacks the effective point override receipt')
    pins = native_quantity_manifest(mp, run_dir)
    attempt = point_attempt_root(mp, run_dir)
    sref = sigma_ref_fb(mp)
    for relative in ("result.json", "output/exclusion.json"):
        path = attempt / relative
        if not os.path.exists(path):
            if pins is not None and relative == "output/exclusion.json":
                verify_native_quantity(path, pins)
            continue
        verify_native_quantity(path, pins)
        try:
            with open(path) as fh:
                d = json.load(fh)
            if not isinstance(d, dict) or not any(k in d for k in ("limits", "obs_limit", "mu95_obs")):
                raise ValueError("artifact has no limit representation")
            if relative == "result.json":
                errors = source_errors(d, run_dir, required=("limits" in d or "limit_status" in d))
                if errors:
                    raise ValueError("; ".join(errors))
                if os.path.isfile(os.path.join(run_dir, "inputs/task_contract.json")):
                    from ravel.validation.certificates import validate_pack_certificates
                    primary = (d.get("limit_source") or {}).get("path") or (d.get("pointers") or {}).get("exclusion")
                    validate_pack_certificates(run_dir, primary, (d.get("pointers") or {}).get("cert"))
            # Preserve the documented archive diagnostic; do not apply it
            # to a modern explicitly resolved result merely sharing these values.
            band = d.get("exp_limits", d.get("mu95_exp_band"))
            obs = d.get("obs_limit", d.get("mu95_obs"))
            if "limit_status" not in d and "limits" not in d and obs == 1.0 \
                    and isinstance(band, list) and len(band) == 5 and len(set(band)) == 1:
                d["quality"] = "floored-legacy"
            limits = read_limits(d)
            coordinates = point_parameters(mp)
            for key, value in coordinates.items():
                if d.get(key) is not None and float(d[key]) != float(value):
                    raise ValueError(f"{key} differs from the planned point")
            out = dict(mu95_obs=limits.observed.value,
                       mu95_exp=limits.expected[2].value,
                       mu95_exp_band=[c.value for c in limits.expected],
                       **coordinates, parameters=coordinates,
                       sigma_ref_fb=d.get("sigma_ref_fb", sref), source=os.path.basename(path))
            if out["sigma_ref_fb"] is not None and (type(out["sigma_ref_fb"]) not in (int, float)
                    or not math.isfinite(out["sigma_ref_fb"]) or out["sigma_ref_fb"] <= 0):
                raise ValueError("sigma_ref_fb must be a finite positive number or null")
            for key in ("quality", *NUMERICAL_METADATA):
                if key in d:
                    out[key] = d[key]
            attach_limits(out, result=limits)
            out.update(point_statistics(d, run_dir))
            if required(run_dir):
                from ravel.workflow.physics_review import status
                out["physics_review"] = status(run_dir)
            if mp.get('override'):
                out.update(overrides.metadata(mp['override']))
            return out
        except (ValueError, TypeError, OSError) as exc:
            # A corrupt preferred headline cannot silently fall back to an older
            # exclusion file. Preserve the failed point in the planned population.
            raise ValueError(f"invalid limit artifact {path}: {exc}") from exc
    return None


def point_status(mp):
    """Return (state, mu95_obs_or_None) for one manifest point by inspecting its run dir."""
    run_dir = os.path.join(REPO,mp["run_dir"])
    if os.path.exists(os.path.join(run_dir,"execution_state.json")):
        from ravel.workflow.scan_babysitter import point_state
        state = point_state(run_dir)
        if state != "done":
            return state,None
        from ravel.workflow.state_io import read_json
        try:
            report=read_json(point_attempt_root(mp, run_dir)/"output/native_execution_result.json")
        except (ValueError,OSError):
            return "failed",None
        if mp.get('override') and report.get('point_receipt_sha256') != mp['override']['receipt_sha256']:
            return 'failed', None
        if report.get("statistics")=="yields" and "quantities" not in mp:
            return "done",None
    try:
        h = harvest_point(mp)
    except (ValueError, OSError):
        return "failed", None
    if h is not None:
        return "done", h.get("mu95_obs")
    status_txt = str(point_log_root(mp, run_dir) / "STATUS.txt")
    if os.path.exists(status_txt):
        tail = open(status_txt).read().strip().splitlines()
        last = tail[-1] if tail else ""
        if "FAIL" in last or "STOPPED" in last:
            return "failed", None
        if any(k in last for k in ("START", "pipeline start", "PASS", "ALL_STAGES_COMPLETE")):
            return "running", None
    return "pending", None


def cmd_status(args):
    scandir, man = load_manifest(args.scandir)
    counts = {"done": 0, "running": 0, "failed": 0, "pending": 0}
    print(f"scan {man['name']}  ({man['n_points']} points)")
    for mp in man["points"]:
        st, mu = point_status(mp)
        counts[st] += 1
        mus = f"  mu95_obs={mu:.3f}" if mu is not None else ""
        print(f"  {mp['tag']}  {point_parameters(mp)}  [{st}]{mus}")
    print("  " + "  ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_assemble(args):
    directory, manifest = load_manifest(args.scandir)
    from .point_overrides import metadata
    rows = []; missing = []; invalid = {}
    general = manifest.get("schema_version") == SCHEMA_VERSION
    for point in manifest["points"]:
        try:
            harvested = harvest_point(point)
        except (ValueError, OSError) as exc:
            invalid[point["tag"]] = str(exc)
            harvested = None
        if harvested is None:
            missing.append(point["tag"])
            continue
        rows.append({"tag": point["tag"], "status": "completed", **harvested, **metadata(point.get('override'))})
    if not rows:
        print("no completed points; preserving the complete missing population")
    result = {"schema_version": SCHEMA_VERSION, "name": manifest["name"],
        "model": manifest.get("model"), "analysis_id": manifest.get("analysis_id"),
        "n_planned": manifest["n_points"], "n_done": len(rows), "n_missing": len(missing),
        "missing_tags": missing, "invalid_points": invalid, "points": rows,
        "point_population": []}
    from ravel.physics.inference.situations import labels as statistics_labels
    qualified = {}
    for row in rows:
        for label in statistics_labels(row.get("statistics")):
            qualified.setdefault(label, []).append(row["tag"])
    if qualified:
        result["limitations"] = [{"key": "statistics-qualified", "note": label, "points": tags}
                                 for label, tags in qualified.items()]
    completed = {row['tag']: row for row in rows}
    for point in manifest['points']:
        # Historical producers sometimes supplied coordinates only in the result.
        supplied = point if point.get('parameters') or any(type(v) in (int, float) for v in point.values()) else completed.get(point['tag'])
        coordinates = point_parameters(supplied) if supplied else {}
        result['point_population'].append({'tag': point['tag'], 'parameters': coordinates,
            'status': 'failed' if point['tag'] in invalid else 'missing' if point['tag'] in missing else 'completed',
            **metadata(point.get('override'))})
    if "data_schema" in manifest:
        result["data_schema"] = manifest["data_schema"]
    if general:
        result.update({key: manifest[key] for key in ("axes", "datasets", "quantities", "output")})
        output = manifest["output"]
    else:
        # Numerical transport for explicitly supplied older manifests; no grid is inferred.
        for row in rows:
            row["excluded_obs"] = read_limits(row).observed.exclusion()
        if "plane" in manifest:
            result["plane"] = manifest["plane"]
        result["n_observed_roots"] = sum(read_limits(row).observed.usable() for row in rows)
        result["n_expected_roots"] = sum(read_limits(row).expected[2].usable() for row in rows)
        output = {"format": "json", "path": "scan.json"}
    if getattr(args, "nlo_renorm", None):
        from ravel.physics.xsec_conventions import MissingInput
        raise MissingInput("supply --normalization-contract; process-selected corrections are retired")
    normalization = None
    if getattr(args, "normalization_contract", None):
        # The supplied contract binds every row by tag and coordinate (named axes or limit rows).
        normalization = apply_nlo_renorm(rows, args.normalization_contract, manifest)
        result["points"] = rows
        result["normalization"] = normalization
    out = Path(args.out) if args.out else Path(directory)/output["path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    if normalization is not None and not general:
        from ravel.physics.production_basis import write_scan
        write_scan(result, out, normalization)
    elif output["format"] == "json":
        from ravel.workflow.state_io import atomic_json
        atomic_json(out, result)
    else:
        import csv
        names = [a["name"] for a in manifest["axes"]]
        quantities = [q["name"] for q in manifest["quantities"]]
        with out.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=["tag", *names, *quantities, "overridden", "regime", "receipt_sha256", "status"])
            writer.writeheader()
            completed = {row['tag']: row for row in rows}
            for population_row in result['point_population']:
                row = completed.get(population_row['tag'], population_row)
                writer.writerow({"tag": row["tag"], **row["parameters"],
                    **{key: row[key] for key in ('overridden', 'regime', 'receipt_sha256')}, 'status': population_row['status'],
                    **{q: json.dumps(row[q], allow_nan=False) if isinstance(row.get(q), (dict, list)) else row.get(q) for q in quantities}})
        # Metadata and custody remain available even in flat-table output.
        from ravel.workflow.state_io import atomic_json
        atomic_json(out.with_suffix(out.suffix+'.metadata.json'), result)
    print(f"assembled {len(rows)}/{manifest['n_points']} supplied points -> {out}")


def _toml_nevents(run_dir, config_rel):
    """Read madgraph.run.nevents from a point's TOML so the prep + driver agree on event count."""
    import tomllib
    path = os.path.join(run_dir, config_rel)
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)
    return int(cfg["madgraph"]["run"]["nevents"])


def launch_point(mp, manifest, args, *, plan=None):
    """Launch exactly the validated capability plan for this point."""
    run_dir = os.path.join(REPO, mp["run_dir"])
    if args.backend == "native":
        from ravel.physics.native_pipeline import build_execution_plan, write_plan
        from ravel.paths import module_command
        plan = plan or build_execution_plan(
            run_dir, mp["config"], model=manifest.get("model"),
            analysis_id=manifest.get("analysis_id"), m_parent=mp.get("m_parent"),
            m_lsp=mp.get("m_lsp"), pdf=getattr(args, "pdf", None),campaign_points=len(manifest.get("points",[mp])))
        cap = plan["capability"]
        print(f"  {mp['tag']}: {cap['model']} -> {cap['routine']} "
              f"({cap['preparation']}, {cap['detector']}, {cap['statistics_adapter']})")
        print("    stages: " + " -> ".join(s["stage"] for s in plan["stages"]))
        if not args.go:
            if getattr(args,"write_plans",False):
                print(f"    proposal saved: {write_plan(plan)}")
            return plan
        from ravel.physics.native_pipeline import verify_execution_approval
        verify_execution_approval(plan)
        path = Path(plan["plan_path"])
        cmd = module_command("ravel.physics.native_pipeline", "run", "--plan", path)
    else:
        if args.go:
            die("live container dispatch is unsupported until an adapter binds exact execution inputs to approval")
        cmd = ["bash", os.path.join(REPO, "native/scripts/run-pipeline.sh"), run_dir, mp["config"]]
        print(f"  {mp['tag']}: container {mp['config']} [DRY DIAGNOSTIC ONLY; live dispatch unsupported]")
        if not args.go:
            return cmd
    logs = point_log_root(mp, run_dir)
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "orchestrator_launch.log").open("a") as log:
        from ravel.workflow.launch_authorization import authorized_popen
        process = authorized_popen(run_dir, plan["required_compute_plan"], cmd,
                                   context={"kind": "scan-dispatch", "plan_sha256": plan["plan_sha256"]},
                                   cwd=run_dir, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    print(f"    -> backgrounded pid={process.pid}")
    return process


def cmd_launch(args):
    scandir, man = load_manifest(args.scandir)
    if args.max < 1:
        die("--max must be positive")
    native = args.backend == "native"
    if not native:
        if args.go:
            die("live container dispatch is unsupported until an adapter binds exact execution inputs to approval")
        running = [mp["tag"] for mp in man["points"] if point_status(mp)[0] == "running"]
        if running and not args.force:
            die(f"point(s) {running} are RUNNING in the shared container backend")
        if args.max > 1 and not args.force:
            die("container backend is sequential; --max must be 1")
    pending = [mp for mp in man["points"] if point_status(mp)[0] == "pending" or
               (native and getattr(args,"resume",False) and point_status(mp)[0] == "failed"
                and (mp.get("override") or os.path.exists(os.path.join(REPO,mp["run_dir"],"execution_state.json"))))]
    if not pending:
        print("no pending points (all done/running/failed)")
        return
    from ravel.workflow import gate_wiring
    pending = [mp for mp in pending if gate_wiring.dispatch_permitted(scandir, mp['tag'])[0]]
    ranked = gate_wiring.prioritize_pending(scandir, [{'id': mp['tag'], 'point': mp} for mp in pending])
    todo = [row['point'] for row in ranked[:args.max]]
    plans = []
    if native:
        from ravel.physics.native_pipeline import build_execution_plan
        # Validate the entire selected batch before preparing or launching any
        # expensive work. A wrong-family request must not partly launch a scan.
        try:
            for mp in todo:
                plans.append(build_execution_plan(
                    os.path.join(REPO,mp["run_dir"]),mp["config"],model=man.get("model"),
                    analysis_id=man.get("analysis_id"),m_parent=mp.get("m_parent"),
                    m_lsp=mp.get("m_lsp"),pdf=getattr(args,"pdf",None),campaign_points=len(man["points"])))
            if args.go:
                from ravel.physics.native_pipeline import verify_execution_approval
                for plan in plans:
                    verify_execution_approval(plan)
        except (ValueError,OSError,KeyError) as exc:
            die(f"native execution plan rejected before launch: {exc}")
    print(f"{len(pending)} pending; {len(todo)} selected [{args.backend}]"
          f"{' [DRY, compute_authorized=false]' if not args.go else ''}")
    for i,mp in enumerate(todo):
        if args.go:
            gate_wiring.bind_steering_child(scandir, Path(REPO) / mp['run_dir'], mp['tag'])
            launch_point(mp,man,args,plan=plans[i] if native else None)
        else:
            with gate_wiring.steering_dispatch(scandir, mp['tag']):
                launch_point(mp,man,args,plan=plans[i] if native else None)
    if not args.go:
        print("  (dry plan; pass --go after the compute plan is approved)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("spec")
    p.add_argument("--dry-run", action="store_true",
                   help="enumerate the grid points WITHOUT writing run dirs / TOMLs / manifest")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("override"); p.add_argument("scandir")
    p.add_argument("--point", required=True); p.add_argument("--record", required=True)
    p.set_defaults(fn=cmd_override)
    p = sub.add_parser("status"); p.add_argument("scandir"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("assemble"); p.add_argument("scandir")
    p.add_argument("--out", default=None)
    p.add_argument("--normalization-contract", default=None, metavar="PATH",
                   help="supplied per-point correction conventions, interpolation and justifications")
    p.set_defaults(fn=cmd_assemble)
    p = sub.add_parser("rebase"); p.add_argument("scandir")
    p.add_argument("--transformation", required=True, metavar="PATH",
                   help="supplied source/target cross sections, component states and response ratios")
    p.add_argument("--scan", default=None, help="scan.json path (default <scandir>/scan.json)")
    p.add_argument("--out", default=None, help="output path (default: in-place)")
    p.set_defaults(fn=cmd_rebase)
    p = sub.add_parser("launch"); p.add_argument("scandir")
    p.add_argument("--backend", choices=["native", "container"], default="native",
                   help="native = run-pipeline-native.sh (VM-free, parallel-ok; preps each point's "
                        "inputs from supplied recipes); container = run-pipeline.sh (shared VM, sequential)")
    p.add_argument("--max", type=int, default=1,
                   help="max points to launch this call (native points run in parallel)")
    p.add_argument("--go", action="store_true")
    p.add_argument("--resume", action="store_true",
                   help="include failed/interrupted durable native points after input/tool repair; preserve prior attempts")
    p.add_argument("--write-plans", action="store_true",
                   help="persist dry native proposals for review and approval binding; does not authorize compute")
    p.add_argument("--pdf", choices=["cteq6l1", "nn23nlo", "nnpdf30"], default=None,
                   help="PDF declaration checked by the selected native adapter")
    p.add_argument("--force", action="store_true",
                   help="override the container sequential-only gate (ONLY with isolated VMs per point)")
    p.set_defaults(fn=cmd_launch)
    args = ap.parse_args()
    if args.cmd != "status":
        refuse_controller_owned(args.cmd, args.spec if args.cmd == "plan" else args.scandir)
    args.fn(args)


if __name__ == "__main__":
    main()
