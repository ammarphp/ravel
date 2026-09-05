# Checklist — choosing the analysis routine  ·  [judgment]

Goal: an analysis routine matching the target paper that this pipeline can run.

## Routine type (Rivet or SimpleAnalysis)
- **Rivet** — native, fast, ATLAS + CMS, ships reference data, gives plots-vs-data for free. The
  default when the analysis has a Rivet routine. Steps 4A, 5, 6 (bundled REF), 7.
- **SimpleAnalysis** — the SR-yield framework many ATLAS/CMS SUSY searches publish a routine for; its
  yields map onto a published pyhf likelihood for the strongest limit. **Native (VM-free) by default
  for EwkCompressed2018/slepton** (`docs/workflow/steps/04-analyze.md` Option B); else the container fallback
  (podman+mapyde, `docs/workflow/analysis-simpleanalysis/`). Steps 4B, 5 (yield/kinematics plots), 7.
- Some analyses ship **both**; either is valid — prefer the one whose published exclusion input
  (likelihood vs distributions) you can reproduce, and record which you used.

The rest of this checklist finds a **Rivet** routine; for SimpleAnalysis see
`docs/workflow/analysis-simpleanalysis/config-decisions.md`.

1. **Find candidates.** Match the paper to a Rivet ID:
   ```bash
   $CONDA run -n rivet rivet --list-analyses | tr ',' '\n' | grep -iE "<EXPERIMENT>_<YEAR>"
   ```
   Rivet IDs encode experiment + Inspire ID, e.g. `ATLAS_2016_I1458270`. The coverage list is at
   rivet.hepforge.org; if its web page is unreachable, the bundled list above is authoritative.
2. **Check usability:**
   ```bash
   $CONDA run -n rivet rivet --show-analysis <ID> | grep -iE "Status|Beams|energies|luminosity|Keywords"
   ```
   Prefer `Status: VALIDATED`. Note the beam energy — the generation √s must match.
3. **Confirm the exclusion input exists *now*, before committing** (so step 6/7 are not a dead end):
   - a published **likelihood**? — `hepdata_fetch.py --routine <ID> --out /tmp/hd` lists the record's
     resources (file_type `HistFactory`/`pyhf`); if present it downloads (step 6.1). Strongest input.
   - else **aligned bundled data** for the counting path:
     ```bash
     ls <…>/envs/rivet/share/Rivet/<ID>.yoda*           # a /REF/ file exists
     gunzip -c <…>/<ID>.yoda.gz | grep -c "y02"          # >0 ⇒ SM background is bundled (not just data)
     ```
     A `/REF/` with both `y01` (data) and `y02` (background), on matching binning, is what the counting
     route needs — many routines bundle only a cutflow or data-only, which does not suffice.
   - else the SR yields must come from a reinterpretation DB or the browser (`data-acquisition.md`) —
     know this at selection time, not at step 6.
4. **Obtaining a non-bundled routine:** download its `<ID>.cc`/`.info`/`.plot` from the analysis page
   into a directory and point Rivet at it with `RIVET_ANALYSIS_PATH` after `rivet-build`.
5. **Certify the routine once** before trusting its limits — see `validation.md` (acceptance vs the
   published cutflow). Record the certification; new model points then inherit it.

Pick one whose required final state your model can populate (jets+MET, dileptons, etc.).
