# Checklist — standardized plot names  ·  [judgment] map · [agent] run

Goal (step 5.2): every plot has a name a scientist can read, while staying traceable to its source.

## Convention (the same for every run)
```
<routine>__<origID>__<label>.<ext>
```
- `<routine>` — the Rivet routine (provenance).
- `<origID>` — the routine's original object id, kept verbatim (so the plot still maps to its HEPData
  table / routine object).
- `<label>` — a slugified physical descriptor: what it shows + the region.

Example: `ATLAS_2016_I1458270__d08-x01-y01__meff-incl_SR-5j.png`.

## No-routine / no-published-data runs (G-CMS-08)
The scheme assumes a routine id + published REF data. A no-routine (Option C) or
sensitivity-only run adapts, never skips: use the run's analysis TAG in place of the routine id,
label expected-only panels as such, and still emit `INDEX.md` — parseable names are what the
verification panel greps.

## Build the label map ([judgment — proceed-with-flag]: derive labels from the routine's booked observables; flag any you had to guess)
`name_plots.py` takes `--labels <rundir>/inputs/plot_labels.json`, a dict keyed by `origID`:
```json
{ "d08-x01-y01": { "label": "meff-incl_SR-5j",
                   "shows": "m_eff(incl) distribution, signal vs ATLAS data (5-jet SR)",
                   "definition": ">=5 jets; aplanarity>0.04; MET/m_eff(5j)>0.25; m_eff>1600 GeV",
                   "source": "REF d08-x01: y01=observed, y02=SM background" } }
```
Read `label`/`definition` from the routine `.cc` (the `book(...)` table ids and SR cuts) and the
paper. `shows`/`definition`/`source` populate the `INDEX.md` legend.

## Run it ([agent])
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/name_plots.py \
  --plots-dir <rundir>/plots/<RIVET_ID> --routine <RIVET_ID> \
  --labels <rundir>/inputs/plot_labels.json \
  --plot-file <…>/envs/rivet/share/Rivet/<RIVET_ID>.plot
```
Writes `<plots-dir>/named/` (renamed copies) + `INDEX.md` (the legend). Without `--labels` it falls
back to the `.plot`/`.py` titles, then the raw id (flagged "unlabeled" in the legend) — a prompt to
add the missing entries.
