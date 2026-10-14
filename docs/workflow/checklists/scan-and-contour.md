# Checklist — scans over named axes

Read with `docs/workflow/steps/08-scan.md`. A scan repeats one admitted per-point computation over
the axes the request names and assembles the results. This checklist keeps a scan honest whatever
its dimensionality or per-point quantity.

If the result disagrees with a supplied reference, follow [reproduction
diagnosis](reproduction-closure.md). Check numerical roots, normalization algebra,
sampling and matched intermediate quantities before attributing the residual.

## Before scanning
- [ ] **The question fixes the scan.** The plan records each axis (name, unit, values or range and
      spacing), the parameters held fixed, the per-point quantity and its statistic, the
      normalization operations and the figures. Nothing in the scan comes from a default layout.
- [ ] **Mode is explicit.** A comparison with a supplied reference (its metric and tolerance
      declared) or a new result with no reference.
- [ ] **Points lie where the inputs apply.** Every point is inside any supplied acceptance or
      efficiency map, the kinematically allowed region and the validity range of each correction.
      A point outside them stays pending until its inputs are acquired or qualified; never
      extrapolate a published response to reach it.
- [ ] **Spec drives it.** One spec JSON; parameters substituted by the orchestrator's keyed line edit
      (never a greedy sed — `.claude/rules/madgraph-pythia.md`).
- [ ] **Each point is a full admitted run** (steps 3–7). Per-point fidelity checks apply to **every**
      point, not just one. A certificate covers its declared artifacts and points; it does not
      transfer across parameter values or models because the routine name is unchanged. State the
      validation coverage of the scanned region.

## Compute honesty
- [ ] **State the cost.** Size the scan from same-process pilots (`cost-preflight` skill). If the
      requested density does not fit the local machine, say so and propose a coarser grid or remote
      execution through the launch guard; do not quietly reduce the axes.
- [ ] **Report coverage, never hide it.** `scan.json` carries `n_done` / `n_planned` / `missing_tags`.
      A result from a partial grid says so on the figure and in `RESULT.md`. A scan is done when the
      points it claims are harvested, not when the orchestrator ran.

## Normalization
- [ ] **Apply exactly the plan's operations, in order.** Each rate, correction or basis change cites
      its pinned source and states its process, charge and flavour basis, order, PDF, scale and
      collision energy (`.claude/rules/statistics.md`). Keep the assembly before each operation so
      its effect is visible.
- [ ] **Know what each operation moves.** A pure re-normalization rescales the signal strength and
      the reference rate inversely: a rate-independent limit is unchanged while the unit-strength
      boundary moves. Verify that invariance numerically after the operation.
- [ ] Record the requested source and target cross-section conventions. Apply
      `assemble --normalization-contract <path>` only when a correction is requested;
      it preserves `mu95 * sigma_ref_fb` and numerical bounds. Each source factor
      and approximation must come from the selected contract.
- [ ] **Compare on the same basis.** A comparison with a reference limit is meaningful only when both
      sides are expressed against the same model rate. Establish the reference's basis from its
      source (for example its ratio to the model rate on its own boundary) and convert your result
      to it before comparing.
- [ ] Compare cross-section limits on the same declared production basis. If the
      basis changes, use `rebase --transformation <path>` with complete component
      accounting and justified response ratios. There is no universal state-count
      factor or negligible-contamination assumption. Validate the unchanged-shape
      premise, retain original artifacts and recompute exclusion status.
      The [convention contract](../../reference/cross-section-conventions.md) defines
      the equations, exact input pins and JSON/JSONL serialization. A transformation
      receipt is not independent physics qualification.
- [ ] **Supplied plotting contract.** Follow the declarative scan specification in
      [the figure contract](figure-contract.md#declarative-scan-plots). The selected
      layers determine observed/expected columns, reference records, exact-match
      tolerance, normalization, axis scales and output names. No comparison layout
      is selected by the presence of a reference table.
- [ ] **Comparison basis.** Supply a matching `model_basis` and the explicit
      per-point normalization multiplier for residual layers. Validate both sides'
      production, response, branching and unit conventions before plotting.
- [ ] **Reference support.** Compare only exact matches within the supplied coordinate
      tolerance. Keep unmatched references, bounds, failed points and missing scan
      points distinct; the planned population is the coverage denominator.


## The result over the axes
- [ ] **Supported interpolation.** A supplied contour layer declares its level and
      quantity. Piecewise linear interpolation uses supported vertices; absent or
      bound vertices mask adjacent triangles. No crossing means no contour legend.
- [ ] **The statistic is the declared one.** An exclusion scan without a prescribed statistic uses
      95% CLs and is never phrased as a discovery; a prescribed statistic is evaluated as written;
      a fit scan reports values, intervals and goodness of fit at each point.
- [ ] **Figures match the dimensionality.** One axis: a curve with its uncertainty band. Two axes: a
      plane with the boundary and, where requested, a colour map. More: declared slices or tables.
      With a reference, draw both on the same axes and quote the declared comparison metric.
- [ ] **Selected reference.** A reproduction supplies matching reference layers and
      source metadata. The request and extracted source figure determine the form.

## Record
- [ ] The scan dir's `RESULT.md` is generated-from / cross-checked against `scan.json` (numbers in the
      prose = numbers in the pack), exactly as a single run's `RESULT.md` tracks `result.json` (step 7).
- [ ] CHECK IN with the requester: show the declared figures, state coverage, the normalization
      operations applied and, with a reference, the agreement under the declared metric.
