# Current project state

This board separates implemented software, historical scientific evidence and completed physicist deliverables. Read it for current state; earlier session records are preserved in the [state-board archive](history/2026-09-05-status-archive.md). The operational entry is [start a physics workflow](../workflow/start.md).

## Architecture hardening

The completed v0.4.0 architecture release covers typed limit transport, artifact-bound comparisons, explicit native normalization, capability dispatch, grounded draft intake, compact current-state handoff and durable dependency-aware execution. All twelve independent consistency, approval and lifecycle findings were repaired and rechecked. Its recorded verification was 1,089 source passes, a separate 40-test wheel run, and 1,081 public-export passes with ten development-artifact skips. These are the prior release's results, not full-suite results for the follow-up below. This engineering work does not close the scientific items below.

Use [scientific result contracts](../reference/scientific-results.md), [durable execution](../workflow/reference/durable-execution.md) and the [native pipeline](../workflow/reference/native-pipeline.md) for current APIs. `src/ravel/` holds Python implementations; `native/` holds native sources and launch/build helpers; `tests/` holds regression and integration checks. Detailed environment information is in [environment](../reference/environment.md).

## Active RRR closure work

The current work adds a source-bound four-state m150/140 experiment with all-event traces,
six slepton control regions, explicit per-bin signal MC constraints, independent-replica
pooling and direct-lepton response diagnostics. A 1,000-event smoke and an independent
20,000-event anchor completed all twelve native stages and all six limit checks.
The anchor gives 48.83 fb observed and 54.69 fb median expected, versus the published
46.633/56.526 fb on the explicitly declared four-state inclusive basis. This single-point
agreement does not close its roughly 11% reconstructed-fraction deficits, 7%/8% own MC
errors, missing truth definition or detector/systematic approximations. The exact small
inputs, numerical outputs and limitations are in the
[public waypoint evidence](../../evidence/audits/2026-09-06-rrr-waypoint/README.md).
The independent 40,000-event precision replica and 20,000-event six-state composition
control have also completed all twelve stages and all six roots. The four-state replica
gives 46.37/57.91 fb observed/median expected on the same inclusive rate basis. Its high/low
reconstructed-fraction diagnostics remain −10.22%/−2.41%, and the low-region own MC error
still exceeds 5%. The first 60,000-event pooled fit reached its one-hour cap without a final limit;
its separately preserved pooled moments meet the 5% high/low MC criterion. A new bounded
zero-event retry is being prepared. The six-state likelihood is complete. The completed origin
reader finds only two stau-containing signal-region selections in the six-state sample;
its original-exposure SR rate ratio to the four-state 20k control is 0.973 ± 0.082 from
conditional MC. This does not establish equivalence or justify a 2/3 rescaling.
The later controls are local research records pending public curation. The full fresh
52-point physics grid has not launched and no acceptance certificate is claimed.

The independent mT2 and RISR comparisons agree with the installed public analysis on all
6,928 two-lepton events in this anchor. A physical boundary control did reveal that the
native RISR CSV rounded values below one to exactly one. The source now writes round-trip
double precision; its isolated candidate passes the boundary test and changes none of the
anchor's RISR decisions. Active campaign binaries remain pinned to their original bytes.
The public cutflow's RISR label differs from the paper/code, and the inherited detector
converter aliases a generic b-tag decision to several experimental working-point flags.
Both are unresolved interpretation/response issues, not silently tuned away.

The formerly failed retained m150/130 likelihood now resolves all six roots with independently
checked profile minima. A 52-template numerical replay is paused between points to
prioritize fresh physics: five completed all six roots, two retain their original
45-minute timeouts and 45 remain unrun. The separate once-only 90-minute retry
phase resolved both timeout cases; its worker-validated summary records seven resolved and
45 ready points. A separate focused 100/98 GeV calculation also completed all six roots;
its observed/median limits differ from the historical calculation by −0.65%/−1.10%.
Together these are eight unique checked points out of 52; 44 remain unrun in this combined
replay population. Earlier standalone controls remain separate.
Both original failures remain in the attempt history. The focused comparison makes a
root-finding error less likely to explain that point's large residual, but it uses the
same historical signal template and does not validate its physics or normalization.
The preceding source checkpoint passed 1,475 cases with 12 optional skips. A separate
230-case native/ROOT run covers the relevant optional dependencies, and all 40 CLI checks
pass with a freshly built wheel, including both installed-wheel checks. Separate checks
also pass 50 publication/evidence tests and 32 waypoint integrity tests. The
[engineering checkpoint](history/2026-09-06-rrr-closure-engineering.md) describes the repairs,
evidence and scientific limits. The subsequent [execution and resource follow-up](history/2026-09-06-rrr-execution-followup.md)
repairs timeout cleanup and allocation enforcement. It also corrects active model-interface
and merging guidance without changing frozen physics. Its focused supervisor checks passed
64 cases, and the new complete source suite passes 1,533 tests with 12 optional skips.
The independently reviewed public candidate passes 1,524 tests with 21 optional skips,
including both installed-wheel checks using its own newly built wheel. Its exact source,
selected evidence and directory inventory were checked separately. The lower leading-parton
control is active under the stricter registered 1.26-million-event ceiling. The public
candidate is verified locally; remote publication and CI remain separate checks.

The [current audit registry](../../evidence/audits/current.json) selects fresh
[native](../../evidence/audits/2026-09-06-native-fidelity/README.md) and
[statistical](../../evidence/audits/2026-09-06-statistical-fidelity/README.md) revalidations.
Their nine-case benchmark retains seven regression passes and two missing generated-YODA
artifacts. All nine numerical-stability checks pass, while uncached acceptance comparisons
remain three PASS, three FAIL and three unscorable. Historical audits and baselines remain
unchanged. This work is tracked as open CR-155 in the [change registry](change-registry.md).

## Earlier RRR diagnosis and native portability follow-up

The earlier follow-up audits all 156 campaign-point records from three retained 52-point slepton scans, refits cached likelihoods and corrects expected-versus-observed contour-family selection. Its original three-of-four native-refit success and one numerical failure remain historical records; the later repair is described above. The official ATLAS model at masses 150/130 GeV reproduces the published observed and expected upper limits within 1%. Removing its signal nuisances and control-region signal strengthens the corresponding limits by about 14% observed and 12% expected. This identifies a relevant modeling effect in a controlled template comparison, not the complete cause of the native discrepancy.

The [macOS portability helpers](../reference/native-portability.md) now expose read-only preflight and build dry runs, use explicit native architecture and conda prefixes, and preserve existing toolchains. Fifty-four portability tests and two existing path tests pass; the current Apple Silicon installation passes 33 prerequisite checks. An independent reviewer reproduced and rechecked the repaired compiler-override mismatch. The new Intel/ARM CI matrix has not yet been credited with a completed remote run, and no clean-Mac or Intel HEP installation was tested.

The [public-analysis survey](../research/2026-09-05-public-hep-analysis-landscape.md) records 26 curated candidates and 45 discovery-index entries, with zero new scientific validations. These overlapping counts do not expand the served-capability board. Final source verification passes 1,155 tests with two release-only skips; the separate 44-test wheel/fidelity run enables both skipped cases. The 21 forensic/refit audit tests pass, along with publication, evidence and agent-surface checks. The adversarial board records 29 PASS, zero FAIL and one optional G21 live-agent-attestation SKIP. The fast cached benchmark passes its scoped gate without an acceptance upgrade. That earlier follow-up was published as public revision `5888f37466a70891a80190bf6671d45f14d89968`; its [remote CI run](https://github.com/ammarphp/ravel/actions/runs/33994944474) completed successfully. The active closure work has a local source checkpoint and further reviewed changes; it has not yet been pushed publicly. See the [dated verification/history](history/2026-09-05-rrr-and-portability.md) and [scientific diagnosis and research program](../research/2026-09-05-rrr-diagnosis-and-research-program.md).

## Reference-task evidence

The standing seven-request demand board measures partial versus complete deliverable evidence, separately from component implementation. P1's mechanical summary audit and P4's shape-engine selftest were previously credited as complete requests despite missing lifecycle or analysis-specific closure. They are now partial. Preserved component results remain useful; no autonomous success rate is inferred from this board.

<!-- CAPABILITY-STATUS:HEADLINE:BEGIN (auto-generated by scripts/gen_status.py from
     benchmarks/capabilities.json — DO NOT EDIT inside these markers) -->
**Reference-task coverage 0.50 (WARN)** on the project's benchmark of 7 reference physicist tasks — real requests collected from CERN researchers, used as the standing coverage yardstick (internal audit dimension "R9"). **0 of 7 fully served** (none yet; 0 served by a designed refusal), **7 partially served** (P1, P2, P3, P4, P5, P6, P7), **0 not yet built**. Task list, scoring, and definitions: `benchmarks/capabilities.json` → `docs/development/audit.md`. These are internal coverage categories, not measured autonomous success rates or a percentage of scientific correctness. The live audit inventory score depends on which development artifacts are installed.
<!-- CAPABILITY-STATUS:HEADLINE:END -->

<!-- CAPABILITY-STATUS:BOARD:BEGIN (auto-generated by scripts/gen_status.py from
     benchmarks/capabilities.json — DO NOT EDIT inside these markers) -->
| Prompt | task_mode | Status | Residual |
|---|---|---|---|
| P1 | summary_plot | partial | figure target and current approved lifecycle completion |
| P2 | summary_plot | partial | first execution through the now-built G1 track (T1 interference basis care) |
| P3 | projection | partial | UFO acquisition |
| P4 | reproduce | partial | 2408.00049 artifact-bound per-instance R5 closure |
| P5 | reproduce | partial | — |
| P6 | anomaly_search | partial | — |
| P7 | projection+reinterpret | partial | D2 truth-event-maker for full end-to-end R5 (reader + statistics-half already validated on real data) |
<!-- CAPABILITY-STATUS:BOARD:END -->

## Implemented components

<!-- CAPABILITY-STATUS:CAPABILITIES:BEGIN (auto-generated by scripts/gen_status.py from
     benchmarks/capabilities.json — DO NOT EDIT inside these markers) -->
| Capability | Status |
|---|---|
| G1_summary_track | built |
| G2a_effmap_folding | built |
| G2b_shape_fit | built |
| G2c_projection | built |
| G2d_replane | built |
| G3_generator_config_gates | partial |
| G4_basis_manifest | built |
| G5_trap_sweep | built |
| G6_ladder | built |
| M1_resource_sweep | built |
| M4a_plot_lint | built |
<!-- CAPABILITY-STATUS:CAPABILITIES:END -->

## Scientific evidence and remaining work

<!-- VALIDATION-STATUS:BEGIN -->
9 cases are registered in the historical benchmark baseline. 7 compare observed model-independent S95 in events, with a worst residual of 8.6%. Acceptance is separately scorable in 6 cases (4 PASS, 1 WARN, 1 FAIL), and unscorable in 3. These are historical measurements, not a fresh end-to-end reproduction claim. All cases, including failed certifications, appear in [validation pages](../validation/README.md).
<!-- VALIDATION-STATUS:END -->

The current full cached replay retains seven regression passes and two missing-YODA provenance failures. The final replay uses the installed rivet environment to compare cached acceptance inputs: three PASS, three FAIL and three unscorable. Three regression passes therefore retain acceptance-certification FAIL; their historical regression floors remain separate. A regression pass is not a new acceptance certificate.

- The corrected eRJR Lorentz-frame expression increased SRlow selection from 43 to 95 on the same 200,000 retained events. The 23.1% acceptance shortfall still fails the 15% threshold.
- The original compressed-slepton comparison retains a 24.9% observed median absolute residual, with 50 matched points of 52 planned. The forensic follow-up preserves this archival statistic. The PDF rescan and later original-PDF campaign have separate medians and populations; neither is a controlled isolation of the PDF or detector response. Four PDF-rescan detector samples are incomplete, and all three campaigns retain interpolation estimates rather than newly certified numerical roots.
- Fresh acceptance campaigns, correlated-systematic validation, statistical coverage/toy calibration, held-out end-to-end autonomy measurements and prospective method-learning experiments remain separate research work. Architecture tests cannot establish those results.
- The two missing provenance artifacts remain unresolved. Their absence is retained in the full benchmark denominator; the single bundled fast replay remains runnable.

See the [fidelity implementation report](history/2026-09-05-physics-fidelity.md), [prior hardening audit](history/2026-09-05-hardening.md), [limitations](../reference/limitations.md) and [prospective governance experiment](../../benchmarks/governance/README.md) for scope and follow-up evidence. Historical baselines and original scientific runs have not been rewritten to improve reported outcomes.
