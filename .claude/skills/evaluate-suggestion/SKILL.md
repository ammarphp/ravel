---
name: evaluate-suggestion
description: Practically evaluate a co-designer / supervisor suggestion (or one of your own proposals) for the hep-agentic-pipeline before building it — its utility, where it fits in the workflow, how additive it is, its cost/risk, and the strongest form to implement. Use when a design idea is proposed, to decide adopt / adapt / defer / decline with reasoning.
when_to_use: a new design idea, feature, or pipeline change is proposed (by the supervisor, a colleague, or yourself) and you need a principled adopt/adapt/defer/decline decision before building
allowed-tools: Bash, Read, Grep, Glob
---
# Skill — evaluate a design suggestion before building it

A good idea poorly placed is wasted work; a weak idea built early is debt. Before implementing any
proposed change, run it through this evaluation and report the verdict. Push back when warranted — the
goal is the strongest version of the right ideas, not agreeable execution of every idea.

## The six questions (answer each with evidence)
1. **Utility — what problem does it actually solve?** Name the concrete failure or gap it removes. If you
   can't point to one (a measured defect, a missing deliverable, a real user need), it's speculative.
2. **Placement — where in the workflow does it live?** Pre-analysis (setup/gate before compute),
   during-analysis (a stage), or post-analysis (a check-in that may trigger a re-run/adjustment)? Name
   the exact step/checklist. If it changes SCOPE (a new task/detector/stat mode, a refusal line, a
   fidelity label), it lands in `docs/reference/scope.md` first. A change with no clear home is usually
   premature.
3. **Additivity — how much marginal value over what exists?** Does it duplicate or overlap an existing
   tool/step? Quantify the delta. "Nice but redundant" is a decline.
4. **Cost & risk.** Build effort, compute cost, new dependencies, failure modes, and what it could
   regress (run the benchmark gate in your head: would it touch the trust warranty?).
5. **Generality.** Does it generalize across analyses (good — it's product), or is it specific to one
   run (then it's a record/example, not workflow)? Per-paper logic is the anti-pattern this project
   guards against.
6. **The strongest form.** If adopted, what is the maximally-useful version? (e.g. a *measurable gate*
   beats a *documented hope*; a *typed schema* beats prose; matching the *published* form beats an
   invented one.) State it. For trigger/routing/escalation WORDING changes (skill descriptions,
   intake routing), the strongest form is MEASURED: should/shouldn't-trigger prompts weighted
   toward near-misses, split train/held-out so the wording isn't tuned to its own test set —
   `docs/research/routing-evaluation.md` is the live harness.

## The verdict
Conclude with one of: **ADOPT** (build it, in the strongest form, at the named placement) · **ADAPT**
(adopt a modified form — say what changes) · **DEFER** (good but not now — name the trigger that makes
it worth doing) · **DECLINE** (with the reason — redundant / wrong placement / not general / cost>value).
Give the reasoning, not just the label.

## After a verdict of ADOPT/ADAPT
Build it, then run the `embed-and-commit` skill (embed in the workflow + commit). The idea isn't
delivered until it's in the workflow and committed.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "The supervisor proposed it; declining feels rude" | The whole point of this skill: push back when warranted. DECLINE-with-reasoning is a valid, respectful verdict; agreeable execution of a weak idea is debt. |
| "It helped this run, so it belongs in the workflow" | Per-paper logic is the named anti-pattern; what doesn't generalize is a record (trial-run), not product. |
| "Keeping the old guidance line too is harmless" | Catalogue D1: ONE stale checklist line kept re-installing the 1-D collapse across sessions — superseded text is live ammunition; remove it. |

## Stop conditions
- The suggestion changes SCOPE (task/detector/stat mode, a refusal line, a fidelity label) →
  it lands as a `docs/reference/scope.md` row BEFORE any build starts.
- No named concrete failure/gap after question 1 → the verdict cannot be ADOPT; it is DEFER
  (name the trigger) or DECLINE.
