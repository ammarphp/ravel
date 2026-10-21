---
name: route-analysis
description: Resolve the whole scientific request to current source-backed routine, detector, model and statistical operations. Use after physicist-intake, on zero routine hits, unfamiliar operations or missing inputs; preserve unresolved parent requirements while discovering, retrieving, adapting and qualifying components.
when_to_use: step 2; no routine/likelihood; unfamiliar/custom operation; off-grid extension; adapter mismatch
allowed-tools: Bash, Read
---
# Skill — resolve the whole question through current capabilities

State the required output and precision in the user's terms. Choose the cheapest method that meets the output, validity domain and precision, record why each cheaper method is insufficient or missing with evidence in `inputs/method-decision.json`, and stop when the answer is complete. Validate and render the record with `ravel method-decision --rundir RUN` before CHECK-IN 1 approval; full and scan launches refuse a missing, invalid or unjustified decision.

Keep exact original request bytes and every requested experiment, parameter domain, metric
and output. An accepted component, supplied-event diagnostic or published-figure overlay
does not complete the parent question. Public recovery and reversible
preparation use existing authorization; do not add a redundant confirmation step.

Read `inputs/capability_recovery.json`, or the recovery packet printed when `ravel initiate`
finds no legacy parser match. The parser's `unsupported` can mean unresolved intent. Use
`ravel.workflow.capability_routing` to inspect the actual selected source's `science.MODES`,
dispatch implementations and exact native compatibility registry without importing engines.
Grounded host intent or a typed scientific specification can resolve unfamiliar wording.
Candidate suggestions are planning hints, not scientific admission or execution authority.

Run the physics trap sweep (`docs/workflow/checklists/physics-traps.md`) and record how each
hit changes the source/input/model requirements. A shape label, LLP object, dark shower,
interference or width is a reason to inspect the appropriate model, not a blanket refusal.

## 1. Discover and retrieve across the requested scope

Search publications, the local analysis catalogue and relevant computational dependencies;
retain all requested experiments and physical-domain boundaries. `routine_fetch` matches
codes/literal identifiers, so a vocabulary query returning 0/0 is not absence. Extract the
paper/HEPData identifier and re-query. Inspect exact source, not only catalogue metadata.

```bash
ravel analyses list --query '<request terms>'
python -m ravel.workflow.routine_fetch --query '<analysis code or literal identifier>'
```

Use `resource-sweep` for public likelihoods, response maps, cards, tables, code and citations.
Inspect hits and existing retained official inputs. An outage is unknown; a missing identifier
can often be recovered without asking the user. A missing public resource, incompatible
adapter and genuinely missing private data have different recovery paths.

## 2. Reuse or adapt the actual compatible operation

- **Analysis construction:** inspect `analyze` backends (`analysis-ir`, `native-construction`,
  `routine-build`, preserved Rivet/SimpleAnalysis source/built routes) and computational
  providers. No routine does not imply particle-level proxy only. A custom native route
  needs complete source/output/response/runtime qualification before stronger claims.
- **Detector response:** choose by the selected analysis and supplied event semantics.
  `native_capabilities.resolve_capability` is exact compatibility admission for that legacy
  chain, not an exhaustive registry of all possible analyses. Historical parity and timing
  do not transfer to another routine, container, card or model.
- **Statistics:** inspect published/native/HS3 likelihoods, channels/modifiers/overlap,
  interference, control contamination and restricted custom statistical/continuous/joint
  models. Each has its own source contract. `shape_fit.py` represents a restricted binned
  1-D family; an incompatible fit needs a compatible native/custom adapter and validation,
  rather than an automatic downgrade of the user's question.
- **Off-grid extension:** map validity bounds limit reuse and reference comparisons, not
  the scientific interest of a new point. Keep requested coordinates. Acquire or
  generate/qualify missing per-point response/model/statistical inputs; never extrapolate
  unknown efficiencies or interpolate a published reference without justification.
- **Quantities and figures:** ratio/covariance/rebin/normalization operations have explicit
  contracts. A published-figure quotation is evidence reuse; a new limit needs model,
  response and statistical validation. An optional plotting failure must not erase valid
  numeric output; requested missing styling/figures remain unmet.
- **Prospective sensitivity:** preserve the requested metric and explicit response/background
  scenarios. A hypothetical tagger does not require an invented ROC or immediate training.
  Same-luminosity parameter/response studies do not need a new target luminosity. Expected
  significance/discovery reach is distinct from CLs exclusion; it needs its own calibrated
  model/validation route. No unverified observed discovery claim is admitted.

## 3. Qualify the bounded route and continue the original question

Apply the existing adapter's validation and complete input inventory, then prepare an
ordinary `ravel plan --spec` or the applicable generation/reproduction route. Source presence
alone proves neither runtime consumption nor applicability. Bind actual source/cards/runtime,
quantity definitions, reference and uncertainty checks, then use the existing exact-scope
compute approval and review. Reuse valid approval only within its recorded scope.

Legacy shape-fit/R5 and detector-fidelity gates still withhold unvalidated limit claims.
Diagnose failures and prepare a controlled compatible successor. A generator-level or
sensitivity diagnostic is explicitly partial and never replaces the required fit/limit.
When indispensable private inputs are missing, retain the dependent obligation as unmet;
continue independent public work without inventing those inputs. Report a precise barrier and
constructive next step, not a scientifically meaningless keyword refusal.

## Stop conditions

- Do not execute an incompatible adapter, a model outside its declared domain or unapproved compute.
- Do not manufacture efficiencies, covariance, event samples, likelihoods or a discovery claim.
- A failed parser/routine query, absent plot package, held R5 or off-grid map entry does not
  silently shrink the requested experiment population, scan domain, metric or output.
- Revalidate route contracts before execution. Keep parent acceptance against the original
  question separate from component admission and partial delivery.

## Live steering before dispatch

Read `ravel gate-wiring steer state --rundir <run>` before each dispatch.
Acknowledge new events with `ravel gate-wiring steer ack <event-id> --rundir <run>
--interpretation <text> [--amended-plan <path>]`. Reconcile requirements and
redirects in the amended plan, then call `dispatch_permitted(run, node_id)`.
A scope increase needs CHECK-IN 1 reapproval even after acknowledgement.
Pause and veto prevent dispatch. Priority orders eligible pending work inside
the existing budget. Preserve earlier results. Research-board posts are advisory
and grant neither steering nor approval.
