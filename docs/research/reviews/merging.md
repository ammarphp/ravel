# Interrogation — merging (Session 2, 2026-06-09/10)

_Defects → fixes → **measured** before/after. Stage close: `--full` exit 0, **5/5 green** (the
gluino-merged case registered at Good/Ideal)._

## The measured centerpiece — merged gluino-pair (new run `2026-06-10_..._gluino-merged`)

1. **Merging-scale choice is now measured, not folklore** (fixes MERGE-D5/D10 + the
   m/4-vs-m/10 checklist inconsistency): matched-σ stability scan (1k events/point, one compile):
   matched/LO = 0.939 / 0.958 / 0.981 at xqcut = 100 / 150 / 250 → plateau 4.4%, production
   **xqcut=250 (=m/4)**, 10k events, matched σ 0.19856 pb (**−1.2% vs LO**, inside the ≤5%
   tolerance now written into `merging.md` and pinned in the run's provenance).
2. **The high-multiplicity story corrected** (with S5): the unmerged gluino driving-5j residual is a
   **+13.2% excess** (cert WARN), not a deficit. Merging *reduces* it — ME weights replace the
   Monash shower's overestimate of hard wide-angle emission off the colour-octet pair:
   5j 1.132→**1.081** (PASS @8.1%, Good), 6jm 1.254→1.129, 6jt 1.096→1.045. The original
   "attributed: merging (deficit)" cause-class in the certified gluino record was **wrong** — both
   gluino cases' registry notes now carry the corrected attribution. (Contrast: the squark
   high-mult residuals WERE deficits and merging closed them upward — both behaviors are now
   measured in this portfolio, which is exactly what a trust warranty should contain.)
3. **qCut sensitivity** (fixes MERGE-D2): qCut=1.25×xqcut (the house factor; MG default 1.5×)
   vs 1.5× variant: matched σ +0.7%, but cert PASS@8.1% → WARN@12% — the 1.25× choice is mildly
   better and is now documented with this measurement (`outputs/variants/`).
4. **Tune × merging overlap** (with S5): A14-merged cert PASS@7.4% (vs Monash-merged 8.1%, A14
   unmerged 4.4%) — the effects tame overlapping physics and do not stack linearly. Pipeline tune
   policy deferred to Session 3 with all four measured combinations on record.
5. **Limit invariance**: s95 recovery 1.000/1.029 (Ideal) — the statistical machinery is unaffected
   by merging, as designed; µ₉₅(obs)=0.0550 with k=1.939 on the matched σ.

## Other defects → state

| ID | Finding | State |
|---|---|---|
| MERGE-D1 | "empty Events/" critical | FALSE ALARM (agent raced the live job); the real ask — post-gen LHE validation — is in the drivers (`test -s`) + `lhe_check.py` (S4) |
| MERGE-D4 | DJR plots missing | **DEFERRED** (Session 3; KNOWN-LIMITATIONS): stand-in evidence = the stability scan + qCut variant + matched-σ tolerance, all measured |
| MERGE-D5 | no matched-σ tolerance | FIXED: |matched/LO−1| ≤ 5% normative (`merging.md`), provenance-pinned per run |
| MERGE-D6/D13 | nQmatch / ptj-auto_ptj_mjj undocumented | FIXED in `merging.md` + S6's measured ptj finding (applied cut = xqcut, card line misleading) |
| MERGE-D7 | merged LHE into plain shower undetected | FIXED via `lhe_check.py` ickkw detection (S4) |
| MERGE-D9 | roles wrong for runs without exclusion.json | FIXED: `--driving-sr-override` (S4) + the gate always passes a fresh `--exclusion` |
| MERGE-D10 | σ-source ambiguity for merged runs | FIXED: provenance records pre-veto AND matched σ + which one normalizes (S3 schema) |
| MERGE-D12 | merged runs lacked figures | FIXED: squark-merged (S2) + gluino-merged 5j overlay shipped and provenance-gated |

## Carry-over (user-approved)
**Squark +3j** (`trial-runs/_scratch-squark-3j/overnight_gen.sh`, ready, NOT launched — user opted to
let the next session decide the compute): targets the residual squark-merged 5j deficit (26%,
non-driving); xqcut=80 held fixed to isolate the +3j ME effect vs the certified +2j sample; est
16–27 h compile-dominated, ~25 GB; next session: run the script, then `pythia_shower_merged`
(nJetMax=3, qCut=100) → Rivet → score against the squark-merged case.
