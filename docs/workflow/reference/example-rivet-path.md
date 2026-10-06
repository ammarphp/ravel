# Walkthrough — the Rivet path (a colored-production search)

A filled-in shape of `docs/workflow/README.md` for a jets+E_T^miss search with a Rivet routine. Replace the
bracketed values with your analysis + model.

| Step | What you do |
|---|---|
| 2 routine | `routine_fetch.py --query "[ATLAS/CMS code or Inspire id]"` → the Rivet routine id; confirm `Beams`/`Status` |
| 2 model | a colored simplified model (e.g. gaugino/squark pair, parent→jets+LSP); cards per `docs/workflow/checklists/model-cards.md` |
| 3 generate | `p p > [parents]` at the routine's √s; **merge** the extra-jet multiplicities if the SRs need ≥4 jets (`docs/workflow/checklists/merging.md`) → LHE → Pythia8 → HepMC3 |
| 4 analyze | `rivet -a [RIVET_ID] …` → YODA (the routine's SR counters + m_eff distributions) |
| 5 visualize | `rivet-mkhtml` + `name_plots.py`; `overlay_on_data.py` for the publication-grade signal-over-data figure |
| 6 data | `rivet_ref_yields.py` from the bundled REF (and `hepdata_fetch.py --tables` for the full tables); `nlo_xsec.py` for the k-factor |
| 7 exclude | `pyhf_exclude.py counting --sigma-scale [k]` → µ₉₅; the most-sensitive SR drives it |
| cert | `validate_cutflow.py --exclusion …` vs the published acc×eff grid (tiered + attribution); `reinterpret_db.py` cross-check |

The signal+background overlay rising above the data in the sensitive SR is the visible exclusion;
`pyhf` turns it into the limit. High-jet-multiplicity SRs are only correct with merging.
