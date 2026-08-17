# Checklist — the ADVERSARIAL VERIFICATION PANEL  ·  Tier A [agent] · Tier B [judgment]

Read with `workflow/steps/09-verify.md`. MANDATORY before any result is delivered: the drafted final
check-in / `RESULT.md` does not go to the physicist until every box below has a verdict. Findings are
**appended to the final check-in verbatim** — never silently fixed.

## THE NUMBER-INTEGRITY RULE (governs the whole run, verified here)
- **Agents must never adjust numbers, tolerances, selections, or protocols *toward a target*** (a
  published value, a hoped-for agreement, a passing cert). Adjustments are made for stated physics
  reasons only, prospectively, and in the open.
- **Any mid-run change of protocol, tolerance, selection, or instruction MUST be logged in the run's
  `DEVIATIONS.md`** at the moment it is made — what changed, from what, to what, why, and what it
  touches. The ledger's check-in is defined in `checklists/check-ins.md`. An unlogged change
  discovered later is itself a FAIL-severity finding.
- **A discrepancy between a quoted number and its machine artifact is an automatic FAIL** — no
  materiality threshold, no "rounding" defense beyond the artifact's own printed precision. The
  artifacts (`scan.json` / `result.json` / `sensitivity.json` / `figures.json`) are the single
  sources of truth; prose is generated from them, never the reverse.

## Tier A — MECHANICAL INTEGRITY ([agent]; Haiku/Sonnet-class sufficient)
Run `trial-runs/_infrastructure/validate_run_state.py --rundir <rundir>` first (lifecycle: required
stages present + invariants incl. R5/pairing/ladder-order/certify-before-limit), then
`trial-runs/_infrastructure/verify_pack.py <rundir>` (artifact integrity); paste both reports here.
Then, by hand:
- [ ] **`validate_run_state.py --rundir` exit 0** (lifecycle: required stages present + invariants
      incl. R5/pairing/ladder-order/certify-before-limit — a `full|scan` run that reached generation
      must carry a `logs/ladder.json` smoke-rung PASS, and any limit-shipping run (incl. a scan) must
      carry a discoverable non-FAIL acc×eff cert: a FAIL or absent cert hard-BLOCKS the limit, and a
      scan's per-point `scan.json` attestation does not waive it).
- [ ] **`validate_run_state.py --rundir <rundir> --verify-provenance` exit 0** (provenance, not
      presence — G19). Beyond the base `run_state.json` check, this rejects a REQUIRED
      physics-lifecycle artifact that was hand-written or backfilled: a discoverable
      `sr_plausibility.json` whose `generated_by` is absent/empty/hand-written — or is not the tool
      that must produce it (`sr_plausibility.py`) — hard-FAILs (exit 1, `PROVENANCE FAIL:` on stderr).
      It ALSO recomputes the artifact's `input_fingerprint` over its declared inputs
      (`outputs/sr_yields.json` + `outputs/pyhf_exclusion/exclusion.json`, the same
      plausibility-domain canonicalization the emitter uses) and hard-FAILs when the stored fingerprint
      no longer matches — a stale artifact left in place after its inputs changed (a backfill).
      Presence alone never satisfies the gate; this closes the backfill loophole where a plausibility
      verdict is typed in by hand, or a real verdict is kept after the yields/limit underneath it moved.
- [ ] **Verification ladder present + consistent** — `VERIFICATION-LADDER.md` exists
      (`checklists/verification-ladder.md`), every rung has exactly one status, every RESULT.md
      gap labeled CONFIRMED actually has its bracket in the table, and `not-checked` rungs
      reappear in the RESULT.md limitations. Missing ladder ⇒ FAIL (the run is unattributed).
- [ ] **Every number traces.** Each number in the final check-in and `RESULT.md` (limits µ₉₅ obs/exp,
      yields, σ, k-factors, A×ε, coverage counts, masses, lumi) is found in — or derived with the
      derivation shown from — `scan.json` / `result.json` / `sensitivity.json` / `figures.json`.
      List each quoted number next to its artifact value. Mismatch ⇒ **automatic FAIL**.
- [ ] **Units.** Every quantity carries its unit; the unit matches the artifact's convention
      (fb vs pb, GeV, fb⁻¹). A unitless headline number is a finding.
- [ ] **Figure files exist.** Every figure cited in the check-in / `RESULT.md` / `figures.json` is on
      disk (png, and pdf where declared).
- [ ] **Every displayed figure has a caption** (`what_it_shows` populated in `figures.json`; the
      check-in shows it). `criteria_pass` recorded per `checklists/plot-criteria.md`.
- [ ] **Figure contract fulfilled or WARNed** — declared targets carry a `generated_counterpart`
      (`checklists/figure-contract.md`); unfulfilled targets are explicitly WARNed, not omitted.
- [ ] **Coverage claims match the artifact.** "N of M points", "full grid", "partial" in the prose
      equal `n_done`/`n_planned`/`missing_tags` in `scan.json` (or the run's coverage fields).
- [ ] **Deviations ledger present and complete.** `DEVIATIONS.md` exists; every mid-run
      protocol/tolerance/selection/instruction adjustment appears in it; every renorm/rebase-style
      provenance block in the artifacts has a matching ledger entry. Missing ledger with such blocks
      present ⇒ FAIL (verify_pack.py checks this mechanically).
- [ ] **No OPEN defect note (N5/G26).** `run_state.open_defect_notes` carries no `status:"open"`
      entry: a number from a helper flagged mid-run with an open defect note must not feed the
      comparison/check-in. `verify_pack.py` FAILs (exit 1) on any open note — fix the helper or
      substitute the blessed tool, then flip the note to `status:"fixed"`. Enforced at a delivery
      turn-end by the DELIVERY-only `branch_open_defect` Stop-branch (token `G26-OPEN-DEFECT:`).

## Tier B — PHYSICS ADVERSARY ([judgment]/Fable-class; fresh context, artifacts only)
The adversary receives the artifacts + figures, **not** the narrative's conclusions, and attempts to
REFUTE the headline claims. Start from TWO attack lists before free-form attacks: the real past
process failures — `framework/FAILURE-CATALOGUE.md`, walking each catalogued class against this
run — and the domain trap catalogue — `checklists/physics-traps.md` T1–T12, RE-RUNNING the sweep
independently (a mismatch with the run's recorded `traps_checked/traps_hit` is itself a finding).
The run's own P8 kill-the-result attacks (`checklists/judgment-protocols.md`) are seeds, not
substitutes: verify each, then go beyond them.
- [ ] **Basis choices.** Every comparison like-for-like: σ normalization (LO vs NLO+NLL, flat-k vs
      k(m)), charge/flavour state content, sample-σ vs model-σ, binning/plane conventions. State
      whether any defensible alternative basis would flip the verdict.
- [ ] **Statistical treatment.** `stat_mode` matches what was actually done; limit reaches the true
      CLs=0.05 crossing; expected band ordered and the median is the median; single-SR vs combined
      justified; systematics not under-quoted (`.claude/rules/statistics.md`). 95% CL exclusion
      language only — never discovery.
- [ ] **Proxy validity.** Every proxy (fast-sim, reimplemented selection, truth-level shortcut,
      AD/tagger stand-in) is declared, and its domain of validity covers the region the headline
      quotes. A proxy quietly extrapolated beyond validation is a finding.
- [ ] **Assumption flags complete.** `limitations[]` + `RESULT.md` caveats cover every material
      assumption the adversary can reconstruct from the artifacts. Each unflagged one is a finding.
- [ ] **Refutation attempt recorded.** For each headline claim: the strongest attack found, and why
      it does (finding) or does not (survives) succeed — from the artifacts alone.

## Verdict
| verdict | meaning | delivery |
|---|---|---|
| **PASS** | no findings survive | deliver; append verdict + verify_pack report |
| **CONCERNS** | findings survive but none overturn the headline | deliver **with** findings appended, each answered (fixed+noted, or accepted into `limitations[]`) |
| **FAIL** | a finding overturns/blocks the headline (incl. any number-integrity FAIL) | do **not** deliver; fix, log in `DEVIATIONS.md`, re-run BOTH tiers |

Findings format (append to the check-in): `[tier/severity] claim attacked — evidence (artifact:field) —
disposition`. A silent fix — changing the deliverable without the finding appearing in the check-in —
violates this checklist by itself.
