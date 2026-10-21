#!/usr/bin/env python3
"""resource_census -- the RESOURCE SWEEP (source-ladder rungs 1-5, automated).

The failure this kills: the analysis's public code/data sitting unexamined online while the run
improvises around "unavailable" information (for example, an analysis's public repository that
nobody checked, or a HEPData download that looked impossible). For a given analysis it walks, cheaply and
WITHOUT downloading bulk data:

  R1  HEPData record        tables + the RESOURCES tab (likelihoods, efficiency maps, cards)
  R2  analysis routines     Rivet + SimpleAnalysis via routine_fetch.py
  R3  arXiv                 e-print metadata (source availability for figure extraction)
  R4  GitHub                repository search on the analysis id + arXiv id (gh CLI)
  R5  INSPIRE               forward citations (recasts + THESES carry cutflows) + Zenodo search

Manual rungs it CANNOT walk (recorded as pointers in the output): collaboration glance/twiki
pages and JS-walled public-results pages (browser territory), MA5-PAD/CheckMATE listings.

Several analyses, or a topic with no reference paper, use the same sweep:
  --analysis inspire=<id>[,arxiv=<id>][,id=<code>]   repeatable, one census per analysis
  --keyword "<topic words>"                          HEPData + INSPIRE search; the top --limit
                                                     candidates are each censused (--search-only
                                                     records the search alone)

Output with --rundir: one file per analysis, inputs/resource_census/ins<id>.json, one per
keyword search, inputs/resource_census/search-<slug>.json, and the index
inputs/resource_census.json that the lifecycle gate reads. The index lists every entry and
search in the folder (later runs add to it) and carries `rungs` keyed "<entry>/<rung>"; with a
single analysis it also keeps that census's own fields (analysis_id, inspire, arxiv, rungs).
--markdown prints the CHECK-IN 1 "what exists online" block. Fail-soft per rung (network
trouble -> rung status ERROR with the reason -- never a fabricated 'nothing exists'), fail-LOUD
when nothing succeeds (exit 3).

Usage:
  python3 resource_census.py --inspire <record> --arxiv <YYMM.NNNNN> \
      --analysis-id <analysis code> [--rundir <dir>] [--markdown]
  python3 resource_census.py --analysis inspire=<record>,id=<analysis code> \
      --analysis inspire=<record> --rundir <dir>
  python3 resource_census.py --keyword "dilepton resonance" [--limit 5] [--search-only] \
      --rundir <dir>
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import urllib.parse

from ravel.workflow import discovery_http

HERE = os.path.dirname(os.path.abspath(__file__))


def _get_json(url, timeout=25):
    """JSON from a public discovery service as a plain client (see discovery_http)."""
    return discovery_http.get_json(url, timeout=timeout)


def _resolve_timestamp(cli_timestamp=None):
    """generated_utc: --timestamp else $RESOURCE_CENSUS_UTC else "" -- never datetime.now()."""
    if cli_timestamp:
        return cli_timestamp
    return os.environ.get("RESOURCE_CENSUS_UTC", "")


def _fingerprint(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update((str(p) + "\x00").encode("utf-8"))
    return h.hexdigest()


def _count_recipe_hits(s):
    if not isinstance(s, dict) or s.get("status") != "OK":
        return 0
    if isinstance(s.get("hits"), dict):
        return sum(len(v.get("repos", [])) + len(v.get("code", []))
                   for v in s["hits"].values() if isinstance(v, dict))
    return int(s.get("n", 0))


def build_recipe_search_record(tool, model, symptom, searches, timestamp=""):
    """Assemble recipe_search.json from already-fetched per-source `searches` dicts (offline/pure).
    D8 RESOLVE: a diagnosed generator-model failure is searched externally CO-PRIMARY, not last."""
    ok = [k for k, v in searches.items() if isinstance(v, dict) and v.get("status") == "OK"]
    return {
        "schema_version": 1,
        "generated_utc": timestamp,
        "generator": "resource_census.py",
        "generated_by": "resource_census.py --debug recipe-search",
        "input_fingerprint": _fingerprint(tool, model, symptom),
        "mode": "recipe-search",
        "query": {"tool": tool, "model": model, "symptom": symptom},
        "searches": searches,
        "searches_ok": ok,
        "n_hits": sum(_count_recipe_hits(v) for v in searches.values()),
        "co_primary": True,
    }


def _recipe_search_main(argv):
    ap = argparse.ArgumentParser(prog="resource_census.py --debug recipe-search",
                                 description="tool+model+symptom-keyed external recipe/fix search (D8)")
    ap.add_argument("--debug", required=True, help="mode selector; must be 'recipe-search'")
    ap.add_argument("--tool", required=True, help="failing tool, e.g. madgraph|pythia|delphes")
    ap.add_argument("--model", required=True, help="BSM/HV model, e.g. SVJ|wino-c1n2|slepton")
    ap.add_argument("--symptom", default="", help="free-text symptom/error keywords")
    ap.add_argument("--rundir", default=None, help="write inputs/recipe_search.json here")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--timestamp", default=None)
    args = ap.parse_args(argv)
    if args.debug != "recipe-search":
        print(f"resource_census: unknown --debug mode {args.debug!r} (only 'recipe-search')",
              file=sys.stderr)
        return 2
    searches = {}
    gh_terms = [t for t in (f"{args.model} {args.tool}",
                            f"{args.tool} {args.symptom}".strip(), args.model) if t and t.strip()]
    try:
        searches["github"] = rung_github(gh_terms)          # reuse the code-search rung (D8 recipe-in-config)
    except Exception as e:
        searches["github"] = {"status": "ERROR", "reason": f"{type(e).__name__}: {e}"[:300]}
    q = urllib.parse.quote(" ".join(x for x in (args.model, args.tool, args.symptom) if x))
    try:
        lit = _get_json("https://inspirehep.net/api/literature?q=" + q +
                        "&size=5&fields=titles,arxiv_eprints,document_type")
        hits = lit.get("hits", {}).get("hits", [])
        searches["inspire"] = {"status": "OK", "n": len(hits),
                               "sample": [{"title": (h.get("metadata", {}).get("titles", [{}]) or [{}])[0].get("title"),
                                           "arxiv": [e.get("value") for e in
                                                     h.get("metadata", {}).get("arxiv_eprints", [])]}
                                          for h in hits]}
    except Exception as e:
        searches["inspire"] = {"status": "ERROR", "reason": f"{type(e).__name__}: {e}"[:300]}

    rec = build_recipe_search_record(args.tool, args.model, args.symptom, searches,
                                     _resolve_timestamp(args.timestamp))
    if not rec["searches_ok"]:
        print("resource_census recipe-search: EVERY search failed -- a network/environment finding, "
              "NOT evidence that no recipe exists. Do not close the failure as if the search ran.",
              file=sys.stderr)
        print(json.dumps(rec, indent=1)[:2000], file=sys.stderr)
        return 3
    if args.rundir:
        dest = os.path.join(args.rundir, "inputs", "recipe_search.json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w") as f:
            json.dump(rec, f, indent=2)
        print(f"wrote {dest}")
    else:
        print(json.dumps(rec, indent=2))
    return 0


GEN_STAGES = {"madgraph", "pythia", "shower", "lhe_check", "generate", "generation"}


def _load_run_state(rundir):
    try:
        with open(os.path.join(rundir, "run_state.json")) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _is_generator_model_failure(rec, rel):
    if isinstance(rec, dict):
        if rec.get("failure_class") == "tool_generator_model":
            return True
        if rec.get("stage") in GEN_STAGES:
            return True
    return bool(re.search(r"(madgraph|pythia|shower|gen)", rel or "", re.I))


def assert_recipe_search(rundir):
    """D8 close-block: an OPEN generator-model failure must not be closed without a recipe_search.json.
    Returns (exit_code, messages)."""
    st = _load_run_state(rundir)
    gen_open = []
    for rel in (st.get("open_failure_records") or []):
        try:
            with open(os.path.join(rundir, rel)) as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError):
            rec = {}
        if _is_generator_model_failure(rec, rel):
            gen_open.append(rel)
    has_recipe = os.path.isfile(os.path.join(rundir, "inputs", "recipe_search.json"))
    if gen_open and not has_recipe:
        return 1, ["D8 RESOLVE: generator-model failure(s) open (" + ", ".join(gen_open[:5]) +
                   ") but no inputs/recipe_search.json -- run `resource_census.py --debug "
                   "recipe-search` CO-PRIMARY before closing (a diagnosed generator failure cannot "
                   "be closed on local diagnosis alone)."]
    if gen_open:
        return 0, [f"recipe_search.json present for {len(gen_open)} open generator-model failure(s)"]
    return 0, ["no open generator-model failure -- recipe-search close-block N/A"]


def _assert_recipe_search_main(argv):
    ap = argparse.ArgumentParser(prog="resource_census.py --assert-recipe-search")
    ap.add_argument("--assert-recipe-search", action="store_true", required=True)
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.rundir):
        print(f"resource_census: not a directory: {args.rundir}", file=sys.stderr)
        return 2
    code, msgs = assert_recipe_search(args.rundir.rstrip("/"))
    if args.json:
        print(json.dumps({"gate": "recipe-search-close", "exit": code, "messages": msgs}, indent=2))
    else:
        for m in msgs:
            print(m)
    return code


RECIPE_ARTIFACTS = ("inputs/recipe_search.json", "inputs/generation_recipe.json",
                    "inputs/model_recipe.json")


def _load_contract(rundir):
    for rel in ("inputs/task_contract.json", "task_contract.json"):
        try:
            with open(os.path.join(rundir, rel)) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def assert_pre_generate(rundir):
    """D7 PREVENT: a declared BSM/HV model must carry a FETCHED generation-recipe artifact before
    generating. Conservative: no declared targets.model -> pass (no false block on SM/unknown)."""
    c = _load_contract(rundir)
    model = (c.get("targets") or {}).get("model") if isinstance(c, dict) else None
    if not model:
        return 0, ["no declared targets.model -- pre-generate recipe gate N/A (conservative pass)"]
    have = next((r for r in RECIPE_ARTIFACTS if os.path.isfile(os.path.join(rundir, r))), None)
    if have:
        return 0, [f"generation recipe present ({have}) for model {model!r}"]
    return 1, [f"D7 PREVENT: BSM/HV model {model!r} declared but no fetched generation recipe "
               "(inputs/recipe_search.json | inputs/generation_recipe.json). Fetch the model's "
               "UFO/restrict-card/process recipe (`resource_census.py --debug recipe-search --tool "
               f"madgraph --model {model!r}`) BEFORE launching mg5/generate_events."]


def _assert_pre_generate_main(argv):
    ap = argparse.ArgumentParser(prog="resource_census.py --assert-pre-generate")
    ap.add_argument("--assert-pre-generate", action="store_true", required=True)
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.rundir):
        print(f"resource_census: not a directory: {args.rundir}", file=sys.stderr)
        return 2
    code, msgs = assert_pre_generate(args.rundir.rstrip("/"))
    if args.json:
        print(json.dumps({"gate": "pre-generate-recipe", "exit": code, "messages": msgs}, indent=2))
    else:
        for m in msgs:
            print(m)
    return code


GEN_LAUNCH_RE = re.compile(
    r"generate_events|mg5_aMC|\bmg5\b|pythia_shower|run-pipeline-native\.sh|\.cmnd\b|madevent"
    # RAVEL's own launch forms: a supervised run, partitioned execution and a backend launch.
    r"|\bravel\s+(?:run|partitions\s+run|backend\s+(?:launch|worker))(?![\w-])"
    r"|ravel\.workflow\.(?:partitioned_execution\s+run|execution_backend\s+(?:launch|worker))(?![\w-])"
    # A supervised backend stage, the native launcher and the in-process backend drivers.
    r"|ravel\.workflow\.stage_supervisor\b[^;&|]*--backend-plan"
    r"|ravel\.workflow\.backends\.native\s+launch(?![\w-])"
    r"|\bdrive_stage\s*\(|backend_driver\.drive\s*\("
    # Python that loads a launch module under any name and calls into it (import aliases,
    # from-imports and importlib): the driver module, or a launch call on the backend,
    # partition or lease modules.
    r"|\bpython[\d.]*\b[^\n]*\bravel\.physics\.backend_driver\b"
    r"|\bpython[\d.]*\b[^\n]*\bimport\s+backend_driver\b"
    r"|\bpython[\d.]*\b[^\n]*\b(?:execution_backend|partitioned_execution|machine_lease|backends\.native)\b"
    r"[^\n]*\b(?:submit|worker|capacity|run|launch|acquire|held|drive)\s*\("
    r"|\bpython[\d.]*\b[^\n]*\b(?:execution_backend|partitioned_execution|machine_lease|backends\.native)\s+import\s+"
    r"[^\n;]*\b(?:submit|worker|capacity|run|launch|acquire|held)\b",
    re.I)
_MODULE_CLI = re.compile(r"\b(?:\S*/)?python[\d.]*\s+(?:-[A-Za-z]+\s+)*-m\s+ravel(?:\.cli)?(?=\s|$)")


def normalize_launch_command(cmd):
    """Quotes removed and ``python -m ravel[.cli]`` written as ``ravel``, so equivalent spellings match."""
    text = re.sub(r"[\"'\\]", "", cmd or "")
    text = _MODULE_CLI.sub("ravel", text)
    return re.sub(r"\s+", " ", text)


def is_generation_launch(cmd):
    return bool(GEN_LAUNCH_RE.search(cmd or "") or GEN_LAUNCH_RE.search(normalize_launch_command(cmd)))


RUN_MARKERS = ("inputs/task_contract.json", "task_contract.json", "inputs/checkin1_approval.json",
               "inputs/science.json", "inputs/science-plan.json", "inputs/scoped-plan.json",
               "inputs/native_execution_plan.json")


def _command_words(cmd):
    """Shell words of ``cmd`` with quoting honoured, so a quoted path keeps its spaces; None when unparsable."""
    import shlex
    try:
        return shlex.split(cmd or "", comments=False, posix=True)
    except ValueError:
        return None


def _rundir_candidates(cmd):
    words = _command_words(cmd)
    if words is None:
        return []
    found = []
    for index, word in enumerate(words):
        if word.startswith("--rundir="):
            found.append(word.split("=", 1)[1])
        elif word == "--rundir" and index + 1 < len(words):
            found.append(words[index + 1])
    for word in words:
        for piece in re.split(r"[;&|]", word):
            if "trial-runs/" in piece:
                found.append(piece if os.path.isabs(piece) else piece[piece.index("trial-runs/"):])
    return [value for value in found if value]


READ_ONLY_TOOLS = frozenset(("grep", "rg", "egrep", "fgrep", "cat", "less", "more", "head", "tail", "ls", "find",
                             "sed", "awk", "wc", "file", "stat", "git", "diff", "echo", "printf", "which", "type"))


def launches(cmd):
    """True when some command segment matches a launch form and does not start with a read-only tool.

    A newline separates commands like ``;`` does.
    """
    if not is_generation_launch(cmd):
        return False
    import shlex
    try:
        lexer = shlex.shlex(re.sub(r"\r?\n", " ; ", cmd or ""), posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return True  # unparsable: treat as a launch
    segments, current = [], []
    for token in tokens:
        if token and set(token) <= set(";&|"):
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    for words in segments:
        if words and is_generation_launch(" ".join(words)) and os.path.basename(words[0]) not in READ_ONLY_TOOLS:
            return True
    return False


def _resolve_rundir_from_command(cmd, project_dir):
    """The run directory a launch command names (an explicit --rundir, else a trial-runs path), or None.

    Quoted paths keep their spaces. A path resolves to the nearest enclosing directory
    that carries a run marker (a task contract, CHECK-IN 1 approval or study plan).
    """
    for p in _rundir_candidates(cmd):
        cand = p if os.path.isabs(p) else os.path.join(project_dir or ".", p)
        for _ in range(12):
            if any(os.path.isfile(os.path.join(cand, marker)) for marker in RUN_MARKERS):
                return cand
            nxt = os.path.dirname(cand)
            if nxt == cand:
                break
            cand = nxt
    return None


def _pre_generate_hook_main(argv):
    ap = argparse.ArgumentParser(prog="resource_census.py --pre-generate-hook")
    ap.add_argument("--pre-generate-hook", action="store_true", required=True)
    ap.add_argument("--command", required=True)
    ap.add_argument("--project-dir", default=os.environ.get("CLAUDE_PROJECT_DIR", "."))
    args = ap.parse_args(argv)
    if not is_generation_launch(args.command or ""):
        return 0                               # not a generation launch
    rd = _resolve_rundir_from_command(args.command, args.project_dir)
    if not rd and not launches(args.command):
        return 0                               # the launch pattern appears only in a read-only command
    if not rd:
        # A launch whose run cannot be identified does not run: its gates cannot be checked.
        print("PRE-GENERATE BLOCK: this launch names no run directory that can be identified; pass "
              "--rundir <run> (a directory holding its task contract, CHECK-IN 1 approval or study plan)",
              file=sys.stderr)
        return 2
    code, msgs = assert_pre_generate(rd)
    if code == 1:
        for m in msgs:
            print(m, file=sys.stderr)
        print("PRE-GENERATE BLOCK (D7): fetch the model recipe before generating -- "
              "steps/03-generate.md", file=sys.stderr)
        return 2                               # PostToolUse block convention
    return 0


def _selftest():
    fails = []
    searches = {"github": {"status": "OK", "hits": {"t1": {"repos": [1, 2], "code": [3]}}},
                "inspire": {"status": "ERROR", "reason": "offline"}}
    rec = build_recipe_search_record("madgraph", "SVJ", "undecayed empty SR", searches, "")
    ok1 = (rec["schema_version"] == 1 and rec["mode"] == "recipe-search" and rec["n_hits"] == 3
           and rec["searches_ok"] == ["github"] and rec["co_primary"] is True)
    print(f"[selftest] 1 recipe_search record assembly (n_hits=3, ok=[github]): {'ok' if ok1 else 'FAIL'}")
    if not ok1: fails.append("recipe_search record assembly wrong")
    ok2 = (rec["input_fingerprint"] == _fingerprint("madgraph", "SVJ", "undecayed empty SR")
           and _fingerprint("a", "b", "c") != _fingerprint("a", "b", "d"))
    print(f"[selftest] 2 input_fingerprint stable+sensitive: {'ok' if ok2 else 'FAIL'}")
    if not ok2: fails.append("fingerprint not stable/sensitive")
    rc = _recipe_search_main(["--debug", "not-a-mode", "--tool", "x", "--model", "y"])
    ok3 = (rc == 2)
    print(f"[selftest] 3 --debug not-a-mode -> exit 2: {'ok' if ok3 else 'FAIL'}")
    if not ok3: fails.append(f"bad --debug mode returned {rc}, expected 2")
    with tempfile.TemporaryDirectory(prefix="rc_selftest_") as td:
        os.makedirs(os.path.join(td, "logs"))
        with open(os.path.join(td, "logs", "madgraph.failure.json"), "w") as f:
            json.dump({"stage": "madgraph", "failure_class": "tool_generator_model"}, f)
        with open(os.path.join(td, "run_state.json"), "w") as f:
            json.dump({"open_failure_records": ["logs/madgraph.failure.json"]}, f)
        code, _ = assert_recipe_search(td)
        ok4 = (code == 1)
        print(f"[selftest] 4 open gen-model failure w/o recipe_search -> exit 1: {'ok' if ok4 else 'FAIL'}")
        if not ok4: fails.append("close-block did not fire on missing recipe_search")
        os.makedirs(os.path.join(td, "inputs"))
        with open(os.path.join(td, "inputs", "recipe_search.json"), "w") as f:
            json.dump({"schema_version": 1, "mode": "recipe-search"}, f)
        code, _ = assert_recipe_search(td)
        ok5 = (code == 0)
        print(f"[selftest] 5 recipe_search present -> exit 0: {'ok' if ok5 else 'FAIL'}")
        if not ok5: fails.append("close-block still firing after recipe_search added")
    with tempfile.TemporaryDirectory(prefix="rc_selftest_") as td:
        os.makedirs(os.path.join(td, "inputs"))
        with open(os.path.join(td, "inputs", "task_contract.json"), "w") as f:
            json.dump({"targets": {"model": "SVJ (dark quark)"}}, f)
        code, _ = assert_pre_generate(td)
        ok6 = (code == 1)
        print(f"[selftest] 6 BSM model, no recipe -> exit 1: {'ok' if ok6 else 'FAIL'}")
        if not ok6: fails.append("pre-generate gate did not fire on missing recipe")
        with open(os.path.join(td, "inputs", "generation_recipe.json"), "w") as f:
            json.dump({"model": "SVJ", "process": "p p > ..."}, f)
        code, _ = assert_pre_generate(td)
        ok7 = (code == 0)
        print(f"[selftest] 7 recipe present -> exit 0: {'ok' if ok7 else 'FAIL'}")
        if not ok7: fails.append("pre-generate gate still firing after recipe added")
    with tempfile.TemporaryDirectory(prefix="rc_selftest_") as td:
        rd = os.path.join(td, "trial-runs", "2026-07-09_svj")
        os.makedirs(os.path.join(rd, "inputs"))
        with open(os.path.join(rd, "inputs", "task_contract.json"), "w") as f:
            json.dump({"targets": {"model": "SVJ"}}, f)
        cmd = "bash run-pipeline-native.sh trial-runs/2026-07-09_svj config.toml"
        rc_block = _pre_generate_hook_main(["--pre-generate-hook", "--command", cmd,
                                            "--project-dir", td])
        rc_noop = _pre_generate_hook_main(["--pre-generate-hook", "--command", "ls -la",
                                           "--project-dir", td])
        ok8 = (rc_block == 2 and rc_noop == 0)
        print(f"[selftest] 8 pre-generate-hook blocks mg5 w/o recipe (2), noop on non-gen (0): "
              f"{'ok' if ok8 else 'FAIL'}")
        if not ok8: fails.append(f"pre-generate-hook wrong: block={rc_block} noop={rc_noop}")
    v_abs = hepdata_absence_verdict("1001", 404,
                                    {"status": "OK", "hepdata_listed": False, "ids": []})
    v_inc = hepdata_absence_verdict("1002", 404,
                                    {"status": "OK", "hepdata_listed": True,
                                     "ids": [{"schema": "HEPDATA", "value": "ins1009"}]})
    v_out = hepdata_absence_verdict("1001", 503, None)
    v_net = hepdata_absence_verdict("1001", None, None)
    v_unc = hepdata_absence_verdict("1001", 404, {"status": "ERROR", "reason": "timeout"})
    ok9 = (v_abs["status"] == "ABSENT" and v_abs["corroborated_by_inspire"] is True
           and v_inc["status"] == "ERROR" and v_inc["classification"] == "inconsistent"
           and v_out["classification"] == "outage-or-block"
           and "NOT evidence" in v_out["meaning"]
           and v_net["classification"] == "outage-or-block"
           and v_unc["status"] == "ABSENT" and v_unc["corroborated_by_inspire"] is False)
    print(f"[selftest] 9 R1 absence-vs-outage verdict (404->ABSENT, 404+inspire-listed->"
          f"inconsistent, 5xx/net->outage): {'ok' if ok9 else 'FAIL'}")
    if not ok9: fails.append("hepdata_absence_verdict classification wrong")
    ok10 = (_rung_ok({"status": "OK"}) and _rung_ok(v_abs) and not _rung_ok(v_out)
            and "NO HEPDATA RECORD" in _r1_markdown_line(v_abs)
            and "NOT evidence" in _r1_markdown_line(v_out))
    print(f"[selftest] 10 ABSENT walks the rung + markdown keeps the distinction: "
          f"{'ok' if ok10 else 'FAIL'}")
    if not ok10: fails.append("_rung_ok/_r1_markdown_line wrong")
    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("resource_census selftest: PASS (10 case(s))")
    return 0


def _inspire_hepdata_xcheck(inspire_id):
    """Does INSPIRE's literature record list a HEPDATA external id for this paper?
    Corroboration for the absence verdict -- INSPIRE is the independent registry of which
    papers have a HEPData record at all."""
    return discovery_http.inspire_hepdata_ids(inspire_id)


def hepdata_absence_verdict(inspire_id, http_status, inspire_xcheck):
    """Classify an R1 HEPData failure: DEFINITIVE ABSENCE vs OUTAGE/BLOCK (observed 2026-08-28).

    The physicist decision that hinges on this (drop-the-analysis vs wait-for-the-outage) must
    never be made on a conflated signal: a served 404 from the open record-JSON API means NO
    record exists (a Cloudflare block / outage manifests as 403/5xx/network trouble, never a
    served 404). INSPIRE's external-id list corroborates; if INSPIRE DOES list a HEPDATA id the
    404 is inconsistent and absence must NOT be concluded."""
    url = f"https://www.hepdata.net/record/ins{inspire_id}?format=json"
    if http_status == 404:
        listed = (inspire_xcheck or {}).get("hepdata_listed")
        if listed:
            return {"status": "ERROR", "classification": "inconsistent",
                    "http_status": 404, "url": url, "inspire_xcheck": inspire_xcheck,
                    "reason": "open API served 404 but INSPIRE lists a HEPDATA external id -- "
                              "do NOT conclude absence; re-check manually (browser) before any "
                              "drop decision."}
        corroborated = ((inspire_xcheck or {}).get("status") == "OK" and listed is False)
        return {"status": "ABSENT", "http_status": 404, "url": url,
                "corroborated_by_inspire": corroborated, "inspire_xcheck": inspire_xcheck,
                "meaning": f"DEFINITIVE absence: the open record-JSON API served a 404 -- no "
                           f"HEPData record exists for ins{inspire_id} (a block/outage would be "
                           "403/5xx/network trouble, never a served 404)"
                           + ("" if corroborated else "; INSPIRE corroboration unavailable"),
                "decision_note": "drop-vs-wait may rely on this: absence is a state of the "
                                 "world, not an outage to wait out."}
    reason = (f"HTTP {http_status}" if http_status else "network error (no HTTP status)")
    return {"status": "ERROR", "classification": "outage-or-block",
            "http_status": http_status, "url": url, "reason": reason,
            "meaning": "server/network failure (Cloudflare block, 5xx, timeout) -- NOT evidence "
                       "of absence; retry later or check in a browser. A definitive absence is "
                       "an API 404 (status ABSENT)."}


def _rung_ok(v):
    """A rung counts as WALKED when it reached a definitive answer: OK (record found) or
    ABSENT (definitively no record). ERROR/SKIPPED did not answer."""
    return isinstance(v, dict) and v.get("status") in ("OK", "ABSENT")


def _r1_markdown_line(r1):
    """The CHECK-IN 1 line for R1 -- the absence/outage distinction must survive into the
    physicist-facing text, not just the JSON."""
    s = r1.get("status")
    if s == "ABSENT":
        cor = (", INSPIRE lists no HEPDATA id" if r1.get("corroborated_by_inspire")
               else "; INSPIRE corroboration unavailable")
        return (f"- HEPData: NO HEPDATA RECORD exists (definitive: open-API 404{cor}) -- "
                f"plan around absence, do not wait for an outage ({r1.get('url', '')})")
    if s == "ERROR":
        if r1.get("classification") == "outage-or-block":
            return ("- HEPData: UNREACHABLE (outage/Cloudflare block -- NOT evidence of "
                    f"absence; retry or check in a browser): {r1.get('reason', '')}")
        return f"- HEPData: ERROR ({r1.get('classification', '?')}): {r1.get('reason', '')}"
    return (f"- HEPData: {r1.get('n_tables', '?')} tables; "
            f"{len(r1.get('likelihood_candidates', []))} likelihood-like + "
            f"{len(r1.get('efficiency_map_candidates', []))} efficiency-map-like resources "
            f"({r1.get('url', '')})")


def rung_hepdata(inspire_id):
    """R1: the record's tables + resources tab. Resources are where reinterpretation material
    lives (full likelihoods, efficiency maps, SLHA cards) -- NOT under 'tables'.
    The record is looked up as ins<id>, then under any record id INSPIRE lists for the paper.
    A failure is CLASSIFIED: served 404 -> ABSENT (definitive, INSPIRE-corroborated);
    403/5xx/network -> ERROR outage-or-block (never evidence of absence)."""
    found = discovery_http.fetch_hepdata_record(inspire_id)
    if found["status"] != "OK":
        status = found["http_status"]
        v = hepdata_absence_verdict(inspire_id, status, found.get("inspire_xcheck"))
        if status is None or (v["status"] == "ERROR" and v.get("classification") == "outage-or-block"):
            v["reason"] = found.get("reason") or v.get("reason")
        v["attempts"] = found.get("attempts", [])
        return v
    data = found["record"]
    tables = [t.get("name", "") for t in data.get("data_tables", [])]
    resources = []
    for res in (data.get("record", {}) or {}).get("resources", []) or data.get("resources", []):
        resources.append({"name": res.get("filename") or res.get("description", ""),
                          "type": res.get("type", ""), "url": res.get("url", "")})
    likelihoods = [r for r in resources if re.search(
        r"likelihood|histfactory|statistical|workspace|pyhf", json.dumps(r), re.I)]
    effmaps = [r for r in resources if re.search(
        r"eff|acceptance|map|tracklet|parameteri", json.dumps(r), re.I)]
    out = {"status": "OK", "url": f"{discovery_http.HEPDATA}/record/{found['ref']}",
           "n_tables": len(tables), "table_names_sample": tables[:12],
           "n_resources": len(resources), "resources": resources[:40],
           "likelihood_candidates": likelihoods, "efficiency_map_candidates": effmaps}
    recid = data.get("recid") or (data.get("record") or {}).get("recid")
    if recid:
        out["hepdata_recid"] = recid
    if found["resolved_via"] != "inspire-id":
        out["resolved_via"] = found["resolved_via"]
        out["attempts"] = found["attempts"]
    return out


def rung_routines(query):
    """R2: Rivet + SimpleAnalysis via the routine resolver (codes, not vocabulary). Local source
    trees are scanned when present; the packaged catalogue snapshot is always consulted, and an
    absent tree is reported as not checked rather than as zero matches. `query` is one string
    or several (e.g. the INSPIRE id and the analysis code); their matches are merged."""
    from ravel.workflow import routine_fetch
    queries = [query] if isinstance(query, str) else [q for q in query if q]
    found = None
    for q in queries:
        part = routine_fetch.find_routines(q)
        if found is None:
            found = part
            continue
        found["query"] += " | " + q
        for key in ("rivet", "simpleanalysis", "catalog"):
            have = {json.dumps(m, sort_keys=True) for m in found[key]["matches"]}
            found[key]["matches"] += [m for m in part[key]["matches"]
                                      if json.dumps(m, sort_keys=True) not in have]
    checked = [k for k in ("rivet", "simpleanalysis", "catalog") if found[k]["checked"]]
    return {"status": "OK" if checked else "ERROR", "query": found["query"], "checked": checked,
            "not_checked": [k for k in ("rivet", "simpleanalysis") if not found[k]["checked"]],
            "routines": found, "report": routine_fetch.format_report(found)[-2000:]}


def rung_arxiv(arxiv_id):
    """R3: metadata via the export API; source tarball is what fetch_figures consumes."""
    url = ("http://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv_id))
    with discovery_http.open_url(url, accept="application/atom+xml", timeout=25) as r:
        xml = r.read().decode("utf-8", "replace")
    title = re.search(r"<title>([^<]+)</title>\s*<id>", xml) or re.search(
        r"<entry>.*?<title>([^<]+)</title>", xml, re.S)
    return {"status": "OK", "abs": f"https://arxiv.org/abs/{arxiv_id}",
            "e_print": f"https://arxiv.org/e-print/{arxiv_id}",
            "title": (title.group(1).strip() if title else "(unparsed)")}


def _gh():
    """The GitHub CLI: RAVEL_GH if set, else `gh` on PATH."""
    for g in (os.environ.get("RAVEL_GH"), shutil.which("gh")):
        if not g:
            continue
        try:
            subprocess.run([g, "--version"], capture_output=True, timeout=10)
            return g
        except Exception:
            continue
    return None


def rung_github(terms):
    """R4: GitHub search per term — repositories AND code. Code search is the rung that finds
    recast repos which never carry the analysis id in their name/description (the RS1/mapyde
    case: the id lives in its run configs)."""
    g = _gh()
    if g is None:
        return {"status": "SKIPPED", "reason": "gh CLI not found (set RAVEL_GH or put gh on PATH) -- walk this rung manually "
                                                "(github.com search on the analysis + arXiv ids)"}
    hits = {}
    for term in terms:
        if not term:
            continue
        q = urllib.parse.quote(f'"{term}"')
        entry = {"repos": [], "code": []}
        out = subprocess.run(
            [g, "api", f"search/repositories?q={q}&per_page=6",
             "--jq", ".items[] | {full_name, html_url, pushed_at, description}"],
            capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            entry["repos"] = [json.loads(l) for l in out.stdout.splitlines() if l.strip()]
        else:
            entry["repos_error"] = out.stderr.strip()[:160]
        outc = subprocess.run(
            [g, "api", f"search/code?q={q}&per_page=8",
             "--jq", ".items[] | {repo: .repository.full_name, path, html_url}"],
            capture_output=True, text=True, timeout=60)
        if outc.returncode == 0:
            seen, rows = set(), []
            for l in outc.stdout.splitlines():
                if not l.strip():
                    continue
                row = json.loads(l)
                if row["repo"] not in seen:
                    seen.add(row["repo"])
                    rows.append(row)
            entry["code"] = rows
        else:
            entry["code_error"] = outc.stderr.strip()[:160]   # code search needs an auth token
        hits[term] = entry
    return {"status": "OK", "hits": hits}


def rung_inspire_zenodo(inspire_id, analysis_id):
    """R5: forward citations (recasts + theses -- theses carry the cutflows) + Zenodo."""
    out = {"status": "OK"}
    url = ("https://inspirehep.net/api/literature?sort=mostrecent&size=20"
           "&fields=titles,document_type,arxiv_eprints"
           f"&q=refersto%20recid%20{inspire_id}")
    data = _get_json(url)
    total = data.get("hits", {}).get("total", 0)
    entries = []
    for h in data.get("hits", {}).get("hits", []):
        md = h.get("metadata", {})
        title = (md.get("titles") or [{}])[0].get("title", "")
        dtype = ",".join(md.get("document_type", []))
        entries.append({"title": title[:110], "type": dtype})
    theses = [e for e in entries if "thesis" in e["type"]]
    recasty = [e for e in entries if re.search(r"reinterpret|recast|constrain|implication",
                                               e["title"], re.I)]
    out["inspire"] = {"total_citations": total, "recent_sample": entries,
                      "theses_in_sample": theses, "recast_like_in_sample": recasty,
                      "note": "sample = 20 most recent only; walk the full list for a deep hunt"}
    try:
        z = _get_json("https://zenodo.org/api/records?size=5&q=" +
                      urllib.parse.quote(f'"{analysis_id}"'))
        zhits = [{"title": r.get("metadata", {}).get("title", "")[:110],
                  "doi": r.get("doi", "")} for r in z.get("hits", {}).get("hits", [])]
        out["zenodo"] = {"n": z.get("hits", {}).get("total", 0), "sample": zhits}
    except Exception as e:                                    # zenodo is the optional half
        out["zenodo"] = {"status": "ERROR", "reason": str(e)[:160]}
    return out


MANUAL_RUNGS = [
    "Collaboration public pages (ATLAS glance / CMS public results): JS-walled -- use the "
    "browser (Chrome MCP) when the record above lacks something the paper says exists.",
    "Recast DB listings not queried live here: MadAnalysis5 PAD, CheckMATE, SModelS "
    "(SModelS is installed locally -- reinterpret_db.py).",
    "Analysis TWiki / auxiliary-material page linked from the paper's footnotes.",
]


OFFLINE_NOT_CONSULTED = "offline: network egress unavailable; not consulted"
OFFLINE_NO_COPY = "offline: network egress unavailable; no local mirror copy"


def _offline_metadata(mirror):
    return {"offline": True, "mirror": os.path.abspath(mirror) if mirror else None}


def _mirror_hepdata(inspire, mirror):
    if mirror:
        path = os.path.join(os.path.abspath(mirror), "hepdata", f"ins{inspire}", "record.json")
        try:
            with open(path) as stream:
                record = json.load(stream)
            if isinstance(record, dict):
                return {"status": "OK", "source": "local-mirror", "path": path,
                        "keys": sorted(record)}
        except (OSError, ValueError):
            pass
    return {"status": "SKIPPED", "reason": OFFLINE_NO_COPY}


def census_one(inspire, arxiv=None, analysis_id=None, *, offline=False, mirror=None):
    """Walk R1-R5 for one analysis -> the per-analysis census record."""
    inspire = discovery_http.inspire_digits(inspire)
    rungs = {}
    for name, fn, fnargs in [
        ("R1_hepdata", rung_hepdata, (inspire,)),
        ("R2_routines", rung_routines, ([f"ins{inspire}", analysis_id],)),
        ("R3_arxiv", rung_arxiv, (arxiv,)) if arxiv else ("R3_arxiv", None, ()),
        ("R4_github", rung_github, ([analysis_id, arxiv, f"ins{inspire}"],)),
        ("R5_citations", rung_inspire_zenodo, (inspire, analysis_id or "")),
    ]:
        if offline and name == "R1_hepdata":
            rungs[name] = _mirror_hepdata(inspire, mirror)
            continue
        if offline and name != "R2_routines":
            rungs[name] = {"status": "SKIPPED", "reason": OFFLINE_NOT_CONSULTED}
            continue
        if fn is None:
            rungs[name] = {"status": "SKIPPED", "reason": "no --arxiv given"}
            continue
        try:
            rungs[name] = fn(*fnargs)
        except Exception as e:
            rungs[name] = {"status": "ERROR", "reason": f"{type(e).__name__}: {e}"[:300]}
    return {"schema_version": 1, "kind": "analysis", "id": f"ins{inspire}",
            "analysis_id": analysis_id, "inspire": inspire, "arxiv": arxiv,
            "rungs": rungs, "manual_rungs": MANUAL_RUNGS,
            **(_offline_metadata(mirror) if offline else {}),
            "rungs_ok": [k for k, v in rungs.items() if _rung_ok(v)]}


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "query"


def keyword_search(query, limit=5, *, offline=False, mirror=None):
    """HEPData + INSPIRE searches for a topic -> the search record with merged candidates."""
    searches = {}
    for name, fn in (("hepdata_search", discovery_http.search_hepdata),
                     ("inspire_search", discovery_http.search_inspire)):
        if offline:
            searches[name] = {"status": "SKIPPED", "reason": OFFLINE_NOT_CONSULTED}
            continue
        try:
            searches[name] = fn(query, size=max(limit, 1) * 2)
        except Exception as e:
            searches[name] = {"status": "ERROR", "reason": f"{type(e).__name__}: {e}"[:300]}
    candidates = {}
    for name, source in (("hepdata_search", "hepdata"), ("inspire_search", "inspire")):
        for hit in searches[name].get("hits") or []:
            if not hit.get("inspire"):
                continue
            c = candidates.setdefault(hit["inspire"], {
                "inspire": hit["inspire"], "title": hit.get("title"), "arxiv": None,
                "analysis_id": None, "collaborations": [], "found_by": []})
            c["found_by"].append(source)
            c["arxiv"] = c["arxiv"] or hit.get("arxiv")
            c["analysis_id"] = c["analysis_id"] or next(iter(hit.get("analysis_ids") or []), None)
            for coll in hit.get("collaborations") or []:
                if coll not in c["collaborations"]:
                    c["collaborations"].append(coll)
            for key in ("hepdata_recid", "n_tables", "analyses"):
                if hit.get(key) is not None:
                    c[key] = hit[key]
    # dicts keep first-seen order, so ties stay in search-relevance order
    ordered = sorted(candidates.values(), key=lambda c: -len(c["found_by"]))
    return {"schema_version": 1, "kind": "search", "id": "search-" + _slug(query),
            "query": query, "searches": searches, "candidates": ordered,
            **(_offline_metadata(mirror) if offline else {}),
            "rungs": {k: {"status": v.get("status"), "n_hits": len(v.get("hits") or []),
                          **({"reason": v["reason"]} if offline and "reason" in v else {})}
                      for k, v in searches.items()},
            "rungs_ok": [k for k, v in searches.items() if v.get("status") == "OK"]}


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def _rung_summary(v):
    keep = ("status", "classification", "url", "n_tables", "n_hits", "reason")
    return {k: v[k] for k in keep if isinstance(v, dict) and k in v}


def write_index(rundir, timestamp=""):
    """Rebuild inputs/resource_census.json from every record in inputs/resource_census/.
    A single-analysis census written before the folder existed is moved into it first."""
    inputs = os.path.join(rundir, "inputs")
    folder = os.path.join(inputs, "resource_census")
    index_path = os.path.join(inputs, "resource_census.json")
    if os.path.isfile(index_path):
        try:
            with open(index_path) as f:
                prior = json.load(f)
        except (OSError, json.JSONDecodeError):
            prior = None
        if isinstance(prior, dict) and prior.get("kind") != "resource-census-index" and prior.get("rungs"):
            ident = (f"ins{prior['inspire']}" if prior.get("inspire")
                     else _slug(str(prior.get("analysis_id") or "census")))
            prior.setdefault("kind", "analysis")
            prior.setdefault("id", ident)
            dest = os.path.join(folder, ident + ".json")
            if not os.path.exists(dest):
                _write_json(dest, prior)
    entries, searches, rungs, records = [], [], {}, {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name)) as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("rungs"), dict):
            continue
        ident = name[:-5]
        rel = f"inputs/resource_census/{name}"
        records[ident] = doc
        if doc.get("kind") == "search":
            searches.append({"id": ident, "query": doc.get("query"), "file": rel,
                             "n_candidates": len(doc.get("candidates") or []),
                             "rungs_ok": doc.get("rungs_ok", [])})
        else:
            entries.append({"id": ident, "inspire": doc.get("inspire"),
                            "analysis_id": doc.get("analysis_id"), "arxiv": doc.get("arxiv"),
                            "file": rel, "rungs_ok": doc.get("rungs_ok", [])})
        for rung, v in doc["rungs"].items():
            rungs[f"{ident}/{rung}"] = _rung_summary(v)
    index = {"schema_version": 2, "kind": "resource-census-index",
             "generator": "resource_census.py", "generated_utc": timestamp,
             "entries": entries, "searches": searches, "rungs": rungs,
             "rungs_ok": [k for k, v in rungs.items() if _rung_ok(v)],
             "manual_rungs": MANUAL_RUNGS}
    if len(entries) == 1 and not searches:
        only = records[entries[0]["id"]]
        index.update({"analysis_id": only.get("analysis_id"), "inspire": only.get("inspire"),
                      "arxiv": only.get("arxiv"), "rungs": only["rungs"],
                      "rungs_ok": [k for k, v in only["rungs"].items() if _rung_ok(v)]})
    _write_json(index_path, index)
    return index_path, index


def _markdown(census):
    if census.get("offline"):
        lines = [f"\n### Resource census: {census.get('analysis_id') or census['id']} (offline)"]
        for name, rung in census["rungs"].items():
            detail = (f"local-mirror {rung['path']}; keys: {', '.join(rung['keys'])}"
                      if rung.get("source") == "local-mirror" else rung.get("reason", "local lookup"))
            lines.append(f"- {name}: {rung.get('status')}; {detail}")
        return "\n".join(lines)
    rungs = census["rungs"]
    r1 = rungs.get("R1_hepdata", {})
    r2 = rungs.get("R2_routines", {})
    r5 = rungs.get("R5_citations", {})
    gh_hits = rungs.get("R4_github", {}).get("hits", {})
    n_gh = sum(len(v.get("repos", [])) + len(v.get("code", []))
               for v in gh_hits.values() if isinstance(v, dict))
    label = census.get("analysis_id") or census["id"]
    lines = [f"\n### Resource census: {label} (what exists online for this analysis)",
             _r1_markdown_line(r1)]
    found = r2.get("routines") or {}
    if found:
        parts = []
        for key, name in (("rivet", "Rivet"), ("simpleanalysis", "SimpleAnalysis"),
                          ("catalog", "catalogue snapshot")):
            part = found.get(key) or {}
            parts.append(f"{name} {len(part.get('matches') or [])}" if part.get("checked")
                         else f"{name} not checked")
        lines.append("- Routines: " + ", ".join(parts))
    else:
        lines.append("- Routines: see R2 report (Rivet/SimpleAnalysis resolver output)")
    lines.append(f"- GitHub: {n_gh} repos across the id searches" +
                 (" — LOOK at them before declaring anything unavailable" if n_gh else
                  " (searched; none — record that, it caps the source-ladder)"))
    insp = r5.get("inspire", {})
    lines.append(f"- Forward citations: {insp.get('total_citations', '?')} total; "
                 f"{len(insp.get('theses_in_sample', []))} theses + "
                 f"{len(insp.get('recast_like_in_sample', []))} recast-like in the recent sample "
                 f"(theses carry cutflows)")
    lines.append("- Manual rungs still open: " + " · ".join(m.split(":")[0] for m in MANUAL_RUNGS))
    return "\n".join(lines)


def _search_markdown(search):
    lines = [f"\n### Resource search: \"{search['query']}\""]
    if search.get("offline"):
        lines.append("- Offline; remote searches not consulted")
    for k, v in search["searches"].items():
        failure_status = v.get("status", "ERROR") if search.get("offline") else "ERROR"
        lines.append(f"- {k}: " + (f"{v.get('total', '?')} total, {len(v.get('hits') or [])} read"
                                   if v.get("status") == "OK" else f"{failure_status} {v.get('reason', '')}"))
    for c in search["candidates"][:15]:
        lines.append(f"- ins{c['inspire']} {c.get('analysis_id') or ''} {c.get('title') or ''} "
                     f"[{', '.join(c['found_by'])}]".replace("  ", " "))
    return "\n".join(lines)


def _parse_analysis(spec):
    fields = {}
    for part in spec.split(","):
        key, sep, value = part.partition("=")
        key = key.strip().lower()
        if not sep or key not in ("inspire", "arxiv", "id") or not value.strip():
            raise argparse.ArgumentTypeError(
                f"--analysis {spec!r}: use inspire=<id>[,arxiv=<id>][,id=<analysis code>]")
        fields[key] = value.strip()
    if "inspire" not in fields:
        raise argparse.ArgumentTypeError(f"--analysis {spec!r} needs inspire=<id>")
    try:
        discovery_http.inspire_digits(fields["inspire"])
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))
    return fields


def reading_targets(reading):
    """``(analyses, keywords)`` a pinned request reading names, for a census with no hand-typed ids.

    Identifier facts give analyses: an INSPIRE id anchors one record (with the arXiv id and analysis
    code the reading also states); an arXiv id or analysis code alone is a keyword search. Without
    identifiers, publication titles, else model terms with experiments, are the topic keywords.
    Nothing is inferred beyond what the reading states.
    """
    if not isinstance(reading, dict):
        raise ValueError("the reading is not a JSON object")
    facts = [f for f in reading.get("facts") or () if isinstance(f, dict)]
    ids = {}
    for fact in facts:
        value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
        if fact.get("type") == "identifier" and isinstance(value.get("id"), str):
            ids.setdefault(value.get("scheme"), []).append(value["id"])
    analyses, keywords = [], []
    inspire = ids.get("inspire") or []
    arxiv, codes = ids.get("arxiv") or [], ids.get("analysis") or []
    for index, record in enumerate(inspire):
        analyses.append({"inspire": record, "arxiv": arxiv[index] if len(inspire) == 1 and arxiv else None,
                         "id": codes[index] if len(inspire) == 1 and codes else None})
    if not inspire:
        keywords += list(dict.fromkeys(arxiv + codes))
    if not analyses and not keywords:
        titles = [str((f.get("value") or {}).get("text") or "").strip() for f in facts
                  if f.get("type") == "publication_title"]
        keywords += [t for t in titles if t]
    if not analyses and not keywords:
        terms = [str((f.get("value") or {}).get("text") or "").strip() for f in facts
                 if f.get("type") in ("model_term", "experiment")]
        terms = [t for t in dict.fromkeys(terms) if t]
        if terms:
            keywords.append(" ".join(terms))
    return analyses, keywords


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--fetch-published-data" in argv:
        # The registered acquisition operation keeps one implementation entry. Numeric
        # data acquisition retains the data reader's source-policy and completeness guards.
        from ravel.workflow import hepdata_fetch
        return hepdata_fetch.main([a for a in argv if a != "--fetch-published-data"])
    # New modes dispatch BEFORE the required-arg parse (--inspire is required=True): a recipe search
    # keyed on a free-text model has no INSPIRE id (shape_fit's pre-parse intercept pattern).
    if "--selftest" in argv:
        return _selftest()
    if "--debug" in argv:
        if "--offline" in argv:
            print("resource_census: --offline is unavailable for --debug", file=sys.stderr)
            return 2
        return _recipe_search_main(argv)
    if "--assert-recipe-search" in argv:
        return _assert_recipe_search_main(argv)
    if "--assert-pre-generate" in argv:
        return _assert_pre_generate_main(argv)
    if "--pre-generate-hook" in argv:
        return _pre_generate_hook_main(argv)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inspire", help="INSPIRE record id (digits, 'ins' prefix optional)")
    ap.add_argument("--arxiv", default=None, help="arXiv id, YYMM.NNNNN (with --inspire)")
    ap.add_argument("--analysis-id", default=None, help="the experiment analysis code (with --inspire)")
    ap.add_argument("--analysis", action="append", type=_parse_analysis, default=[],
                    metavar="inspire=ID[,arxiv=ID][,id=CODE]",
                    help="one analysis to census (repeatable)")
    ap.add_argument("--keyword", action="append", default=[], metavar="TEXT",
                    help="topic search on HEPData + INSPIRE (repeatable)")
    ap.add_argument("--limit", type=int, default=5,
                    help="keyword candidates to census per search (default 5)")
    ap.add_argument("--search-only", action="store_true",
                    help="record keyword searches without censusing their candidates")
    ap.add_argument("--rundir", default=None,
                    help="write inputs/resource_census/<id>.json + the inputs/resource_census.json index")
    ap.add_argument("--markdown", action="store_true", help="print the CHECK-IN 1 block")
    ap.add_argument("--timestamp", default=None)
    ap.add_argument("--offline", action="store_true", help="consult local sources only")
    ap.add_argument("--mirror", help="local source mirror directory (requires --offline)")
    ap.add_argument("--reading", default=None, metavar="READING_JSON",
                    help="census the analyses and topic a pinned request reading names "
                         "(identifier facts; else its publication titles, model terms and experiments)")
    ap.add_argument("--controller-output", default=None,
                    help="write one self-contained census record with every member embedded")
    args = ap.parse_args(argv)
    if args.mirror and not args.offline:
        ap.error("--mirror requires --offline")
    offline_fields = _offline_metadata(args.mirror) if args.offline else {}
    analyses = list(args.analysis)
    if args.inspire:
        analyses.insert(0, {"inspire": args.inspire, "arxiv": args.arxiv, "id": args.analysis_id})
    elif args.arxiv or args.analysis_id:
        ap.error("--arxiv/--analysis-id describe the --inspire analysis; use --analysis for several")
    if args.reading:
        try:
            from ravel.workflow.state_io import read_json
            found, keywords = reading_targets(read_json(args.reading))
        except (OSError, ValueError) as exc:
            ap.error(f"--reading: {exc}")
        analyses += found
        args.keyword = list(args.keyword) + keywords
    if not analyses and not args.keyword:
        if args.reading and args.controller_output and not args.rundir:
            # The controller's census of a pinned reading that names no analysis or topic: the sweep's first
            # rung (the request's own stated facts) definitively found nothing to sweep. That is a record of
            # this request, never a network finding; no public source was consulted or read as absent.
            _write_json(args.controller_output, {
                "schema_version": 1, **offline_fields, "records": [], "targets": {"analyses": [], "keywords": []},
                "rungs": {"reading/targets": {
                    "status": "ABSENT",
                    "reason": "the pinned reading names no analysis identifier, publication title, model term "
                              "or experiment; no public source was consulted"}}})
            return 0
        ap.error("give --inspire, --analysis, --keyword or a --reading that names an analysis or topic")

    local_options = {"offline": True, "mirror": args.mirror} if args.offline else {}
    searches = [keyword_search(q, args.limit, **local_options) for q in args.keyword]
    if not args.search_only:
        seen = {discovery_http.inspire_digits(a["inspire"]) for a in analyses}
        for search in searches:
            for c in search["candidates"][:max(args.limit, 0)]:
                if c["inspire"] not in seen:
                    seen.add(c["inspire"])
                    analyses.append({"inspire": c["inspire"], "arxiv": c.get("arxiv"),
                                     "id": c.get("analysis_id")})
    censuses = [census_one(a["inspire"], a.get("arxiv"), a.get("id"),
                           **local_options) for a in analyses]

    records = censuses + searches
    if not args.offline and not any(r["rungs_ok"] for r in records):
        print("resource_census: EVERY rung failed -- that is a network/environment finding, "
              "NOT evidence that nothing exists. Do not proceed as if the sweep ran.",
              file=sys.stderr)
        print(json.dumps(records, indent=1)[:2000], file=sys.stderr)
        return 3

    if args.controller_output:
        if args.rundir:
            ap.error("--controller-output and --rundir are separate output modes")
        _write_json(args.controller_output, {"schema_version": 1, **offline_fields, "records": records,
                    "rungs": {f"{index}/{name}": rung for index, rec in enumerate(records)
                              for name, rung in (rec.get("rungs") or {}).items()}})
    elif args.rundir:
        folder = os.path.join(args.rundir, "inputs", "resource_census")
        write_index(args.rundir, _resolve_timestamp(args.timestamp))   # keeps a prior census
        for rec in records:
            dest = os.path.join(folder, rec["id"] + ".json")
            _write_json(dest, rec)
            print(f"wrote {dest}")
        index_path, index = write_index(args.rundir, _resolve_timestamp(args.timestamp))
        if offline_fields:
            index.update(offline_fields)
            _write_json(index_path, index)
        print(f"wrote {index_path}")
    elif len(records) == 1:
        print(json.dumps(records[0], indent=1))
    else:
        print(json.dumps(records, indent=1))

    if args.markdown:
        for search in searches:
            print(_search_markdown(search))
        for census in censuses:
            print(_markdown(census))
    return 0


if __name__ == "__main__":
    sys.exit(main())
