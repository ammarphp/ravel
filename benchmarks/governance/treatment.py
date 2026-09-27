"""Treatment manifests, subject prompt assembly and treatment-identity audits (WP10).

Every arm's prompt is the common envelope (``treatments/envelope.md``) with its four
placeholders substituted. The ``instructions`` and ``full`` arms append the scientific
instruction text (``treatments/scientific-instructions.md``) after one blank line, with the
same bytes in both arms. Both files are development texts written for this repository (decision
E-36): they cover the same points as the private research packet's candidate texts without copying
them. They are frozen here for development only; the final bytes need review and preregistration
before any scored run (H-14).

``arm_manifest`` builds the slice-design §4.3 manifest for one arm. Two audits check treatment
identity: ``treatment_diff`` verifies that the four manifests differ exactly in the declared
factors and describe the frozen texts, and ``behavioral_diff`` verifies that the broker really
handled the same stale and clean submissions differently by arm, so a no-op guard, a false
block or an output-only difference fails. ``check_prompt`` verifies one delivered prompt against
its arm's manifest (the instruction segment is present, with exactly the frozen bytes, only when
the manifest includes it); ``render_prompt`` assembles a prompt from texts the caller verified
and holds, so a coordinator never re-reads a frozen text between verification and delivery.

The mechanism-study variant (``mechanism_study=True``: diagnostic feedback in all four arms) is
LIBRARY-LEVEL ONLY in this slice: ``arm_design``, ``arm_manifest``, ``treatment_diff`` and
``behavioral_diff`` accept it, but no campaign can carry it (the campaign manifest has no design
field, ``runner.arm_manifests`` builds the primary 2x2 and a campaign load rejects any other
arms), and ``cli.py treatment-diff`` refuses it. Standard library only.
"""
from __future__ import annotations

import itertools
import os
import re
import stat
from pathlib import Path

from . import guard
from .broker import ACCEPTED, NOT_ACCEPTED
from .canonical import ContractError, canonical_bytes, digest, is_sha256, require, sha256_bytes, sha256_file
from .experiment import ARMS

TREATMENTS_DIR = Path(__file__).with_name("treatments")
FROZEN_FILES = {"envelope": "envelope.md", "instructions": "scientific-instructions.md"}
PLACEHOLDERS = ("TASK_PROMPT", "INPUT_ROOT", "OUTPUT_ROOT", "RESOURCE_POLICY")
SEPARATOR = b"\n"  # after the envelope's final newline: exactly one blank line
COMMON_FIELDS = ("envelope_sha256", "tool_guide_sha256", "client_sha256", "broker_sha256",
                 "stage_workers_sha256", "kernel_source_sha256", "interpreter_sha256",
                 "operation_schema_sha256")
COMMON_SOURCES = tuple(name[:-len("_sha256")] for name in COMMON_FIELDS)
GUARD_MODES = ("audit", "block")
FEEDBACK = ("silent", "diagnostic")
FEEDBACK_SHOWN = ("none", "silent_ack", "diagnostic")
# Manifest fields that may (and must) differ across arms; everything else must be identical.
FACTOR_FIELDS = ("instructions.included", "instructions.text_sha256", "guard.mode", "guard.feedback",
                 "prompt_template_sha256")
PROBES = ("stale", "clean")
PROBE_FIELDS = ("submission_sha256", "mode", "feedback", "accepted", "diagnostics", "feedback_shown",
                "response")

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
# Arm names, guard modes and treatment vocabulary (with inflections), bounded by non-letters so that
# names joined by underscores or digits (``baseline_01``, ``arm2``) match and ``fully`` or ``harmless``
# do not. camelCase is split first (``fullArm``, ``BaselineRun``).
_ARM_TERMS = re.compile(r"(?<![a-z])(?:%s|enforc[a-z]*|guard[a-z]*|treatment[a-z]*|block[a-z]*|audit[a-z]*|arms?)"
                        r"(?![a-z])" % "|".join(sorted(ARMS)), re.IGNORECASE)
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def frozen_bytes(name: str) -> bytes:
    """Exact bytes of a frozen treatment text: ``"envelope"`` or ``"instructions"``."""
    require(name in FROZEN_FILES, f"unknown treatment text: {name!r}")
    data = (Path(TREATMENTS_DIR) / FROZEN_FILES[name]).read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{FROZEN_FILES[name]}: not UTF-8") from exc
    require(text and text == text.lstrip() and text.endswith("\n") and not text.endswith("\n\n")
            and "\r" not in text, f"{FROZEN_FILES[name]}: must start with text and end with exactly one LF")
    return data


def appended_instructions() -> bytes:
    """The exact bytes appended to the envelope in instruction arms: the separator plus the frozen text."""
    return SEPARATOR + frozen_bytes("instructions")


def arm_identifying_terms(text: str) -> list:
    """Words in subject-visible text that name an arm, a guard mode or the treatment itself."""
    require(isinstance(text, str), "subject-visible text must be a string")
    return sorted({match.group(0).lower() for match in _ARM_TERMS.finditer(_CAMEL.sub(" ", text))})


def assemble_prompt(*, request_text: str, input_root: str, output_root: str, resource_policy: str,
                    include_instructions: bool) -> str:
    """The exact subject prompt: envelope with placeholders substituted, plus instructions if included."""
    require(type(include_instructions) is bool, "include_instructions: boolean required")
    return render_prompt(frozen_bytes("envelope"), appended_instructions() if include_instructions else None,
                         request_text=request_text, input_root=input_root, output_root=output_root,
                         resource_policy=resource_policy)


def render_prompt(envelope: bytes, appended: bytes | None, *, request_text: str, input_root: str, output_root: str,
                  resource_policy: str) -> str:
    """``assemble_prompt`` from given bytes: ``envelope`` (the frozen envelope) with its placeholders
    substituted, plus ``appended`` (the separator and the frozen instruction text) or nothing.

    For a coordinator that verified the frozen texts against its manifests once and holds them:
    it never re-reads a file between that verification and a delivery."""
    require(type(envelope) is bytes and (appended is None or type(appended) is bytes),
            "render_prompt: envelope bytes and appended bytes or None required")
    values = {"TASK_PROMPT": request_text, "INPUT_ROOT": input_root, "OUTPUT_ROOT": output_root,
              "RESOURCE_POLICY": resource_policy}
    for name, value in values.items():
        require(isinstance(value, str) and value and value == value.strip(),
                f"{name}: nonempty string without surrounding whitespace required")
        require("\r" not in value and "{{" not in value and "}}" not in value,
                f"{name}: must not contain CR or template braces")
        require(name == "TASK_PROMPT" or "\n" not in value, f"{name}: single line required")
    try:
        template = envelope.decode("utf-8")
        tail = "" if appended is None else appended.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("render_prompt: texts must be UTF-8") from exc
    found = _PLACEHOLDER.findall(template)
    missing, extra = sorted(set(PLACEHOLDERS) - set(found)), sorted(set(found) - set(PLACEHOLDERS))
    require(not missing, f"envelope is missing placeholders {missing}")
    require(not extra, f"envelope has unknown placeholders {extra}")
    require(len(found) == len(set(found)), "envelope repeats a placeholder")
    prompt = _PLACEHOLDER.sub(lambda match: values[match.group(1)], template) + tail
    require("{{" not in prompt and "}}" not in prompt, "unreplaced template braces in the assembled prompt")
    terms = arm_identifying_terms(prompt)
    require(not terms, f"subject-visible prompt contains arm-identifying terms {terms}")
    return prompt


def check_prompt(prompt: str, manifest: dict, *, instructions_sha256: str) -> list:
    """Violations (empty when none) of one delivered prompt against its arm's §4.3 manifest.

    ``instructions_sha256`` is the campaign's frozen appended-instruction hash (the
    ``text_sha256`` of its instruction arms). The appended segment is the prompt's suffix that
    starts with the separator after a line end. An arm whose manifest includes instructions must
    end with a segment hashing to its ``text_sha256``; an arm without them must not end with one
    hashing to the campaign's. Only hashes are used, so the check needs no copy of the texts: a
    changed instruction file, an instruction segment in the wrong arm or a missing one fails.
    """
    require(isinstance(prompt, str) and prompt, "prompt: nonempty string required")
    require(isinstance(manifest, dict) and isinstance(manifest.get("instructions"), dict),
            "manifest: a treatment manifest required")
    require(is_sha256(instructions_sha256), "instructions_sha256: expected SHA-256")
    data = prompt.encode("utf-8")
    suffixes = {sha256_bytes(data[i:]) for i in range(1, len(data))
                if data[i - 1:i] == b"\n" and data[i:i + len(SEPARATOR)] == SEPARATOR}
    included, text_sha256 = manifest["instructions"]["included"], manifest["instructions"]["text_sha256"]
    violations = []
    if included:
        if text_sha256 != instructions_sha256:
            violations.append("the manifest's instruction hash is not the campaign's frozen instruction text")
        if not data.endswith(b"\n") or text_sha256 not in suffixes:
            violations.append("the prompt does not end with the frozen instruction text the manifest includes")
    elif instructions_sha256 in suffixes:
        violations.append("the prompt carries the instruction text its manifest excludes")
    if not included and text_sha256 is not None:
        violations.append("the manifest excludes instructions but names an instruction hash")
    return violations


def arm_design(arm: str, *, mechanism_study=False) -> dict:
    """Declared factors of one arm (§4.3): {"included", "mode", "feedback"}.

    Primary 2x2: audit arms are silent, block arms diagnostic. The mechanism study gives
    diagnostic feedback in all four arms, so only permission to continue differs.
    """
    require(arm in ARMS, f"unknown arm: {arm!r}")
    require(type(mechanism_study) is bool, "mechanism_study: boolean required")
    block = ARMS[arm]["enforcement"]
    return {"included": ARMS[arm]["instructions"], "mode": "block" if block else "audit",
            "feedback": "diagnostic" if block or mechanism_study else "silent"}


def _frozen_hashes(included):
    """(text_sha256, prompt_template_sha256) of the frozen texts for an arm with or without instructions."""
    appended = appended_instructions()
    template = frozen_bytes("envelope") + (appended if included else b"")
    return (sha256_bytes(appended) if included else None), sha256_bytes(template)


def _check_common(common, label="common"):
    require(isinstance(common, dict) and set(common) == set(COMMON_FIELDS),
            f"{label}: fields must be {sorted(COMMON_FIELDS)}")
    for name in COMMON_FIELDS:
        require(is_sha256(common[name]), f"{label}.{name}: expected SHA-256")


def arm_manifest(arm: str, *, common: dict, instructions_text: bytes, guard_impl_sha256: str,
                 mechanism_study=False) -> dict:
    """Treatment manifest for one arm (§4.3), bound to the texts ``assemble_prompt`` delivers.

    ``instructions_text`` must equal the frozen instruction file bytes and ``common.envelope_sha256``
    the frozen envelope, so the manifest cannot describe text the subject never receives.
    ``text_sha256`` hashes the exact appended bytes (``appended_instructions()``: the one-LF
    separator plus the instruction text). ``prompt_template_sha256`` hashes the unrendered arm
    template: the envelope, plus the appended bytes when instructions are included.
    """
    design = arm_design(arm, mechanism_study=mechanism_study)
    _check_common(common)
    require(is_sha256(guard_impl_sha256), "guard_impl_sha256: expected SHA-256")
    require(common["envelope_sha256"] == sha256_bytes(frozen_bytes("envelope")),
            "common.envelope_sha256 is not the frozen envelope that assemble_prompt delivers")
    require(type(instructions_text) is bytes and instructions_text == frozen_bytes("instructions"),
            "instructions_text must be the exact frozen instruction bytes that assemble_prompt delivers")
    text_sha256, template_sha256 = _frozen_hashes(design["included"])
    return {"schema_version": 1, "arm": arm,
            "instructions": {"included": design["included"], "text_sha256": text_sha256},
            "guard": {"mode": design["mode"], "feedback": design["feedback"],
                      "implementation_sha256": guard_impl_sha256},
            "common": {name: common[name] for name in COMMON_FIELDS},
            "prompt_template_sha256": template_sha256}


def kernel_source_digest(src_root) -> str:
    """Canonical digest of the sorted [{path, sha256}] list of ``src/ravel/**/*.py`` (§4.3).

    ``src_root`` is the source root that holds ``ravel/``; paths are recorded as
    ``src/ravel/...`` whatever the checkout location, so the digest identifies the source.
    These are the files the kernel's stage fingerprints hash. Symlinked files or directories
    are rejected.
    """
    root = Path(src_root)
    package = root / "ravel"
    require(package.is_dir() and not package.is_symlink(), f"kernel package directory not found: {package}")
    entries = []
    for current, dirs, files in os.walk(package):
        for name in dirs:
            require(not (Path(current) / name).is_symlink(), f"symlinked kernel directory: {name}")
        for name in files:
            path = Path(current) / name
            if name.endswith(".py"):
                require(stat.S_ISREG(path.lstat().st_mode), f"not a regular file: {path.relative_to(root)}")
                entries.append({"path": "src/" + path.relative_to(root).as_posix(), "sha256": sha256_file(path)})
    require(entries, f"no kernel sources under {package}")
    return digest(sorted(entries, key=lambda entry: entry["path"]))


def _file_sha256(path, label):
    require(isinstance(path, (str, os.PathLike)) and Path(path).is_file(), f"{label}: not a file: {path}")
    return sha256_file(path)


def common_hashes(paths: dict) -> dict:
    """The §4.3 ``common`` block from source paths.

    ``paths`` has exactly the keys envelope, tool_guide, client, broker, stage_workers,
    kernel_source, interpreter, operation_schema. ``kernel_source`` is the source root that holds
    ``ravel/`` (see ``kernel_source_digest``). Every other value is one file, or a nonempty list
    of files with distinct names hashed as the canonical digest of the sorted [{path: name,
    sha256}] list.
    """
    require(isinstance(paths, dict) and set(paths) == set(COMMON_SOURCES),
            f"paths: fields must be {sorted(COMMON_SOURCES)}")
    common = {}
    for name in COMMON_SOURCES:
        value = paths[name]
        if name == "kernel_source":
            common[f"{name}_sha256"] = kernel_source_digest(value)
        elif isinstance(value, (list, tuple)):
            require(value and all(isinstance(p, (str, os.PathLike)) for p in value),
                    f"{name}: nonempty list of file paths required")
            names = [Path(p).name for p in value]
            require(len(set(names)) == len(names), f"{name}: file names must be distinct")
            common[f"{name}_sha256"] = digest(sorted(({"path": Path(p).name, "sha256": _file_sha256(p, name)}
                                                      for p in value), key=lambda entry: entry["path"]))
        else:
            common[f"{name}_sha256"] = _file_sha256(value, name)
    return common


def _leaves(value, prefix=""):
    """Dotted-key leaves of nested objects; lists and empty objects are leaves."""
    if not (isinstance(value, dict) and value):
        return {prefix: value}
    leaves = {}
    for key, item in value.items():
        leaves.update(_leaves(item, f"{prefix}.{key}" if prefix else key))
    return leaves


def _differences(flat):
    """Every dotted field that is absent in some arm or not byte-identical across arms, per arm."""
    fields = sorted(set().union(*(row.keys() for row in flat.values())))
    return {field: {arm: flat[arm][field] for arm in ARMS if field in flat[arm]} for field in fields
            if any(field not in flat[arm] for arm in ARMS)
            or len({canonical_bytes(flat[arm][field]) for arm in ARMS}) > 1}


def _flatten_manifest(arm, manifest):
    """Validate one manifest's structure and return its fields as dotted keys (without ``arm``)."""
    require(isinstance(manifest, dict) and set(manifest) == {"schema_version", "arm", "instructions", "guard",
                                                             "common", "prompt_template_sha256"},
            "manifest fields must be arm, common, guard, instructions, prompt_template_sha256, schema_version")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1, "schema_version: expected 1")
    require(manifest["arm"] == arm, f"manifest is for arm {manifest['arm']!r}")
    instructions, guard = manifest["instructions"], manifest["guard"]
    require(isinstance(instructions, dict) and set(instructions) == {"included", "text_sha256"},
            "instructions: fields must be included, text_sha256")
    require(type(instructions["included"]) is bool, "instructions.included: boolean required")
    require(instructions["text_sha256"] is None or is_sha256(instructions["text_sha256"]),
            "instructions.text_sha256: SHA-256 or null")
    require(isinstance(guard, dict) and set(guard) == {"mode", "feedback", "implementation_sha256"},
            "guard: fields must be feedback, implementation_sha256, mode")
    require(guard["mode"] in GUARD_MODES, f"guard.mode: one of {GUARD_MODES}")
    require(guard["feedback"] in FEEDBACK, f"guard.feedback: one of {FEEDBACK}")
    require(is_sha256(guard["implementation_sha256"]), "guard.implementation_sha256: expected SHA-256")
    _check_common(manifest["common"])
    require(is_sha256(manifest["prompt_template_sha256"]), "prompt_template_sha256: expected SHA-256")
    return _leaves({key: value for key, value in manifest.items() if key != "arm"})


def treatment_diff(manifests: dict, *, mechanism_study=False) -> dict:
    """Check that the four arm manifests differ exactly in the declared factors (§4.3).

    ``mechanism_study`` names the design the campaign declares (default: the primary 2x2); it is
    never inferred from the manifests, so an all-diagnostic set fails unless the mechanism study
    is declared. ok only if every ``common`` field and ``guard.implementation_sha256`` are
    identical, each arm's instructions flag and guard mode/feedback match that design, and the
    envelope, appended-instruction and prompt-template hashes are those of the frozen texts
    ``assemble_prompt`` delivers. ``differences`` lists every field whose value is not identical
    across arms, per arm. Never raises on bad manifests: problems are returned as violations.
    """
    require(type(mechanism_study) is bool, "mechanism_study: boolean required")
    if not isinstance(manifests, dict) or set(manifests) != set(ARMS):
        return {"ok": False, "differences": {},
                "violations": [f"manifests must be keyed by exactly the arms {sorted(ARMS)}"]}
    flat, violations = {}, []
    for arm in ARMS:
        try:
            flat[arm] = _flatten_manifest(arm, manifests[arm])
        except ContractError as exc:
            violations.append(f"{arm}: {exc}")
    if violations:
        return {"ok": False, "differences": {}, "violations": violations}
    differences = _differences(flat)
    violations += [f"{field} differs across arms: {values}" for field, values in differences.items()
                   if field not in FACTOR_FIELDS]
    if {row["common.envelope_sha256"] for row in flat.values()} != {sha256_bytes(frozen_bytes("envelope"))}:
        violations.append("common.envelope_sha256 is not the frozen envelope")
    design_name = "mechanism study" if mechanism_study else "primary 2x2"
    for arm in ARMS:
        design, row = arm_design(arm, mechanism_study=mechanism_study), flat[arm]
        for field, key in (("instructions.included", "included"), ("guard.mode", "mode"),
                           ("guard.feedback", "feedback")):
            if row[field] != design[key]:
                violations.append(f"{arm}: {field} is {row[field]!r}, declared {design[key]!r} ({design_name})")
        text_sha256, template_sha256 = _frozen_hashes(design["included"])
        if row["instructions.text_sha256"] != text_sha256:
            violations.append(f"{arm}: instructions.text_sha256 must be "
                              + ("the frozen appended instructions" if design["included"] else "null"))
        if row["prompt_template_sha256"] != template_sha256:
            violations.append(f"{arm}: prompt_template_sha256 is not the frozen "
                              + ("envelope plus instructions" if design["included"] else "envelope"))
    return {"ok": not violations, "differences": differences, "violations": violations}


def probe_from_custody(entry: dict) -> dict:
    """One ``behavioral_diff`` probe from the broker's custody line for a ``submit`` call (§6).

    ``submission_sha256`` is the digest of the custody ``args`` (the submitted body); ``mode``,
    ``feedback``, ``accepted`` and ``diagnostics`` are the custody ``guard`` record;
    ``feedback_shown`` is the custody field; ``response`` is the custody ``result``, which must be
    the full submit result the subject received, without ``submission_id`` (it numbers calls, not
    treatments).
    """
    require(isinstance(entry, dict) and entry.get("op") == "submit" and entry.get("ok") is True,
            "custody entry: a successful submit call required")
    require({"args", "guard", "feedback_shown", "result"} <= set(entry),
            "custody entry: args, guard, feedback_shown and result required")
    guard, result = entry["guard"], entry["result"]
    require(isinstance(guard, dict) and set(guard) == {"mode", "feedback", "accepted", "diagnostics"},
            "custody entry: guard fields must be accepted, diagnostics, feedback, mode")
    require(isinstance(result, dict) and "submission_id" in result, "custody entry: result must be the submit result")
    return {"submission_sha256": digest(entry["args"]), "mode": guard["mode"], "feedback": guard["feedback"],
            "accepted": guard["accepted"], "diagnostics": guard["diagnostics"],
            "feedback_shown": entry["feedback_shown"],
            "response": {key: value for key, value in result.items() if key != "submission_id"}}


def _check_probe(probe, label):
    require(isinstance(probe, dict) and set(probe) == set(PROBE_FIELDS),
            f"{label}: fields must be {sorted(PROBE_FIELDS)}")
    require(is_sha256(probe["submission_sha256"]), f"{label}.submission_sha256: expected SHA-256")
    require(probe["mode"] in GUARD_MODES, f"{label}.mode: one of {GUARD_MODES}")
    require(probe["feedback"] in FEEDBACK, f"{label}.feedback: one of {FEEDBACK}")
    require(type(probe["accepted"]) is bool, f"{label}.accepted: boolean required")
    require(isinstance(probe["diagnostics"], list) and all(isinstance(d, dict) for d in probe["diagnostics"]),
            f"{label}.diagnostics: list of objects required")
    require(probe["feedback_shown"] in FEEDBACK_SHOWN, f"{label}.feedback_shown: one of {FEEDBACK_SHOWN}")
    response = probe["response"]
    require(isinstance(response, dict) and type(response.get("accepted")) is bool
            and isinstance(response.get("message"), str),
            f"{label}.response: submit result with boolean accepted and string message required")
    require("submission_id" not in response, f"{label}.response: must not carry submission_id")


def _check_observation(obs):
    require(isinstance(obs, dict) and set(obs) == set(PROBES), f"observation fields must be {sorted(PROBES)}")
    for name in PROBES:
        _check_probe(obs[name], name)
    try:
        canonical_bytes(obs)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"not canonical JSON: {exc}") from exc


def expected_response(accepted: bool, feedback: str, recorded: list) -> dict:
    """The exact submit response (without submission_id) the §6 broker gives for one guard verdict.

    Its first message line is the acceptance constant; silent feedback shows nothing else;
    diagnostic feedback appends ``guard.feedback_text`` of the recorded diagnostics (nothing when
    there are none) and shows exactly ``guard.subject_diagnostics`` of them (an empty list on a
    clean submission). Anything else a broker adds (coaching, a value, another field) is a
    subject-visible difference the treatment does not declare."""
    message = ACCEPTED if accepted else NOT_ACCEPTED
    if feedback == "silent":
        return {"accepted": accepted, "message": message}
    text = guard.feedback_text(recorded)
    return {"accepted": accepted, "message": message + (f"\n{text}" if text else ""),
            "diagnostics": guard.subject_diagnostics(recorded)}


def _expected(accepted, feedback, recorded):
    """expected_response, or None when the recorded diagnostics are not guard diagnostics."""
    try:
        return expected_response(accepted, feedback, recorded)
    except (KeyError, TypeError, ValueError):
        return None


def _shown(recorded):
    try:
        return guard.subject_diagnostics(recorded)
    except (KeyError, TypeError):
        return None


def behavioral_diff(observations: dict, *, mechanism_study=False) -> dict:
    """Check the broker's recorded handling of the SAME two submissions in every arm.

    ``observations[arm]`` is {"stale": probe, "clean": probe}: a submission citing a stale
    artifact and a fully supported current one, each probe built by ``probe_from_custody``.

    ok only if: the probes are the same two submissions in every arm; the stale probe drew
    nonempty guard diagnostics identical in every arm and the clean probe drew none; every broker
    ran its declared mode/feedback; arms with the same guard settings received byte-identical
    output (the instructions factor never changes the broker); every arm accepted the clean probe
    with the same acknowledgement (no false block); block arms refused the stale probe without the
    clean acknowledgement; audit arms accepted it; silent arms returned exactly the clean response
    and no diagnostics; every response is exactly ``expected_response`` of its recorded verdict
    (the acceptance constant as the first message line, then in diagnostic arms exactly the
    guard's feedback text and subject diagnostics, and no other field), so subject-visible content
    beyond the declared feedback (a hint, a value, hidden codes) fails in every arm; and in the
    mechanism study the stale responses differ across arms only in ``accepted`` and the first
    message line. A no-op guard, a guard that blocks in audit arms or blocks clean work, and a
    difference only in what the subject sees therefore fail; ``differences`` makes any
    arm-dependent output visible. Never raises on bad observations.
    """
    require(type(mechanism_study) is bool, "mechanism_study: boolean required")
    if not isinstance(observations, dict) or set(observations) != set(ARMS):
        return {"ok": False, "differences": {},
                "violations": [f"observations must be keyed by exactly the arms {sorted(ARMS)}"]}
    violations = []
    for arm in ARMS:
        try:
            _check_observation(observations[arm])
        except ContractError as exc:
            violations.append(f"{arm}: {exc}")
    if violations:
        return {"ok": False, "differences": {}, "violations": violations}
    differences = _differences({arm: _leaves(observations[arm]) for arm in ARMS})
    if "stale.submission_sha256" in differences or "clean.submission_sha256" in differences:
        violations.append("the probes are not the same submissions in every arm")
    if observations["baseline"]["stale"]["submission_sha256"] == observations["baseline"]["clean"]["submission_sha256"]:
        violations.append("the stale and clean probes are the same submission")
    if "stale.diagnostics" in differences:
        violations.append("recorded guard diagnostics differ across arms")
    if "clean.response.message" in differences:
        violations.append("the clean acknowledgement differs across arms")
    designs = {arm: arm_design(arm, mechanism_study=mechanism_study) for arm in ARMS}
    for arm, other in itertools.combinations(ARMS, 2):
        same_settings = (designs[arm]["mode"], designs[arm]["feedback"]) == (designs[other]["mode"],
                                                                              designs[other]["feedback"])
        if same_settings and canonical_bytes(observations[arm]) != canonical_bytes(observations[other]):
            violations.append(f"{arm} and {other} share guard settings but received different broker output")
    if mechanism_study and any(field.startswith("stale.response.") and field not in ("stale.response.accepted",
                                                                                    "stale.response.message")
                               for field in differences):
        violations.append("mechanism study: stale-probe responses differ beyond acceptance and message")
    if mechanism_study and len({observations[arm]["stale"]["response"]["message"].partition("\n")[2]
                                for arm in ARMS}) > 1:
        violations.append("mechanism study: stale-probe feedback text differs across arms beyond its first line")
    for arm in ARMS:
        design, stale, clean = designs[arm], observations[arm]["stale"], observations[arm]["clean"]
        if not stale["diagnostics"]:
            violations.append(f"{arm}: guard recorded no diagnostics for the stale probe")
        if clean["diagnostics"]:
            violations.append(f"{arm}: the clean probe drew guard diagnostics")
        for name in PROBES:
            probe = observations[arm][name]
            if (probe["mode"], probe["feedback"]) != (design["mode"], design["feedback"]):
                violations.append(f"{arm}: broker ran {probe['mode']}/{probe['feedback']} on the {name} probe, "
                                  f"declared {design['mode']}/{design['feedback']}")
            if probe["response"]["accepted"] != probe["accepted"]:
                violations.append(f"{arm}: {name} response acceptance differs from the custody record")
            shown = "diagnostic" if design["feedback"] == "diagnostic" and probe["diagnostics"] else "silent_ack"
            if probe["feedback_shown"] != shown:
                violations.append(f"{arm}: {name} feedback_shown is {probe['feedback_shown']!r}, expected {shown!r}")
            if design["feedback"] == "silent":
                if "diagnostics" in probe["response"]:
                    violations.append(f"{arm}: silent feedback showed diagnostics on the {name} probe")
            elif probe["response"].get("diagnostics") != _shown(probe["diagnostics"]):
                violations.append(f"{arm}: the {name} probe did not show exactly the recorded diagnostics")
            expected = _expected(probe["accepted"], design["feedback"], probe["diagnostics"])
            response = probe["response"]
            first = response["message"].split("\n", 1)[0]
            if first != (ACCEPTED if response["accepted"] else NOT_ACCEPTED):
                violations.append(f"{arm}: the {name} message does not start with the acceptance constant")
            if expected is None:
                violations.append(f"{arm}: the {name} probe's recorded diagnostics are not guard diagnostics")
            elif canonical_bytes(response) != canonical_bytes(expected):
                violations.append(f"{arm}: the {name} response is not exactly the declared feedback of its verdict "
                                  "(extra or altered subject-visible content)")
        if not clean["accepted"]:
            violations.append(f"{arm}: refused the clean probe")
        if design["mode"] == "block":
            if stale["accepted"]:
                violations.append(f"{arm}: accepted a submission with blocking diagnostics")
            if stale["response"]["message"] == clean["response"]["message"]:
                violations.append(f"{arm}: a blocked submission received the clean acknowledgement")
        elif not stale["accepted"]:
            violations.append(f"{arm}: audit mode refused the submission")
        if design["feedback"] == "silent" and canonical_bytes(stale["response"]) != canonical_bytes(clean["response"]):
            violations.append(f"{arm}: acknowledgement differs from the clean acknowledgement")
    return {"ok": not violations, "differences": differences, "violations": violations}
