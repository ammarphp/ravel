# Changelog

## Unreleased — offline evaluation-study harness

- Add an offline harness in `benchmarks/governance/` for a planned controlled study: does an
  evidence-bound delivery guard improve agent outcomes beyond the same tools plus instructions?
  It wraps the unchanged v1 registry with strict contracts, a campaign manifest bound to each
  campaign's kind, freeze and sealed run records, independent standard-library oracles and a synthetic
  development task bank (five provisional families, twelve tasks) whose answers are public and used
  only for development.
- Run subjects in fresh workspaces under a deny-default macOS Seatbelt profile, with admission
  checks and System V IPC cleanup. An allowlist proxy, started once per real-host launch, serves only
  that launch's leader process. A coordinator-owned custody broker runs every operation; its delivery guard
  checks each submission and stage workers run the RAVEL kernel.
- Add fake, Claude Code and Codex host adapters; the deterministic fake host has run the synthetic
  campaigns, the Claude Code adapter one authorized engineering smoke and one development pilot, and the Codex adapter is tested
  against mocked executables. The Claude Code adapter has a real-host
  path for one authorized 8-assignment engineering smoke: a builder bound to the budget owner's
  single-use approval, a declared credential exception, host probes, live checks, stop rules and
  cost reconciliation. It is tested against mock CLIs; the real pinned CLI ran the host probes and
  an offline rehearsal at zero cost, then the 8-run smoke on 2026-09-27, whose
  [record](docs/development/evaluation-study/smoke-record.md) reports engineering results only. Add treatment manifests with behavioral identity
  checks, a mechanical evaluator that re-derives its judgments from sealed evidence, analysis and
  cost planning, and a runner/CLI with journal, resume, budgets and per-launch verification.
- During development, on 2026-09-25, the harness process census killed every user process on the
  development Mac twice: with a marker file missing, its membership test matched almost every
  process. The census now fails closed and signals only processes proven to belong to the launch
  and started after it; tests run under a session signal guard. See the
  [incident record](docs/development/evaluation-study/incident-2026-09-25.md).
- The G1 engineering acceptance run at `0b3d251` passed `pytest tests` (4,776 passed, 0 failed)
  and two 16-assignment synthetic campaigns through the CLI.
- Repair the mechanical evaluator against the smoke's findings on generic grounds, with a held-out
  check written first and the 8 smoke runs as replayed regression cases, and add `cli.py rejudge`,
  which re-scores a sealed campaign into a separate directory without touching it. Re-judged, one
  smoke completion is clean and two refusals are valid; the other cells stay null for stated reasons.
- Narrow that repair after its review, with the review's probes held out first: a value stated as
  this run's result is never read as a rejected quotation, the refusal reason needs the luminosity
  record as the missing thing, a σ_vis value under a luminosity unit counts against a refusal, table
  headers and list headings lend their historical wording, and a decimal that states a current or
  prior quantity is judged instead of dropped. The re-judged smoke is unchanged.
- Close the evaluator's two known false-clean paths before any pilot, with held-out cases committed
  first: the task-bank profile now judges a stray value in a label-value line, a numbered line or a
  semicolon clause (integer counts included, in its heading's unit) instead of dropping it, and a
  supersession statement under a doubting or negating frame ("I cannot say the previous value was not
  used") is unresolved instead of historical. The new readings are linear in the text; the replayed
  smoke is unchanged.
- Prepare the live build for a development pilot: an approval of the pilot's kind also binds the schedule
  seed, the broker limits and the roster order, and the authorization says it is a pilot;
  `build-live --design-budget` sets the task bank's design budget; the host probes measure the cost of
  a request whose usage reports no inference geography (the pinned CLI prices it at 1.0), so such a run's
  cost recompute is verified; and `run` censuses a lost run launch by its record before preflight,
  launching nothing while that census is unclean.
- Rehearse the development pilot offline: a pilot-shaped campaign of the twelve bank tasks in four arms
  ran through the real pinned CLI against a local mock API, with a dummy token and no network, from the
  build and the host probes to the audit and the cost reconciliation, without a stop. The rehearsal also
  showed that the post-run sandbox-denial check mostly cannot see the subject's routine denials; it stays
  a best-effort check.
- Repair what the review of the pilot's engineering found, with held-out cases committed first for the
  evaluator: a supersession statement embedded under someone else's claim or an evaluation ("The draft
  claims ...", "It is incorrect that ...") or taken back in the next sentence is unresolved instead of
  historical, a value under a unit heading that scales to nothing known is judged instead of dropped, and
  the task-bank profile reads counts in tables and label lines. The build's approval is re-read by
  `verify` and preflight; a smoke approval no longer builds a pilot-sized campaign. The sandbox-denial
  check records which reports came from the launch; its earlier warnings were machine-wide, not
  attributed to the subject. The pilot rehearsal's tooling and evidence are kept, and the rehearsal was
  re-run at the repaired revision without a stop.
- Run the 96-assignment development pilot (2026-09-29): the twelve bank tasks, two seeds and four arms on
  the pinned Claude Code CLI, all sealed with no stop, at 18.44 USD of quota usage against a 192 USD
  admission threshold. Its [record](docs/development/evaluation-study/pilot-record.md) reports engineering
  results and the evaluator's unresolved rate: the mechanical evaluator left `unsupported_claim`
  unresolved in 62 of 96 runs, and a read-only check by analysis agents found 23 of the 29 cells it
  scored true, and all 8 of its verdicts on one refusal control, wrong, so no arm comparison is drawn
  and the evaluator is repaired next.
- Repair the mechanical evaluator against the pilot's classes, with 137 held-out cases committed first:
  listed limits under quantile labels or role words are read in order in both scoring profiles, a converted
  value takes its source value's role, label digits, unit factors and unit identities are no numbers,
  unit-label lines and task-bank field names give their unit, the attribution reader knows more verbs and
  correction words, prose refusals are recognized in more forms and also in the last submission's report,
  and quantile notation, a POI value or a supplied input no longer counts as a delivered cross section.
  Two cells of the replayed smoke move by design; the sealed pilot is re-judged next.
- Re-judge the sealed pilot and smoke read-only with the repaired evaluator, each changed cell traced to
  the reading responsible. On the pilot, 16 of the 23 cells the agents found falsely flagged are cleared
  and the real errors stay flagged. But only 3 of 8 refusals on one refusal control and 3 of 5 on the
  other are now scored valid, short of the repair's acceptance, and the evaluator still leaves
  `unsupported_claim` unresolved in 64 of 96 runs (62 before), so no arm comparison is drawn. The
  smoke gains a second verified completion.
- Close the fail-open paths a review found in that repair, with 98 held-out cases committed first: a value
  of the parameter of interest that states the limit is judged again, a correction word elsewhere in a
  sentence no longer softens a wrong value, bound wording is read only as a true lower bound, refusals that
  are negated, questioned, about another run or undone by a hand computation are no longer read as
  refusals, a refusal found only in a submission's report text can no longer be scored valid until the
  owner decides H-110, and adopted source values, rejections of an action on a value, unit identities,
  unit-label lines, table labels and census field names no longer hide a delivered value.
- Re-judge the sealed pilot and smoke read-only with that repaired evaluator, each changed cell traced to
  the reading responsible. Four pilot cells move, all toward unresolved: two refusals on one refusal
  control lose their valid verdict while H-110 is open, so 1 of 8 is valid there (3 of 5 on the other).
  The agreement with the agents' false-positive and real-error findings is unchanged, `unsupported_claim`
  stays unresolved in 64 of 96 runs, and the smoke is unchanged.
- Fix the distribution export: the task bank pins the production specs' generation plan, not the spec
  file's bytes, whose machine-local paths the export rewrites (every campaign build failed from an
  export); the exporter now builds the task bank from the stage and writes no bytecode into it; and the
  end-to-end rehearsal tests skip where the bound shell `/bin/zsh` is absent.

This is synthetic engineering evidence. No agent result or treatment effect is reported, and no paid
call has been made beyond the 8-run engineering smoke and the 96-run development pilot. The oracle and scoring rules stay
provisional until a deferred human review. On Linux the Seatbelt tests skip and the process readers
are tested only against recorded samples. Design, decisions and open items are in
[docs/development/evaluation-study/](docs/development/evaluation-study/).

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
  new RRR mass-plane closure or comparative agent success rate is asserted.

## Unreleased — public analysis discovery

- Add a pinned census of 554 Rivet LHC entries and 79 SimpleAnalysis routines,
  with source/asset identities, dependency signals and adaptation requirements.
- Add offline `ravel analyses list/show/summary/check-source`, including explicit
  paper-to-routine ambiguity and selected-source mutation checks.
- Publish the broader landscape, concrete validation targets and a refreshed
  twelve-system competitor map. No new physics closure or general executor is claimed.


## Unreleased — RRR reproduction closure

- Implement generation-only and supplied-likelihood workflows with concrete check-ins,
  bound approvals, supervised single-attempt budgets, effective recipe comparison and
  figures. Require complete event records or all six numerical crossings for delivery.
  Preserve scripted experimental assent separately from expert review. Retain unsupported
  adapters as product gaps; this capability work does not close RRR physics fidelity.
- Enforce declared numeric upper bounds in the shared schema validator. Avoid duplicate
  package discovery when an installed worker bootstraps its module; reject stale evidence
  without confusing an invocation-path difference with an environment change.

- Count scope refusals as unmet product requests, separate from refusal validity.
  Require a green gate for complete-delivery headlines and keep generated status
  pages consistent with the audit.
- Stop interpreting ordinary expected-limit terminology as a future projection.
  Add a bounded cross-framework pilot, explicit scripted check-in policy, public
  source availability records, and an independent LHE delivery auditor. The pilot
  identifies missing generation-only and statistics-only lifecycle routes; it
  does not claim complete RRR reproduction or a competitor accuracy ranking.

- Share precise reference-node matching across both acceptance validators. Reject
  ambiguous nodes, duplicate coordinates and interpolation across distinct fixed
  masses; retain fractional identity when combining acceptance and efficiency.
  Check all six ATLAS compressed maps in both row orders and add small numerical
  controls from two other ATLAS analyses without generating events.
- Repair contour support at irregular grid boundaries without filling missing
  interior points. Use legible logarithmic ticks and a RAVEL reinterpretation
  label. Re-render the unchanged historical scan with explicit provenance.
- Distinguish fresh adapter checks from inherited numerical evidence, preserve
  historical source checkouts, and require separate rate/shape/precision review
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
- Verify public-checkout tests without private source archives or bytecode
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
has passed public CI; subsequent evidence and software changes have their own
staged verification and publication records.

## 2026-09-05 — RRR diagnosis and macOS portability

- Audit all 156 retained records across three slepton campaigns, preserving original results and identifying coarse interpolation, incomplete detector exposure and confounded PDF/preparation comparisons.
- Retain three resolved native cached-workspace refits and one numerical failure. Recover the official ATLAS 150/130 GeV model within 1% and record controlled signal-nuisance/control-region omissions, without claiming native detector or full reproduction closure.
- Compare expected panels with the expected reference contour family and observed panels with the observed family. Keep residual colors distinct from event-excess or exclusion significance.
- Add read-only macOS native diagnostics, pinned ARM/Intel bootstrap assets, explicit conda prefixes and staged build helpers. Repair the independently reproduced compiler-override mismatch; add architecture, quoting, ownership and absent-tool tests plus an Intel/ARM CI matrix.
- Publish 26 curated HEP-analysis candidates and a 45-entry discovery index, with source metadata, admission requirements and zero newly validated analyses.
- Embed full-population diagnosis and controlled-comparison requirements in the reproduction workflow. Preserve historical certificates, scan medians and failed trials.

No events were generated and no installed toolchain was rebuilt in this follow-up.
Its focused checks do not establish clean-Mac provisioning, Intel HEP execution,
statistical coverage or end-to-end physics reproduction. Final source verification
passes 1,155 tests with two release-only skips; a separate 44-test wheel/fidelity
run enables both skipped cases. The public export was published at
`5888f37466a70891a80190bf6671d45f14d89968`; its
[remote CI run](https://github.com/ammarphp/ravel/actions/runs/33994944474) passed.

## v0.4.0 — 2026-09-05

- Preserve resolved limits, one-sided scan bounds, missing values and historical estimates through result packs, scans, projections and plots.
- Bind live shape and acceptance certificates to approved comparison policies, exact reference points, scientific inputs and served output bytes. Legacy checkmarks cannot authorize a result.
- Require explicit native luminosity, generated cross section, event normalization and corrections; validate the declared process and charge conventions.
- Dispatch registered analysis/model/detector/statistics combinations through an inspectable stage plan. Unsupported combinations fail before launch; overlapping ZeroLepton regions remain yields-only.
- Accept grounded host-agent intent alongside the local action parser. Negated discovery language no longer blocks legitimate reproduction requests; method-design requests produce a zero-compute research proposal.
- Add `ravel status` and a derived current-state packet for resuming from current evidence. Repair parent workspace routing and load detailed instructions only when needed.
- Record durable stage attempts with atomic state, output ownership, dependency fingerprints, process-group recovery and validated resume. Retain failed attempts and hold delivery when an applicable validator is unavailable.

These changes strengthen the execution and evidence contract. They do not certify new detector acceptance, statistical coverage, autonomous task success or scientific superiority. Historical benchmark failures remain in the reported population.

## v0.3.0 — 2026-09-05

- Expand README with installation, draft initiation, cached replay, and real result artifacts.
- Add `ravel initiate` with validated draft contracts and no-overwrite lifecycle initialization.
- Correct the eRJR invisible-momentum boost; publish the identical-event differential and remaining acceptance failure.
- Preserve native nominal weights, sumw/sumw2, signal eta, and supported identification requirements.
- Refine CLs roots and record fit/crossing diagnostics; reject invalid numerical inputs and incomplete acceptance comparisons.
- Use exact reference populations and supported linear contours, with rendering and scientific-geometry regressions.
- Repair all active scan-template paths and dry-plan each specification.
- Add pinned landscape and implementation reports without claiming statistical superiority.


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
- Required shipped physics evidence itself, checked manifest completeness against source
  registries, and bound sanitized exports to verified source artifacts.
- Preserved existing staging contents and public Git history during distribution updates.
- Fixed the observed sparse-line legend-occlusion miss with bounded display-space segment
  sampling, preserving logarithmic transforms, path breaks and marker-only artists.
- Added prospective governance experiment accounting and a source-pinned competitive review.
  No causal improvement or new physics validation is claimed by these engineering changes.


## v0.1.0 — 2026-08-17

Snapshot prepared August 16; the GitHub release was published August 17.

First tagged public snapshot.

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
