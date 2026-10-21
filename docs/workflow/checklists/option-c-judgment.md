# Checklist — Option-C physics judgment  ·  reconstructing a selection from paper prose

Option C (step 4 §C) says WHAT the no-routine path is; this checklist is the HOW of its judgment
— an auditable transcription from source text to selection code. Record the response limits
before comparing sensitivities.

## 1. The selection-reconstruction protocol (prose → code, auditable)
Build `<rundir>/inputs/selection_transcription.md` BEFORE writing analysis code:
- **Object table** — one row per physics object: definition in the paper's words (algorithm,
  R, pT/η cuts, grooming, WPs) → the particle-level realization → what is LOST (calibration,
  pileup, detector smearing) → the fidelity consequence. Every column filled or the row is
  flagged; an object requiring unpublished response inputs (tagger WP with unpublished ε) is a trap-T10 flag, not
  an improvisation.
- **Cut ledger** — one row per selection step, IN THE PAPER'S ORDER, each with the paper's exact
  sentence quoted (page/section), the transcription, and AMBIGUITIES as numbered entries (does
  "leading two jets" mean pre- or post-cleaning? which mass definition?). Every ambiguity gets:
  the chosen reading + why + the conservative-default check (P7) + a CHECK-IN flag if it moves
  yields at the >10% level (estimate cheaply with truth-level counts).
- **The [judgment] rule:** where the paper is silent, choose the reading that WEAKENS the
  sensitivity claim, and record the alternative — never the reading that makes the method look
  better (number-integrity: silent choice-shopping is the failure).

## 2. Proxy-choice judgment (what detector effect matters for THIS observable class)
Particle-level is not one fidelity — rank what the observable actually depends on:
- **Mass-shape analyses** (bump hunts, substructure masses): resolution smearing DOMINATES —
  a truth-level mass peak is unrealistically narrow → sensitivity OVER-estimated. Either smear
  by the paper's quoted resolution (declare the number + source) or state the over-estimate
  direction explicitly in every deliverable.
- **Count/efficiency analyses** (SR yields): object-efficiency products dominate — use published
  per-object ε where they exist (T10/D-route), else the proxy is declared UN-calibrated.
- **ML/AD-method analyses**: validate method ordering, relative gains and absolute sensitivity
  separately. State which claims survive the declared response variations.

## 3. The anchor ladder (Option C's substitute for cutflow certification)
No routine ⇒ no published cutflow cert ⇒ every Option-C run declares which anchors it DID hit
(ladder rungs; not-checked is loud):
1. **Object-level sanity**: truth-object multiplicities/spectra vs any published distribution
   (digitized) — the cheapest reality check.
2. **Method-internal reference**: compare the published method curve (ROC/SIC, efficiency
   plateau or mass-sculpting check) over its declared domain.
3. **Relative-sensitivity ordering**: the paper's method ranking at its supplied reference points.
4. **Absolute normalization**: ONLY with a declared σ×A anchor (published σ, digitized
   efficiency); otherwise the deliverable stays `sensitivity-expected-only` with the ×N absolute
   caveat quantified against the nearest applicable published number.
Record the evidence available for each rung. Missing anchors leave the corresponding
claim unattributed (PLAUSIBLE-UNATTRIBUTED in RESULT.md).

## 4. Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "The paper obviously means X, everyone does X" | Resolve alternative readings in the cut ledger, with the source location and sensitivity consequence. |
| "Truth-level is close enough for a mass bump" | An unsmeared peak can overstate mass resolution and sensitivity; use a qualified response and retain its uncertainty. |
| "I'll validate at the end against Fig N" | Attribution requires ladder bracketing; rungs 1–2 run BEFORE the heavy stages or the run ships unattributed. |
| "No routine means free rein on the method" | Option C is a TRANSCRIPTION exercise with declared deviations, not a redesign; every deviation from the paper's procedure is a numbered flag + DEVIATIONS entry. |

## Stop conditions
- An object/cut requires additional source inputs for transcription (unpublished tagger, detector-internal
  quantity) → trap T10 consequence: efficiency-map route if maps exist, else the honest block
  for that piece — never a silent stand-in.
- The ambiguity ledger's yield-moving entries (>10%) are unanswered at CHECK-IN 1 → the run
  proceeds only on the conservative readings, all flagged.
