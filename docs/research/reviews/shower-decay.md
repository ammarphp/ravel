# Interrogation — shower/decay (Session 2, 2026-06-09)

_Stage S5: Pythia 8.312 showering + SLHA decays — the `pythia_shower`/`pythia_shower_merged` bridges
(`trial-runs/_infrastructure/`), the per-run `config/shower*.cfg` files, and the decay-physics claims
the pipeline rests on. Centerpiece: a **measured tune A/B study** (Monash 2013 default vs ATLAS A14)
on the certified gluino case. Evidence only — certified runs and the benchmark gate stay Monash; the
pipeline-wide tune policy is a Session-3 decision. Single `run_benchmark.py --full` at stage close._

## Defects found

| ID | Sev | Where | Finding | Status |
|---|---|---|---|---|
| SD-D1 | **crit (fidelity)** | all certified shower cfgs | **Tune never validated**: every certified run showers with Pythia 8.312's default **Monash 2013** (`Tune:pp=14` when absent), but the published acc×eff grids we certify against were produced with **A14+NNPDF2.3LO** (`Tune:pp=21` in this Pythia, verified in `xmldoc/Tunes.xml`). Measured on the gluino case: the tune alone moves the driving-SR residual **13.2% → 4.4%** and the cert verdict WARN → PASS (table below) — most of the high-multiplicity residual is tune, not "merging" as previously attributed | **MEASURED** (study below); adoption deferred to Session-3 policy (re-locks + merging interplay). KNOWN-LIMITATIONS entry added |
| SD-D2 | major | `trial-runs/2026-06-08_*/config/shower*.cfg` | **Config drift** across the four certified runs: absolute vs relative `Beams:LHEF` paths (two of each — relative paths silently depend on the shower cwd; absolute paths are machine-specific), `Check:epTolErr=1e-2` loosened in one run with no recorded rationale, cosmetic `Next:*` divergence (audit table below) | **FIXED (template)**: canonical commented template at `docs/workflow/reference/shower-config-template.cfg` (tune line included but commented pending Session 3; documents that the default-when-absent IS Monash 2013). Recommended, not imposed — certified cfgs untouched (they are run records) |
| SD-D3 | major (docs = physics claims) | KNOWN-LIMITATIONS | **Spin/polarization modeling gaps undocumented**: SLHA-table decays are phase-space — exactly right for scalars, a real loss for C1/N2 → W/Z + LSP lepton angles and for tau spin-density (details below). The Wave-1 diagnosis note "`Check:rapidityOrder=1` controls polarization" is **wrong twice over**: the setting is `SpaceShower:rapidityOrder` (no `Check:` variant exists in 8.312) and it orders ISR emissions in rapidity — nothing to do with decay spin correlations | **FIXED (docs)**: KNOWN-LIMITATIONS entry with the isotropy hierarchy + the MadSpin fix path + the rapidityOrder correction |
| SD-D4 | major (doc accuracy) | `.claude/rules/madgraph-pythia.md` | **MODSEL rule was factually wrong** (S4-validated): MadGraph does NOT write MODSEL into banners, and Pythia 8.312 imports SLHA DECAY tables regardless of MODSEL — the real silent failure is **width-only/empty DECAY tables** (and MSOFT-derived wrong spectra) | **FIXED**: rule rewritten; actionable core kept (always verify first-LHE-event masses + decay products pre-shower, now automated via `lhe_check.py`, referenced). Same stale claim still echoed in `CLAUDE.md` (gotcha line) and `docs/workflow/checklists/model-cards.md` ("ignores the SLHA DECAY tables") — **outside the approved edit list; flagged for the orchestrator** (the actionable advice there, "always include MODSEL", remains correct) |
| SD-D5 | minor | `pythia_shower.cc` / `pythia_shower_merged.cc` | **Opaque failure semantics**: up to 9 `pythia.next()` failures are silently *skipped* (output has fewer events than requested, exit still 0; the only trace is the stderr "wrote N events" line); the 10th abort breaks the loop. LHE end-of-file manifests as repeated aborts → silent truncation when `nEvents` > LHE count. No `Random:setSeed` handling: reruns are bit-identical (default seed) — good for controls, a trap for "shower again for more stats". σ printed in **mb** while the HepMC carries **pb** | **DOCUMENTED** (review below; the verify step in `steps/03-generate.md` already compares written-count + σ). Code changes not approved this session (binary rebuild out of scope); env-var tune knob refactor deferred |

## SD-D1 — the tune A/B study (measured)

**Method.** Certified gluino LHE (`…gluino-pair/build_madgraph/Events/run_gluino/unweighted_events.lhe.gz`,
10k events) gunzipped to a /tmp copy; two cfgs built from the certified `config/shower.cfg` differing
ONLY in `Beams:LHEF` (the /tmp copy) and the one added line `Tune:pp = 21` (A14+NNPDF2.3LO,
verified against `xmldoc/Tunes.xml`; applied-setting positively confirmed in the init echo:
`Tune:pp | 21 | 14 …`). Both showered with `trial-runs/_infrastructure/pythia_shower` (10k events),
Rivet `ATLAS_2016_I1458270` (plain invocation, as the certified run), then
`validate_cutflow.py --sigma-pb 0.201 --lumi-fb 3.2 --m-parent 1000 --m-lsp 100` with the run's own
`exclusion.json` for SR roles — identical arguments to the certified cert.

**Control validity.** The Monash control reproduced the certified per-SR A×ε **bit-identically**
(every `mine` value equal to all recorded digits, verdict WARN, worst |Δµ₉₅| 13.2%) — expected, since
the cfg sets no `Random:setSeed` and Pythia's default-seed runs are deterministic; this validates the
A/B methodology end-to-end.

**Result** (published values are the **flagged NEAREST node (1000,0)** — no (1000,100) node exists in
the grid, per the S4 finding; absolute ratios carry that node bias, but the A14/Monash column is
node-independent):

| SR | pub A×ε @(1000,0) | Monash A×ε (=certified) | A14 A×ε | ratio Monash | ratio A14 | **A14/Monash** |
|---|---|---|---|---|---|---|
| 2jl | 0.1547 | 0.15433 | 0.15692 | 0.998 | 1.014 | 1.017 |
| 2jm | 0.1561 | 0.14873 | 0.14823 | 0.953 | 0.950 | 0.997 |
| 2jt | 0.0268 | 0.02209 | 0.02059 | 0.825 | 0.769 | 0.932 |
| 4jt | 0.0383 | 0.03648 | 0.03698 | 0.952 | 0.965 | 1.014 |
| **5j (driving)** | 0.0737 | 0.08346 | 0.07696 | **1.132** | **1.044** | **0.922** |
| 6jm | 0.0381 | 0.04778 | 0.03978 | 1.254 | 1.044 | 0.833 |
| 6jt | 0.0311 | 0.03408 | 0.03338 | 1.096 | 1.073 | 0.980 |

Cert verdicts: Monash **WARN** (worst driving |Δµ₉₅| **13.2%**, 6jm off-tolerance at 25.4%) →
A14 **PASS** (worst driving |Δµ₉₅| **4.4%**, zero attributions). MC stats: ~835 raw events in 5j
(±3.5% independent; the two samples share the LHE so the A/B shifts are strongly correlated), ~400–480
in 6jm — the coherent downward pattern across the multi-jet tails (5j −7.8%, 6jm −16.7%, 2jt −6.8%) is
the tune's reduced shower/MPI jet activity, not a fluctuation.

**Reading.** The Wave-1 diagnosis predicted 2–3 pp of tune sensitivity; measured: **8.8 pp on the
driving 5j** (13.2 → 4.4) and **21 pp on 6jm** (25.4 → 4.4). Two consequences, stated carefully:
1. The certified gluino residual is an **excess** vs the (1000,0) node that A14 largely removes —
   the benchmark's standing "attributed: merging" story (which predicts a *deficit* from missing ME
   multiplicities) does not describe this case's sign; the dominant cause is **tune** (Monash's
   busier shower/UE inflating jet multiplicities relative to ATLAS A14 production). The `cases.json`
   note + STATUS "Session-2 target: merging" line should be revisited with this evidence.
2. **Recommendation (Session 3 decision):** adopt `Tune:pp = 21` pipeline-wide for certifications
   against ATLAS-produced grids; re-shower the four certified runs; re-lock the benchmark (expected:
   gluino A×ε Acceptable → Good/Ideal; squark cases shift at the 1–2% level — re-measure, and check
   the **merged** case explicitly since tune × MLM-matching interplay (qCut vetoes on a softer
   shower) is not a free lunch). Caveats: one mass point, 10k events, NEAREST-node bias on absolute
   ratios. Until then certified runs and the gate **stay Monash** — the locked baseline is the
   regression contract, and this study is the evidence file for changing it deliberately.

Artifacts: /tmp only (study cfgs, HepMCs, yodas, `cert_{monash,a14}.{md,json}`) — this table is the
durable record; nothing in the certified run dirs was touched.

## SD-D2 — shower-cfg drift audit (all four certified runs)

| Setting | gluino-pair | squark-pair | squark-merged | C1N2-WZ | Verdict |
|---|---|---|---|---|---|
| `Beams:LHEF` path | absolute | absolute | **relative** | **relative** | drift, unintentional — relative depends on shower cwd (works only from repo root); absolute is machine-specific. Template: absolute, framed as a per-run record |
| Tune | absent (=Monash) | absent | absent | absent | consistent; policy → Session 3 (SD-D1) |
| `SLHA:useDecayTable` | on | on | on | on | consistent, correct |
| LSP `1000022:mayDecay` | off | off | off | off | consistent, correct |
| `JetMatching` block | — | — | on/scheme 1/setMad off/qCut 100/nJetMax 2/nQmatch 4/clFact 1.0 | — | **intentional** (the merged run; matches `checklists/merging.md`, `setMad=off` deliberate) |
| `Print:quiet` | on | on | on | on | consistent |
| `Next:numberShowEvent` | 0 | 0 | 0 | absent (default 1) | cosmetic drift |
| `Next:numberCount` | 0 | 0 | 0 | 2000 | cosmetic drift (progress lines; useful for long runs) |
| `Check:epTolErr` | absent (default 1e-4) | absent | absent | **1e-2** | intentional-looking but **unrecorded** loosening: its shower log shows 2 warn-level "energy-momentum not quite conserved" events in 20k and 0 aborts. Plausibly needed for EWKino LHE precision; the cfg's own comment block doesn't say. Template documents the default + when/how to justify loosening |
| Comments | none | none | none | header comments | cosmetic |

Canonical template (recommendation, not imposition): **`docs/workflow/reference/shower-config-template.cfg`**
— commented, tune line present-but-commented (default-when-absent = Monash 2013 documented), matching
block for merged LHEs, epTolErr/seed/progress knobs with their defaults and the justification rule.
Certified cfgs left untouched: they are the records of what ran.

## SD-D3 — decay-physics documentation (the claims, stated precisely)

- **Scalar squark q̃ → q χ̃₁⁰ is EXACTLY isotropic** — a scalar has no spin to correlate; Pythia's
  phase-space SLHA decay loses no information. The squark cases' 2–4% certs are not limited by this.
- **Gluino 3-body g̃ → q q̄ χ̃₁⁰ via heavy off-shell squarks**: angular correlations exist but are
  mild (the propagator is far off-shell and near-flat across the Dalitz region); phase-space decay is
  a small approximation for these observables (jet-counting SRs).
- **C1/N2 → W/Z + LSP with leptonic W/Z**: Pythia's SLHA-table decay chain does **not** propagate the
  W/Z polarization into the lepton angular distributions — a real modeling loss affecting lepton
  pT/angular acceptance. Secondary to the attributed fast-sim floor for the certified point
  (Δm = 200 GeV, on-shell bosons), but real; the proper fix is **MadSpin at LHE level**
  (Session-3 prototype candidate).
- **Tau polarization**: W/Z → τ decays go through Pythia's internal `TauDecays` machinery (its spin
  treatment is good where it knows the production correlations), but in SLHA chains the tau
  spin-density from the parent is not fully propagated; affects leptonic-tau contributions to lepton
  SRs at the few-% level for these analyses.
- **Correction to the Wave-1 diagnosis**: "`Check:rapidityOrder=1` controls polarization" is wrong —
  no `Check:rapidityOrder` exists in 8.312; `SpaceShower:rapidityOrder` (default on) orders ISR
  emissions in rapidity, QCD-only, hard subcollision only. Nothing to do with decay spin.
- **QED FSR / lepton dressing — checked, consistent**: both routines use **bare** `PromptFinalState`
  leptons with ATLAS Run-2 efficiency+smearing (`ATLAS_2018_I1676551.cc` lines 27–33:
  `PromptFinalState` + `SmearedParticles(…, ELECTRON_EFF_ATLAS_RUN2_MEDIUM/MUON_EFF_ATLAS_RUN2_MEDIUM,
  …)`; `ATLAS_2016_I1458270.cc` likewise for its lepton vetoes). **No `DressedLeptons` projection** —
  the routines expect plain post-FSR leptons, which is exactly what our default-FSR shower
  (`TimeShower:QEDshowerByL=on`) provides. No shower-side change warranted; the residual
  bare-vs-calibrated electron difference (~1% near pT thresholds) is a routine-side convention inside
  the fast-sim floor.

All but the FSR check are now in `docs/reference/limitations.md` (Physics fidelity, two new entries).

## SD-D5 — `pythia_shower.cc` / `pythia_shower_merged.cc` review (documentation; no code changes)

- **nAbort semantics**: `if (!pythia.next()) { if (++iAbort < nAbort) continue; else break; }` with
  `nAbort=10` — failed events are *skipped*, not regenerated: the output silently carries fewer than
  the requested events (exit 0 either way); the 10th cumulative abort ends the run. LHE **EOF** also
  arrives as `next()==false`, so requesting more events than the LHE holds burns the abort budget and
  truncates silently. Distinct from Pythia-internal retries ("hadronLevel failed; try again" happens
  *inside* `next()`). Operational guard that exists today: the stderr `wrote N events` line + the
  step-3 verify (count + σ vs MadGraph).
- **Weight handling**: the HepMC3 plugin defaults (`m_store_weights=true`) write Pythia's full weight
  container per event — one nominal weight for our `use_syst=False` LHEs (= σ in pb under LHA
  strategy ±3; observed `W 2.009e-01` for the gluino sample). A multiweight LHE would propagate every
  weight into the HepMC; the guards are upstream (`lhe_check.py`) and Rivet-side (`--skip-weights`).
- **HepMC3 units**: `evt->set_units(Units::GEV, Units::MM)` (plugin line 76); per-event
  `GenCrossSection` set from `sigmaGen()*1e9` (mb → **pb**, what Rivet reads). The binary's stderr
  prints σ in **mb** — a known cosmetic inconsistency with the HepMC content.
- **Seed handling**: neither binary nor any certified cfg touches `Random:setSeed` (default **off**)
  → Pythia initializes from its fixed default seed every run → **bit-identical reruns** of the same
  cfg+LHE+binary (measured: the Monash control reproduced the certified cert exactly). Right behavior
  for regression/control studies; a trap for naive "more statistics" reruns — documented in the
  template (`Random:setSeed/seed` commented with the rule).
- **Deferred refactor** (not approved this session — binary rebuild out of scope): an env-var/flag
  tune knob (e.g. `PYTHIA_TUNE` → `Tune:pp`) so A/B studies and the Session-3 policy switch don't
  require editing per-run cfgs; plus a nonzero exit (or a `wrote N != requested` sentinel) when the
  abort path truncates the sample, and σ printed in pb.

## Fixes applied — measured

| Fix | Evidence |
|---|---|
| Tune A/B study (SD-D1) | Monash control **bit-identical** to the certified cert (WARN, 13.2%); A14 → PASS, 4.4%, table above. Evidence-only by design: certified artifacts + gate untouched (gate stays Monash and held — see below) |
| Canonical shower-cfg template (SD-D2) | `docs/workflow/reference/shower-config-template.cfg` (new; tune commented + Monash-default documented; hygiene grep clean — no trial-run references) |
| KNOWN-LIMITATIONS entries (SD-D1, SD-D3) | Two new Physics-fidelity entries: tune sensitivity (with the measured 5j/6jm numbers) and spin/tau/polarization gaps (with the MadSpin path + rapidityOrder correction) |
| Rules rewording (SD-D4) | `.claude/rules/madgraph-pythia.md` SLHA-invariant section rewritten to the S4-validated facts (no MODSEL injection by MadGraph; DECAY import unconditional on MODSEL; width-only tables are the killer; MODSEL still mandatory for internal-machinery channels; `lhe_check.py` referenced as the automated guard) |
| Bridge-binary semantics documented (SD-D5) | This file (nAbort/EOF truncation, weight container, GEV/MM + pb-vs-mb, deterministic default seed) |

## Deferred (with why)

- **Pipeline-wide A14 adoption + benchmark re-lock** → Session-3 policy decision: touches all four
  certified runs and the locked baseline; needs the merged-case tune×matching re-measurement first.
  The numbers + recommendation above are the decision input.
- **MadSpin prototype at LHE level** (the proper spin-correlation fix for C1N2-type chains) →
  Session 3: needs the mg5 env + a fresh generation pass; its benefit at the certified point is
  bounded (on-shell, Δm=200; the fast-sim floor dominates) — right place to evaluate it is the next
  EWK analysis with lepton-angular-sensitive SRs.
- **Bridge-binary refactor** (env-var tune knob, truncation sentinel/exit code, pb σ print) — code
  changes/rebuild not approved this session.
- **Benchmark gluino attribution note** (`cases.json` "merging") — registry edits invite a re-lock
  discussion (same posture as S4's registry-notes deferral); the measured reattribution evidence is
  recorded here + KNOWN-LIMITATIONS.
- **Stale MODSEL echoes outside the approved file set**: `CLAUDE.md` gotcha line ("a missing MODSEL
  silently disables SLHA decays") and `docs/workflow/checklists/model-cards.md` ("ignores the SLHA DECAY
  tables") carry the pre-correction claim; their actionable advice (always include MODSEL) stays
  valid → one-line orchestrator follow-up.

## Gate (the single `--full` run at stage close)

`python3 benchmarks/run_benchmark.py --full` → **exit 0, 4/4 OK**, metrics unchanged vs the
committed baseline (field-stripped comparison: only `generated`/timing differ): squark 2.4% Ideal /
s95 1.01/1.03 / µ₉₅ 0.22254; merged 3.9% Ideal / 1.01/1.03 / 0.22580; gluino 13.2% Acceptable /
1.00/1.02 / 0.05237 (WARN, unchanged — stays Monash by design); C1N2 6.4% Good / 2.7123. This stage
changed no run artifact, no helper invoked by the gate, and no registry file — regression-free by
construction; the tune study lived entirely in /tmp.
