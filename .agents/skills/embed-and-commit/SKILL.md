---
name: embed-and-commit
description: After iterating on any tool/script/process in hep-agentic-pipeline, embed the change in the workflow docs and commit it as a reviewable milestone. Use at the end of every code/process change — the workflow IS the product, so a code change that is not embedded in the workflow docs is not done.
when_to_use: after changing any trial-runs/_infrastructure tool, a workflow step/checklist, or a process — before reporting the change complete
allowed-tools: Bash, Read, Edit, Grep
---
# Skill — embed every change in the workflow, register it, then commit

The deliverable of this project is the **workflow** (the agent-facing instructions), not the artifacts a
run happens to produce. So a code or process change is only *done* when it is **embedded in the workflow
docs**, **registered**, and **committed**. This skill is the closing checklist for any iteration. Run it
before you say a change is finished.

## 1. Embed (the workflow is the product)
For each tool/flag/behaviour you changed or added, confirm it is referenced where an agent would look:
- New/changed `trial-runs/_infrastructure/*.py` → documented in the relevant `workflow/steps/NN-*.md`
  and/or `workflow/checklists/*.md` (the invocation, the flags, when to use it).
- New flag on an existing tool (e.g. `--sr-reader`, `--plane dm`, `--logy`) → the doc that invokes that
  tool must mention the flag and *when* to use it. A new flag with no doc reference is the classic gap.
- New workflow step/gate → wired into `workflow/WORKFLOW.md` (the step table) and cross-referenced from
  the adjacent steps.
- Quick audit: `grep -rIE '<tool-or-flag>' workflow/ .claude/` — **0 hits = unembedded = not done.**
- Update `DIRECTORY.md` for any new file (or run the `directory-keeper` skill).
- **Skill edited?** Re-mirror: `python3 trial-runs/_infrastructure/sync_skills.py` (single source =
  `.claude/skills/`; the surface gate fails on drift).

## 1b. REGISTER (binding — charter §7: every change lands in the registry)
`framework/CHANGES-REGISTRY.md` gets its entry in the SAME commit: a new `CR-NNN` (ID · date ·
what · why · where-embedded · status) for a new fix/feature, or the existing entry's **status
flip** (OPEN → EMBEDDED with the fix + wiring named; or DEFERRED with its trigger). A change
with no registry entry is not done — this checklist is the registry's enforcement point.

## 2. Keep it shippable
- Run the surface gate: `python3 trial-runs/_infrastructure/check_agent_surface.py` — it asserts
  the routing fork, dead refs, skill frontmatter+mirror, DIRECTORY map, readiness/step-count
  agreement, and the hygiene grep in one shot. Fix what it names.
  - The surface gate is now ALSO a git **pre-commit hook** (D16/G20) — install it once per
    clone/worktree with `bash trial-runs/_infrastructure/install_git_hooks.sh`. It writes a
    `pre-commit` into the shared git hooks dir (resolved via `git rev-parse --git-path hooks`,
    the common `.git/hooks`) that runs the read-only `check_agent_surface.py` and propagates its
    exit code, so a commit that leaves the agent surface inconsistent is blocked at commit time,
    not just by this manual step. The installed hook itself is untracked by design (it lives in
    the git common dir, shared across worktrees); the tracked installer makes it reproducible.
- Run the distribution-hygiene grep (`workflow/DISTRIBUTION.md`); it must stay clean (no run-specific
  worked numbers in the agent docs).
- If infra in the benchmark path changed (`pyhf_exclude.py`, `validate_cutflow.py`, `cases.json`), run
  `python3 framework/benchmark/run_benchmark.py --full` and confirm `GATE: OK` (restore the committed
  `results.json` afterward — `--full`/`--fast` overwrite the baseline). A flaky "missing or stale"
  BREACH is a known benchmark mtime race; re-run once to confirm before treating it as real.

## 3. Commit as a reviewable milestone
- One commit per coherent change (don't bundle unrelated edits). Subject = what changed; body = the
  why + the embedding + the verification (gate result, what you ran). End with the project's
  `Co-Authored-By` trailer.
- If on the default branch, branch first.

**Done = embedded + REGISTERED (CR entry/status) + hygiene-clean + (gate green if infra) +
committed.** Not just "the code runs."

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "The code runs — the change is done" | Done is the bold line above. 0 grep hits in `workflow/` = unembedded = not done (the classic new-flag gap). |
| "The docs already cover this tool somewhere" | Catalogue D2: stale/hedged doc lines re-installed a ~9 h/point default. Run the greps; do not recall. |
| "I'll add the registry entry in a follow-up commit" | Charter §7 binds the CR entry into the SAME commit; a deferred entry is how a fix becomes unfindable. |
| "Exit 0 on the push/gate — milestone landed" | CR-003's addendum: a clean-looking push had silently stranded 14 commits (HTTP 400). Verify state (`git log`, the remote ref, the gate's own report), never the exit path. |

## Stop conditions
- Surface gate or hygiene grep red → fix before committing; never commit over a red gate.
- Benchmark BREACH after touching gated infra → re-run once (the known mtime race); a
  REPRODUCED breach blocks the commit until diagnosed — never refresh the baseline to pass.
