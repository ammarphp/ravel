"""Execution-bound compiled matrix-element probe, with no generated events.

The first operation is deliberately restricted to a known SM QED tree control.
The static UFO route remains non-executing. A private MG5 copy, explicit effective
card, compiled parameter dump and independent analytic oracle provide a scoped
numerical witness. They do not certify a general model or fast simulation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from ravel.validation import model_probe_witness as witness


OPERATION = "qed-annihilation-tree"
MODEL = "sm"
PROCESS = "e+ e- > mu+ mu- / z h QED=2"
ENV_KEYS = {"LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "SDKROOT",
            "MACOSX_DEPLOYMENT_TARGET", "CONDA_PREFIX", "COMPILER_PATH", "GCC_EXEC_PREFIX"}
EXCLUDED = {".git", "__pycache__", ".DS_Store"}


def _keys(value, required, name):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError(f"{name} requires exactly {', '.join(sorted(required))}")


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be nonempty text")


def validate(config):
    _keys(config, {"operation", "runtime", "parameter_card", "phase_space_file", "oracle_file",
                   "expected_parameters", "required_checks", "max_seconds"}, "model-probe config")
    if config["operation"] != OPERATION:
        raise ValueError(f"model probe currently supports only {OPERATION}")
    runtime = config["runtime"]
    _keys(runtime, {"madgraph", "python", "compiler", "make", "artifacts", "environment"}, "runtime")
    for key in ("madgraph", "python", "compiler", "make"):
        _text(runtime[key], key)
        if not Path(runtime[key]).is_absolute() or re.search(r"[\s'\";]", runtime[key]):
            raise ValueError("MG5 runtime paths must be absolute and contain no whitespace, quotes or semicolons")
    if not isinstance(runtime["artifacts"], list):
        raise ValueError("runtime artifacts must be a unique path list")
    for path in runtime["artifacts"]:
        _text(path, "runtime artifact")
        if not Path(path).is_absolute():
            raise ValueError("runtime dependency artifacts must be absolute files")
    if len(runtime["artifacts"]) != len(set(runtime["artifacts"])):
        raise ValueError("runtime artifacts must be a unique path list")
    environment = runtime["environment"]
    if not isinstance(environment, dict) or set(environment) - ENV_KEYS:
        raise ValueError("unsupported model-probe runtime environment key")
    for key, value in environment.items():
        _text(value, key)
    expected = config["expected_parameters"]
    _keys(expected, {"aEWM1", "Me", "MM"}, "expected parameters")
    witness.number(expected["aEWM1"], "aEWM1", positive=True)
    if any(type(expected[k]) not in (int, float) or expected[k] != 0 for k in ("Me", "MM")):
        raise ValueError("first analytic control requires Me=MM=0")
    required = config["required_checks"]
    if (not isinstance(required, list) or any(not isinstance(x, str) for x in required)
            or len(required) != len(set(required)) or set(required) - set(witness.CHECK_NAMES)
            or not set(witness.MANDATORY_CHECKS) <= set(required)):
        raise ValueError("required checks must include effective_parameters, amplitude_reference and lorentz")
    if type(config["max_seconds"]) is not int or not 1 <= config["max_seconds"] <= 3600:
        raise ValueError("probe max_seconds must be an integer from 1 to 3600")
    for key in ("parameter_card", "phase_space_file", "oracle_file"):
        _text(config[key], key)


def _path(value, base, *, directory=False):
    raw = Path(value).expanduser()
    path = raw if raw.is_absolute() else Path(base) / raw
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError(f"scientific input must not traverse a symlink: {path}")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f"missing {'directory' if directory else 'file'}: {path}")
    return path.resolve()


def _load(path):
    def unique(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"nonfinite JSON value: {value}")
    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=invalid)


def _runtime_files(directory):
    result = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part in EXCLUDED for part in relative.parts) or path.suffix in {".pyc", ".pyo", ".pkl"}:
            continue
        if path.is_symlink():
            if not path.resolve().is_relative_to(directory) or path.is_dir():
                raise ValueError(f"runtime symlink escapes its source or is a directory: {path}")
        if path.is_file():
            result.append(path.resolve())
    return sorted(set(result))


def _card_parameters(path):
    block, values = None, {}
    for raw in path.read_text().splitlines():
        tokens = raw.split("#", 1)[0].strip().split()
        if not tokens:
            continue
        if tokens[0].lower() == "block":
            if len(tokens) < 2:
                raise ValueError("malformed parameter-card block")
            block = tokens[1].lower()
            continue
        if tokens[0].lower() == "decay":
            block = None
            if len(tokens) != 3 or tokens[2].lower() == "auto":
                raise ValueError("model probe requires explicit finite widths, never DECAY Auto")
            witness.number(float(tokens[2].replace("D", "e").replace("d", "e")), "card width")
            continue
        if block in {"sminputs", "mass"}:
            if len(tokens) != 2:
                raise ValueError("unsupported scalar SMINPUTS/MASS parameter row")
            address = (block, int(tokens[0]))
            if address in values:
                raise ValueError(f"duplicate parameter-card address: {address}")
            values[address] = witness.number(float(tokens[1].replace("D", "e").replace("d", "e")), "card parameter")
    try:
        return {"aEWM1": values[("sminputs", 1)], "Me": values[("mass", 11)], "MM": values[("mass", 13)]}
    except KeyError as exc:
        raise ValueError("explicit inverse alpha, electron mass and muon mass are required in the parameter card") from exc


def inputs(config, base_dir):
    validate(config)
    runtime = config["runtime"]
    source = _path(runtime["madgraph"], base_dir, directory=True)
    for name in ("bin/mg5_aMC", "VERSION", "models/sm/parameters.py", "models/sm/restrict_default.dat"):
        if not (source / name).is_file():
            raise ValueError(f"missing pinned MG5 control input: {name}")
    if not re.search(r"^version\s*=\s*2\.9\.27\s*$", (source / "VERSION").read_text(), re.M):
        raise ValueError("first compiled adapter is pinned to MG5 2.9.27")
    files = _runtime_files(source)
    for key in ("python", "compiler", "make"):
        path = Path(runtime[key]).resolve()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f"missing executable {key}")
        files.append(path)
    files += [_path(path, base_dir) for path in runtime["artifacts"]]
    files += [_path(config[key], base_dir) for key in ("parameter_card", "phase_space_file", "oracle_file")]
    card = _path(config["parameter_card"], base_dir)
    if _card_parameters(card) != config["expected_parameters"]:
        raise ValueError("supplied parameter card differs from declared effective point")
    points = witness.validate_points(_load(_path(config["phase_space_file"], base_dir)))
    witness.validate_oracle(_load(_path(config["oracle_file"], base_dir)), points, config["expected_parameters"])
    return sorted(set(files))


def fingerprint(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "size": path.stat().st_size}


def _materialize_aliases(work):
    """Make MG5's bounded standalone output regular before final custody.

    MG5 2.9.27 leaves four unused event-generation include placeholders in a
    standalone export. They are the only dangling links allowed for removal,
    after the actual standalone executable has successfully evaluated. All live
    aliases must resolve to regular files inside this private work directory.
    Validate the full topology before replacing or removing any link.
    """
    work = Path(work).absolute()
    if any(path.is_symlink() for path in (work, *work.parents)) or not work.is_dir():
        raise ValueError("alias materialization requires a regular private work directory")
    placeholders = {f"PROC_probe/SubProcesses/{name}.inc": f"../Source/{name}.inc"
                    for name in ("lhe_event_infos", "run_config", "maxparticles", "run")}
    prepared = []
    for link in sorted(path for path in work.rglob("*") if path.is_symlink()):
        relative, raw_target = link.relative_to(work).as_posix(), str(link.readlink())
        try:
            target = link.resolve()
        except RuntimeError as exc:
            raise ValueError("generated alias contains a symlink cycle") from exc
        if not target.is_relative_to(work):
            raise ValueError("generated alias escapes the private work directory")
        if not target.exists():
            if placeholders.get(relative) != raw_target:
                raise ValueError("unknown dangling generated alias")
            prepared.append({"link": link, "raw_target": raw_target, "target": None})
        else:
            if not target.is_file():
                raise ValueError("generated alias target must be a regular internal file")
            mode = target.stat().st_mode & 0o7777
            if mode & 0o7000:
                raise ValueError("generated alias target has unsupported special permission bits")
            temporary = link.with_name(link.name + ".ravel-materialization")
            if temporary.exists() or temporary.is_symlink():
                raise ValueError("generated alias temporary destination already exists")
            prepared.append({"link": link, "raw_target": raw_target, "target": target,
                             "fingerprint": fingerprint(target), "mode": mode})
    records = []
    for row in prepared:
        link, target = row["link"], row["target"]
        record = {"path": str(link), "original_link_target": row["raw_target"]}
        if target is None:
            link.unlink()
            record.update(action="removed_unused_standalone_placeholder",
                          reason="Exact pinned event-generation include alias; absent and unused by the successfully evaluated standalone executable")
        else:
            temporary = link.with_name(link.name + ".ravel-materialization")
            with target.open("rb") as source, temporary.open("xb") as destination:
                shutil.copyfileobj(source, destination)
            temporary.chmod(row["mode"])
            if (fingerprint(target) != row["fingerprint"]
                    or target.stat().st_mode & 0o7777 != row["mode"]
                    or fingerprint(temporary)["sha256"] != row["fingerprint"]["sha256"]
                    or temporary.stat().st_size != row["fingerprint"]["size"]):
                raise ValueError("generated alias target changed during byte materialization")
            temporary.replace(link)
            record.update(action="materialized_internal_file", source={**row["fingerprint"], "mode": row["mode"]},
                          materialized={**fingerprint(link), "mode": link.stat().st_mode & 0o7777})
        records.append(record)
    if any(path.is_symlink() for path in work.rglob("*")):
        raise ValueError("generated work still contains an alias after materialization")
    for row in prepared:
        if row["target"] is not None:
            copied = fingerprint(row["link"])
            if (fingerprint(row["target"]) != row["fingerprint"]
                    or row["target"].stat().st_mode & 0o7777 != row["mode"]
                    or copied["sha256"] != row["fingerprint"]["sha256"]
                    or copied["size"] != row["fingerprint"]["size"]
                    or row["link"].stat().st_mode & 0o7777 != row["mode"]):
                raise ValueError("generated alias bytes or mode changed after materialization")
    return records


def _write(path, value):
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with Path(path).open("x") as stream:
        stream.write(text)


def _private_workspace(parent, output):
    """Reserve WORK for the output already authenticated by _approved_worker."""
    parent, output = Path(parent).absolute(), Path(output).absolute()
    if any(path.is_symlink() for path in (parent, *parent.parents, output, *output.parents)):
        raise ValueError("attempt workspace and selected output must not traverse symlinks")
    try:
        selected = output.relative_to(parent / "outputs").as_posix()
    except ValueError as exc:
        raise ValueError("attempt workspace requires its selected in-run output") from exc
    if not parent.is_dir() or not re.fullmatch(r"(?:attempt|repair)-[1-9][0-9]*", selected):
        raise ValueError("attempt workspace requires one selected attempt directory")
    work = parent / "work/model-probe" / selected
    if any(path.is_symlink() for path in (work, *work.parents)) or work.exists():
        raise ValueError("private selected-attempt workspace already exists or traverses a symlink")
    work.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(exist_ok=False)
    return work


def _deliver_capsule(work, process, subdir, output, measured):
    """Deliver checked nonempty byte copies; preserve the full build in WORK."""
    work, process, subdir, output = (Path(path).absolute() for path in (work, process, subdir, output))
    if (any(path.is_symlink() for directory in (work, process, subdir, output)
            for path in (directory, *directory.parents))
            or not all(directory.is_dir() for directory in (work, process, subdir, output))
            or process != work / "PROC_probe" or not subdir.is_relative_to(process / "SubProcesses")):
        raise ValueError("capsule requires regular internal generated directories and a regular output")
    if any(path.is_symlink() for path in work.rglob("*")):
        raise ValueError("retained attempt workspace contains an unmaterialized alias")
    capsule = output / "compiled-witness"
    if capsule.exists() or capsule.is_symlink():
        raise ValueError("capsule destination already exists")
    selected = [(subdir / "check", capsule / "check"),
                (process / "Cards/param_card.dat", capsule / "param_card.dat"),
                (work / "commands.mg5", capsule / "commands.mg5"),
                (work / "evaluate.log", capsule / "evaluate.log")]
    witness_sources = {"driver": subdir / "check_sa.f", "matrix_element": subdir / "matrix.f",
                       "external_legs": subdir / "nexternal.inc", "external_masses": subdir / "pmass.inc",
                       "effective_parameters": process / "Source/MODEL/input.inc",
                       "effective_couplings": process / "Source/MODEL/coupl.inc"}
    selected += [(path, capsule / "generated" / path.relative_to(process)) for path in witness_sources.values()]
    for root in (process / "Source", process / "SubProcesses"):
        selected += [(path, capsule / "generated" / path.relative_to(process)) for path in sorted(root.rglob("*"))
                     if path.is_file() and path.suffix in {".f", ".inc"} and path.stat().st_size > 0]
    selected += [(path, capsule / path.name) for path in sorted(work.glob("*.log"))
                 if path.is_file() and path.stat().st_size > 0]
    prepared = {}
    for source, destination in selected:
        if (any(path.is_symlink() for path in (source, *source.parents))
                or not source.is_file() or not source.is_relative_to(work)):
            raise ValueError("capsule source must be an internal regular file")
        before = {**fingerprint(source), "mode": source.stat().st_mode & 0o7777}
        if before["size"] == 0 or before["mode"] & 0o7000:
            raise ValueError("capsule source must be nonempty with supported permission bits")
        if destination in prepared and prepared[destination][0] != source:
            raise ValueError("capsule has conflicting selected byte copies")
        prepared[destination] = (source, before)
    artifacts = [{**fingerprint(path), "mode": path.stat().st_mode & 0o7777}
                 for path in sorted(work.rglob("*")) if path.is_file()]
    capsule.mkdir(exist_ok=False)
    rows = []
    for destination, (source, before) in prepared.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        destination.chmod(before["mode"])
        after = {**fingerprint(destination), "mode": destination.stat().st_mode & 0o7777}
        if ({**fingerprint(source), "mode": source.stat().st_mode & 0o7777} != before
                or any(before[key] != after[key] for key in ("sha256", "size", "mode"))):
            raise ValueError("capsule source/copy bytes or mode changed")
        rows.append({"source": before, "delivered": after})
    if (artifacts != [{**fingerprint(path), "mode": path.stat().st_mode & 0o7777}
                      for path in sorted(work.rglob("*")) if path.is_file()]
            or any(path.is_symlink() for path in work.rglob("*"))):
        raise ValueError("retained attempt workspace changed during capsule delivery")
    if parse_measurements((capsule / "evaluate.log").read_text(), measured["m2"]) != measured:
        raise ValueError("delivered measurement byte copy differs from the actual compiled witness")
    manifest = capsule / "capsule-manifest.json"
    _write(manifest, {"schema_version": 1, "kind": "compiled_model_probe_capsule", "physics_validated": False,
        "copies": rows, "retained_workspace": {"path": str(work), "artifacts": artifacts,
            "custody": "Supplemental complete workspace inventory verified at capsule delivery. Lifecycle reuse checks the delivered capsule and bound original inputs/runtime; it does not automatically rehash WORK."},
        "witness_files": {name: str(capsule / "generated" / path.relative_to(process))
                          for name, path in witness_sources.items()},
        "empty_workspace_files_retained": [row for row in artifacts if row["size"] == 0],
        "scope": "Compiled witness and selected generated Fortran/card/log byte copies; complete tool/build/cache evidence retained in WORK, not a portable toolchain"})
    return {"directory": str(capsule), "manifest": fingerprint(manifest),
            "compiled_binary": fingerprint(capsule / "check"), "measurement_log": fingerprint(capsule / "evaluate.log")}


def _approved_worker(config, output_dir):
    output = Path(output_dir).absolute()
    if re.search(r"[\s'\";]", str(output)):
        raise ValueError("MG5 output paths must contain no whitespace, quotes or semicolons")
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("model-probe output must not traverse symlinks")
    for parent in (output, *output.parents):
        if (parent / "inputs/science-plan.json").is_file():
            from ravel.workflow import science
            proposal = science.verify_worker(parent)
            spec = science.execution_spec(parent)
            if (spec["mode"] != "domain" or spec["task"].get("domain") != "model-probe"
                    or spec["task"].get("config") != config):
                raise ValueError("model probe differs from the current approved scientific task")
            if config["max_seconds"] > proposal["max_seconds"]:
                raise ValueError("model-probe ceiling exceeds the approved supervisor ceiling")
            if not output.is_relative_to(parent / "outputs"):
                raise ValueError("probe outputs must be inside the approved output root")
            if output.resolve() != (parent / proposal["output_directory"]).resolve():
                raise ValueError("probe output differs from the exact currently selected attempt")
            return parent
    raise ValueError("compiled model probe requires its approved supervised scientific worker")


def commands(runtime, process_dir):
    return ("set auto_update 0\nset automatic_html_opening False\nset nb_core 1\nset run_mode 0\n"
            f"set fortran_compiler {runtime['compiler']}\nimport model {MODEL}\n"
            f"generate {PROCESS}\noutput standalone {process_dir} -nojpeg\nquit\n")


def driver(evaluation_points, aewm1_symbol, ee_symbol):
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", symbol) for symbol in (aewm1_symbol, ee_symbol)):
        raise ValueError("invalid generated Fortran parameter symbol")
    lines = ["      PROGRAM RAVEL_PROBE", "      IMPLICIT NONE", "      REAL*8 ZERO",
             "      PARAMETER (ZERO=0D0)", "      INCLUDE 'coupl.inc'",
             "      INCLUDE '../../Source/MODEL/input.inc'", "      INCLUDE 'nexternal.inc'",
             "      REAL*8 P(0:3,NEXTERNAL), PMASS(NEXTERNAL), ANS", "      INTEGER I",
             "      CALL SETPARA('param_card.dat')", "      INCLUDE 'pmass.inc'",
             "      WRITE(*,'(A,1X,ES26.17E3)') 'RAVEL_PARAMETER aEWM1',",
             f"     & {aewm1_symbol}",
             "      WRITE(*,'(A,1X,ES26.17E3)') 'RAVEL_PARAMETER ee',",
             f"     & {ee_symbol}", "      DO I=1,NEXTERNAL",
             "        WRITE(*,'(A,1X,I2,1X,ES26.17E3)')",
             "     &  'RAVEL_MASS', I, PMASS(I)", "      ENDDO"]
    for point in evaluation_points:
        for leg, momentum in enumerate(point["momenta"], 1):
            for component, value in enumerate(momentum):
                literal = f"{float(value):.17e}".replace("e", "D")
                lines.append(f"      P({component},{leg})={literal}")
        lines += ["      CALL SMATRIX(P,ANS)",
                  "      WRITE(*,'(A,1X,ES26.17E3)')",
                  f"     & 'RAVEL_M2 {point['id']}', ANS"]
    return "\n".join([*lines, "      END", ""]) 


def _symbol(process_dir, name):
    declarations = "\n".join(path.read_text() for path in
                              (process_dir / "Source/MODEL/input.inc", process_dir / "Source/MODEL/coupl.inc"))
    found = {match.group(0) for match in re.finditer(r"\b(?:mdl_)?" + re.escape(name) + r"\b", declarations, re.I)}
    if len({symbol.lower() for symbol in found}) != 1:
        raise ValueError(f"generated model does not expose unique effective {name}")
    return sorted(found)[0]


def parse_measurements(text, expected_ids):
    result = {"parameters": {}, "masses_gev": {}, "m2": {}}
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("RAVEL_"):
            continue
        tokens = line.split()
        if len(tokens) != 3 or tokens[0] not in {"RAVEL_PARAMETER", "RAVEL_MASS", "RAVEL_M2"}:
            raise ValueError("malformed compiled witness marker")
        target = {"RAVEL_PARAMETER": "parameters", "RAVEL_MASS": "masses_gev", "RAVEL_M2": "m2"}[tokens[0]]
        identity = int(tokens[1]) if target == "masses_gev" else tokens[1]
        if identity in result[target]:
            raise ValueError("duplicate compiled witness measurement")
        value = float(tokens[2].replace("D", "e").replace("d", "e"))
        result[target][identity] = witness.number(value, "compiled measurement")
    if set(result["parameters"]) != {"aEWM1", "ee"} or set(result["masses_gev"]) != {1, 2, 3, 4}:
        raise ValueError("compiled effective parameter/mass dump is incomplete")
    if set(result["m2"]) != set(expected_ids):
        raise ValueError("compiled phase-space measurement coverage is incomplete or foreign")
    result["masses_gev"] = [result["masses_gev"][leg] for leg in range(1, 5)]
    return result


def run(config, base_dir, output_dir):
    validate(config)
    parent = _approved_worker(config, output_dir)  # No external execution or output creation before custody.
    files = inputs(config, base_dir)
    before = [fingerprint(path) for path in files]
    points = witness.validate_points(_load(_path(config["phase_space_file"], base_dir)))
    oracle = witness.validate_oracle(_load(_path(config["oracle_file"], base_dir)), points, config["expected_parameters"])
    evaluation_points = witness.evaluations(points)
    runtime = config["runtime"]
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = _private_workspace(parent, output)
    deadline = time.monotonic() + config["max_seconds"]
    records = []
    # MG5 otherwise consumes a global home configuration and writes its history.
    # Omit HOME instead of redirecting or modifying the user's home state.
    env = {key: value for key, value in os.environ.items() if key in {"USER", "LOGNAME", "LANG", "LC_ALL"}}
    env.update(runtime["environment"])
    # Only the bound make and compiler directories precede fixed system tools.
    env["PATH"] = os.pathsep.join([str(Path(runtime["make"]).parent), str(Path(runtime["compiler"]).parent), "/usr/bin", "/bin"])
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    temp = work / "tmp"
    temp.mkdir()
    env["TMPDIR"] = str(temp)
    def call(argv, cwd, name):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("model-probe total compute ceiling exhausted")
        log_path = work / (name + ".log")
        record = {"argv": list(map(str, argv)), "cwd": str(cwd), "log": str(log_path)}
        records.append(record)
        with log_path.open("x") as log:
            try:
                completed = subprocess.run(record["argv"], cwd=cwd, env=env, stdout=log,
                                           stderr=subprocess.STDOUT, timeout=remaining, check=False)
                record["returncode"] = completed.returncode
            except subprocess.TimeoutExpired as exc:
                record["timed_out"] = True
                raise ValueError(f"model probe timed out in {name}") from exc
        if completed.returncode:
            raise ValueError(f"model probe {name} failed ({completed.returncode}); retained log {log_path}")
        return log_path.read_text(errors="replace")
    try:
        source = _path(runtime["madgraph"], base_dir, directory=True)
        private = work / "mg5"
        shutil.copytree(source, private, symlinks=False,
                        ignore=shutil.ignore_patterns(*EXCLUDED, "*.pyc", "*.pyo", "*.pkl"))
        # Retained source configuration is an input; private execution uses an explicit overlay.
        overlay = private / "input/mg5_configuration.txt"
        overlay.write_text(f"fortran_compiler = {runtime['compiler']}\nrun_mode = 0\nnb_core = 1\n"
                           "auto_update = 0\nautomatic_html_opening = False\nnotification_center = False\n")
        process = work / "PROC_probe"
        script = work / "commands.mg5"
        script.write_text(commands(runtime, process))
        # -O avoids MG5's shell-based self re-execution; Python -s disables user
        # packages, and MG5 -s suppresses its additional caffeinate process.
        # Standalone export itself compiles MODEL and DHELAS inside this bound.
        call([runtime["python"], "-B", "-O", "-s", private / "bin/mg5_aMC", "-s", script], work, "export")
        subprocesses = sorted((process / "SubProcesses").glob("P*"))
        if len(subprocesses) != 1 or not subprocesses[0].is_dir():
            raise ValueError("exclusive control must generate exactly one subprocess")
        subdir = subprocesses[0]
        source_driver = driver(evaluation_points, _symbol(process, "aEWM1"), _symbol(process, "ee"))
        (subdir / "check_sa.f").write_text(source_driver)
        shutil.copyfile(_path(config["parameter_card"], base_dir), process / "Cards/param_card.dat")
        call([runtime["make"], "-j1", f"FC={runtime['compiler']}"], process / "Source", "build-model")
        call([runtime["make"], "-j1", "check", f"FC={runtime['compiler']}"], subdir, "build-driver")
        text = call([subdir / "check"], subdir, "evaluate")
        measured = parse_measurements(text, [p["id"] for p in evaluation_points])
        details = witness.compare(points, oracle, config["expected_parameters"], measured, config["required_checks"])
        aliases = _materialize_aliases(work)
        after = [fingerprint(path) for path in inputs(config, base_dir)]
        if before != after:
            raise ValueError("model-probe source, runtime or scientific inputs changed during execution")
        generated = [fingerprint(path) for path in sorted(process.rglob("*")) if path.is_file()]
        caches = [fingerprint(path) for path in sorted(private.rglob("*")) if path.is_file()
                  and (path.suffix in {".pkl", ".pyc", ".pyo"} or "__pycache__" in path.parts)]
        capsule = _deliver_capsule(work, process, subdir, output, measured)
        details.update(operation=OPERATION, model=MODEL, process=PROCESS, measured=measured,
                       new_generated_events=0, generator_version=(private / "VERSION").read_text().strip(),
                       execution={"commands": records, "environment": env, "generated_artifacts": generated,
                                  "inputs": before, "private_cache_artifacts": caches,
                                  "generated_alias_materialization": aliases,
                                  "private_workspace": str(work), "delivered_capsule": capsule,
                                  "private_configuration": fingerprint(overlay),
                                  "command_script": fingerprint(script), "executed_binary": fingerprint(subdir / "check"),
                                  "compiled_binary": capsule["compiled_binary"]})
        result = {"schema_version": 1, "domain": "model-probe", "status": "passed" if details["checks_passed"] else "failed",
                  "physics_validated": False, "details": details, "limitations": [
                      "One massless SM pure-photon tree process and finite phase-space coverage only; no general model validation.",
                      "Analytic reference tests spin/color-averaged matrix elements, not cross sections, PDFs, showering, detector response or CLs.",
                      "Lorentz comparison uses the same generated amplitude and is a consistency check, not an independent model implementation.",
                      "The complete supplemental WORK inventory is verified at capsule delivery; lifecycle reuse guards delivered capsule and original inputs/runtime, without an automatic WORK rehash.",
                      "Ward, gauge-pair, decay, resonance, permutation and spin-decay coverage retain their explicit applicability statuses.",
                      "Declared native runtime artifacts are bound; this is not a portable toolchain or an arbitrary-UFO security sandbox."]}
        _write(output / "model-probe-result.json", result)
        return result
    except Exception as exc:
        _write(work / "failure.json", {"schema_version": 1, "status": "failed", "physics_validated": False,
                                       "operation": OPERATION, "error": str(exc), "commands": records,
                                       "inputs": before, "new_generated_events": 0})
        raise
