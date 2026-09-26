# Checklist — choosing the analysis routine  ·  [judgment]

Goal: an analysis routine matching the target paper that this pipeline can run.

## Discover first, then assess admission

Use the installed offline census before assuming that a missing native adapter means
no public routine exists:

```sh
ravel analyses list --query "<paper identifier or topic>"
ravel analyses show <framework:routine>
ravel analyses check-source <framework:routine> --source <upstream-checkout>
```

The [landscape guide](../../research/2026-09-26-analysis-landscape.md) gives snapshot
coverage and the adaptation plan. A paper can map to multiple routine variants;
select explicitly. Source-byte verification does not establish compilation,
detector fidelity, a usable likelihood, or compute approval. Compare the snapshot
with the actual installed routine/runtime before proposing execution.

## Routine type (Rivet or SimpleAnalysis)

- **Rivet** preserves particle-level measurements and selected searches across several
  experiments. Use the public routine when its objects and output match the task.
  Reference data, covariance and likelihood availability require separate checks.
- **SimpleAnalysis** is the public ATLAS framework for truth/reconstructed-object
  selections and region yields. Ravel's registered native adapters have explicit
  routine/model/statistics restrictions. For other routines, assess an external
  native interface and dependencies; do not promise container or declarative-engine
  compatibility without checking it.
- Some papers have multiple routines or frameworks. Choose by the required observable,
  input event level, validated response and published inference input. Record the
  selection and its limitations in CHECK-IN 1.

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
