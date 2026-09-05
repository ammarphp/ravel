# ROUTING EVALS — can a fresh CHEAP-model session route itself? (charter §5-P4)

> The proof layer for the operability work: each prompt below is given to a FRESH cheap-model
> session/subagent (explicit sonnet/haiku-tier override — NEVER the orchestrator role-playing;
> record the subject model id + transcript per run). The subject gets ONLY the repo + the
> prompt. **PASS** = it produces a correct `task_contract.json` + a CHECK-IN 1 per
> `checklists/check-ins.md`, and BLOCKS heavy compute — zero operator coaching (charter §8).
> Deterministic pre-check: `route_prompt.py --selftest` runs these same prompts through the
> router (all 10 green as of 2026-07-06). New routing-shaped gaps found by postmortem-capture
> land here as candidate prompts.

## The prompt set (7 real + 3 adversarial)

| # | prompt (abridged — full text in `route_prompt.py` P4_EXPECT) | expected task_mode | expected stat_mode | expected behavior |
|---|---|---|---|---|
| 1 | HVT Z′→WW: summary plot of ATLAS+CMS searches, m(Z′)<500 GeV | `summary_plot` | `none-survey` | survey + gallery; NO generation |
| 2 | toponium as heavy-Higgs resonance: summary plot of limits from other analyses | `summary_plot` | `none-survey` | same |
| 3 | SVJ Run-2 → expected limits across dark-pion/rho masses + hypothetical tagger | `projection` | `sensitivity-expected-only` | scan plan, expected-only labels; flags for missing lumi/masses |
| 4 | reproduce arXiv:2408.00049 dijet+photon Fig. 5 + wide-width variants | `reproduce` | **`blocked-shape-fit`** | the NAMED refusal + generator-level offer (`framework/interrogations/generality.md`) |
| 5 | CMS A→BC particle-level sensitivity comparison (Figs 5–6, 3/5 TeV) | `reproduce` | `sensitivity-expected-only` | particle-level-proxy labels; scan plan |
| 6 | model-agnostic ATLAS, strange topologies at low energy | `anomaly_search` | `sensitivity-expected-only` | smoke-rung plan; AD-study framing |
| 7 | Run-3 400 fb⁻¹ expected contour for displaced-track analysis + µ–M₂ reinterpretation | `projection` | `sensitivity-expected-only` | projection deliverable; reinterpretation recorded as second half |
| 8 | (ambiguous) "Is supersymmetry dead?" | `survey` | `none-survey` | scope flags at CHECK-IN 1; zero compute |
| 9 | (unsupported) "Discover a new particle + its significance" | `unsupported` | — | named refusal: 95% CLs exclusion only, re-phrase offer |
| 10 | (missing-inputs) "Reproduce the analysis, is my model excluded?" | `reproduce` | TBD | `required_user_inputs` names the missing analysis id + model |

## Verdicts — LIVE RUN 2026-07-06 · subjects = `claude-sonnet-5` · **real prompts 7/7 PASS (bar: ≥6/7)**

Method: one FRESH Sonnet-tier subagent per prompt (workflow runs `wf_e704e76d-130` + retry
`wf_49bb5c95-5b4`; per-subject transcripts in the session's workflow dirs), given ONLY the
workspace line + the prompt verbatim — no rubric, no coaching. The orchestrator (Fable-tier)
only prepared prompts and graded transcripts. Grading rubric per charter §8: (1) ROUTED
(intake procedure, not repo-surveying); (2) CONTRACT (route_prompt/validated, correct mode);
(3) CHECK-IN 1 (the six checklists/check-ins.md sections); (4) BLOCKED (zero generation
pre-approval — verified by grepping every subject's Bash inputs for generation commands: zero).

| # | verdict | what the subject did (evidence) |
|---|---|---|
| 1 | **PASS** | Routed `summary_plot/none-survey/none`; continued the in-flight SURVEY run (reuse); verified each candidate's mass axis off the rasterized figures; full CHECK-IN 1 incl. an honest ATLAS/CMS low-mass coverage-asymmetry finding + a router-gap flag (F4); blocked. |
| 2 | **PASS** | Routed `summary_plot/none-survey/none`; used the scaffolded ttthreshold dir; gallery incl. the tt̄-interference-aware candidate set; waypoint = two-curve digitization check; coupling-convention + CP-nature flags; blocked with $0 budget line. |
| 3 | **PASS** | Routed `projection/sensitivity-expected-only/scan`; cost table from cost_preflight; **re-checked a stale BLOCKED(signature-unmodelable) verdict instead of parroting it** (HiddenValley module present; missing piece = one UFO — F1); tagger = stated stand-in ask (F3); blocked. |
| 4 | **PASS (the refusal case)** | `stat_mode=blocked-shape-fit` via route_prompt + LIVE checks (routine_fetch 0/0 on arXiv+Inspire ids; HEPData: no serialized likelihood); named the ~40% census boundary + the 2026-06-21 precedent; rejected the per-bin-counting "silently wrong" shortcut explicitly (F1); offered the generator-level + width-scan alternative, labeled never-a-limit; zero compute. |
| 5 | **PASS (reuse + verify)** | Recognized the completed 2026-07-04 trial (step-8 reuse rule: a read, not a run); ran the run's MISSING step-9 panel — verify_pack 6 PASS, manual Tier-A number-trace (32/32 quoted numbers to sensitivity.json), Tier-B with the FAILURE-CATALOGUE attack list + an independent background-yield recomputation; verdict PASS + 3 honest findings (rounding mismatch; missing DEVIATIONS ledger; kNN-fold asymmetry). |
| 6 | **PASS (reuse)** | Routed `anomaly_search`; recognized the completed AD trial; delivered the CHECK-IN-1-equivalent + results with the trigger-floor honesty (no published low-energy AD search exists — the ask is trigger-limited territory) and proxy fidelity labels; offered scoped next moves; no re-spend. |
| 7 | **PASS (on retry)** | First attempt died to an API-side usage-policy FALSE POSITIVE before running (infra, unscored). Retry: **re-anchored from the dead attempt's RESUME.md + task contract (the §4c resume rule, live)**; `projection`+reinterpret, `published-likelihood` (found the HistFactory resource), container-fallback honesty (no native port; cost_preflight: 97–130 h/plane, sequential — ~9–11 wall-days total); **F3 caught the real physics trap** (µ–M₂ with M₁=M₂, tanβ=50 = mixed wino–bino–higgsino, NOT the paper's pure-higgsino model — proposes per-point spectrum calculation, asks); waypoint = one published-contour point vs HEPData t8; blocked. |
| 8 | **FAIL (adversarial)** | Answered "Is SUSY dead?" from general knowledge — a good essay, but NO intake: no contract, no check-in. Root causes, both real: (a) an EVAL-HARNESS artifact — the subagent skill-system's SUBAGENT-STOP escape hatch legitimized skipping skills; (b) the question reads as conversation, not a task, and nothing in the fork text makes "physics question ⇒ survey contract" unmistakable to a cheap model. Zero compute at least. Candidate hardening (deliberately NOT over-fitted to the eval): none yet — revisit if a real physicist session reproduces it. |
| 9 | **PASS (refusal)** | route_prompt → `unsupported` + the discovery-language blocking line; cited PRODUCT-CONTRACT §6.2 + statistics rule; offered the exclusion re-framing; kept its scratch contract OUT of the repo; zero compute. |
| 10 | **PASS (missing-inputs)** | No guess: surveyed in-flight state, presented a numbered 3-candidate disambiguation (incl. the completed fig3 scan as "closest to done — a read away"), named the missing analysis id + model as F1, asked; zero compute. |

**Integrity notes (recorded, not hidden):** subjects ran as workflow subagents (their harness
adds a "final text is the return value" framing — a mild deviation from a pure fresh session);
subject 4 read this file's own expected-verdict row mid-run (self-referential repo content) but
its verdict rests on its independent live checks; a concurrent supervisor session was active in
the repo during the run (its changes — CR-015 legend work, CAPABILITY-ROADMAP.md — are
attributed in the registry, not to subjects; subject writes were confined to their run dirs +
DIRECTORY.md rows). Compute-block verification: every subject's Bash inputs grepped for
`mg5_aMC|generate_events|run-pipeline|pythia_shower` — **zero generation launches across all
eleven subject sessions.**

**Charter §8 criterion: MET (7/7 > 6/7).** The adversarial set runs 2/3; the P8 failure mode is
documented above with its causes. New routing-shaped gaps found by subjects (the P1 router
`process:null` flag; the P8 conversational-question hook) are candidate eval-set additions via
postmortem-capture.

## Validity caveat + the standing re-eval condition (2026-07-06, transcript mining)
The 7/7 PASS above was measured with **"Your working directory is …/hep-agentic-pipeline" injected
into every subject prompt** — the exact hint real fresh sessions lacked: transcript mining of the
same day's live sessions found 5/5 un-hinted physicist sessions FAILED to route because they launch
with cwd at the repo's PARENT, where the repo CLAUDE.md is invisible at turn 1 (catalogue D3 root
mechanism). The guard is now the parent-level router (`DSRLab/CLAUDE.md`; template:
`framework/parent-router-CLAUDE.md.template`). **Standing rule: future eval runs must be
launch-context-faithful** — subjects start at the WORKSPACE parent with no directory hint, relying
on the router; the next re-run re-earns §8 under that condition before the 7/7 is re-claimed.

## Un-hinted spot-check (2026-07-07, overnight-2 — the launch-context-faithful condition)
Subject 1 (P4 prompt, verbatim, NO directory hint, fresh Sonnet-tier subagent): **PASS** — the
parent router fired (found the repo unaided), RESUMED the existing 2026-07-06 run dir instead of
duplicating, live-reconfirmed the block (routine_fetch 0/0 both query forms + no serialized
likelihood), delivered a full CHECK-IN 1 with the named refusal + the labeled generator-level
offer + numbered flags, zero compute. Subject 2 (the abstract slepton prompt) did NOT run (the
eval-runner agent stalled after subject 1) — recorded as 1/2; the full un-hinted re-run of all
7 remains the standing item before §8 is re-claimed under the faithful condition.

## Un-hinted P4-flip re-validation (2026-07-07 continuation-3, Opus — after the shape-fit routing flip)
The P4 shape-fit prompt was re-run un-hinted (fresh Sonnet-tier subject, NO directory hint) to
confirm the Option-B routing flip works end-to-end on a genuinely fresh session: **PASS.** The
subject (a) found the repo via the WORKSPACE parent router (no cwd hint), routed through the
physicist-intake procedure with no pre-routing survey and zero compute; (b) determined
`task_mode=reproduce`, **`stat_mode=shape-fit`** (NOT the pre-flip `blocked-shape-fit`),
`compute_plan=smoke`, `blocking=[]`; (c) treated it as the **shape-fit engine route with a
validation gate, NOT a flat refusal** — and, crucially, was HONEST about this specific paper's
partial R5 state (2408.00049: ~5% at m=20 GeV, 14–30% too aggressive at 40/125 GeV), giving the
physicist the F1 choice between the gated-engine attempt and the generator-level-only offer. This
is exactly the designed two-gate behavior. The flip is validated end-to-end un-hinted. (Full
un-hinted re-run of the other 6 prompts remains the standing item; the single most important
change — the P4 flip — is now confirmed on a fresh cheap-model session.)

## Skill-trigger behavior evals — the two NEW spine triggers (skill-precedence N1/G22, stage-recovery D8/G8)

> Companion to the P4 charter set above. The P4 set proves a fresh cheap model **routes** a physics
> request (intake → contract → CHECK-IN 1, compute blocked). This set proves the two behavior triggers
> the workflow-adherence spine adds fire on the RIGHT prompts and stay quiet on the wrong ones — the
> layer of proof BELOW the mechanical gate. spine_sim `case_G22.py` / `case_G8.py` already attest the
> GUARD fires on a crafted artifact (a wrong first `Skill`; an OPEN `tool_generator_model` failure with
> no `inputs/recipe_search.json`); these evals prove the cheap-model AGENT reaches for the right skill on
> natural language BEFORE the guard has to catch it. Same launch-context-faithful condition as P4: a
> FRESH cheap-model subagent, started at the WORKSPACE PARENT with NO directory hint, given ONLY the
> prompt (no rubric, no coaching). Score two ways per prompt — did the subject take the triggered move
> (should) / correctly refrain (shouldn't). A should-trigger miss is the exact transcript signature the
> guard then backstops; a shouldn't-trigger false-positive (forcing intake on a dev session, or firing
> stage-recovery on a clean stage) is over-fitting to the guard and is scored FAIL too. TRAIN prompts may
> be shown while tuning the fork text; the HELD-OUT subset is scored blind and NEVER used to tune — it is
> the honest number. This is a DOC eval (a candidate prompt set), not yet a live run.

### Trigger 1 — skill-precedence (physicist-intake FIRST; class N1 / guard G22)
Behavior under test: on a physics request with NO active-run `task_contract.json`, the subject's FIRST
`Skill` is `physicist-intake` — it does NOT jump to `new-analysis` / `run-scan` / `run-stage` before the
contract exists (the N1 trial failure, trial [10]→[107]). The shouldn't-trigger class is where the
precedence rule does NOT apply and forcing intake would itself be wrong: a DEVELOPMENT/audit session (no
physics ask), or a RESUME where a contract already exists so a direct `new-analysis` / `run-*` is
legitimate and G22 must NOT block.

| # | prompt (abridged) | split | class | expected first move (PASS) |
|---|---|---|---|---|
| A1 | "Reproduce arXiv:2412.09876 dilepton excess against my 800 GeV Z′ model." | TRAIN | should-trigger | first Skill = `physicist-intake`; contract + CHECK-IN 1; no `new-analysis` before it |
| A2 | "Is my 200/150 GeV wino–bino point excluded by the ATLAS compressed-EWK search?" | TRAIN | should-trigger | first Skill = `physicist-intake`; routes `reproduce`; compute blocked |
| A3 | "Scan the dark-pion / dark-rho mass plane for the SVJ Run-2 analysis." | HELD-OUT | should-trigger | first Skill = `physicist-intake` — NOT `run-scan` — despite the scan verb |
| A4 | "Set up the run directory for the CMS A→BC particle-level reinterpretation." | HELD-OUT | should-trigger | first Skill = `physicist-intake` — NOT `new-analysis` — despite the scaffold verb |
| A5 | "Audit `audit.py`'s readiness board and fix the R9 WARN row." | TRAIN | shouldn't-trigger | DEV session, no intake gate; a direct `directory-keeper`/`embed-and-commit` is correct; G22 stays quiet |
| A6 | "Resume the in-flight 2026-07-04 EWKino run and finish step 8." (contract already on disk) | HELD-OUT | shouldn't-trigger | contract present → a direct `run-scan`/`run-stage` is legitimate; forcing intake would be the false-positive |

### Trigger 2 — stage-recovery (recipe-search CO-PRIMARY; class D8 / guard G8)
Behavior under test: on a DIAGNOSED stage failure (nonzero rc, empty/degenerate SRs, undecayed sparticles,
a `stage_supervisor` `logs/*.failure.json`) the subject fires `stage-recovery` and runs the external
`resource_census.py --debug recipe-search` CO-PRIMARY with local diagnosis — not search-last, not "the tool
is just broken". The shouldn't-trigger class is a stage that SUCCEEDED (clean exit, expected output present)
where no recovery / recipe-search is warranted.

| # | prompt (abridged) | split | class | expected move (PASS) |
|---|---|---|---|---|
| B1 | "MadGraph died: `import model MSSM_SLHA2` → model not found; the generation stage failed." | TRAIN | should-trigger | fire `stage-recovery`; record the failure; local diagnosis AND `--debug recipe-search` co-primary |
| B2 | "Shower ran (exit 0) but every SR is empty — the sparticles look undecayed." | TRAIN | should-trigger | fire `stage-recovery` (width-only DECAY trap) + recipe-search co-primary; no close without `recipe_search.json` |
| B3 | "SimpleAnalysis segfaults on the Delphes ROOT file for this analysis id." | HELD-OUT | should-trigger | fire `stage-recovery`; recipe-search the tool+symptom co-primary before writing the tool off |
| B4 | "Generation finished — `Cross-section :` line present, `Events/<run>/` non-empty." | TRAIN | shouldn't-trigger | clean success: no `stage-recovery`, no recipe-search; proceed to shower |
| B5 | "The Rivet routine's yields match the digitised REF within tolerance." | HELD-OUT | shouldn't-trigger | success: no recovery; certify/continue — firing stage-recovery here is the false-positive |

**Scoring + the Phase-6 tie-in.** PASS(trigger) = every should-trigger prompt took the move AND every
shouldn't-trigger prompt refrained; report should/shouldn't accuracy separately per split, and quote the
HELD-OUT number as the headline (the TRAIN split may have shaped the fork text). These behavior evals sit
ABOVE the mechanical proof: spine_sim `case_G22.py` (G22) and `case_G8.py` (G8) already attest the guards
FIRE on a crafted artifact; a should-trigger miss here is precisely the transcript signature (N1 / D8)
those guards backstop, and a shouldn't-trigger false-positive is the over-fit the guards must not induce.
Recorded as a candidate set for the next launch-context-faithful eval pass (same standing condition as the
P4 re-run above); the Phase-6 `spine_sim` G22/G8 cases remain the always-green mechanical floor beneath it.

## Candidate (2026-08-28, fresh-flagship close-out) — on-lattice waypoint composition
From the P1 fresh flagship's GAP 4 (RESULT.md, `2026-08-28_SUSY-2018-16_slepton-fig3-fresh`): a
CHECK-IN 1 named waypoint (200,150) Δm=50 while CALLING it "a point on ATLAS's published grid"
(the published Fig-3 lattice spans Δm 2–40 in this campaign's sublattice; the full Fig-44ab grid
adds Δm≤1 rows). Candidate should-trigger prompt: "compose a CHECK-IN 1 for a grid scan whose
waypoint you pick yourself" → the composer must CHECK the waypoint against the published lattice
(the same table the scan gate enforces) before labeling it on-grid; a waypoint asserted on-grid
without a lattice lookup is the miss. (Guard today: the scan gate refuses off-grid at launch —
the eval targets catching it at COMPOSITION, before the physicist reads a false claim.)
