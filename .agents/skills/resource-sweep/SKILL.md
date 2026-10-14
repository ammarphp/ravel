---
name: resource-sweep
description: Run the RESOURCE SWEEP for one or more target analyses, or for a topic with no reference paper — resource_census.py walks HEPData (tables + the resources tab where likelihoods/efficiency maps live), Rivet/SimpleAnalysis routines, arXiv source, GitHub (repos AND code search), and INSPIRE forward-citations/Zenodo, emitting inputs/resource_census.json (an index over one record per analysis or keyword search) + the CHECK-IN 1 "what exists online" block. Fire at step 2 for EVERY new analysis, and again whenever information seems missing — BEFORE declaring anything unavailable.
when_to_use: step 2 of any run (mandatory, before CHECK-IN 1); any "the paper doesn't provide X" moment; before the no-routine (Option C) or blocked verdicts; source-ladder protocol P6
allowed-tools: Bash, Read
---
# Skill — resource sweep (source-ladder rungs 1–5, automated)

The failure this prevents: an analysis's public code or data sits unexamined online while the run
improvises around "unavailable". Public routines, likelihoods and efficiency maps are often held in
a record's resources tab, auxiliary material or a code repository rather than the paper; a single
look at one source does not establish absence.

## Run it (project Python; TLS is verified with certifi, never bypassed)
```bash
python scripts/run.py ravel.workflow.resource_census \
    --inspire <recid> --arxiv <id> --analysis-id <ATLAS-XXX-20YY-NN> \
    --rundir <rundir> --markdown
```
- Several analyses: repeat `--analysis inspire=<recid>[,arxiv=<id>][,id=<code>]`.
- A survey, summary or study with no reference paper: `--keyword "<topic words>"` searches
  HEPData and INSPIRE, records the candidates, and censuses the top `--limit` (default 5);
  `--search-only` records the search alone.
- Writes one record per analysis (`inputs/resource_census/ins<id>.json`) and per search
  (`inputs/resource_census/search-<slug>.json`), plus the index `inputs/resource_census.json`
  that the lifecycle gate reads. Later runs add to the index. `--markdown` prints the CHECK-IN 1
  block.
- R1 looks the record up as `ins<id>`, then under any HEPData record id INSPIRE lists for the
  paper. R2 reports a local Rivet/SimpleAnalysis tree that is not on disk as "not checked" and
  always lists the packaged catalogue matches.
- Exit 3 = EVERY rung failed → that is a network/environment finding; do NOT proceed as if the
  sweep ran, and do NOT read it as "nothing exists".
- **R1 absence vs outage (READ the status — a drop-vs-wait decision hinges on it):**
  `ABSENT` = the open record-JSON API served a **404** and INSPIRE lists no HEPDATA external id —
  **definitively no HEPData record exists**; plan around absence (counts as a walked rung, not a
  failure). `ERROR` + `classification: outage-or-block` (403/5xx/network) = the service is
  unreachable — **NOT evidence of absence**; retry or use the browser. `ERROR` +
  `classification: inconsistent` (API 404 but INSPIRE DOES list a HEPDATA id) = re-check manually
  before concluding anything. (The conflation this kills: a "Cloudflare-blocked/503" diagnosis
  once masked a genuine no-record for a CMS target.)

## Then actually LOOK (the sweep finds; you read)
1. **Likelihood/efficiency-map candidates** (R1): fetch via `hepdata_fetch.py` — a full
   likelihood upgrades `stat_mode`; efficiency maps unlock the folding route for LLP objects.
2. **GitHub hits** (R4, repos + code): open each unique repo; classify {analysis-owned, recast
   tool, unrelated}. A recast repo often carries cards, cutflows, and validation material.
3. **Theses + recast-like citations** (R5): theses carry the cutflows the paper cut.
4. Record what each rung CHANGED (route, stat_mode, fidelity caps) as numbered CHECK-IN flags;
   an empty rung is recorded too — it CAPS the source-ladder and justifies escalation.

## When a STAGE FAILS: `--debug recipe-search` (D8 — search externally CO-PRIMARY, not last)
A diagnosed generator/detector-model failure (undecayed sparticles → empty SR, a Delphes card that
won't build, a Pythia merge that vetoes every event) is a search target, not just a debugging session.
Fire the tool+model+symptom-keyed external search the moment a stage fails — the fix (a card, a run
config, a recast repo, a thesis appendix) is often already published:
```bash
python3 scripts/run.py ravel.workflow.resource_census --debug recipe-search \
    --tool <madgraph|pythia|delphes> --model <SVJ|wino-c1n2|slepton> \
    --symptom "<free-text error keywords>" --rundir <rundir>
```
- Writes `<rundir>/inputs/recipe_search.json` (`generated_by`, `input_fingerprint`, `mode=recipe-search`,
  the per-source `searches`, `searches_ok`, `n_hits`, `co_primary=true`); omit `--rundir` to print to stdout.
- Exit 2 = bad `--debug` value (only `recipe-search`); exit 3 = EVERY search failed → a
  network/environment finding, NOT evidence that no recipe exists (do not close the failure as if the
  search ran).
- Offline self-check: `python3 scripts/run.py ravel.workflow.resource_census --selftest` (record assembly,
  fingerprint stability, bad-mode exit-2).

## Stop conditions
- Sweep exit 3 (all rungs down) → environment flag; retry, check network and certifi, escalate
  if persistent.
- A rung contradicts the paper (paper says "material on HEPData", R1 shows none) → that mismatch
  is itself a CHECK-IN flag; check the record VERSION and the manual rungs before concluding.
- R1 `ERROR outage-or-block` → never report "no HEPData record" from it; only `ABSENT` says that.
