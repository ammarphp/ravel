---
name: resource-sweep
description: Run the RESOURCE SWEEP for a target analysis in hep-agentic-pipeline — resource_census.py walks HEPData (tables + the resources tab where likelihoods/efficiency maps live), Rivet/SimpleAnalysis routines, arXiv source, GitHub (repos AND code search), and INSPIRE forward-citations/Zenodo, emitting inputs/resource_census.json + the CHECK-IN 1 "what exists online" block. Fire at step 2 for EVERY new analysis, and again whenever information seems missing — BEFORE declaring anything unavailable.
when_to_use: step 2 of any run (mandatory, before CHECK-IN 1); any "the paper doesn't provide X" moment; before the no-routine (Option C) or blocked verdicts; source-ladder protocol P6
allowed-tools: Bash, Read
---
# Skill — resource sweep (source-ladder rungs 1–5, automated)

The failure this kills: the analysis's public code/data sitting unexamined online while the run
improvises around "unavailable" (the missed-RRR-repo incident — the sweep's code search finds
`scipp-atlas/mapyde-tutorial` from `ins1767649` unprompted; the "impossible" HEPData download
that fell to a second look).

## Run it (conda env for TLS certs — system python has no CA bundle; NEVER bypass verification)
```bash
<conda> run -n rivet python trial-runs/_infrastructure/resource_census.py \
    --inspire <recid> --arxiv <id> --analysis-id <ATLAS-XXX-20YY-NN> \
    --rundir <rundir> --markdown
```
- Writes `<rundir>/inputs/resource_census.json`; `--markdown` prints the CHECK-IN 1 block.
- Exit 3 = EVERY rung failed → that is a network/environment finding; do NOT proceed as if the
  sweep ran, and do NOT read it as "nothing exists".

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
python3 trial-runs/_infrastructure/resource_census.py --debug recipe-search \
    --tool <madgraph|pythia|delphes> --model <SVJ|wino-c1n2|slepton> \
    --symptom "<free-text error keywords>" --rundir <rundir>
```
- Writes `<rundir>/inputs/recipe_search.json` (`generated_by`, `input_fingerprint`, `mode=recipe-search`,
  the per-source `searches`, `searches_ok`, `n_hits`, `co_primary=true`); omit `--rundir` to print to stdout.
- Exit 2 = bad `--debug` value (only `recipe-search`); exit 3 = EVERY search failed → a
  network/environment finding, NOT evidence that no recipe exists (do not close the failure as if the
  search ran).
- Offline self-check: `python3 trial-runs/_infrastructure/resource_census.py --selftest` (record assembly,
  fingerprint stability, bad-mode exit-2).

## Manual rungs the script cannot walk (do these when the paper claims something the sweep lacks)
- Collaboration public pages / TWiki (JS-walled): browser territory — Chrome MCP.
- MA5-PAD / CheckMATE listings; SModelS locally via `reinterpret_db.py`.

## Stop conditions
- Sweep exit 3 (all rungs down) → environment flag, retry under the conda env, escalate if
  persistent.
- A rung contradicts the paper (paper says "material on HEPData", R1 shows none) → that mismatch
  is itself a CHECK-IN flag; check the record VERSION and the manual rungs before concluding.
