# Orchestration — moving across pipeline stages

The **conceptual** stage map for an agent (or scientist) driving one analysis. Deliberately short.
(For the multi-**session** build plan — which session to run next — see the repo-root `ORCHESTRATION.md`;
this file is the per-run *pipeline* map, that one is the per-project *session* map.)

> **The pipeline is implemented and certified in `workflow/`.** Start at `workflow/WORKFLOW.md` (9 steps; 8 = scan→contour, 9 = the mandatory verification panel).
> It runs **natively** (conda, no containers) on the **Rivet path** AND — by default — on the
> **SimpleAnalysis path** (the VM-free native backend, `workflow/reference/native-pipeline.md`;
> the podman+mapyde container is the legacy fallback for analyses with no native port). Pick the
> path by what the analysis provides (`workflow/checklists/choosing-routine.md`).

## The two paths (after the reinterpretation paper, arXiv:2306.11055, generalized)
Both start MadGraph → Pythia8 and end at pyhf; they differ in **how detector effects are applied**:

```
  scientist's request → model + target analysis
        │
   MadGraph (LHE) → Pythia8 (HepMC, incl. CKKW-L/MLM merging)
        │
        ├── Rivet path (native, primary):   Rivet routine applies the analysis selection +
        │     **Rivet's own detector smearing** (no Delphes) → YODA (SR yields / distributions)
        │
        └── SimpleAnalysis path (NATIVE by default; container = legacy fallback): **Delphes** fast detector sim →
              SimpleAnalysis selection → sa2json → signal patch   (this is the paper's chain)
        │
   pyhf → 95% CL exclusion (CLs)   [+ named overlay plots vs the published data]
```
**Delphes is used on the SimpleAnalysis path only.** The Rivet path substitutes Rivet's smearing
functions (a recognized recasting approach) — a deliberate divergence from the paper's Delphes-centric
chain, documented per analysis. Both feed the same pyhf stage.

## How an agent should navigate
1. Read the request; identify the target analysis + which routine it provides → pick the path.
2. Open `workflow/WORKFLOW.md` and follow the 9 steps; **load each `steps/NN-*.md` on demand** (one at a
   time) to keep context small.
3. Carry only the **interface artifact** (the output file) between steps — not the whole prior context.
4. Record environment/data changes in `stages/01-event-generation/changes/` (generation) or the run's
   `RESULT.md` (records).

## Scientist check-in protocol (every step)
- **Check in at the points each step marks** (e.g. after the cards are defined, before a long run).
  Show the concrete artifact (a card, a σ, a plot) and ask for confirmation.
- **Incorporate feedback locally:** re-open only the affected step/checklist; do not restart the run or
  re-derive unrelated decisions (prevents over-correction + context loss).
- **Escalate** (stop and ask) when an input is missing/ambiguous, a result fails a sanity check, or a
  requested change would invalidate an earlier confirmed decision.

## Conventions
Before authoring or editing any instruction file, read `../conventions/agent-doc-conventions.md` (keeps
agent-docs and pedagogical-docs separate, and instructions short enough for low-cost models).
