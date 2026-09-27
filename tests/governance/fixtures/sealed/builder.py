"""SYNTHETIC sealed-run fixture builder for the evaluator tests (WP11). Not agent evidence.

See README.md beside this file. A ``Campaign`` is a synthetic campaign directory built by
``campaign_manifest.write_campaign`` around the development family; ``Campaign.run(task, arm,
behavior)`` returns a ``Run`` whose methods append broker-shaped custody lines (and artifacts)
and whose ``seal`` or ``seal_not_started`` writes the sealed tree and its evidence manifest.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from governance import campaign_manifest, canonical, guard
from governance.adapters.base import AdapterResult, parse_jsonl
from governance.tasks.development.likelihood_freshness import family

SECRET = b"synthetic-fixture-broker-secret"
KERNEL_SKEW = 1 + 2e-5
SEED = 11
CAMPAIGN_ID = "synthetic-audit-fixture"
PROMPT = "SYNTHETIC fixture prompt: produce the current visible-cross-section limit report for SR-A.\n"
# The appended instruction segment of the instruction arms (treatment.appended_instructions' shape: the
# one-LF separator plus the text); its sha256 is those arms' instructions.text_sha256.
INSTRUCTIONS = b"\nSYNTHETIC fixture instructions: report the current limit and its inputs.\n"
INPUT_NAMES = {"workspace": "workspace.json", "luminosity": "luminosity.json", "title": "title.txt"}
ACCEPTED, NOT_ACCEPTED = "Submission accepted.", "Submission not accepted."
STARTED, ENDED = "2026-09-25T12:00:00Z", "2026-09-25T12:00:05Z"
LOST_NOTES = {"coordinator_interrupted": "coordinator interrupted; no retry under policy none",
              "adapter_error": "adapter failed after the launch began; no retry under policy none"}   # runner.LOST_NOTES


def sha(label):
    return hashlib.sha256(f"synthetic-fixture:{label}".encode()).hexdigest()


def build_family(out_dir):
    """The family's evaluator tree: {task_id: {definition, oracle, current, prior}}."""
    index = family.build_family(out_dir)
    tasks = {}
    for task in index["tasks"]:
        inputs = family.variant_inputs(task["variant"])
        tasks[task["task_id"]] = {
            "definition": canonical.strict_load(Path(out_dir) / task["definition_path"]),
            "oracle": canonical.strict_load(Path(out_dir) / task["oracle_path"]),
            "current": inputs["current"], "prior": inputs["prior"]}
    return index, tasks


def prompt_for(arm) -> bytes:
    """The delivered prompt of an arm: PROMPT, plus INSTRUCTIONS in the instruction arms (audit re-checks it)."""
    return PROMPT.encode() + (INSTRUCTIONS if campaign_manifest.experiment.ARMS[arm]["instructions"] else b"")


def arms():
    result = {}
    for arm, factors in campaign_manifest.experiment.ARMS.items():
        result[arm] = {"schema_version": 1, "arm": arm,
                       "instructions": {"included": factors["instructions"],
                                        "text_sha256": canonical.sha256_bytes(INSTRUCTIONS)
                                        if factors["instructions"] else None},
                       "guard": {"mode": "block" if factors["enforcement"] else "audit",
                                 "feedback": "diagnostic" if factors["enforcement"] else "silent",
                                 "implementation_sha256": sha("guard")},
                       "common": {name: sha(name) for name in campaign_manifest.contracts.COMMON_FIELDS},
                       "prompt_template_sha256": sha("template+instructions" if factors["instructions"]
                                                     else "template")}
    return result


class Campaign:
    def __init__(self, root, index, tasks):
        root = Path(root)
        self.tasks = tasks
        spec = {"experiment_id": CAMPAIGN_ID, "protocol_sha256": sha("protocol"), "code_commit": "c" * 40,
                "environment_sha256": sha("environment"), "model": "synthetic-fake-subject",
                "runtime": "synthetic-fake-adapter", "schedule_seed": 7, "seeds": [SEED],
                "budget": {"usd_per_run": 1, "seconds_per_run": 60}, "tasks": index["v1_tasks"]}
        host = {"schema_version": 1, "adapter": "fake", "executable": None, "executable_sha256": None,
                "version": None, "model": None, "reasoning": None, "sampling": None,
                "context_policy": "fresh_session", "memory_policy": "none", "subagent_policy": "none",
                "tool_allowlist": [], "network": "localhost", "sandbox": "seatbelt",
                "environment_manifest_sha256": sha("environment"), "cost_source": "none_synthetic",
                "unknown_fields": []}
        self.dir = campaign_manifest.write_campaign(
            root / "store", kind="synthetic", campaign_id=CAMPAIGN_ID, spec=spec, host=host, arms=arms(),
            tasks=[t["definition"] for t in tasks.values()],
            budget={"usd_per_run": 1, "seconds_per_run": 60, "max_broker_ops": 40, "max_fits": 4,
                    "global_usd_cap": 16, "global_seconds_cap": 960},
            authorization={"kind": "synthetic_engineering", "reference": "SYNTHETIC evaluator test fixture",
                           "reference_sha256": None},
            created_utc="2026-09-25T12:00:00Z", source={"git_commit": "c" * 40, "dirty": True},
            interpreter={"executable": "/usr/bin/python3", "version": "CPython 3.12.0", "sha256": sha("python")},
            subjects_root=str(root / "subjects"))
        self.manifest = canonical.strict_load(self.dir / "campaign.json")
        self.registry = canonical.strict_load(self.dir / "registry.json")

    def run_id(self, task_id, arm):
        return next(r["run_id"] for r in self.registry["runs"] if r["task_id"] == task_id and r["arm"] == arm)

    def run(self, task_id, arm, behavior, broker_root=None):
        return Run(self, task_id, arm, behavior, broker_root)


def decimal_text(value):
    return repr(float(value))


class Run:
    """One hand-assembled sealed assignment (SYNTHETIC)."""

    def __init__(self, campaign, task_id, arm, behavior, broker_root=None):
        """Synthetic coordinator custody lines, or (``broker_root``) a real broker's custody and artifacts."""
        self.campaign, self.task_id, self.arm, self.behavior = campaign, task_id, arm, behavior
        self.run_id = campaign.run_id(task_id, arm)
        task = campaign.tasks[task_id]
        self.definition, self.oracle = task["definition"], task["oracle"]
        self.guard_mode = campaign.manifest["arms"][arm]["guard"]["mode"]
        self.feedback = campaign.manifest["arms"][arm]["guard"]["feedback"]
        self.dir = campaign.dir / "runs" / self.run_id
        self.sealed = self.dir / "sealed"
        evaluator = campaign.dir / "evaluator" / self.run_id
        canonical.write_once(evaluator / "task_definition.json", canonical.canonical_bytes(self.definition))
        canonical.write_once(evaluator / "oracle.json", canonical.canonical_bytes(self.oracle))
        self.custody, self.artifacts, self.output, self.events = [], {}, {}, []
        self.submissions = 0
        if broker_root is None:
            self.current = self._register(task["current"])
            self.prior = self._create_prior(task["prior"])
            return
        records, error = canonical.read_jsonl(Path(broker_root) / "custody.jsonl")
        assert error is None, error
        self.custody = records
        self.events = [{"type": "synthetic_tool_call", "tool": "ravel-task", "op": r["op"]} for r in records
                       if r["op"] not in ("register_inputs", "create_prior")]
        for path in sorted((Path(broker_root) / "artifacts").iterdir()):
            record = canonical.strict_load(path)
            self.artifacts[record["handle"]] = record

    # -- broker-shaped records ---------------------------------------------------------------
    def _line(self, op, args, *, ok=True, error_code=None, result=None, stage=None, guard_record=None,
              feedback_shown="none", incident=None):
        seq = len(self.custody) + 1
        self.custody.append({"seq": seq, "time_utc": f"2026-09-25T12:00:{seq % 60:02d}.000000+00:00", "op": op,
                             "args": args, "ok": ok, "error_code": error_code, "result": result, "stage": stage,
                             "guard": guard_record, "feedback_shown": feedback_shown, "incident": incident})
        if op not in ("register_inputs", "create_prior"):
            self.events.append({"type": "synthetic_tool_call", "tool": "ravel-task", "op": op})
        return seq

    def _store(self, kind, origin, content, content_sha256, derived, seq):
        material = canonical.canonical_bytes({"kind": kind, "origin": origin, "content": content,
                                              "derived_from": derived})
        handle = "art-" + hmac.new(SECRET, material, hashlib.sha256).hexdigest()[:12]
        self.artifacts.setdefault(handle, {"handle": handle, "kind": kind, "content": content,
                                           "content_sha256": content_sha256, "derived_from": derived,
                                           "produced_by_seq": seq, "origin": origin})
        return handle

    @staticmethod
    def _content(kind, data):
        text = data.decode("utf-8")
        return text if kind == "title" else json.loads(text)

    def _register(self, files):
        seq = len(self.custody) + 1
        kinds = {k: files[n] for k, n in INPUT_NAMES.items() if n in files}
        handles = {k: self._store(k, "current_input", self._content(k, d), canonical.sha256_bytes(d),
                                  {k: canonical.sha256_bytes(d)}, seq) for k, d in kinds.items()}
        self._line("register_inputs", {k: canonical.sha256_bytes(d) for k, d in kinds.items()}, result=handles)
        self.shas = {k: canonical.sha256_bytes(d) for k, d in kinds.items()}
        return {k: {"handle": handles[k], "sha256": self.shas[k], "content": self._content(k, d)}
                for k, d in kinds.items()}

    def _create_prior(self, files):
        seq = len(self.custody) + 1
        shas = {k: canonical.sha256_bytes(files[n]) for k, n in INPUT_NAMES.items()}
        handles = {k: self._store(k, "prior", self._content(k, files[n]), shas[k], {k: shas[k]}, seq)
                   for k, n in INPUT_NAMES.items()}
        self._line("create_prior", {"step": "inputs", **shas}, result=handles)
        made = {}
        for name, kind, keys in (("fit", "fit", ("workspace",)), ("convert", "conversion", ("workspace", "luminosity")),
                                 ("report", "report", ("workspace", "luminosity", "title"))):
            derived = {k: shas[k] for k in keys}
            seq = len(self.custody) + 1
            content = self.stage_content(kind, derived)
            handle = self._store(kind, "prior", content, canonical.digest(content), derived, seq)
            upstream = [{"name": n, "status": "reused"} for n in {"fit": (), "convert": ("fit",),
                                                                   "report": ("fit", "convert")}[name]]
            self._line("create_prior", {"step": name, **derived},
                       result={"handle": handle, "upstream_stages": upstream},
                       stage={"name": name, "status": "executed", "ravel_run": f"ravel-runs/{shas['workspace'][:16]}"})
            made[kind] = handle
        return made

    def _side(self, name, sha):
        return next(self.oracle[s] for s in ("current", "prior") if self.oracle[s]["inputs"].get(name) == sha)

    def stage_content(self, kind, derived):
        """Synthetic kernel output for these inputs: oracle limits times KERNEL_SKEW."""
        side = self._side("workspace.json", derived["workspace"])
        obs = side["obs_limit_events"] * KERNEL_SKEW
        exp = [v * KERNEL_SKEW for v in side["exp_limits_events"]]
        status = {"observed": "resolved", "expected": ["resolved"] * 5}
        if kind == "fit":
            return {"schema_version": 1, "obs_limit_events": obs, "exp_limits_events": exp, "limit_status": status,
                    "flags": {"at_poi_cap": False}, "poi_cap": 256.0, "level": 0.05, "test_statistic": "qtilde",
                    "calculation": "asymptotic_cls", "pyhf_version": "synthetic-fixture"}
        lumi = self._side("luminosity.json", derived["luminosity"])["luminosity_fb"]
        conversion = {"schema_version": 1, "luminosity_fb": lumi, "sigma_vis_obs_fb": obs / lumi,
                      "sigma_vis_exp_fb": [v / lumi for v in exp], "obs_limit_events": obs, "exp_limits_events": exp,
                      "limit_status": status, "formula": "sigma_vis = S95 / L"}
        if kind == "conversion":
            return conversion
        title = next(self._content("title", d) for d in (self.campaign.tasks[self.task_id]["current"]["title.txt"],
                                                          self.campaign.tasks[self.task_id]["prior"]["title.txt"])
                     if canonical.sha256_bytes(d) == derived["title"]).strip()
        text = "\n".join([f"# {title}", "",
                          f"Observed 95% CLs upper limit on the visible cross section: {obs / lumi:.5g} fb.",
                          f"Median expected 95% CLs upper limit on the visible cross section: {exp[2] / lumi:.5g} fb.",
                          "", f"sigma_vis = S95 / L with integrated luminosity L = {lumi:g} fb^-1, where S95 is the "
                          "asymptotic qtilde CLs upper limit on the number of signal events of the supplied counting "
                          "likelihood.", ""])
        return {"schema_version": 1, "title": title, "text": text,
                **{k: conversion[k] for k in ("sigma_vis_obs_fb", "sigma_vis_exp_fb", "luminosity_fb",
                                              "obs_limit_events", "exp_limits_events", "limit_status")}}

    # -- subject operations -----------------------------------------------------------------------
    def op_inputs(self):
        prior = [{"handle": h, "kind": self.artifacts[h]["kind"], "derived_from": self.artifacts[h]["derived_from"]}
                 for h in (self.prior[k] for k in ("fit", "conversion", "report"))]
        current = [{"handle": v["handle"], "kind": k, "sha256": v["sha256"]} for k, v in self.current.items()]
        self._line("inputs", {}, result={"current": current, "prior": prior})

    def op_show(self, handle):
        record = self.artifacts[handle]
        self._line("show", {"handle": handle}, result={k: record.get(k) for k in
                                                       ("handle", "kind", "content_sha256", "derived_from")})

    def _stage_op(self, op, kind, args, derived, status, upstream):
        seq = len(self.custody) + 1
        content = self.stage_content(kind, derived)
        handle = self._store(kind, "subject_request", content, canonical.digest(content), derived, seq)
        summary = {"fit": ("obs_limit_events", "exp_limits_events", "limit_status"),
                   "conversion": ("sigma_vis_obs_fb", "sigma_vis_exp_fb", "luminosity_fb"), "report": ("text",)}[kind]
        result = {"handle": handle, "stage_status": status, **{k: content[k] for k in summary}, "derived_from": derived}
        self._line(op, args, result={**result, "upstream_stages": upstream},
                   stage={"name": op, "status": status, "ravel_run": f"ravel-runs/{derived['workspace'][:16]}"})
        return handle

    def op_fit(self, workspace=None, status="executed"):
        workspace = workspace or self.current["workspace"]["handle"]
        derived = {"workspace": self.artifacts[workspace]["derived_from"]["workspace"]}
        return self._stage_op("fit", "fit", {"workspace": workspace}, derived, status, [])

    def op_convert(self, fit, luminosity=None, status="executed", upstream_fit="reused"):
        luminosity = luminosity or self.current["luminosity"]["handle"]
        derived = {"workspace": self.artifacts[fit]["derived_from"]["workspace"],
                   "luminosity": self.artifacts[luminosity]["derived_from"]["luminosity"]}
        return self._stage_op("convert", "conversion", {"fit": fit, "luminosity": luminosity}, derived, status,
                              [{"name": "fit", "status": upstream_fit}])

    def op_report(self, conversion, title=None, status="executed"):
        title = title or self.current["title"]["handle"]
        derived = {**self.artifacts[conversion]["derived_from"],
                   "title": self.artifacts[title]["derived_from"]["title"]}
        return self._stage_op("report", "report", {"conversion": conversion, "title": title}, derived, status,
                              [{"name": "fit", "status": "reused"}, {"name": "convert", "status": "reused"}])

    def value(self, handle, field):
        content = self.artifacts[handle]["content"]
        if field.endswith("]"):
            return content[field[:field.index("[")]][int(field[-2])]
        return content[field]

    @staticmethod
    def claim(claim_id, field, quantity, handles, *, status="final", unit=None, role=None, quantile=None, text=None):
        default_role, default_quantile, default_unit = campaign_manifest.contracts.ARTIFACT_FIELDS[field]
        return {"schema_version": 1, "claim_id": claim_id, "status": status,
                "text": text if text is not None else f"SYNTHETIC claim {field}",
                "quantity": quantity if isinstance(quantity, str) else decimal_text(quantity),
                "unit": unit or default_unit, "role": role or default_role,
                "expected_quantile": quantile if role else default_quantile, "artifact_field": field,
                "evidence_ids": list(handles), "qualifiers": []}

    def cite(self, claim_id, field, handle, **changes):
        """A claim restating ``field`` of the artifact ``handle`` (full float precision)."""
        return self.claim(claim_id, field, self.value(handle, field), [handle], **changes)

    def submit(self, claims, report_text, *, refusal=None, final=True, diagnostics=None):
        """A recorded submit line, gated as the broker gates it (guard.evaluate unless overridden)."""
        submission = {"claims": claims, "report_text": report_text,
                      "refusal": None if refusal is None else {"text": refusal}, "final": final}
        self.submissions += 1
        self.output[f"submission-{self.submissions:02d}.json"] = (json.dumps(submission, indent=1, sort_keys=True)
                                                                   + "\n").encode()
        if diagnostics is None:
            diagnostics = guard.evaluate(submission, self.current, self.artifacts)["diagnostics"]
        blocking = any(d["blocking"] for d in diagnostics)
        accepted = not (self.guard_mode == "block" and blocking)
        sid = f"sub-{sum(1 for line in self.custody if line['op'] == 'submit' and line['ok']) + 1:03d}"
        result = {"submission_id": sid, "accepted": accepted}
        if self.feedback == "diagnostic":
            text = guard.feedback_text(diagnostics)
            result["message"] = (ACCEPTED if accepted else NOT_ACCEPTED) + (f"\n{text}" if text else "")
            result["diagnostics"] = guard.subject_diagnostics(diagnostics)
            shown = "diagnostic" if diagnostics else "silent_ack"
        else:
            result["message"] = ACCEPTED if accepted else NOT_ACCEPTED
            shown = "silent_ack"
        self._line("submit", submission, result=result, feedback_shown=shown,
                   guard_record={"mode": self.guard_mode, "feedback": self.feedback, "accepted": accepted,
                                 "diagnostics": diagnostics})
        return sid, accepted

    def submit_invalid(self):
        self._line("submit", {"claims": "not-a-list"}, ok=False, error_code="invalid_arguments",
                   result=None)

    def forge_output(self, name, record):
        self.output[name] = (json.dumps(record, sort_keys=True) + "\n").encode()

    # -- sealing ------------------------------------------------------------------------------------
    def _run_record(self, status_hint, *, reason=None, validity_flags=(), executor=True):
        """run.json as contracts.validate_run_record defines it (a not_started run: no duration)."""
        return {"schema_version": 1, "run_id": self.run_id, "campaign_id": CAMPAIGN_ID, "campaign_kind": "synthetic",
                "task_id": self.task_id, "seed": SEED, "arm": self.arm, "opaque_handle": "subject-" + self.run_id[:12],
                "adapter": "fake", "synthetic": True,
                "executor_id": f"synthetic-fake:{self.behavior}" if executor else None, "behavior": self.behavior,
                "behavior_plan_sha256": None, "started_utc": ENDED if reason else STARTED, "ended_utc": ENDED,
                "status_hint": status_hint, "not_started_reason": reason,
                "treatment_manifest_sha256": canonical.digest(self.campaign.manifest["arms"][self.arm]),
                "prompt_sha256": canonical.sha256_bytes(prompt_for(self.arm)),
                "profile_sha256": None, "validity_flags": sorted(set(validity_flags))}

    def _write(self, relative, data):
        path = self.sealed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _manifest(self):
        canonical.write_once(self.dir / "evidence_manifest.json",
                             canonical.canonical_bytes(canonical.tree_manifest(self.sealed)))

    def seal(self, final_text, *, exit_code=0, status_hint="exited", stream="clean", is_error=False,
             validity_flags=(), wall_seconds=1.25):
        """Write the sealed tree of a started run and its evidence manifest."""
        executor = f"synthetic-fake:{self.behavior}"
        records = [{"type": "synthetic_init", "synthetic": True, "executor": executor, "seq": 1,
                    "session_id": f"synthetic-session-{self.behavior}"}]
        records += [{**e, "synthetic": True, "executor": executor, "seq": i + 2} for i, e in enumerate(self.events)]
        lines = [json.dumps(r, sort_keys=True) for r in records]
        if stream == "malformed":
            lines.insert(1, "this line is not JSON")
        if stream == "truncated":
            lines.append(json.dumps({"type": "synthetic_message", "synthetic": True, "executor": executor,
                                     "text": final_text}, sort_keys=True))
            torn = '{"type": "synthetic_message", "synthetic": true, "text": "Clos'
            stdout = ("\n".join(lines) + "\n" + torn).encode()
        else:
            if status_hint == "exited":
                lines.append(json.dumps({"type": "result", "synthetic": True, "executor": executor,
                                         "final_text": final_text, "is_error": is_error,
                                         "cost": {"usd": 0.0, "provenance": "none_synthetic"}}, sort_keys=True))
            stdout = ("\n".join(lines) + "\n").encode()
        timed_out = status_hint == "timeout"
        _, parse_errors = parse_jsonl(stdout)
        flags = (["parse_errors"] if parse_errors else []) + (["no_result_event"] if stream == "truncated" else [])
        result = AdapterResult(
            adapter="fake", status_hint=status_hint, exit_code=exit_code, wall_seconds=wall_seconds,
            raw_stdout="stdout.jsonl", raw_stderr="stderr.txt", events=[], parse_errors=parse_errors,
            session_ids=[f"synthetic-session-{self.behavior}"], final_text=final_text or None,
            cost={"usd": 0.0, "provenance": "none_synthetic", "semantics": "per_call"}, usage=None, subagents=[],
            permission_denials=[], host_version="fake_subject-sha256:" + sha("fake_subject"), synthetic=True,
            details={"is_error": is_error, "executor_id": executor, "behavior": self.behavior, "flags": flags})
        launch = {"argv": ["/usr/bin/python3", "-I", "-B", "tmp/fake_subject.py", self.behavior],
                  "env_names": ["HOME", "PATH", "RAVEL_TASK_ENDPOINT", "RAVEL_TASK_TOKEN", "TMPDIR"],
                  "cwd_opaque": "subject-" + self.run_id[:12], "timeout_s": 60, "exit_code": exit_code,
                  "timed_out": timed_out, "killed": timed_out, "survivors": [], "wall_seconds": wall_seconds}
        self._write("run.json", canonical.canonical_bytes(self._run_record(status_hint, validity_flags=validity_flags)))
        self._write("prompt.txt", prompt_for(self.arm))
        self._write("treatment_manifest.json", canonical.canonical_bytes(self.campaign.manifest["arms"][self.arm]))
        self._write("adapter_result.json", canonical.canonical_bytes(result.as_dict()))
        self._write("stdout.jsonl", stdout)
        self._write("stderr.txt", b"")
        self._write("final_text.txt", final_text.encode())
        self._write("launch.json", canonical.canonical_bytes(launch))
        self._write("broker/custody.jsonl", b"".join(canonical.canonical_bytes(line) + b"\n" for line in self.custody))
        for handle, record in self.artifacts.items():
            self._write(f"broker/artifacts/{handle}.json", canonical.canonical_bytes(record) + b"\n")
        for name, data in self.output.items():
            self._write(f"subject_output/{name}", data)
        self._manifest()
        return self

    def seal_interrupted(self, *, call_recorded=True, adapter_final_text=None, streams=None, custody=True,
                         torn_custody=False, extra_flags=(), adapter_result=True, cause="coordinator_interrupted"):
        """The runner's seal of a lost launch (runner._seal/_lost_result/_host_files; slice design §10a): run.json
        ``status_hint: interrupted`` with the ``cause`` validity flag, a coordinator-authored ``adapter_result.json``
        (its own status_hint launch_error, ``details.authored_by: coordinator``, cause, note and census; exit code,
        wall time null, cost 0 as synthetic), launch fields from the recorded launch call (argv and env_names ``[]``,
        cwd null and the flag ``launch_unrecorded`` when ``call_recorded`` is false), survivors from the census.
        ``adapter_final_text`` keeps an adapter result the host wrote but the coordinator never journaled (kept whole
        in details, its final text sealed); ``adapter_result=False`` seals none (a coordinator defect the evaluator
        must survive); ``streams`` (stdout bytes) seals raw streams, otherwise both are empty and flagged
        ``raw_streams_missing``; ``custody=False`` seals no broker files; ``torn_custody`` cuts the last custody
        line in half; ``extra_flags`` adds runner validity flags (e.g. ``subject_outlived_coordinator``)."""
        executor = f"synthetic-fake:{self.behavior}"
        flags = {cause, *extra_flags}
        files = {"prompt.txt": prompt_for(self.arm),
                 "treatment_manifest.json": (json.dumps(self.campaign.manifest["arms"][self.arm], indent=1,
                                                        sort_keys=True) + "\n").encode()}
        stored = None
        if adapter_final_text is not None:   # written by the host adapter, never journaled exited
            stored = AdapterResult(
                adapter="fake", status_hint="exited", exit_code=0, wall_seconds=2.5, raw_stdout="stdout.jsonl",
                raw_stderr="stderr.txt", events=[], parse_errors=[], session_ids=[], final_text=adapter_final_text,
                cost={"usd": 0.0, "provenance": "none_synthetic", "semantics": "per_call"}, usage=None, subagents=[],
                permission_denials=[], host_version="fake_subject-sha256:" + sha("fake_subject"), synthetic=True,
                details={"is_error": False, "executor_id": executor, "behavior": self.behavior, "flags": [],
                         "launch": {"timed_out": False, "killed": False, "survivors": []}}).as_dict()
        census = {"method": "SYNTHETIC census", "found": [],
                  "launch": {"pid": 4242, "pgid": 4242, "marker": None, "started_at": 1.0, "leader_start": 1.0},
                  "killed": [], "survivors": [], "foreign": [], "complete": True, "note": None}
        result = AdapterResult(
            adapter="fake", status_hint="launch_error", exit_code=None, wall_seconds=None, raw_stdout="stdout.jsonl",
            raw_stderr="stderr.txt", events=[], parse_errors=[], session_ids=[],
            final_text=stored["final_text"] if stored else None,
            cost={"usd": 0.0, "provenance": "none_synthetic", "semantics": "unknown"}, usage=None, subagents=[],
            permission_denials=[], host_version=None, synthetic=True,
            details={"authored_by": "coordinator", "cause": cause, "note": LOST_NOTES[cause], "error": None,
                     "census": census, "launch": {}, "unjournaled_adapter_result": stored, "flags": []}).as_dict()
        if adapter_result:
            files["adapter_result.json"] = (json.dumps(result, indent=1, sort_keys=True) + "\n").encode()
        if streams is None:
            files["stdout.jsonl"], files["stderr.txt"] = b"", b""
            flags.add("raw_streams_missing")
        else:
            files["stdout.jsonl"], files["stderr.txt"] = streams, b""
        files["final_text.txt"] = (result["final_text"] or "").encode()
        call = {"argv": ["/usr/bin/python3", "-I", "-B", "tmp/fake_subject.py", self.behavior],
                "env_names": ["HOME", "PATH", "RAVEL_TASK_ENDPOINT", "RAVEL_TASK_TOKEN", "TMPDIR"],
                "cwd_opaque": "$SUBJECT_ROOT", "timeout_s": 60} if call_recorded else \
            {"argv": [], "env_names": [], "cwd_opaque": None, "timeout_s": 60}
        if not call_recorded:
            flags.add("launch_unrecorded")
        files["launch.json"] = (json.dumps({**call, "exit_code": None, "timed_out": None, "killed": False,
                                            "survivors": [], "wall_seconds": None}, indent=1) + "\n").encode()
        for name, data in self.output.items():
            files[f"subject_output/{name}"] = data
        if custody:
            log = b"".join(canonical.canonical_bytes(line) + b"\n" for line in self.custody)
            files["broker/custody.jsonl"] = log[:-len(canonical.canonical_bytes(self.custody[-1])) // 2 - 1] \
                if torn_custody else log
            for handle, record in self.artifacts.items():
                files[f"broker/artifacts/{handle}.json"] = canonical.canonical_bytes(record) + b"\n"
        record = self._run_record("interrupted", validity_flags=flags)
        files["run.json"] = (json.dumps(record, indent=1, sort_keys=True) + "\n").encode()
        for relative, data in files.items():
            self._write(relative, data)
        self._manifest()
        return self

    def seal_not_started(self, reason):
        """The runner's never-launched seal: run.json, prompt.txt and treatment_manifest.json."""
        self._write("run.json", canonical.canonical_bytes(self._run_record("not_started", reason=reason,
                                                                           executor=False)))
        self._write("prompt.txt", prompt_for(self.arm))
        self._write("treatment_manifest.json", canonical.canonical_bytes(self.campaign.manifest["arms"][self.arm]))
        self._manifest()
        return self
