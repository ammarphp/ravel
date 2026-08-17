#!/usr/bin/env python3
"""resource_census -- the RESOURCE SWEEP (source-ladder rungs 1-5, automated; CR-017).

The failure this kills: the analysis's public code/data sitting unexamined online while the run
improvises around "unavailable" information (the missed-RRR-repo incident; the HEPData
"impossible download" that fell to a second look). For a given analysis it walks, cheaply and
WITHOUT downloading bulk data:

  R1  HEPData record        tables + the RESOURCES tab (likelihoods, efficiency maps, cards)
  R2  analysis routines     Rivet + SimpleAnalysis via routine_fetch.py
  R3  arXiv                 e-print metadata (source availability for figure extraction)
  R4  GitHub                repository search on the analysis id + arXiv id (gh CLI)
  R5  INSPIRE               forward citations (recasts + THESES carry cutflows) + Zenodo search

Manual rungs it CANNOT walk (recorded as pointers in the output): collaboration glance/twiki
pages and JS-walled public-results pages (browser territory), MA5-PAD/CheckMATE listings.

Output: <rundir>/inputs/resource_census.json (machine) and, with --markdown, the CHECK-IN 1
"what exists online" block (human). Fail-soft per rung (network trouble -> rung status ERROR
with the reason -- never a fabricated 'nothing exists'), fail-LOUD on no rung succeeding.

Usage:
  python3 resource_census.py --inspire 1767649 --arxiv 1911.12606 \
      --analysis-id ATLAS-SUSY-2018-16 [--rundir <dir>] [--markdown]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse

UA = {"User-Agent": "hep-agentic-pipeline resource_census (research use)"}
HERE = os.path.dirname(os.path.abspath(__file__))
GH_CANDIDATES = ("gh", os.path.expanduser("~/.local/bin/gh"))

# Verified TLS or nothing: the system python on this host lacks a CA bundle; certifi (present in
# the conda envs) supplies one. NO ssl-noverify fallback -- that residue was flagged by the
# transcript mining as a shipped liability. If this raises, run under the rivet/reinterp env.
try:
    import ssl
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:                                             # no certifi: default context
    _SSL_CTX = None


def _get_json(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            raise RuntimeError(
                "TLS verification failed under this python (no CA bundle). Re-run under a conda "
                "env with certifi (e.g. `<conda> run -n rivet python resource_census.py ...`). "
                "Do NOT bypass verification.") from e
        raise


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


GEN_LAUNCH_RE = re.compile(r"generate_events|mg5_aMC|\bmg5\b|pythia_shower|run-pipeline-native\.sh|\.cmnd\b|madevent",
                           re.I)


def _resolve_rundir_from_command(cmd, project_dir):
    m = re.search(r"trial-runs/[^\s\"']+", cmd or "")
    if not m:
        return None
    p = m.group(0)
    cand = p if os.path.isabs(p) else os.path.join(project_dir or ".", p)
    for _ in range(12):
        if (os.path.isfile(os.path.join(cand, "inputs", "task_contract.json"))
                or os.path.isfile(os.path.join(cand, "task_contract.json"))):
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
    if not GEN_LAUNCH_RE.search(args.command or ""):
        return 0                               # not a generation launch
    rd = _resolve_rundir_from_command(args.command, args.project_dir)
    if not rd:
        return 0                               # can't identify the run dir; defer to the step-doc gate
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
    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("resource_census selftest: PASS (8 case(s))")
    return 0


def rung_hepdata(inspire_id):
    """R1: the record's tables + resources tab. Resources are where reinterpretation material
    lives (full likelihoods, efficiency maps, SLHA cards) -- NOT under 'tables'."""
    url = f"https://www.hepdata.net/record/ins{inspire_id}?format=json"
    data = _get_json(url)
    tables = [t.get("name", "") for t in data.get("data_tables", [])]
    resources = []
    for res in (data.get("record", {}) or {}).get("resources", []) or data.get("resources", []):
        resources.append({"name": res.get("filename") or res.get("description", ""),
                          "type": res.get("type", ""), "url": res.get("url", "")})
    likelihoods = [r for r in resources if re.search(
        r"likelihood|histfactory|statistical|workspace|pyhf", json.dumps(r), re.I)]
    effmaps = [r for r in resources if re.search(
        r"eff|acceptance|map|tracklet|parameteri", json.dumps(r), re.I)]
    return {"status": "OK", "url": f"https://www.hepdata.net/record/ins{inspire_id}",
            "n_tables": len(tables), "table_names_sample": tables[:12],
            "n_resources": len(resources), "resources": resources[:40],
            "likelihood_candidates": likelihoods, "efficiency_map_candidates": effmaps}


def rung_routines(query):
    """R2: Rivet + SimpleAnalysis via the existing resolver (codes, not vocabulary)."""
    rf = os.path.join(HERE, "routine_fetch.py")
    out = subprocess.run([sys.executable, rf, "--query", query],
                         capture_output=True, text=True, timeout=120)
    text = (out.stdout + out.stderr).strip()
    return {"status": "OK" if out.returncode == 0 else "NONZERO",
            "query": query, "report": text[-2000:]}


def rung_arxiv(arxiv_id):
    """R3: metadata via the export API; source tarball is what fetch_figures consumes."""
    url = ("http://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv_id))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        xml = r.read().decode("utf-8", "replace")
    title = re.search(r"<title>([^<]+)</title>\s*<id>", xml) or re.search(
        r"<entry>.*?<title>([^<]+)</title>", xml, re.S)
    return {"status": "OK", "abs": f"https://arxiv.org/abs/{arxiv_id}",
            "e_print": f"https://arxiv.org/e-print/{arxiv_id}",
            "title": (title.group(1).strip() if title else "(unparsed)")}


def _gh():
    for g in GH_CANDIDATES:
        try:
            subprocess.run([g, "--version"], capture_output=True, timeout=10)
            return g
        except Exception:
            continue
    return None


def rung_github(terms):
    """R4: GitHub search per term — repositories AND code. Code search is the rung that finds
    recast repos which never carry the analysis id in their name/description (the RRR/mapyde
    case: the id lives in its run configs)."""
    g = _gh()
    if g is None:
        return {"status": "SKIPPED", "reason": "gh CLI not found -- walk this rung manually "
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # New modes dispatch BEFORE the required-arg parse (--inspire is required=True): a recipe search
    # keyed on a free-text model has no INSPIRE id (shape_fit's pre-parse intercept pattern).
    if "--selftest" in argv:
        return _selftest()
    if "--debug" in argv:
        return _recipe_search_main(argv)
    if "--assert-recipe-search" in argv:
        return _assert_recipe_search_main(argv)
    if "--assert-pre-generate" in argv:
        return _assert_pre_generate_main(argv)
    if "--pre-generate-hook" in argv:
        return _pre_generate_hook_main(argv)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inspire", required=True, help="INSPIRE record id (digits, no 'ins')")
    ap.add_argument("--arxiv", default=None, help="arXiv id, e.g. 1911.12606")
    ap.add_argument("--analysis-id", default=None, help="e.g. ATLAS-SUSY-2018-16")
    ap.add_argument("--rundir", default=None, help="write inputs/resource_census.json here")
    ap.add_argument("--markdown", action="store_true", help="print the CHECK-IN 1 block")
    args = ap.parse_args(argv)

    rungs = {}
    for name, fn, fnargs in [
        ("R1_hepdata", rung_hepdata, (args.inspire,)),
        ("R2_routines", rung_routines, (f"ins{args.inspire}",)),
        ("R3_arxiv", rung_arxiv, (args.arxiv,)) if args.arxiv else
        ("R3_arxiv", None, ()),
        ("R4_github", rung_github, ([args.analysis_id, args.arxiv,
                                     f"ins{args.inspire}"],)),
        ("R5_citations", rung_inspire_zenodo, (args.inspire, args.analysis_id or "")),
    ]:
        if fn is None:
            rungs[name] = {"status": "SKIPPED", "reason": "no --arxiv given"}
            continue
        try:
            rungs[name] = fn(*fnargs)
        except Exception as e:
            rungs[name] = {"status": "ERROR", "reason": f"{type(e).__name__}: {e}"[:300]}

    ok = [k for k, v in rungs.items() if v.get("status") == "OK"]
    census = {"schema_version": 1, "analysis_id": args.analysis_id,
              "inspire": args.inspire, "arxiv": args.arxiv,
              "rungs": rungs, "manual_rungs": MANUAL_RUNGS,
              "rungs_ok": ok}
    if not ok:
        print("resource_census: EVERY rung failed -- that is a network/environment finding, "
              "NOT evidence that nothing exists. Do not proceed as if the sweep ran.",
              file=sys.stderr)
        print(json.dumps(census, indent=1)[:2000], file=sys.stderr)
        return 3

    if args.rundir:
        dest = os.path.join(args.rundir, "inputs", "resource_census.json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w") as f:
            json.dump(census, f, indent=1)
        print(f"wrote {dest}")
    else:
        print(json.dumps(census, indent=1))

    if args.markdown:
        r1 = rungs.get("R1_hepdata", {})
        r5 = rungs.get("R5_citations", {})
        gh_hits = rungs.get("R4_github", {}).get("hits", {})
        n_gh = sum(len(v.get("repos", [])) + len(v.get("code", []))
                   for v in gh_hits.values() if isinstance(v, dict))
        print("\n### Resource census (what exists online for this analysis)")
        print(f"- HEPData: {r1.get('n_tables', '?')} tables; "
              f"{len(r1.get('likelihood_candidates', []))} likelihood-like + "
              f"{len(r1.get('efficiency_map_candidates', []))} efficiency-map-like resources "
              f"({r1.get('url', '')})")
        print(f"- Routines: see R2 report (Rivet/SimpleAnalysis resolver output)")
        print(f"- GitHub: {n_gh} repos across the id searches" +
              (" — LOOK at them before declaring anything unavailable" if n_gh else
               " (searched; none — record that, it caps the source-ladder)"))
        insp = r5.get("inspire", {})
        print(f"- Forward citations: {insp.get('total_citations', '?')} total; "
              f"{len(insp.get('theses_in_sample', []))} theses + "
              f"{len(insp.get('recast_like_in_sample', []))} recast-like in the recent sample "
              f"(theses carry cutflows)")
        print("- Manual rungs still open: " + " · ".join(m.split(":")[0] for m in MANUAL_RUNGS))

    return 0


if __name__ == "__main__":
    sys.exit(main())
