# Architecture

These pages explain how RAVEL plans, runs and checks a calculation. Each page has one figure and a short
explanation. The coding agent's own step-by-step procedures are in [the workflow guide](../workflow/README.md).

## Overview

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/overview.svg">
  <img alt="Overview of RAVEL: you ask a coding agent, which follows the workflow guide under guardrails and drives the ravel package; RAVEL uses public inputs, runs MadGraph5_aMC@NLO, Pythia 8, Delphes with SimpleAnalysis or Rivet, and pyhf, and records every step in a run directory that ends in a 95% CLs exclusion limit." src="../figures/svg/light/overview.svg" width="100%">
</picture>

## Reading the figures

- **Colours mark layers.** Amber is you and the check-ins, pink is the coding agent and its guidance, red is the
  guardrails and the checks a step must pass, blue is RAVEL, green is external software and public data, and grey is
  records and evidence.
- **Shapes mark roles.** Rounded boxes are components, actions and records; their colour says which. The chamfered
  shape is a check-in; at CHECK-IN 1 and CHECK-IN 2 the work stops for you. In the overview, stacked boxes are the
  stored run records. In the lifecycle, the filled dot is your request, the hollow ring is intake, numbered rings are
  steps, octagons are check-ins and grey bands group the phases.
- **Lines.** Solid grey arrows show the flow of work; amber arrows return work to you at a check-in; dashed arrows
  show loops and optional paths, and a dashed group holds alternatives of which exactly one runs.

## The nine steps

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/lifecycle.svg">
  <img alt="How a calculation runs: a request goes through Intake, Environment and Inputs and route to CHECK-IN 1. One model point then goes through Generate, Analyze, Visualize, Acquire data and Exclude; CHECK-IN 2 is held once during these steps, at the agreed waypoint. Scan repeats steps 3 to 7 for each grid point, and Verify precedes the final check-in." src="../figures/svg/light/lifecycle.svg" width="100%">
</picture>

| Step | What it does |
|---|---|
| [1. Environment](stage-1-environment.md) | Makes sure this computer can run the native HEP toolchain. |
| [2. Inputs and route](stage-2-inputs.md) | Finds what has been published for the analysis, decides how to run it and prepares the plan you approve at CHECK-IN 1. |
| [3. Generate](stage-3-generate.md) | Generates the signal events for one model point. |
| [4. Analyze](stage-4-analyze.md) | Applies the detector response and the analysis selection, on the route chosen at step 2. |
| [5. Visualize](stage-5-visualize.md) | Draws the figures that compare the signal with the published data. |
| [6. Acquire data](stage-6-acquire-data.md) | Fetches the published likelihood or per-region counts for step 7, and the published contour for a scan. |
| [7. Exclude](stage-7-exclude.md) | Computes the 95% CLs exclusion limit for one model point and writes the result pack. |
| [8. Scan](stage-8-scan.md) | Repeats steps 3 to 7 over a grid of model points and draws the exclusion contour, next to the published one when it exists. |
| [9. Verify](stage-9-verify.md) | Checks every number and the physics before anything is delivered. |

## Across all steps

- [Check-ins](checkins.md): the two gates where the work stops for you, deviation notices, and the final delivery.
- [Guardrails](guardrails.md): what checks the coding agent's actions.
- [Records and evidence](records.md): what every run keeps, and how evidence is curated.
- [Where the work runs](backends.md): the native toolchain, the container fallback and Python-only routes.

## Detailed architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/architecture.svg">
  <img alt="Detailed architecture of RAVEL in three columns: you, the coding agent and its guidance, and the guardrails; the RAVEL package and where it runs; and the public inputs, external HEP software, and records and evidence. Contents listed below the figure." src="../figures/svg/light/architecture.svg" width="100%">
</picture>

| Panel | Contains | Page |
|---|---|---|
| You | Physicist, and the four check-ins | [Check-ins](checkins.md) |
| Agent and guidance | Coding agent, instructions, workflow guide, skills, physics reviewer | [Workflow guide](../workflow/README.md) |
| Guardrails | Session hooks, compute gate, deviation guard, stop checks, lifecycle validator | [Guardrails](guardrails.md) |
| RAVEL | Command line, intake and routing, run ledger, resource census, supervised execution, scans and contours, statistics, cross sections, plotting, validation | [The nine steps](#the-nine-steps) |
| Execution | Native toolchain, container fallback, Python only | [Where the work runs](backends.md) |
| Public inputs | HEPData, papers and code, routine catalogue | [Step 2: Inputs and route](stage-2-inputs.md) |
| External HEP software | MadGraph5_aMC@NLO, Pythia 8, Delphes, SimpleAnalysis, Rivet, pyhf, SModelS (cross-check) | [Toolchain](../../README.md#toolchain-and-platforms) |
| Records and evidence | Run directory, result pack, curated evidence, benchmarks, continuous integration | [Records and evidence](records.md) |

[Open the detailed architecture as a PDF](../figures/pdf/architecture.pdf).
