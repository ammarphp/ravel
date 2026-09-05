# RESULT — native-backend validation point: slepton (200,150) end-to-end, VM-free

Deliverable: validation — native-vs-container parity (no new physics claim).

**Status: COMPLETE (backfilled record).** This is the run that established the native backend
as trustworthy — the evidence behind "bit-for-bit" in `workflow/reference/native-pipeline.md`
and the PLAN-OF-RECORD's no-VM constraint. Generated 2026-06-16 fully natively (MadGraph →
`pythia_shower` → DelphesHepMC3 → `delphes2sa_native.py` → `native_simpleanalysis.py` +
`rjr_resolve` → `sa2json_native.py` → `pyhf_exclude.py`), 50k events, slepton-bino (200,150).

## Key numbers (artifacts in this dir)
- **Per-SR yields:** `output/EwkCompressed2018.txt` — the native SA reproduced the container's
  per-SR yields **bit-for-bit (141/141 SRs)** on the same Delphes input class.
- **Limit parity:** observed µ₉₅ = **6.333** (native, `output/exclusion.json`) vs **6.366**
  (container reference) — **0.51%** on a fully independent native generation.
- **Stage evidence:** the complete 7-stage log chain in `logs/` (madgraph/pythia/delphes/
  analysis[Delphes2SA]/simpleanalysis/sa2json/pyhf) + `logs_driver.out` + `logs/STATUS.txt`.
- **Config:** `config/sleptons_50k.toml` (tracked since the run).

## Caveats
- Generated PRE-CR-002: the run card lacked `[madgraph.run.options]` (ptj1min=0, not 50) —
  IDENTICAL on both sides of the comparison, so the parity statement stands; absolute σ_tag
  is on the pre-fix basis (FAILURE-CATALOGUE B2; rescan = CR-004).
- `output/exclusion.json` predates the CR-001 µ-floor fix; this point is not hyper-excluded
  (µ₉₅ ≈ 6.3), so the floor pathology does not apply.
- **Record hygiene:** RESULT.md backfilled 2026-07-06 (audit A4-07 — the run that certified
  the native backend had no record and its evidence chain was gitignored; both fixed).
