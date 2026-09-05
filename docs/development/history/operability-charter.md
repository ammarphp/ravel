# OPERABILITY CHARTER — make the workflow cheap-model-executable, routable, and durable

> **This file IS the prompt.** To execute it, open a FRESH session (strongest available model —
> Claude Fable 5 / GPT-5.5 extra-high; execution guidance in §9) with workspace = this repo and say:
> **"Development session: execute docs/development/history/operability-charter.md end-to-end."**
> Written 2026-07-04 by the Fable-5 session that built most of this pipeline; it encodes that
> session's context so the executor does not re-derive or duplicate what exists.
>
> **Changelog** — v1.1 (2026-07-06): gap-hunt hardening. Added the GATE MAP (§4b), the
> COMPACTION/MULTI-SESSION rule (§4c), the MEMORY-DOES-NOT-SHIP warning (§4d), the concrete
> per-skill staleness audit (§4.3), the cheap-model eval-subject rule (P4), hunt-sourced P1
> stale-artifact targets, and the execution-guidance block (§9). Companion files created:
> `docs/development/change-registry.md` (the dated fix registry, seeded) and
> `docs/reference/failure-modes.md` (real incidents → guards; the Tier-B attack list).

## 0. Mission (why this charter exists)
The physics pipeline works and is validated (see §2). The remaining product risk is the **agent
control layer**: today it assumes a strong model reading prose. Real users are CERN/ATLAS/CMS
physicists on **cheaper models** (Sonnet/Haiku, low-effort tiers) who will supervise judgment calls
themselves. Every expensive-model insight must therefore become a **skill, script, schema, test, or
contract line** — anything living only in prose or chat memory is lost. Compute budget is finite
(>$1000 spent); nothing here launches heavy MC.

## 1. Vocabulary (use these meanings consistently)
- **Pipeline** — the physics toolchain itself: MadGraph→Pythia8→(Rivet|SimpleAnalysis)→viz→pyhf.
- **Workflow** — the agent-facing procedure that drives the pipeline: `docs/workflow/README.md` →
  `steps/01…09` → `checklists/`. The workflow is the product.
- **Harness** — the *executable* control layer: scripts/validators/schemas that force correctness
  instead of trusting prose (`trial-runs/_infrastructure/*.py`, `benchmarks/`, `audit.py`).
- **Skill** — a self-contained reusable procedure in `.claude/skills/<name>/SKILL.md` (Claude Code)
  / `.agents/skills/<name>/SKILL.md` (Codex): YAML frontmatter whose `description:` is the TRIGGER
  (platforms auto-suggest skills by matching it), body = the procedure, optional helper files.
- **Scaffolding** — everything above plus routing surfaces (`CLAUDE.md`, `AGENTS.md`,
  `docs/workflow/start.md`): the structure that lets ANY session land in the right procedure.
- **Subagent** — a bounded side-context for context-heavy work (survey, verification) returning a
  structured summary; never the keeper of durable knowledge.

## 2. Ground truth — what EXISTS (verified; do NOT rebuild these)
- **Routing**: `CLAUDE.md` (two-session fork at top), `AGENTS.md` (Codex mirror), `docs/workflow/start.md`
  (physicist entrypoint), check-in system `docs/workflow/checklists/check-ins.md` (plan check-in w/ figure
  gallery + early-verification waypoint + 3-response-mode footer; deviation check-ins + DEVIATIONS.md;
  results deck; caption + WHY rules).
- **Figure contract**: `figure_target.py` (declare/resolve/attach/show/compose + axes-as-facts),
  `fetch_figures.py --figure` (tex-map→pdf-page→textual), `hepdata_fetch.py` (`figure_index`,
  `--tables`), `figure_manifest.py` (archetype recipes + hints).
- **Scan layer**: `scan_orchestrator.py` (plan/launch[--backend native|container]/status/assemble
  [--nlo-renorm]/rebase), `scan_contour.py` (line/grid/fig3 layouts, `--limit-kind`, no-interpolation
  reference rule), `prepare_native_slepton.py`, `run-pipeline-native.sh` (VM-free native chain —
  bit-for-bit SimpleAnalysis vs container; full point ≈30–50 min, ≤4 parallel).
- **Verification**: step `09-verify.md` + `checklists/verification-panel.md` (mechanical tier +
  physics adversary) + `verify_pack.py`; `result_pack.py` (result.json/figures.json);
  `benchmarks/run_benchmark.py --fast|--full` (locked gate); `scripts/audit.py`.
- **Six skills exist** (`.claude/skills/`): run-stage, certify, new-analysis, directory-keeper,
  embed-and-commit, evaluate-suggestion. As of this charter they EXPORT to the public repo.
- **Evidence** (dev-only): two docx reviews (`HEP Workflow Codex Audit`, `Architectural
  Brainstorming` in the workspace root), two generality trials (CMS A→BC dijet; ATLAS model-agnostic
  AD) with 12+11 recorded gaps, `framework/OPTION-C-DESIGN.md` (no-routine path grounded in
  Collider-Bench: paper `../2605.13950v1.pdf`, repo github.com/dfaroughy/Collider-Bench),
  `docs/development/history/mission-and-plan.md`, `docs/reference/limitations.md`, `docs/development/status.md`.

## 3. Observed failures driving this charter (real, from live physicist trials)
The full incident list — what happened, how it was caught, where the guard now lives — is
**`docs/reference/failure-modes.md`**; the step-9 Tier-B verification adversary uses it as an attack
list. The headline failures:
F1. **Fresh-session routing failed in practice**: 4 real sessions did not route on "Initiate…" and
    burned tokens surveying the sprawl. (Partial fix already landed: the two-session fork at the top
    of CLAUDE.md/AGENTS.md. NOT yet verified on cheap models; no skill-level trigger exists.)
F2. **Skills were never exported** (export policy listed `.claude/` dev-only — flipped as of this
    charter) and the six existing skills cover a fraction of the workflow (nothing for intake,
    routing, scan, figure-contract, verification, cost preflight, postmortem).
F3. **Model-tier gap**: `[Opus]` step tags exist but no policy says what a WEAK model must do at
    those points (execute? escalate to human? refuse?).
F4. **Steps 1–7 read as single-point procedure**; the 70+-point scan requirement (step 8) was
    historically missed by fresh sessions — routing/emphasis, partially fixed, must be eval-tested.
F5. **No task contract / cost preflight**: nothing forces "classify the request → name missing
    inputs → estimate cost → block heavy compute pending approval" as a MACHINE artifact.
F6. Known pipeline bugs (fix, they gate result quality): pyhf µ-floor at 1.0 on hyper-excluded
    points (the "dark red cells"); `prepare_native_slepton.py` drops `[madgraph.run.options]`
    (ptj1min → phase-space drift). Both diagnosed in `trial-runs/sleptonscan_fig3_SCAN/RESULT.md`.

## 4. Target architecture (five surfaces; map, don't churn)
1. **Root routing**: `CLAUDE.md` + `AGENTS.md` — short, identical invariants, the session fork.
   A consistency CHECK (script) keeps them agreeing.
2. **Product contract**: NEW `docs/reference/scope.md` (recommended by the Codex-audit docx; still
   missing): supported task modes, detector modes (particle-level | rivet-smearing |
   simpleanalysis-delphes-native | container), stat modes (published-pyhf | best-SR-counting |
   simplified | stability-only | blocked-shape-fit), fidelity labels, refusal cases, result
   semantics (95% CLs, never discovery).
3. **Skills** (the judgment, operationalized): mirrored `.claude/skills/` ↔ `.agents/skills/`
   (single source + a sync script; do NOT hand-maintain two copies). Author with the
   `superpowers:writing-skills` discipline where available. Minimum set (each: trigger-rich
   description, inputs/outputs, stop conditions, escalation criteria, pointers to harness scripts):
   - `physicist-intake` (ANY natural-language HEP request → task contract + CHECK-IN 1; blocks compute)
   - `route-analysis` (contract → mode/detector/stat routing; names missing inputs)
   - `run-scan` (step-8 outer loop incl. reuse rule, native backend, disk budget)
   - `figure-contract` (declare→extract→echo→counterpart→compose)
   - `verification-panel` (step 9, two tiers, verdict semantics)
   - `cost-preflight` (events×points×walltime×disk estimate; dry-run/smoke/full ladder)
   - `postmortem-capture` (gaps→GAPS section→chips/registry; feeds §5 evals)
   - **EXISTING-SKILLS AUDIT (concrete staleness, verified 2026-07-06 — fix these, don't just
     "refresh"):** re-verify EVERY existing skill against steps 01–09, the figure contract, the
     check-in system, and the native backend before it ships. Known defects per skill:
     · `new-analysis` — says "follow docs/workflow/README.md (steps 3→7)", omitting step 8 (scan) and
       step 9 (mandatory verification panel) — it REINFORCES failure F4; fires at the step-2
       boundary where CHECK-IN 1 must be composed but never mentions check-ins; its skeleton
       creates no `DEVIATIONS.md` ledger stub though `checklists/check-ins.md` makes the ledger
       mandatory; and its example run-dir name is a dated dev trial-run (a distribution leak once
       skills export — replace with a placeholder).
     · `run-stage` — covers Rivet-only analyze: no SimpleAnalysis/Delphes/NATIVE-backend path
       though native is the step-8 default; tells the agent to hand-read the first LHE event
       instead of running the mandated `src/ravel/validation/lhe_check.py` guard; cites a
       bare "R5" rigor tag defined only in dev-only archives (dangling once skills export).
     · `certify` — routes per-run certification to `validate_cutflow.py`, now classified one-time
       per routine; never mentions `certify_acceptance.py` / the step-3.5 detector-fidelity gate
       or the step-9 `verify_pack.py` panel.
     · `embed-and-commit` — current on the benchmark gate but lacks the CHANGES-REGISTRY entry
       step that §7 makes binding (it is THE closing checklist — the registry is unenforced
       without this edit).
     · `directory-keeper`, `evaluate-suggestion` — materially current; re-verify triggers only.
4. **Harness** (weak models are FORCED through scripts, not trusted with prose): keep tools where
   they live (`trial-runs/_infrastructure/` — do NOT mass-move; 899+ references) but ADD:
   - `check_agent_surface.py` — CLAUDE↔AGENTS agreement; every referenced skill/file exists; skill
     frontmatter valid; DIRECTORY.md paths real; readiness numbers agree (README/STATUS/AUDIT);
     no trial-run leakage in docs/workflow/.
   - `route_prompt.py` — prompt → `task_contract.json` (schema below) — deterministic first pass,
     [Opus]/human confirms; refuses heavy compute unapproved.
   - `validate_task_contract.py`, `cost_preflight.py` (walltime/disk model from the measured
     30–50 min/point), plus wire the existing `verify_pack.py` into step 9 explicitly.
   - `task_contract.json` schema: prompt, task_mode (survey|reproduce|reinterpret|projection|scan|
     summary_plot|anomaly_search|no_routine|unsupported), model/process/analysis/figure targets,
     detector_mode, stat_mode, required_user_inputs, assumptions, compute_plan(dry|smoke|full|scan),
     cost_estimate, approval_required=true.
5. **Records/evidence**: unchanged policy (trial-runs dev-only, quarantine never delete), plus the
   **dated fix-registry** (`docs/development/change-registry.md`, ADR-style: ID, date, what, why, where
   embedded, status — the user asked for exactly this). **EXISTS as of v1.1**, seeded with the open
   F6 fixes (CR-001 µ-floor, CR-002 run.options, CR-003 export push-lease) + the deferred physics
   queue (CR-004 residual-closure rescan, CR-005 native generality, CR-006 clean-room self-drive);
   P2 extends it, `embed-and-commit` enforces it.

## 4b. GATE MAP — per-stage gates (binding)
| Stage boundary | Gate | Where |
|---|---|---|
| generation → shower | `lhe_check.py` (masses/MODSEL/BR rows/weights/merged-flag) | `src/ravel/validation/lhe_check.py`, mandatory pre-shower |
| detector (step 3.5) | detector-fidelity gate: `verify_smearing.py` (Rivet) / Delphes-card match | `checklists/detector-fidelity.md` |
| acceptance | `certify_acceptance.py` (per-run SA/Delphes) / `validate_cutflow.py` (one-time per routine) | step 3.5 / `framework/validation/` |
| artifacts (step 9, tier A) | `verify_pack.py` (numbers trace, figures exist, coverage, DEVIATIONS present) | `src/ravel/validation/verify_pack.py` |
| regression | `run_benchmark.py --fast` (per session) / `--full` (any physics change) | `benchmarks/` |
| delivery | the step-9 verification panel, both tiers (Tier B attacks via `FAILURE-CATALOGUE.md`) | `checklists/verification-panel.md` |

**Binding rule: no stage output feeds the next stage without its gate; a skipped gate is a
`DEVIATIONS.md` entry** (what was skipped, why, what risk it leaves open). Every new skill's stop
conditions NAME its gate script so small errors are caught at step boundaries instead of
compounding to step 9.

## 4c. COMPACTION / MULTI-SESSION rule (durable run state)
Physicist scans are multi-hour by this repo's own numbers (~30–50 min/point → a grid is hours to
overnight), so mid-run context compaction and session restarts are NORMAL operation, not incidents.
Therefore, binding:
- **Any run expected to outlive a session maintains a checkpoint file + a `RESUME.md`** in the run
  dir — updated at each check-in and each launch: current state, what is running (pids/logs), the
  exact resume commands, and what remains. The proven pattern is the 52-point fig3 scan's
  pause/resume (dev repo: `trial-runs/sleptonscan_fig3_SCAN/RESUME.md`; `scan_orchestrator.py
  status` is already resumable — the rule just points at it).
- **After compaction or a restart, re-anchor from files, never from an auto-summary**: re-read
  `docs/workflow/start.md` (physicist) or the dev read order → the run's `task_contract.json` →
  `RESUME.md` before acting. **PLAN-OF-RECORD-style files are authority over auto-summaries**
  (they carry dated supersession blocks; an auto-summary carries whatever survived compaction).
- P2 wires this into the physicist-intake and run-scan skills' stop conditions; P4 may add an
  interrupt-mid-scan recovery eval.

## 4d. MEMORY DOES NOT SHIP (warning)
Session auto-memory is operator-local: **nothing a researcher needs may live only in memory** —
it must land in repo files (docs/workflow/, framework/, skills, or the registry). The gap hunts found
load-bearing facts that existed ONLY in memory: the arXiv:2408.00049 generality-audit precedent
(P4 prompt 4's paper — verdict BLOCKED(statistical-paradigm), the no-HEPData-workspace correction),
the native-port design rationale (Delphes2SA writes el/mu_id=0x7FFFFFFF so every lepton-ID cut in
the SA routine is a deliberate no-op — a maintainer would "fix in" ID cuts and silently change
yields), the publication remote + gh identity, the deferred-physics queue (now CR-004), and the
archetype-census numbers. P1 audits for remaining memory-only facts; P2 lands each in its
durable home (`interrogations/generality.md`, `native_simpleanalysis.py` docstring +
`reference/native-pipeline.md`, a dev-only ops note, docs/reference/scope.md respectively).

## 5. Execution phases (audit → build → prove; NO heavy MC anywhere)
- **P0 freeze**: git status clean-point; run `audit.py --check` (read-only by default — no
  restore needed; `--write` only to deliberately refresh `AUDIT.md`), `run_benchmark.py --fast`
  (restore results.json after — known clobber), inventory tracked files. Produce findings BEFORE
  editing.
- **P1 audit** (deliverable `docs/development/history/operability-audit.md`, severity-ranked): the §3 failures +
  stale artifacts (STATUS/KNOWN-LIMITATIONS currency; contradictions between steps/checklists;
  dead paths; gitignore reassessment — tracked junk, missing ignores, oversized files), context-cost
  audit of every doc a physicist session must read (token budget per file; what moves to skills/
  scripts), and the 23 recorded trial gaps mapped to owners.
  **Concrete P1 targets (from the 2026-07-06 gap hunts; verify each is still live, then fix):**
  - `docs/development/history/mission-and-plan.md` **currency** — a dated supersession STATUS block landed
    2026-07-06; keep the pattern (append dated blocks, never silently rewrite) and check the
    remaining sections still match the tree.
  - **Export-tree dangling refs** (the shipped dist references files that do not ship):
    CLAUDE.md's dev route (ORCHESTRATION.md), `stages/…` conda/MadGraph paths and
    `.claude/agents/` refs; README/DIRECTORY/STATUS rows pointing at unshipped `shared/`,
    `stages/`, `SESSIONS/`, `framework/overnight*`, `pedagogical/design-review/`; fix via a
    dead-reference existence check over the staged tree in `check_agent_surface.py` + either ship
    `shared/` per DISTRIBUTION.md or produce dist-variant routing docs at export time.
  - `benchmarks/cases.json` inputs point at dev run dirs absent from the clone —
    BENCHMARK.md's fresh-clone recipe 404s; ship the minimal cert-input subset or present the gate
    as recorded evidence, and add a dist smoke-run to the export script.
  - `docs/development/distribution.md` policy vs `export_distribution.sh` drift: `shared/` listed
    publishable but never copied; the `.claude/` skills+rules export decision taken but not
    recorded there; the framework whitelist vs the new P2 files (PRODUCT-CONTRACT, ROUTING-EVALS,
    AUDIT-OPERABILITY — CHANGES-REGISTRY + FAILURE-CATALOGUE already added v1.1); hygiene-grep
    scope excludes `.claude/` though skills now ship (a dated dev-run example sits in
    `new-analysis` today).
  - CLAUDE.md ↔ AGENTS.md **dev read-list disagreement** (ORCHESTRATION-first vs DIRECTORY-first)
    though AGENTS.md pledges they never disagree — pick one canonical dist-safe order; this is the
    `check_agent_surface.py` agreement assertion.
  - `.gitignore` vs curation policy: the global `*.log` rule swallows trial-run logs the curation
    comment says to keep; the 52+6 scan point dirs' curated outputs (`exclusion.json`/txt/config)
    are entirely untracked; inverted tracking in the two generality trials (≈75 MB regenerable
    feature CSVs tracked while the `build/*.cc|*.py` analysis sources are ignored); ~66 untracked
    paths of status noise.
  - Stale instrument runs + state docs: `docs/development/audit.md` (generated pre-09-verify, "8 step
    files"); `docs/development/status.md` session-log entries missing for the last four landmark commits,
    pre-charter open items, the unresolved +3j parting job; residual step-count "8 steps" spots
    (STATUS, `docs/workflow/orchestration.md`, AUDIT.md R8) — README fixed v1.1; make step-count
    agreement a `check_agent_surface.py` mechanical assertion.
  - `.claude/skills` staleness — the concrete per-skill findings now listed in §4.3.
- **P2 build**: the skills set + mirror sync, the harness scripts, docs/reference/scope.md,
  CHANGES-REGISTRY.md, the two bug fixes (µ-floor; run.options prep). Small, reviewable commits.
- **P3 reconcile**: docs↔skills↔harness cross-references; export policy includes the new surfaces;
  `check_agent_surface.py` green; benchmark green.
- **P4 prove — ROUTING EVALS** (`docs/research/routing-evaluation.md`): the seven REAL physicist prompts
  below + three adversarial ones (ambiguous, unsupported, missing-inputs). For each: expected
  task_mode, detector/stat mode, missing inputs, and the check: a FRESH **cheap-model** session
  (Sonnet-tier) given only the repo + the prompt must produce a correct task contract + CHECK-IN 1
  and BLOCK compute — zero operator help. Fix docs/skills until ≥6/7 pass; record verdicts.
  **Eval-subject rule (binding): the test subjects run as CHEAP-MODEL subagents/sessions with
  explicit sonnet/haiku model overrides — NEVER the orchestrator model.** The (strong) orchestrator
  only prepares prompts and grades transcripts; an orchestrator role-playing the cheap model in its
  own context invalidates the eval. Record the subject model id + transcript per prompt.
  1. "Consider a model (say HVT) with a Z′→WW. Construct a summary plot of ATLAS+CMS searches
     sensitive to Z′→WW for m(Z′) < 500 GeV."
  2. "Assuming toponium is a new resonance (e.g. heavy Higgs), produce a summary plot assessing
     limits on this signal from other LHC analyses."
  3. "Expand ATLAS non-resonant semi-visible jets (Run 2) to expected limits across a wide range of
     dark pion/dark rho masses; assess improvements from a hypothetical dedicated SVJ tagger."
  4. "Reproduce the dijet+photon analysis in arXiv:2408.00049; roughly match Fig. 5, then produce
     results with increasingly large Z′ widths up to 0.3 mZ′."
  5. "Reproduce a simplified particle-level version of CMS A→BC (arXiv:2412.03747); match the
     inclusive/2-prong/3-prong/AD sensitivity comparisons in Figs. 5–6 at 3 and 5 TeV." (done once —
     the eval is whether a CHEAP session routes it)
  6. "I'm interested in model-agnostic searches at ATLAS … strange event topologies in low-energy
     regions." (done once — same)
  7. "Construct an expected Run-3 (400 fb⁻¹) exclusion contour for the ATLAS displaced-track
     analysis (arXiv:2401.14046 + HEPData), overlaid on Fig. 3; also reinterpret Fig. 3 in the
     µ–M₂ plane (higgsino, M₁=M₂, tanβ=50); captions + procedure."
- **P5 report**: what changed / didn't, tests, remaining risks; update STATUS.md with grounded
  numbers only; export+push (`export_distribution.sh … --push`).

## 6. Model-tier policy (encode into every [Opus] tag)
Replace bare `[Opus]` with `[judgment]` + an explicit weak-model behavior, one of:
`escalate-to-physicist` (default: present options + recommendation, wait) · `script-assisted`
(run the named harness script, follow its output) · `proceed-with-flag` (safe default exists;
flag in DEVIATIONS.md). A cheap model must never silently take a judgment step.

## 7. Constraints (unchanged, binding)
No physics-output changes without a named defect; no heavy MC; no discovery language; no invented
physics inputs; trial records quarantined not deleted; every number traceable to artifacts; every
change lands in the CHANGES-REGISTRY; benchmark + audit green before the final push.

## 8. Success criterion
A fresh **Sonnet-tier** session, given only this repo and any §5-P4 prompt, routes itself, produces
a valid task contract + CHECK-IN 1 (gallery, waypoint, flags, cost estimate), blocks compute pending
approval, and knows exactly when to escalate — with zero operator coaching.

## 9. Execution guidance (how to run this charter)
- **Model**: the strongest available (Claude **Fable 5**; Codex-side GPT-5.5 extra-high). Cheap
  models are the SUBJECTS of P4, never the executor.
- **Effort**: HIGH throughout; **max** for the P1 audit and the P4 evals (they are the
  judgment-dense phases).
- **Ultracode / multi-agent**: **ON for P1 and P4** — parallel auditors over disjoint doc/tooling
  surfaces in P1; parallel cheap-model eval subjects in P4 (one subagent per prompt, orchestrator
  grades). **OFF for P2 and P3** — skills/harness/contract authoring is sequential, cross-referenced
  work; parallel agents there churn each other's cross-references and waste tokens.
- **Session shape**: P0→P1 in one session; P2 in small reviewable commits (registry entry each);
  P3 gate-green before P4; P5 last. If a session ends mid-phase, the §4c rule applies (checkpoint +
  re-anchor from files).
