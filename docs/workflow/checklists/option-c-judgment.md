# Checklist — Option-C physics judgment  ·  reconstructing a selection from paper prose

Option C (step 4 §C) says WHAT the no-routine path is; this checklist is the HOW of its judgment
— codified from the two executed trials (CMS A→BC EXO-22-026; ATLAS CWoLa 2005.02983) and their
23 recorded gaps. The failure class this kills: a plausible-looking custom selection that is
quietly NOT the paper's, discovered only at the sensitivity comparison (or never).

## 1. The selection-reconstruction protocol (prose → code, auditable)
Build `<rundir>/inputs/selection_transcription.md` BEFORE writing analysis code:
- **Object table** — one row per physics object: definition in the paper's words (algorithm,
  R, pT/η cuts, grooming, WPs) → the particle-level realization → what is LOST (calibration,
  pileup, detector smearing) → the fidelity consequence. Every column filled or the row is
  flagged; an object you cannot realize (tagger WP with unpublished ε) is a trap-T10 flag, not
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
- **ML/AD-method analyses**: the METHOD-internal comparison (ordering of methods, relative
  gains) survives proxy fidelity far better than absolute numbers — state which of the two
  the deliverable claims (both trials validated ORDERING, and said so).

## 3. The anchor ladder (Option C's substitute for cutflow certification)
No routine ⇒ no published cutflow cert ⇒ every Option-C run declares which anchors it DID hit
(ladder rungs; not-checked is loud):
1. **Object-level sanity**: truth-object multiplicities/spectra vs any published distribution
   (digitized) — the cheapest reality check.
2. **Method-internal benchmark**: the paper's own published method curve (ROC/SIC, efficiency
   plateau, mass-sculpting check) reproduced qualitatively — the AD trial's Fig-1 NN-learnability
   anchor is the worked example.
3. **Relative-sensitivity ordering**: the paper's method ranking at its benchmark points (both
   trials' validation).
4. **Absolute normalization**: ONLY with a declared σ×A anchor (published σ, digitized
   efficiency); otherwise the deliverable stays `sensitivity-expected-only` with the ×N absolute
   caveat quantified against the nearest published number (the CMS trial's ~3× scale note is the
   honest pattern).
Rungs 1–3 reachable in every Option-C run; a run that skips them has an unattributed result
(ladder rule: PLAUSIBLE-UNATTRIBUTED, said in RESULT.md).

## 4. Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "The paper obviously means X, everyone does X" | Both trials logged ambiguities where "obvious" readings differed between two careful passes; the cut ledger exists because prose is not code. |
| "Truth-level is close enough for a mass bump" | Unsmeared peaks are 2–5× narrower than reconstructed ones — sensitivity inflates accordingly; smear or say it. |
| "I'll validate at the end against Fig N" | End-validation cannot ATTRIBUTE a mismatch (ladder bracketing); rungs 1–2 run BEFORE the heavy stages or the run ships unattributed. |
| "No routine means free rein on the method" | Option C is a TRANSCRIPTION exercise with declared deviations, not a redesign; every deviation from the paper's procedure is a numbered flag + DEVIATIONS entry. |

## Stop conditions
- An object/cut cannot be transcribed even approximately (unpublished tagger, detector-internal
  quantity) → trap T10 consequence: efficiency-map route if maps exist, else the honest block
  for that piece — never a silent stand-in.
- The ambiguity ledger's yield-moving entries (>10%) are unanswered at CHECK-IN 1 → the run
  proceeds only on the conservative readings, all flagged.
