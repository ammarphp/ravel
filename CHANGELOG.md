# Changelog

Version headings record package versions; no release tags are published for them.

## Unreleased — CHECK-IN 2 code gate

- Bind version-2 GO to an explicit waypoint manifest, produced/reference artifacts,
  comparison diagnostics and input hashes. Preserve explicit assent to a known discrepancy.
- Retain approval snapshots before covered native and scan launches in a shared checked interface,
  followed by append-only launch events. Lifecycle checks require historical receipts, so a later GO
  cannot backfill authorization. Write real operational UTC timestamps with an injectable test clock.
- Reject extra/duplicate GO options, boolean schema versions and malformed option names; harden
  parameter and trap artifacts against malformed types. Document execution-path coverage in the
  check-in checklist; direct commands outside the checked interface remain outside historical proof.
- Make CHECK-IN 2 a gate in code. `workflow_state.py go` records the physicist's GO in
  `inputs/checkin2_go.json`, bound to the CHECK-IN 2 artefact and the current CHECK-IN 1 approval, so
  editing either voids it. Full and scan launches of the native pipeline, scan launches through the
  Bash guard and campaign budget extensions refuse without it. The lifecycle validator fails a run
  whose recorded full or scan compute has no valid GO; runs dated before 2026-10-07 are waived. A
  single-point full sample launched outside the native pipeline does not record its size, so on that
  path the rule stays written.
- Add adversarial gate case G28. The board now has 30 cases.

## Unreleased — supplied-data scientific studies

- Add approved, bounded `analyze`, `quantities`, `measurement` and `domain` studies
  with exact input/source/runtime custody, explicit failures and CHECK-IN 2.
- Execute unmodified pinned Rivet routines on frozen HepMC; reconcile grouped,
  signed and variation-weight exposure and preserve continuous YODA quantities.
  Match RAW/final bin geometry and avoid applying density bin widths twice.
- Add explicit reconstructed-object selection, complete event-decision comparison,
  overlap/covariance-aware likelihood injection and an upstream SimpleAnalysis
  slim ROOT adapter. The latter still needs an external AnalysisBase build.
- Add ND quantity transport/merge, correlated Gaussian GOF and Spey CLs, bounded
  UFO/EFT/ONNX/lifetime and nuclear/forward/neutrino operations. Publish exact
  schemas, small end-to-end controls and retained failure evidence.
- Preserve the distinction between adapter delivery and physics fidelity. No
  new RRR mass-plane closure is asserted.

## Unreleased — public analysis discovery

- Add a pinned census of 554 Rivet LHC entries and 79 SimpleAnalysis routines,
  with source/asset identities, dependency signals and adaptation requirements.
- Add offline `ravel analyses list/show/summary/check-source`, including explicit
  paper-to-routine ambiguity and selected-source mutation checks.
- Publish the frozen catalogue survey with a browsable index. No new physics closure
  or general executor is claimed.


## Unreleased — RRR reproduction closure

- Implement generation-only and supplied-likelihood workflows with concrete check-ins,
  bound approvals, supervised single-attempt budgets, effective recipe comparison and
  figures. Require complete event records or all six numerical crossings for delivery.
  Preserve scripted experimental assent separately from expert review. Retain unsupported
  adapters as product gaps; this capability work does not close RRR physics fidelity.
- Enforce declared numeric upper bounds in the shared schema validator. Avoid duplicate
  package discovery when an installed worker bootstraps its module; reject stale evidence
  without confusing an invocation-path difference with an environment change.

- Report scope refusals as unmet requests, never as deliveries.
  Require a green gate for complete-delivery headlines and keep generated status
  pages consistent with the audit.
- Stop interpreting ordinary expected-limit terminology as a future projection.
  Add the scripted check-in approval mode, recorded as automated rather than expert
  review, and identify missing generation-only and statistics-only lifecycle routes;
  this does not claim complete RRR reproduction.

- Share precise reference-node matching across both acceptance validators. Reject
  ambiguous nodes, duplicate coordinates and interpolation across distinct fixed
  masses; retain fractional identity when combining acceptance and efficiency.
  Check all six ATLAS compressed maps in both row orders and add small numerical
  controls from two other ATLAS analyses without generating events.
- Repair contour support at irregular grid boundaries without filling missing
  interior points. Use legible logarithmic ticks and a RAVEL reinterpretation
  label. Re-render the unchanged historical scan with explicit provenance.
- Distinguish fresh adapter checks from inherited numerical evidence, keep
  historical records unchanged, and require separate rate/shape/precision review
  at the first reproduction waypoint. Full RRR physics closure remains open.

- Publish the fresh 50/45 GeV result and a three-anchor comparison with all 18
  limits, 114 channel-moment rows and separate reconstructed-fraction diagnostics.
  Show sparse MC, missing reference errors and the 49 uncompleted nominal points.
  Bind the new headline values to the portable evidence verifier.
- Identify refused LHAPDF build/import overrides by variable name without exposing
  their values. Preserve the refusal rules, frozen physics runtimes and dated audit
  evidence through a separately scoped current-source bridge.

- Publish the exact original-event identity diagnostic, all 40 hard-parton
  partitions, and the discrepant fresh 100/98 GeV result with its own inclusive
  normalization. Preserve sparse/zero bins and the limits of the public projection.
- Publish exact small models and every expected quantile for two matched 100/98
  statistical omission controls. These omissions worsen the reference discrepancy;
  the sparse-template and missing-baseline-portfolio limitations remain explicit.
- Add opt-in original-LHA provenance for plain/gzip native showers, retaining the
  original default commands. Bind decoded reads to their opened files and keep
  newly generated content verification distinct from historical replay equality.
- Add explicit Darwin LHAPDF linking that preserves the activated compiler flags
  and checks the selected library/PDF inputs. No existing PDF or toolchain changes.
- Reuse content hashes within a single receipt-validation call while rechecking
  file/tree/ledger identities. Charge generation against the run's own canonical
  plan when unrelated provenance contains another plan with the same filename.

- Publish the independently checked 60,000-event pooled 150/140 GeV result and
  its failed generation-cut equivalence control together. Retain the lower-cut
  rate decomposition, all 38 likelihood channels, three official-model nuisance
  controls and original failed attempts in a standalone arithmetic-verification
  bundle. Bind the two new README/result headlines directly to that evidence.
- Verify the tests of a fresh checkout without the original run archives or bytecode
  overrides. Prevent evidence imports from creating unmanifested cache files;
  require complete source availability whenever any original archive is present.
- Run fresh four-state m150/140 GeV smoke and 20,000-event samples through all twelve
  native stages and all six likelihood roots. Publish exact small likelihood inputs,
  cards, signal moments, fit diagnostics and source hashes in a self-checking waypoint
  bundle. Its single-point limit agreement is conditional on the declared normalization;
  reconstructed-fraction deficits and MC precision remain visible.
- Add all-event accounting, six slepton control-region selections, explicit signal MC
  constraints, strict ancestry/response diagnostics and independent-replica pooling
  based on original generated exposure. Missing reference definitions and empty-bin
  precision remain unresolved rather than becoming successful validations.
- Guard profile optimization with objective, stationarity, bounds and nesting checks;
  verify all six CLs crossings with a frozen fit-start portfolio. Recover a previously
  failed retained fit and preserve numerical replay timeouts in its full population.
- Validate compressed event transport, reject silent shower truncation and malformed
  normalization, and catch zero-parton cards that still require a jet. Write round-trip
  RISR CSV precision after a physical boundary test exposed a serialization error.
- Require exact completed-stage receipts and campaign accounting that includes failed
  attempts. Enforce every recorded fidelity source pin and public waypoint arithmetic,
  including malformed-evidence controls, in publication checks and CI.
- Preserve timeout failure when process cleanup raises, reap the owned child and
  check for active descendants before escalation. Hold retries while cleanup remains
  unresolved. Enforce registered reductions in campaign allocation without changing
  historical approvals or removing failed-event charges.
- Make Git-hook installation fail on path or write errors and work from nested
  directories. Isolate hook tests from user configuration and remove an accidental
  installed-native-binary dependency from the signed-event test fixture.

- Correct model-card guidance and lint wording to inspect the actual UFO mass/mixing
  dependencies. Remove stale lepton/monojet merging exemptions and universal rate heuristics;
  preserve supplied cards, declared approximations and generated-product checks.

Additional physics controls and mass-plane validation remain in progress. This release work does not yet
establish full-plane reproduction, truth-acceptance closure, detector calibration,
statistical coverage or an independent detector holdout. The engineering checkpoint
has passed CI.

## 2026-09-05 — RRR diagnosis and macOS portability

- Audit all 156 retained records across three slepton campaigns, preserving original results and identifying coarse interpolation, incomplete detector exposure and confounded PDF/preparation comparisons.
- Retain three resolved native cached-workspace refits and one numerical failure. Recover the official ATLAS 150/130 GeV model within 1% and record controlled signal-nuisance/control-region omissions, without claiming native detector or full reproduction closure.
- Compare expected panels with the expected reference contour family and observed panels with the observed family. Keep residual colors distinct from event-excess or exclusion significance.
- Add read-only macOS native diagnostics, pinned ARM/Intel bootstrap assets, explicit conda prefixes and staged build helpers. Repair the independently reproduced compiler-override mismatch; add architecture, quoting, ownership and absent-tool tests plus an Intel/ARM CI matrix.
- Embed full-population diagnosis and controlled-comparison requirements in the reproduction workflow. Preserve historical certificates, scan medians and failed trials.

No events were generated and no installed toolchain was rebuilt in this follow-up.
Its focused checks do not establish clean-Mac provisioning, Intel HEP execution,
statistical coverage or end-to-end physics reproduction. Final verification
passes 1,155 tests with two release-only skips; a separate 44-test wheel/fidelity
run enables both skipped cases, and the tree passed CI.

## v0.4.0 — 2026-09-05

- Preserve resolved limits, one-sided scan bounds, missing values and historical estimates through result packs, scans, projections and plots.
- Bind live shape and acceptance certificates to approved comparison policies, exact reference points, scientific inputs and served output bytes. Legacy checkmarks cannot authorize a result.
- Require explicit native luminosity, generated cross section, event normalization and corrections; validate the declared process and charge conventions.
- Dispatch registered analysis/model/detector/statistics combinations through an inspectable stage plan. Unsupported combinations fail before launch; overlapping ZeroLepton regions remain yields-only.
- Accept grounded host-agent intent alongside the local action parser. Negated discovery language no longer blocks legitimate reproduction requests; method-design requests produce a zero-compute research proposal.
- Add `ravel status` and a derived current-state packet for resuming from current evidence. Repair session routing and load detailed instructions only when needed.
- Record durable stage attempts with atomic state, output ownership, dependency fingerprints, process-group recovery and validated resume. Retain failed attempts and hold delivery when an applicable validator is unavailable.

These changes strengthen the execution and evidence contract. They do not certify new detector acceptance, statistical coverage or autonomous task success. Historical benchmark failures remain in the reported population.

## v0.3.0 — 2026-09-05

- Expand README with installation, draft initiation, cached replay, and real result artifacts.
- Add `ravel initiate` with validated draft contracts and no-overwrite lifecycle initialization.
- Correct the eRJR invisible-momentum boost; publish the identical-event differential and remaining acceptance failure.
- Preserve native nominal weights, sumw/sumw2, signal eta, and supported identification requirements.
- Refine CLs roots and record fit/crossing diagnostics; reject invalid numerical inputs and incomplete acceptance comparisons.
- Use exact reference populations and supported linear contours, with rendering and scientific-geometry regressions.
- Repair all active scan-template paths and dry-plan each specification.


### Repository organization included in this release

- Reorganized active implementations into the `ravel` Python package, with separate native
  tooling, environment provisioning, benchmarks, tests, documentation, and evidence trees.
- Replaced the research-heavy README with installation and first-use navigation; retained
  claim checks in dedicated validation pages.
- Added explicit mappings from preserved historical runs to readable public evidence
  collections. Public directory maps now describe the files actually shipped.
- Updated imports, source launchers, packaged assets, native path lookup, hooks, and CI for
  the new layout. The existing native installation and original scientific records are preserved.
- Strengthened migration checks for installed execution, mutation-safe test fixtures,
  enforcement coverage, and strict directory references.

## v0.2.0 — 2026-09-05

- Added the installable `ravel-hep` package and `ravel validate`, `ravel replay`, and diagnostic
  `ravel audit` commands. Cached replay works outside a checkout; the native pipeline remains
  the default for full simulation. Replay dependencies are version- and hash-locked.
- Enforced task-contract schema and strict JSON at approval, lifecycle, and pre-execution
  boundaries. Known generation entry points reject missing, stale or unbound approval records.
- Distinguished statistical S95 recovery, acceptance certification, and mass-plane fidelity.
  All nine benchmark cases now have generated pages, including failures and unscorable cases.
- Required shipped physics evidence itself and checked manifest completeness against source
  registries.
- Fixed the observed sparse-line legend-occlusion miss with bounded display-space segment
  sampling, preserving logarithmic transforms, path breaks and marker-only artists.
- No causal improvement or new physics validation is claimed by these engineering changes.


## v0.1.0 — 2026-08-17

First public snapshot, prepared August 16.

- Full reinterpretation chain (MadGraph5 → Pythia8 → Delphes → Rivet/SimpleAnalysis → pyhf)
  with a governed control plane: typed task contracts, human-approval gates, provenance and
  sha-pinned claim evidence, adversarial gate board.
- Historical statistical-layer result: seven observed model-independent S95 comparisons within
  8.6%; the public CI re-fits one bundled fast case. This was previously described too broadly
  as published-analysis reproduction; acceptance and mass-plane fidelity are separate.
- Native ARM64 execution: 8h55m → 41m47s (12.8×) on the identical 50k-event point.
- Native SimpleAnalysis backend: 3 routines validated bit-for-bit against the containerized
  original (EwkCompressed2018 141/141 signal regions; ZeroLeptonDiscovery2018 10/10;
  EwkThreeLeptonERJR2018 9/9) + a declarative engine for cut-based routines.
- Replay-mode quickstart (3 commands, no HEP-stack install) and a 344-test suite, all CI-green.
