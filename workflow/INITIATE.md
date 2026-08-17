# INITIATE — the physicist session entrypoint

You are a physicist. You do not need to know how this repository works. Start a session with one
message; everything after that arrives as standardized check-ins written in plain physics language
(`checklists/check-ins.md`).

## How to start (accepted prompt forms)
Begin your message with **"Initiate:"** followed by your request, at any of three specificity levels:

| level | example form | what the pipeline does with it |
|---|---|---|
| **specific figure** | "Initiate: reproduce Figure N of arXiv:XXXX.XXXXX" | declares that figure as the target directly |
| **analysis + model** | "Initiate: run <analysis code / paper> on <model / spectrum>" | resolves the routine, proposes the target figure(s) |
| **interest-level** | "Initiate: what does <this class of search> say about <a scenario I care about>?" | surveys candidate analyses and proposes analyses + figures |

Attach anything you have (parameter cards, masses, a preferred figure). Anything missing is proposed
back to you as a numbered flag, never silently assumed.

## What happens next (the promised sequence)
1. **Survey** — your request is resolved to an analysis routine + model + candidate published
   figures. No event generation happens here.
2. **CHECK-IN 1 "PLAN"** — you receive: a plain-language restatement of your request; a GALLERY of
   candidate published figures (pictures + one-line captions) to pick the target from; a proposed
   EARLY-VERIFICATION WAYPOINT (a cheap partial element — e.g. a simulated-background-only curve —
   that you will see side-by-side with the published one before heavy compute); the plan (samples,
   observables, statistics, budget); and NUMBERED FLAGS for every assumption, each with its why and
   the alternatives considered.
3. **Your response — three equal modes**: answer the flags, ask clarifying questions, or propose
   alterations beyond the flags. The plan is a proposal, not a fait accompli.
4. **The run** — generation → analysis → statistics. Any mid-run change of course reaches you
   IMMEDIATELY as its own deviation check-in (and is logged in the run's `DEVIATIONS.md` ledger),
   never batched to the end.
5. **CHECK-IN 2 "EARLY VERIFICATION"** — the waypoint side-by-side; you say **go** or **adjust**
   before the expensive part starts.
6. **Verification panel** — before you see any result, an adversarial panel (`steps/09-verify.md`)
   traces every number to its machine artifact and independently attacks the physics conclusions.
   Its verdict and findings are appended to what you receive, verbatim — never silently fixed.
7. **FINAL CHECK-IN "RESULTS DECK"** — headline figure(s) with clear captions, a key-numbers table
   with per-number file provenance, the validation verdict, limitations, the deviations summary, the
   panel verdict, and next steps.

## Timing expectations
- **CHECK-IN 1 arrives before ANY heavy compute** — no event-generation budget is spent before you
  approve the plan. The survey behind it takes minutes.
- CHECK-IN 2 arrives after a cheap, small-statistics pass — before the bulk of compute.
- A single model point runs in minutes to about an hour; a full mass-plane scan is hours (points run
  in parallel). The results deck states exactly what grid coverage was achieved.
- Results are quoted as **95% CL exclusion limits (CLs)** — this tool never claims a discovery.

## Where things land
Every run lives under `trial-runs/<label>/`: `RESULT.md` (the narrative), `result.json` /
`scan.json` (the machine-checkable numbers — the source of truth for every number quoted to you),
`plots/` (all figures, PNG + PDF), `DEVIATIONS.md` (the mid-run change ledger), and `inputs/` (cards
+ the declared figure contract).

You never need to open these files — the check-ins carry everything — but they are yours to audit.

---

## AGENT EXECUTING THIS REQUEST — your procedure (the physicist reads the sections above; YOU do this)
> **Auto-injected reminder (G1):** on a physics-looking prompt a `UserPromptSubmit` hook
> (`.claude/hooks/userpromptsubmit-router.sh`) runs the deterministic `route_prompt.py` and injects a
> one-line ROUTING reminder pointing at this procedure, and records `--kind route` to the run ledger
> (sets `run_state.routed`, D-3; `physicist-intake` re-asserts it once the run scaffold exists). The
> hook is non-blocking (the hard blocks live in the Skill/pre-generate guards) — if it does not fire
> (skills or hooks unavailable), THIS procedure is the FALLBACK: follow the steps below regardless.
> **PreToolUse Skill guard (G22/N1):** a `PreToolUse`-on-`Skill` hook
> (`.claude/hooks/pretooluse-skill.sh`) HARD-BLOCKS (exit 2) any contract-presupposing skill
> (`new-analysis`/`run-scan`/`run-stage`/`certify`/`route-analysis`/`verification-panel`) until the
> ACTIVE run carries a `task_contract.json` — so the `physicist-intake` skill must run FIRST. Its
> contract check is **session/cwd-scoped to the active run** (resolved from the tool-call `cwd` when it
> sits inside a `trial-runs/<rundir>` tree, else from `session_id` via that run's `run_state.json`) —
> NOT a repo-wide glob, so it still fires in a mature repo full of old
> `trial-runs/*/inputs/task_contract.json` (a glob would leave G22 permanently dead). No resolvable
> active run → blocked (conservative default). FALLBACK when the hook does not fire: this routing rule —
> fire `physicist-intake` first regardless.
1. Fire the **`physicist-intake` skill** (`.claude/skills/physicist-intake/SKILL.md` if your
   platform does not auto-load skills). It runs, in order:
   `route_prompt.py` → `task_contract.json` (validated) · the no-generation survey
   (`routine_fetch.py`, `hepdata_fetch.py`, `fetch_figures.py --map-captions`) ·
   `cost_preflight.py` (the budget line) · the run scaffold (`new-analysis` skill) ·
   **CHECK-IN 1 composed per `checklists/check-ins.md`** · the **compute block**.
2. The procedure behind the check-ins is `WORKFLOW.md` steps 2→9 (in THIS directory):
   step 8 (scan → contour, `run-scan` skill) is the deliverable for any
   reproduction/reinterpretation; step 9 (verification panel, `verification-panel` skill) is
   MANDATORY before anything is delivered.
3. **NO heavy compute before the CHECK-IN 1 go-ahead** — the smoke rung (≤1k events) is the
   ceiling until then. After a restart or context compaction, re-anchor from files
   (`task_contract.json` + the run's `RESUME.md`), never from an auto-summary.

> **Mechanized (A3/N8):** on a physics prompt, subagent fan-out (Agent/Task) is BLOCKED by a PreToolUse guard until `task_contract.json` exists for this session — the pre-routing 8-agent-survey failure (trial QA.1) cannot recur. Fire `physicist-intake` first; fan-out unblocks the moment the contract lands.
