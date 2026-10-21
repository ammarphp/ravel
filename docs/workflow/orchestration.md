# Orchestration — moving across pipeline stages

The **conceptual** stage map for an agent (or scientist) driving one analysis. Deliberately short.

> **The pipeline is implemented in `docs/workflow/`.** Requests start at [start](start.md); the analysis steps are `docs/workflow/README.md` (9 steps; 8 = scan→contour, 9 = the mandatory verification panel).
> It runs **natively** (conda, no containers) on the **Rivet path** AND — by default — on the
> **SimpleAnalysis path** (the VM-free native backend, `docs/workflow/reference/native-pipeline.md`;
> the podman+mapyde container is the legacy fallback for analyses with no native port). Pick the
> path by what the analysis provides (`docs/workflow/checklists/choosing-routine.md`).

## The two paths
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

## Who drives a run
The controller drives every governed run (`ravel ask`, `ravel drive --request-file`; see
[start](start.md)). It selects the route, compiles the steps of this map into a typed plan and
runs each one through the governed step graph; a model session is a worker that one step starts,
with that step's instructions, inputs and tools. The steps' documents are delivered to those
workers as instruction units; nothing here is a sequence an agent executes on its own.

1. The controller reads the request, pins it and selects the route; for an analysis it plans
   steps `docs/workflow/steps/01-*.md` to `09-*.md` (8 = scan to contour, 9 = the mandatory
   verification panel).
2. Each step carries only its **interface artifacts** (its declared inputs and outputs, by
   digest), not the whole prior context.
3. Results leave only through the sink: the delivered result carries its receipt and labels.
4. Record environment changes in `environment/changes/environment-changes.md`, card/data changes in a
   change record beside the changed material, and run outcomes in `RESULT.md`.

A host agent that runs the legacy commands itself (a run the controller does not own) follows
the same steps by loading each `docs/workflow/steps/NN-*.md` on demand; its results carry the
`NOT GOVERNED` label.

## Check-ins
- **CHECK-IN 1, 2 and 3 are typed authority points.** The controller renders each from the run's
  state and presents it at the physicist's terminal, or resolves it from the operator's
  configuration in an unattended run. An answer written anywhere else is not authority.
- **Feedback stays local:** a revision re-plans only the affected steps; completed work and its
  receipts are kept, and a changed plan needs renewed authority before it runs.
- **Escalation:** a worker that meets a missing or ambiguous input, a failed sanity check, or a
  change that would invalidate an earlier confirmed decision escalates; the controller holds that
  branch and asks, while other branches continue within their budgets.

## Conventions
When authoring or editing an instruction file, keep instructions short enough for low-cost models.
