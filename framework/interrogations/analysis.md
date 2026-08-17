# Interrogation — analysis (Session 2, 2026-06-09)

_Stage S4: the analysis/selection stage — `validate_cutflow.py` (cert engine A), the run-local
`certify_axe.py`/`extract_sr.py` adapter (engine B, untouched), `rivet_ref_yields.py` (SR data path),
and the new cross-stage pre-shower guard `lhe_check.py`. Defects → fixes → **measured** against
direct helper re-runs + the single final `run_benchmark.py --full` gate (exactly one run, at stage
close — see the gate line at the bottom)._

## Defects found

| ID | Sev | Where | Finding | Status |
|---|---|---|---|---|
| AN-D1 | crit | `rivet_ref_yields.py` | **Cutflow-only silent failure**: a routine with no scalar SR counters (e.g. ATLAS_2018_I1676551, only `BinnedEstimate1D` cutflows) silently emitted `s=NaN` per SR into the yields JSON (exit 0) — downstream pyhf consumes garbage | **FIXED**: hard error, names the missing counters, distinguishes cutflow-only (pointer to `workflow/reference/example-rivet-ewk-path.md`) from a spec typo (lists the available scalar keys) |
| AN-D2/D6 | crit | `validate_cutflow.py` `published_axe()` | **Nearest-node grid lookup is silent and can be wrong.** Verified instance beyond the known ins1676551 case: the ins1458270 **gluino** acc×eff grid has **NO (1000,100) node** (at m_gluino=1000 only m_LSP ∈ {0,600,800}; m_LSP=100 exists only at m_gluino ≥ 1100). The certified gluino 13.2% residual is measured against the **(1000,0)** node (splitting 1000 vs our 900) — and (1000,0) vs (1100,100) is an exact distance-100 **tie** resolved only by file order. The benchmark registry's "exact node 1000,100" source note is wrong. Nothing recorded which node was used (the `node` field was dropped from the output JSON) | **FIXED** (lookup + provenance): exact node → bit-identical legacy value; else 1-D bracket interpolation (fixed-LSP/splitting axis preferred, mirroring engine B), span-guarded by `--interp-max-span` (default 200 GeV ≈ one grid cell — linear interp across the gluino grid's 600 GeV gap would be unphysical: A×ε changes ~5× across it); else nearest, now **flagged `NEAREST` + caution** in the per-SR `node` field, which is now in the md table, the JSON rows, and the console. Registry-notes correction + 2-D interpolation = open items (KNOWN-LIMITATIONS) |
| AN-D4 | major | `sr_spec.json` lifecycle | **Spec drift risk**: the spec (thresholds/counters) is a frozen copy of the routine's cuts; a routine/Rivet version bump silently invalidates it | **adopt-lite**: `workflow/checklists/data-acquisition.md` now states the re-derivation rule and that the xcheck is the drift guard (full fix = parse the `.cc` at run time; deferred) |
| AN-D5 | major | `rivet_ref_yields.py` | **xcheck printed but not enforced**: the signal-counter vs m_eff-integral cross-check (exactly the drift/mismatch detector for AN-D4) only printed a "should match" note | **FIXED**: `--xcheck-tol` (default 0.10) enforced when both finite and s>0; offending SRs printed; exit nonzero; **no output written** |
| AN-D7/D9 | major | pre-shower / single-weight guards | No automated LHE-side check existed: wrong generated mass (MASS-vs-MSOFT trap), multiweight `<rwgt>`/`<wgt>` LHEs entering single-weight pipelines, mixed weight signs, merged LHE showered with the unmatched bridge — all silent | **FIXED**: new `trial-runs/_infrastructure/lhe_check.py` (stdlib-only, .lhe/.lhe.gz): `--expect-mass PDG:MASS` (first event + banner MASS block, `--mass-tol` 1 GeV), MODSEL check (`--require-modsel`), weight-sign over first N=200 events + init σ, multiweight tag detection (matches `<rwgt`/`<wgt`/`<initrwgt`, not MadGraph's `<mgrwt>`), ickkw merged-detection → which shower bridge. Wired into `workflow/steps/03-generate.md` (pre-shower guard) + `04-analyze.md` (single-weight section) |
| AN-D8 | major | counting model | Signal-MC statistical uncertainty absent from the pyhf model (s enters exact) | **DEFERRED** → KNOWN-LIMITATIONS with the tail-SR rationale: the affected regime (<~5 signal events) is report-only in the cert tiers and O(1%) of combined sensitivity; Phase-2 model upgrade (s±ds from sumW2) |
| AN-D10 | minor | `rivet_ref_yields.py` `integ_above()` | `errAvg()` symmetrises asymmetric published error bars; quadrature sum assumes uncorrelated bins | **documented** (helper docstring + data-acquisition checklist); superseded wherever `--fitted-bkg` provides the analysis's own b±δb (the preferred input since S2/1b) |
| AN-D11 | minor | both helpers | Zero/negative-denominator modes unguarded: σ≤0 or L≤0 → nonsense A×ε (validate_cutflow); REF background integral ≤0 (threshold beyond REF range / wrong ref_table) → b=0±0 counting input (rivet_ref_yields) | **FIXED**: explicit nonzero-exit guards with messages. (Engine B's cutflow first-bin division already returns NaN on an empty first bin — run-local certified artifact, left untouched.) |

## The MODSEL banner finding (assigned open question — resolved)

**Question:** the gluino/squark runs decayed fine, yet `.claude/rules/madgraph-pythia.md` says a
missing `MODSEL` "silently disables SLHA decays". Do their banners carry MODSEL? Does MadGraph
inject it?

**Facts established (files + a direct 50-event shower experiment on this pipeline's Pythia 8.312):**
1. The gluino, squark-pair, and squark-merged LHE banners contain **NO `Block MODSEL`** — and their
   input param cards don't either. Only the C1N2 run's banner has it (from the `_fixed` card).
   **MadGraph does NOT write MODSEL into the banner param card** — the hypothesis is **false**; the
   banner carries exactly what the input card had.
2. Showering the no-MODSEL gluino LHE (Pythia 8.312, `SLHA:useDecayTable=on`) logs
   `No MODSEL found, keeping internal SUSY switched off` **and then**
   `importing DECAY tables for id = {…,1000021,…}` — the gluinos **decay correctly** (verified in
   the output HepMC). Source-confirmed (SLHAinterface.cc): MASS import runs for ifailSpc∈{0,1} and
   **DECAY import is unconditional on MODSEL** — it only needs the table to have BR rows and
   `SLHA:useDecayTable=on`.
3. The same log shows the actual kill mechanism:
   `ignoring empty DECAY tables for id = {…} (total width provided but no Branching Ratios)` —
   **width-only** DECAY entries (what MadGraph's default restrict card has) import nothing, and with
   internal SUSY off (no MODSEL) Pythia cannot compute the channels itself → undecayed sparticles →
   empty SRs. That matches the C1N2 STUMBLES S1 failure: its first LHE came from the
   `set param_card`-ignored run (S2) using the **default** card (width-only entries + no MODSEL).
   The original C1N2 card actually HAS BR rows for C1/N2, so its no-decay attribution to MODSEL
   alone was imprecise.

**Reconciliation for the rules doc (correction for the orchestrator to adopt — `.claude/rules/` is
outside this stage's file set):** "missing MODSEL disables SLHA decays" should read: *missing MODSEL
keeps Pythia's internal SUSY off; explicit DECAY tables **with BR rows** still apply via
`SLHA:useDecayTable=on`, but **width-only** DECAY entries then decay nothing (empty SRs). Include
MODSEL always — it is required the moment any particle relies on Pythia for its decays — and verify
with `lhe_check.py`.* The simplified-model cards used here are safe without it only because every
produced sparticle has explicit BR rows; `lhe_check.py` WARNs on missing MODSEL (FAIL with
`--require-modsel`).

## Fixes applied — measured

| Fix | Regression evidence (before vs after) |
|---|---|
| `validate_cutflow.py` grid lookup + node provenance + `--driving-sr-override` + σ/L guards | All three I1458270 certs re-run with identical args: output JSON **identical except the added `node` field** (verdicts WARN@13% / PASS@2% / PASS@4%, every ratio/role/attribution unchanged); exact-node squark cases report `grid node (m_parent=800, m_lsp=100)`; gluino rows now carry the `NEAREST (1000,0)` caution flag. Interp paths exercised: (1200,100) → `interp@m_lsp=100: m_parent 1100->1300`; (1100,200) → `interp@m_parent=1100: m_lsp 100->300`; node tolerance: (800.5,100) → exact node. Guards: σ=0 and L<0 exit 1 with messages. Exit-0 semantics for PASS/WARN/FAIL preserved (gate parses the JSON verdict) |
| `rivet_ref_yields.py` D1/D5/D11 guards | **Byte-identical regression**: re-ran the S1 commands for BOTH squark runs (`--signal <yoda> --ref <rivet share REF> --spec inputs/sr_spec.json --fitted-bkg inputs/fitted_bkg.json`) — outputs diff-identical to the committed `outputs/sr_yields_fitted.json` in each run (worst live xcheck deviation: merged 2jt 4.9%, well inside the 10% tol). Failure modes verified: C1N2 yoda → cutflow-only error + pointer; counter typo → available-keys error; `--xcheck-tol 0.001` → per-SR XCHECK FAIL lines, exit 1, **no output file written** |
| `lhe_check.py` (new) | All four certified LHEs: gluino PASS (m=1000/100; MODSEL WARN; single-weight; unmerged), squark-pair PASS (m=800/100; MODSEL WARN), squark-merged PASS (**ickkw=1 → MERGED, xqcut=80 detected**; init σ flagged as pre-matching), C1N2 PASS (m=300/300/100, N1 asserted from the banner MASS block since it never appears in events; **MODSEL present**). Failure modes: wrong mass → FAIL rc=1; unknown PDG → FAIL; `--require-modsel` on gluino → FAIL rc=1; malformed `--expect-mass` → usage error |
| Docs | `steps/03-generate.md` pre-shower guard block; `steps/04-analyze.md` single-weight guard + cutflow-only hard-error note; `checklists/complex-analysis.md` grid-lookup paragraph rewritten (the interpolating certifier is now IN `validate_cutflow.py`; the cutflow READER remains the run-local adapter) + scalar-counter qualifier in the table; `checklists/data-acquisition.md` xcheck-enforcement + spec-drift + errAvg notes. Hygiene grep (`gluino-pair|squark-pair|slepton_200|2026-06` over `workflow/ README.md`) **clean** (DISTRIBUTION.md only) |

## Deferred (with why)

- **`--sr-mode cutflow` fold-in** (engine B → engine A): needs a test bed that doesn't regress the
  scalar path mid-session; engine B stays the certified-run adapter, schema-compatible. (Pre-existing
  TODO, unchanged.)
- **2-D grid interpolation + registry-notes correction** for the gluino "(exact node 1000,100)"
  source line in `framework/benchmark/cases.json`: the registry is S1's file and a notes edit
  invites a re-lock discussion; recorded in KNOWN-LIMITATIONS instead. The measured 13.2% residual
  itself is unchanged (it was always vs (1000,0); now it says so).
- **AN-D8 signal-MC-stat** → KNOWN-LIMITATIONS (tail-SR rationale above; Phase-2 model upgrade).
- **AN-D4 full fix** (derive `sr_spec.json` from the routine `.cc` automatically) — adopt-lite
  checklist line shipped; the enforced xcheck now catches drift at run time.
- **`.claude/rules/madgraph-pythia.md` MODSEL wording** — corrected statement above; the file is
  outside this stage's scope.

## Gate (the single `--full` run at stage close)

`python3 framework/benchmark/run_benchmark.py --full` → **exit 0, 4/4 OK** (run exactly once, at
stage close); `results.json` **identical to the committed baseline apart from `generated`/`timing`**
(verified by a field-stripped JSON comparison): squark A×ε 2.4% Ideal / s95 1.01/1.03 / µ₉₅ 0.22254;
merged 3.9% Ideal / 1.01/1.03 / 0.22580; gluino 13.2% Acceptable / 1.00/1.02 / 0.05237 (cert WARN,
attributed merging — unchanged); C1N2 6.4% Good / 2.7123. The stage's changes are regression-free by
construction: exact-node lookups are bit-identical, and the benchmark invokes neither
`rivet_ref_yields.py` nor `lhe_check.py`.
