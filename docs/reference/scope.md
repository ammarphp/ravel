# PRODUCT CONTRACT — what this pipeline does, refuses, and labels

> The binding statement of scope for every session and every user (physicist or agent).
> `route_prompt.py` classifies requests against THIS taxonomy into a machine `task_contract.json`
> (schema: `validate_task_contract.py --schema`); CHECK-IN 1 presents the classification; anything
> outside it is a **named refusal**, never a silent improvisation. Companion docs:
> `docs/workflow/start.md` (how to ask), `docs/reference/limitations.md` (honesty registry).

## 1. Task modes (`task_mode`)

| mode | the ask | deliverable | compute |
|---|---|---|---|
| `survey` | "what analyses say anything about X?" | analysis/figure candidates + plan (no generation) | none |
| `reproduce` | re-derive a published result (validation) | published-vs-ours side-by-side + relative difference | scan (or point, as a declared partial) |
| `reinterpret` | a model the analysis never considered | new exclusion statement on that model | scan (or point, as a declared partial) |
| `scan` | explicit grid / mass-plane request | 2-D µ₉₅=1 contour + coverage | scan |
| `projection` | expected reach at a future lumi / detector variant | expected-only contour/limit, labeled | scan |
| `summary_plot` | combine several analyses' PUBLISHED limits on one canvas | overlay of published limits (+ ours where run) | none-to-point |
| `anomaly_search` | model-agnostic / "strange topologies" | AD-style sensitivity study, expected-only | point-to-scan |
| `no_routine` | no Rivet/SimpleAnalysis routine exists | custom particle-level analysis (Option-C path) | point-to-scan |
| `generate` | generation-only parton control | complete audited LHE, effective recipe, figure and check-in | one bounded approved attempt |
| `likelihood` | supplied workspace or counting approximation | verified observed/expected CLs roots, units, recipe and figure | one bounded approved attempt |
| `unsupported` | outside every row above or across a refusal line | **refusal with the named reason + nearest supported alternative** | none |

**The deliverable of `reproduce`/`reinterpret`/`scan` is a CONTOUR over a grid** (steps
`docs/workflow/steps/08-scan.md`); a single point is a sanity check or a declared partial PoC, never
presented as the product. A single-point QUERY against an already-completed scan is a **read, not
a run** (step 8's reuse rule).

## 2. Detector modes (`detector_mode`)

| mode | what models the detector | when | fidelity ceiling |
|---|---|---|---|
| `rivet-smearing` | the Rivet routine's own smearing/efficiency functions | analysis ships a Rivet routine | fast-sim floor (§5) |
| `simpleanalysis-delphes-native` | Delphes → native SimpleAnalysis (VM-free; **the default** for SA analyses) | SA routine with a native port (today: EwkCompressed2018/slepton — CR-005 tracks generalization) | bit-for-bit vs container (141/141 SRs) |
| `container` | Delphes → SA in the ATLAS x86 container (podman, emulated) | SA analyses with no native port | = native, ~9 h/point, sequential (legacy fallback) |
| `particle-level` | none (truth-level objects, no detector) | `no_routine` / `anomaly_search` / quick sensitivity | proxy only — labeled, never a claimed exclusion of record |
| `parton-level` | none; no shower/hadronization | `generate` | scoped LO generation, no acceptance claim |
| `none` | no detector operation requested | `likelihood` | supplied statistical model only |
| `effmap-folded` | published per-object / per-SR efficiency maps folded over truth objects (no detector sim of our own) | LLP/displaced (trap T2) via D2, or no-routine SUSY via D1 | map's documented accuracy (e.g. ~25%); R5-gated per analysis; out-of-envelope → conservative under-coverage (CR-034) |
| `delphes-custom-uncertified` | Delphes fast-sim (stock ATLAS/CMS card) feeding a CUSTOM selection with no certified routine (the Option-C detector variant) | no Rivet/SA routine exists but a Delphes card is warranted (e.g. τ_h+MET recasts; CR-134) | uncertified fast-sim: labeled proxy, **never an exclusion of record** until per-SR acc×eff certification vs published anchors (T10) closes — the route gate WARNs and CHECK-IN 1 must surface it |

## 3. Statistical modes (`stat_mode` — canonical enum = `result_pack.py` STAT_MODES)

| mode | model | when |
|---|---|---|
| `published-likelihood` | the analysis's serialized pyhf workspace + signal patch | it exists on HEPData (preferred, strongest) |
| `simplified-likelihood` | published simplified/covariance model | provided by the analysis |
| `best-sr-counting` | single-bin counting per SR, quote best expected-CLs SR | no serialized likelihood |
| `combined-counting` | simultaneous multi-bin counting fit | SRs mutually exclusive |
| `stability-only` | no limit — pipeline stability/validation statement only | validation runs |
| `shape-fit` | scoped binned-template fit (`shape_fit.py`): paper's background shape × flexible poly + signal template → CLs; **R5-gated per analysis** | the result is a binned shape/bump fit AND the engine can represent it AND its R5 closes (§6.1) |
| `blocked-shape-fit` | **REFUSAL** fallback: the shape-fit engine cannot represent this fit, or its R5 will not close | see §6.1 |
| `sensitivity-expected-only` | expected-only sensitivity (S/√B, expected CLs) — no observed-data claim | projections, AD studies, tagger what-ifs |
| `none-survey` | no per-run statistics — quotes OTHER analyses' published limits | `survey` / `summary_plot` |
| `none-generation` | no exclusion inference | `generate` |
| `provided-likelihood` | supplied pyhf model or explicit counting approximation | `likelihood`; see [scoped contract](../workflow/reference/scoped-workflows.md) |

Every limit is **95% CL CLs exclusion** (≈1.64σ one-sided). This tool **never** produces a 5σ
discovery claim, a p-value for an excess, or an "observation" — re-phrase or refuse.

## 4. The archetype census (the figure-selection basis)

The archetype census (18 detector-level BSM search routines surveyed;
`figure_manifest.py`): ~85% of the population is counting/cutflow, falling into **4 archetypes**
(A 0ℓ jets+MET · B multilepton/EWino · C 1ℓ+jets · D monojet/MET-binned) that share ONE overlay
primitive + ONE cert primitive; with the per-paper ESCAPE hatch the recipe table covered **94% of
the surveyed population**. The remaining ~6% and every ESCAPE hit is a per-paper
`[judgment]` figure choice via `figure_target.py resolve`. The MASS-PLANE overlay
(`mass_plane_overlay.py`) is the summary form no routine emits natively.

## 5. Fidelity labels (every result carries exactly one)

| label | meaning | evidence artifact |
|---|---|---|
| `bit-for-bit` | native chain reproduces the reference container per-SR yields exactly | 141/141 SR parity; µ₉₅ to 0.51% (`docs/workflow/reference/native-pipeline.md`) |
| `certified` | tiered acc×eff / cutflow certification PASS vs published | `validate_cutflow.py` / `certify_acceptance.py` output (`docs/workflow/checklists/detector-fidelity.md` B(b)) |
| `fast-sim-floor` | standard chain, uncertified region: intrinsic ~10–20% acc×eff floor | `docs/reference/limitations.md` (mapyde tunes ~15%) |
| `particle-level-proxy` | truth-level stand-in, no detector model | declared in `result.json` limitations[] |
| `degraded-anchor` | reference digitized from the published figure (no HEPData table) | provenance notes the digitization |
| `effmap-folded` | published efficiency map folded over truth kinematics; no detector model of our own | map version + validity envelope + map systematic recorded in the basis manifest; R5 closure at ≥2 published points (CR-034) |
| `capability-status-legitimacy` | a `served` status in `benchmarks/capabilities.json` is legitimate ONLY while its named machine gate (`gate{kind,ref,artifact,green_when}`) is currently green AND its evidence artifact ships with a matching checksum; otherwise the reconciler forces the credited status down and R9 is capped. Refusals, including the legacy `served-with-refusal` label, are unmet requests and receive no delivery credit. Refusal validity is assessed separately. A capability status NEVER upgrades itself. A heavy per-analysis R5 closure (gate kind=decision/deferred) can never credit `served` without a run. | enforced by `scripts/audit.py` reconcile over the per-prompt gate (CR-035) |

A result's prose NEVER upgrades its label ("roughly matches" ≠ `certified`). The measured
reproduction quality of record is the registered figure-3 claim in
`docs/validation/results.md`: 52-point scan, 24.9% median same-basis residual.

## 6. Refusal cases (name the line, offer the nearest supported thing)

1. **Shape/template-fit statistics** — NO LONGER a blanket refusal (the scoped shape-fit
   policy). Analyses whose result is a binned shape/bump/template
   fit route to **`shape-fit`**: the scoped engine `shape_fit.py` refits the paper's own background
   shape (a chosen family × a flexible polynomial transfer function) plus the signal template and
   brackets the CLs limit. This paradigm covers the measured **8/20 (~40%)** shape-fit share of the
   surveyed population that the counting machinery alone could not.
   **Two hard gates, per analysis, non-negotiable:**
   - **REPRESENTABILITY** — the engine handles binned 1-D shape/bump fits (dijet/dilepton/diphoton
     invariant-mass, template morphs). A fit it cannot honestly represent (unbinned ML fits,
     multi-observable simultaneous fits, per-event NN discriminants) DOWNGRADES to
     `blocked-shape-fit` with the reason named.
   - **R5 CLOSURE** — no reinterpretation number ships until the engine reproduces the paper's OWN
     published limit/figure within its stated accuracy (verification-ladder R5). `shape_fit.py`
     emits `shape_fit.json` carrying `{mu95_obs, mu95_exp, r5_status ∈ closed|held|na,
     r5_evidence}`; `validate_run_state.py --check` BLOCKS delivery of any `stat_mode=shape-fit` run whose
     `r5_status ≠ closed` (the gate now bites, not just prints). If R5 will not close, the run
     downgrades to `blocked-shape-fit` + the generator-level offer (CR-032). The engine is
     `shape_fit.py` (CR-027); R5 closes per analysis. For a still-open instance (e.g. arXiv:2408.00049, whose
     dijet-family turnover + A/ε-convention chain has
     not yet closed) the honest state is: routed to `shape-fit`, engine attempted, limit HELD by the
     R5 gate — the generator-level shape comparison + `sensitivity-expected-only` remains the
     shippable offer until closure.
2. **Discovery language**: any "discover / 5σ / observe an excess" ask → re-phrased to a 95% CLs
   exclusion or refused.
3. **Invented physics inputs**: missing efficiencies, likelihoods, k-factors, covariances are
   FETCHED (HEPData/paper/WG grids) or FLAGGED — never guessed (`AGENTS.md` hard rule).
4. **Off-grid model points**: outside the published acc×eff grid / kinematic sensitivity
   (step 8's on-grid rule) → the point is refused as uninformative, with the grid bounds stated.
5. **Generation without an approved plan**: any smoke, full, or scan generation before CHECK-IN 1
   approval (`approval_required` is ALWAYS true in the task contract; the compute ladder is
   dry → smoke → full → scan, `cost_preflight.py`).
6. **Beyond-scope physics**: non-LHC colliders, cosmology, detector design, real-data access —
   out of contract; say so.
6b. **Sensitivity integrity**: a `sensitivity-expected-only` number ships only
   when (a) the sensitivity artifact records a **pyhf** `method` — an A×ε-scale borrow of a
   published absolute limit is NOT an expected limit (`check_statistics` hard-FAILs it
   post-epoch) — and (b) a non-FAIL acc×eff certification exists
   (`sensitivity-expected-only ∈ CERT_REQUIRED_STAT_MODES`; `inv_certify_before_limit`).
6c. **Approval is an artifact (the pre-exec compute gate)**: the CHECK-IN 1 go-ahead is recorded as
   `inputs/checkin1_approval.json` via `workflow_state.py approve` (which requires a VALID
   `checkin1.json` + a recorded `cost_preflight.json` budget). smoke/full/scan generation is
   **pre-exec-blocked** without it, and blocked when detached (`nohup`/`setsid`), recipe-less, or
   unsupervised (`inv_approval_before_compute` + the PreToolUse Bash guard).
7. **Projection readiness**: counting-mode limits (`task_mode=projection`,
   `stat_mode=sensitivity-expected-only`) are EXPECTED-ONLY and BRACKETED (stat/syst/frozen). A
   physicist-facing projection number ships only after the R5-analog published-projection
   round-trip closes — the stat–syst–frozen band must CONTAIN a published HL-LHC/Run-3 expected
   limit for a representative analysis at the published f. Until closure, projection is
   not delivered; the offer is the labeled expected-only bracket as a sensitivity study,
   never an exclusion of record. The f=1 identity + scenario-ordering are self-consistency
   selftests, NOT the R5 gate (CR-033).
8. **Replane readiness**: replane (`task_mode=reinterpret` via a composition/plane fold) ships a
   number only after a round-trip reproduces a paper's OWN published contour on the σ×BR leg
   within tolerance. Composition-dependent A×ε is NOT re-simulated by the fold (declared caveat)
   and must be bounded or escalated (trap T3). Synthetic round-trip/monotonicity selftests are
   self-consistency, NOT the R5 gate (CR-033).
9. **First-skill precedence (N1)**: a physics session must invoke `physicist-intake` before any
   downstream skill. Loading `new-analysis` or a `run-*` skill before a validated
   `task_contract.json` exists is refused — the PreToolUse-on-`Skill` gate exits 2 (gate G22).
   The nearest supported thing: run `physicist-intake` first (it routes + gates + composes CHECK-IN 1).
10. **Detached long jobs (N6)**: a long compute detached from the harness (`nohup`/`start_new_session`)
   is refused turn-end unless it carries a durable `run_state.json` entry
   (`bg_kind=detached` + `logfile` + `done_condition` + `next_action`) AND a harness-visible heartbeat.
   DRIVE mandates harness-tracked backgrounding (`run_in_background`) so completion re-invokes the
   agent; a bare `nohup` silently defeats that lever and blinds the physicist (gate G27).

## 7. Result semantics (what a delivered number MEANS)

- Every number traces to a machine artifact (`result.json` / `scan.json` / `exclusion.json` —
  the number-integrity rule, `docs/workflow/checklists/verification-panel.md`).
- Coverage is stated: `n_done`/`n_planned`, partial grids labeled partial (never extrapolated).
- Comparisons are like-for-like: same σ basis (`model_basis` after rebase), observed-vs-observed
  or expected-vs-expected (LIKE-COLUMNS), reference never interpolated.
- A floored/capped µ₉₅ is a **bound, not a limit** (CR-001 `quality` tag; rendered '×').
- Every compute output lands **under the run directory** — a point/scan `OUTDIR` that resolves
  under `/tmp`, `/private/tmp`, or the session scratchpad is rejected at launch and FAILs
  `validate_run_state.py`'s outputs-in-tree invariant (N2/G23); outputs outside the rundir are
  invisible to `verify_pack.py`/`directory-keeper`/`.gitignore` (all key on the rundir).
- Every delivery passes the step-9 verification panel; its verdict ships verbatim with the
  result (never silently fixed).
- Compute reality: native full-chain point ≈ **30–50 min** (parallel, `--max`); a coarse 2-D
  grid is hours; a publication-dense plane is cluster work. Container fallback ≈ 9 h/point,
  sequential.
- Claim integrity: every headline/served claim in the SHIPPED docs (README,
  `docs/workflow/reference/*`, this contract) maps to a shipped, sha256-checksummed artifact via
  `evidence/manifest.json`; `check_evidence.py --check` FAILS if any served claim lacks a
  checksum-matching shipped artifact. 'Shipped' = included in the distribution selection of
  `evidence/collections.json` (CR-030).
- A `summary_plot` deliverable is ACCEPTED only when `summary_audit.py --check` passes (rules R-SA1..8:
  survey↔basis_manifest bijection; disposition completeness; no keyword-only exclusions — a
  dropped curve needs a physics/out-of-range/superseded reason class; legend label↔channel
  derivable from the candidate's survey `final_state`; superseded curves rendered as cross-check,
  not co-equal; per-curve provenance+lumi+obs/exp labelled; drawn coverage annotations consistent
  with every candidate's stated reach; transformation stated). Until the gate is green the run is
  a declared PARTIAL, never 'served' (CR-031).

## 8. Where this contract binds

`route_prompt.py` (deterministic classification) → `validate_task_contract.py` (schema gate) →
CHECK-IN 1 (the physicist sees the classification + cost + flags) → the skills
(`physicist-intake`, `route-analysis`, `cost-preflight`) carry the stop conditions. Any change
to a mode/label/refusal lands HERE first, then in the enum sources it mirrors
(`result_pack.py` STAT_MODES, `task_contract.json` schema), and the change is recorded in
`CHANGELOG.md`.

**Authority of record:** `benchmarks/capabilities.json` is the single source of STATE (what
is served/partial/unbuilt; consumed by `audit.py`). Every prose readiness/served/refusal claim in
README.md, `docs/reference/limitations.md` and the other current-claim files must reconcile to the matrix — enforced by
`check_agent_surface.py` (fail CI on contradiction) (CR-036).

**The full binding chain** (run leg, extending the classification chain above):
`route_prompt.py` → `validate_task_contract.py` (schema) → CHECK-IN 1 → [run] →
`validate_run_state.py --check` (lifecycle: ordering + completeness + mode-invariants incl. R5 closure and
likelihood↔selection pairing; stage matrix DERIVED from §1/§2/§3, legacy runs grandfathered) →
`verify_pack.py` (artifact integrity) → step-9 panel (CR-036).

## 9. Verification of the workflow gates

The workflow-adherence gates (the hooks, Stop-dispatch branches, `validate_run_state.py` invariants,
and skill/tool gates that make an agent FOLLOW the workflow) are themselves a product surface, so their
scope and their bar are stated here like any other:

| scope item | verification mechanism | bar (and its non-goal) |
|---|---|---|
| Verification of the workflow gates | the adversarial gate board: the per-gate harness (`tests/adversarial/`, one case for each of the 30 gates G0a-G28) run by `make green` | every gate case fires and the board is green; NOT a measure of agent task success and NOT a physicist-vetted full-physics run (an explicit non-goal) |

## Supplied-data scientific operations

The [scientific-study contract](../workflow/reference/scientific-studies.md) adds
`analyze`, `quantities`, `measurement` and `domain` proposals alongside the task
routes above. These admit existing event/object records and explicitly supplied
models; they do not relax generation, detector or reproduction gates. In particular,
UFO inspection is not model generation, lifetime geometry is not a displaced-track
efficiency, and a supplied Gaussian measurement likelihood is not an experimental
full likelihood. Requested paths and methods outside those adapters remain unmet
product requests.
