# Step 2 — Inputs  ·  [judgment]  ·  CHECK-IN
`CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda` — every `$CONDA` below.

Decide the analysis routine and the model. Requires physics judgement.

0. **RESOURCE SWEEP (mandatory, before anything is declared unavailable).** The `resource-sweep`
   skill / `resource_census.py` walks HEPData (tables + the RESOURCES tab, where full likelihoods
   and efficiency maps live), the routine resolvers, arXiv source, GitHub (repos AND code search —
   recast repos rarely carry the analysis id in their name), and INSPIRE forward-citations
   (theses carry cutflows):
   ```bash
   $CONDA run -n rivet python trial-runs/_infrastructure/resource_census.py \
       --inspire <recid> --arxiv <id> --analysis-id <code> --rundir <rundir> --markdown
   ```
   → `<rundir>/inputs/resource_census.json` + the CHECK-IN 1 census block. LOOK at every GitHub
   hit and likelihood/efficiency-map candidate before routing; run the trap-sweep
   (`checklists/physics-traps.md`) alongside it. Read the HEPData rung's STATUS, not just its
   contents: `ABSENT` = definitively no record (open-API 404, INSPIRE-corroborated — plan around
   absence); `ERROR outage-or-block` = unreachable, NOT evidence of absence (retry/browser).

1. **Routine.** Resolve the analysis to a routine across **both** ecosystems at once — Rivet (Option A)
   and SimpleAnalysis (Option B) — from a paper code, Inspire id, or keyword:
   ```bash
   python trial-runs/_infrastructure/routine_fetch.py --query "<ATLAS-SUSY-20XX-XX | insNNNN | keyword>"
   ```
   It prints the matching Rivet routine id (→ step 4A) and/or the SimpleAnalysis `DefineAnalysis` name
   (→ step 4B, the mapyde `[simpleanalysis] name`). **It matches the analysis CODE / literal ids**
   (e.g. `SUSY-2018-16`, an Inspire or arXiv id) against the routine files — **not physics
   vocabulary** — so a keyword query ("compressed sleptons") can return 0 hits for an analysis that
   IS covered: extract the code from the paper or HEPData first, then re-query with it. To get the
   **Inspire id** (`insNNNN`, needed below) from an analysis code: search hepdata.net for the code,
   read it off the matched Rivet routine id (`..._I<NNNN>` → `ins<NNNN>`), or skip it —
   `hepdata_fetch.py --routine <RIVET_ID>` resolves the Inspire id from the routine name itself.
   Then confirm a Rivet routine's data:
   ```bash
   $CONDA run -n rivet rivet --show-analysis <RIVET_ID> | grep -iE "Beams|luminosity|Status|Keywords"
   ```
   See `checklists/choosing-routine.md`; for SimpleAnalysis, `../analysis-simpleanalysis/`.
2. **Model + cards.** Define the process and parameter cards for the model under test (see
   `checklists/model-cards.md`). Either use cards supplied by the requester, or write them — the
   final state the model produces must be one the chosen routine selects on.
3. **Figure target ([judgment]).** Declare WHICH published figure this run reproduces — the figure
   contract (`checklists/figure-contract.md`). If the requester named it ("reproduce Fig N of
   arXiv:…"), declare directly; else resolve candidates from the HEPData figure index and choose:
   ```bash
   $CONDA run -n rivet python trial-runs/_infrastructure/hepdata_fetch.py \
     --inspire insNNNN --out <rundir>/outputs/hepdata          # manifest carries figure_index
   $CONDA run -n rivet python trial-runs/_infrastructure/figure_target.py resolve \
     --analysis <ID> --hepdata-manifest <rundir>/outputs/hepdata/hepdata_manifest.json \
     --role summary --model-keywords "<model words>"           # prints ranked candidates; CHOOSE
   # FETCH the published figure BEFORE declaring — declare's --caption must carry the PAPER
   # caption's first sentence, which fetch_figures extracts (figure_map.json); at minimum run
   # --map-captions to get the caption text even when no image can be pulled:
   $CONDA run -n rivet python trial-runs/_infrastructure/fetch_figures.py \
     --inspire insNNNN --figure <N> --out <rundir>/outputs/published    # or: --map-captions
   $CONDA run -n rivet python trial-runs/_infrastructure/figure_target.py declare \
     --rundir <rundir> --role summary --primary --figure-id "Figure <N>" \
     --source <user-prompt|registry-hint|hepdata-table-name|paper-inspection|description-only> \
     --caption "<first sentence of the published PAPER caption>" --inspire insNNNN [--arxiv XXXX.XXXXX] \
     --axes-x <linear|log> --axes-y <linear|log>   # the PUBLISHED axis scales, read off the extracted figure
   ```
   **Record the published axes at declaration** — the axis scales are facts read off the extracted
   figure, not defaults (`checklists/plot-guidelines.md`); the step-5/8 renderers consume them via
   `--figure-target`.
   `resolve` never auto-picks — read the table descriptions and decide. If no paper caption could be
   extracted, fall back to the HEPData table description for `--caption` and note that provenance in
   `--source`. Then `figure_target.py attach-image` (the image fetch_figures extracted — or its
   precise textual reference, a valid degraded state) + `show` (prints the check-in block).
4. Place cards in the run's `inputs/`; record the routine ID and the model in `RESULT.md`.

**arXiv-only requests (G-CMS-11):** an arXiv id resolves to the Inspire id via the arXiv
page's INSPIRE link, `hepdata.net` search, or the Rivet routine name's `_I<NNNN>` suffix —
never stall on "no Inspire id given". The intake layer (`route_prompt.py` →
`inputs/task_contract.json`, validated by `validate_task_contract.py`) already extracted the
ids it could; CHECK-IN 1 presents that contract's flags.

**CHECK-IN 1 "PLAN"** — compose it per `checklists/check-ins.md`, and send it **before ANY heavy
compute**: (i) the plain-language preamble; (ii) the published-figure GALLERY —
`fetch_figures.py --map-captions` extracts every figure + caption into `figure_map.json`; display
several distinct candidates, each with a one-line caption; (iii) the figure target(s) (echoed via
`figure_target.py show`) + the proposed EARLY-VERIFICATION WAYPOINT ([judgment]: a partial
published-figure element reproducible cheaply, to be shown side-by-side at CHECK-IN 2); (iv) the
plan (samples, observables, stats, budget); (v) the NUMBERED FLAGS — every assumption/decision with
its why + alternatives; (vi) the three-response-mode footer (answer the flags / ask clarifying
questions / propose alterations). Generation waits for the response.

**Next:** `steps/03-generate.md`
