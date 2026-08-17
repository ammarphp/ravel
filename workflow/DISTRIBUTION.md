# What is distributed, and what is not

The deliverable is a **journal paper + a public GitHub repository**. Most of this repository is
**development scaffolding for our own work** and must not ship. This file is the authoritative
delineation: every top-level artifact is classified **PUBLISHABLE**, **DEVELOPMENT-ONLY** (a task
artifact — excluded from the public push), or **SANITIZE-FIRST** (publishable only after
machine-specific detail is removed). `trial-runs/_infrastructure/export_distribution.sh`
implements EXACTLY this table (any drift between the two is a defect); the staged tree is
verified by `check_agent_surface.py --stage <dir>` before any push (dev-side process notes:
`SESSIONS/session-4-distribution.md` + `framework/OPS-PUBLISHING.md`, both dev-only).

## PUBLISHABLE (ships in the public repo)
| Path | Why |
|---|---|
| `workflow/` | the agent-facing method (steps, checklists, INITIATE, the two routine paths) — the product |
| `trial-runs/_infrastructure/` | the harness the workflow invokes (routing, gates, scan layer, figure contract) |
| `pedagogical/` (minus `design-review/`) | the explanatory guide for a human (exempt from the trial-run rule) |
| `framework/` **— selected rows only** (table below) | the quality bar + protocol + audit + registries |
| `PRODUCT-CONTRACT.md` | the binding scope/refusal/label taxonomy (added 2026-07-06) |
| `README.md`, `DIRECTORY.md`, `AGENTS.md`, `shared/` | orientation + conventions (shared/ ships as of 2026-07-06 — previously listed but never copied) |
| `stages/01-event-generation/{README.md,scripts/,changes/,docs/}` | the environment bootstrap + change logs + pedagogical docs (added 2026-07-06 — shipped step 01 previously pointed at an unshipped tree); `build/` stays local; `agent/` (the superseded per-stage scaffolding) stays dev-only |
| `.claude/{skills,rules,agents}` + `.agents/skills` | the agent scaffolding IS the product (skills/rules export decision taken 2026-07-06, recorded here; `.agents` is the sync_skills.py mirror) |
| `CITATION.cff`, `LICENSE` | citation + license — the export FAILS LOUD on the placeholder license / `example.invalid` URL unless `--allow-placeholder-license` is passed consciously |
| `evidence_manifest.json`, `EVIDENCE.md` | the served-claim → shipped-artifact map (PRODUCT-CONTRACT sec 7 / CR-030, CR-042) + its rendered table; `framework/check_evidence.py --check --root <stage>` re-verifies both against the actual staged files and aborts the export if any `shipped:true` artifact is missing or sha-mismatched. Their generator/checker (`framework/build_evidence.py`, `framework/check_evidence.py`) stay dev-only — the export gate invokes `check_evidence.py` directly from the dev tree, it does not need to ship |
| a curated **evidence subset** — explicit files, NOT whole run dirs — from 3 `trial-runs/` run dirs: `sleptonscan_fig3_SCAN/{scan.json,scan_manifest.json,RESULT.md,verification.json,inputs/*.json,plots/*.png\|pdf}`; `2026-06-16_slepton_200-150_native/output/{exclusion.json,EwkCompressed2018.txt,*_patch.json}`; `2026-07-06_SURVEY_hvt-zprime-ww-lowmass/{outputs/survey.json,outputs/summary_audit.json,inputs/basis_manifest.json,VERIFICATION-LADDER.md,plots/hvt_zprime_ww_summary.*,plots/qa_*.png}` | the raw artifacts backing the served/served-with-refusal claims in `evidence_manifest.json` — added Task 6.2 so a public reader can actually reach the evidence a served claim cites, not just the doc that states it (the rest of each run dir stays dev-only per the table below) |

**`framework/` row-by-row** (ship the protocol + instruments + registries, not the dev records):
| Under `framework/` | Ships? |
|---|---|
| `STATUS.md`, `AUDIT.md`, `audit.py`, `KNOWN-LIMITATIONS.md`, `ENVIRONMENT.md`, `benchmark/` | **yes** — the bar, the gate (as recorded evidence in the dist — see `benchmark/BENCHMARK.md` §Fresh clone), the honest limitations |
| `PLAN-OF-RECORD.md`, `CHANGES-REGISTRY.md`, `FAILURE-CATALOGUE.md` | **yes** — authority + the fix registry + the incident→guard catalogue (the step-9 Tier-B attack list requires it) |
| `AUDIT-OPERABILITY.md`, `ROUTING-EVALS.md` | **yes** — the operability findings register + the routing-eval record |
| `validation/` + `crosscheck/` + `interrogations/` | yes (protocol docs + the generality census/precedents) |
| `CAPABILITY-ROADMAP.md`, `OPERABILITY-CHARTER.md`, `capability-matrix.json`, `LIMITATIONS-TRIAGE.md`, `DECISION-SHAPE-FIT.md` | **yes** — reconciled 2026-07-08 (Task 6.2; the script always shipped these three .md files, this table previously said the opposite): the capability-layer state (roadmap + charter + matrix + triage) and the shape-fit decision record — `capability-matrix.json` is also an `evidence_manifest.json` claim source, so it must ship for the evidence pack to be publicly checkable |
| `OPTION-C-DESIGN.md`, `TRIAL-*.md` | **no — dev-only** (build plans + trial protocols; their durable content is embedded in the workflow/contract) |
| `OPS-PUBLISHING.md` | **no — dev-only** (publication remote + identity) |
| `overnight/`, `overnight-s3/`, `overnight-roadmap/` | **no — dev-only** (dev-sweep records) |
| `build_evidence.py`, `check_evidence.py`, `tests/`, `gen_status.py` | **no — dev-only** (the evidence-pack tooling, test suite, and README-marker generator; their *output* — `evidence_manifest.json`/`EVIDENCE.md` — ships, they don't) |

## DEVELOPMENT-ONLY (task artifacts — exclude from the public push)
| Path | Why |
|---|---|
| `trial-runs/2026-*/`, `trial-runs/sleptonscan_*/` (minus the curated evidence subset in the PUBLISHABLE table) | our development runs — records, not reference examples. A small curated subset of 3 of these run dirs ships as explicit evidence files (not the run dir itself) to back served claims per PRODUCT-CONTRACT sec 7 — see the PUBLISHABLE table above and `evidence_manifest.json` |
| `ORCHESTRATION.md`, `SESSIONS/` | the multi-session **build plan** + session prompts — not product |
| `framework/` dev rows (table above) | build plans, trial protocols, ops notes, sweep records |
| `stages/01-event-generation/build/` | the local toolchain (gitignored anyway) |
| `.claude/hooks/`, `.claude/settings.json` | operator/machine-specific (absolute card paths) |
| `~/.claude/plans/…`, the auto-memory | outside the repo; never shipped |

## SANITIZE-FIRST (publishable only after machine-specific detail is stripped)
| Path | What to strip before publishing |
|---|---|
| `CLAUDE.md` | the absolute `/Users/…` paths → `$DSRLAB_ROOT` placeholders (the export script does this + a belt-and-braces pass over every staged text file, then greps the stage for leaks) |
| `CITATION.cff`, `LICENSE` | the placeholder license + `example.invalid` URL (fail-loud guard; finalize at publication) |

## The rule for the agent-facing distributable
The `workflow/` docs and `README`/`SESSION-MANUAL`/`CLAUDE.md`/skills describe capability
**generically** — by final state and method ("a 0-lepton jets+MET search", "a routine with a
published likelihood"), never by our trial runs. **Worked numbers (µ₉₅, specific masses, A×ε
residuals, run-local paths) belong in the paper and the pedagogical guide, not in the agent
instructions** — including `workflow/checklists/`, `workflow/reference/`, and
`.claude/skills/` (which ship).

**Enforced checks** (the export script runs all three; `check_agent_surface.py` runs the first
continuously in the dev repo):
```
# dev-run-token leak scan — agent-facing surfaces INCLUDING the shipped skills/rules:
grep -rInE 'gluino-pair|squark-pair|slepton_200|2026-[0-9]{2}-[0-9]{2}_|C1N2-WZ|µ₉₅ *= *[0-9]|mu95 *= *[0-9]' \
  workflow/ README.md CLAUDE.md .claude/ .agents/ shared/ \
  --exclude=DISTRIBUTION.md    # must return nothing
# staged-tree dead-reference scan (every ref in the stage resolves IN the stage):
python3 trial-runs/_infrastructure/check_agent_surface.py --stage <staging-dir>
# evidence gate -- every served claim's `shipped:true` artifact must be present + sha256-matching
# in the stage (PRODUCT-CONTRACT sec 7 / CR-030); the export aborts (no push) if not:
python3 framework/check_evidence.py --check --root <staging-dir>
```
These are **necessary but not sufficient** — they catch tokens, not paraphrase. Worked numbers
can leak by analysis name + value; read the checklists/reference/skills by eye too. The
`pedagogical/` guide is exempt.
