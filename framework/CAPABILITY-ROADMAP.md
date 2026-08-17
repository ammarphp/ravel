<!-- LAST-RECONCILED-AGAINST: capability-matrix.json@2026-07-08 -->
# Capability roadmap — from reproduction engine to reinterpretation practice

**Dated 2026-07-06. Planning authority alongside `PLAN-OF-RECORD.md` (mission).**
This is the dated (2026-07-06) demand-side PLAN. CURRENT per-prompt/per-capability STATE is owned
by `framework/capability-matrix.json` (viewed via `audit.py` R9 / `AUDIT.md` / the
`CAPABILITY-STATUS` blocks); this roadmap governs SEQUENCING and INTENT only. Where a W3 build has
since landed, the matrix status supersedes any "unbuilt" cell below.

**Where the charter stands (verified in-tree 2026-07-06):** `OPERABILITY-CHARTER.md` P0–P3 are
EXECUTED — the P1 findings register (`AUDIT-OPERABILITY.md`, 80 findings), the P2 worklist
(CR-001/002/003 fixed; CR-007…CR-014 embedded; 7 new + 6 fixed skills; `PRODUCT-CONTRACT.md`; the
operability harness), and the P3 reconcile/export (every gate green). **P4 live cheap-model evals
have NOT run** (`ROUTING-EVALS.md` §Verdicts is empty; only the deterministic
`route_prompt.py --selftest` is green). W1 below = the charter remainder (P4, P5) + this roadmap's
addenda.

---

## 1. The demand-side audit: 7 real physicist prompts vs the current architecture

`workflow/WORKFLOW.md` scopes the pipeline to "analyses that have **either** a Rivet routine **or**
a SimpleAnalysis routine" and its product is one shape: simulate → select → exclude (point or scan).
Walking the seven collected CERN-physicist prompts through the steps, fork by fork:

| # | Prompt (short) | Forks the architecture cannot currently take correctly | Verdict |
|---|---|---|---|
| P1 | HVT Z'→WW summary plot, m<500 GeV | (i) *which analyses are sensitive* — no sensitivity-census step exists (route-analysis maps ONE given id); (ii) the product is a **summary plot of published limits rescaled to a common HVT σ×BR basis** — needs NO generation, a track that doesn't exist; (iii) m<500 is below most diboson searches' boosted-regime floor — "coverage is sparse here" must be a first-class, evidenced answer; (iv) HVT model-A vs model-B σ basis | NEW TRACK NEEDED (G1, G4) |
| P2 | Toponium as heavy Higgs; limits from other searches | Census fork as P1; plus THE trap: a ~343 GeV A/H→tt̄ signal **interferes with SM tt̄** (peak–dip) — naive bump limits are invalid, and nothing in the workflow flags it. Basis fork: normalizing the hypothesis to the observed threshold excess | NEW TRACK + TRAP SWEEP (G1, G5, G4) |
| P3 | SVJ expansion + hypothetical tagger | (i) Pythia8 HiddenValley dark-shower config (Λ_d, r_inv, N_c/N_f, portal) — under-specified params, silently-wrong kinematics, no truth-level validation gate; (ii) extension BEYOND the published grid — certification anchors are on-grid only; (iii) "hypothetical dedicated tagger" — no detector-upgrade sensitivity mode | PARTIAL (G3, G2, precedent: `stat_mode=sensitivity-expected-only`) |
| P4 | Dijet+photon 2408.00049, Fig 5 + wide widths | Ran as the 2026-06-21 generality audit: **correctly BLOCKED (statistical-paradigm)** — background shape-fit, the ~40% boundary (8/20 in the pre-registered census, `framework/interrogations/generality.md`). The open fork is a *decision*, not a mystery: keep the named refusal vs build a scoped binned-fit engine | BOUNDARY — DECISION NEEDED (G2b) |
| P5 | CMS A→BC dijet substructure | Ran as trial (11 gaps): Option C particle-level proxy carried it. Open question is §5's: were the recorded gaps THE failure points? No independent bracketing against published checkpoints | RETROFIT LADDER (G6) |
| P6 | ATLAS model-agnostic AD | Ran as trial (12 gaps): CWoLa reproduction. Same attribution question | RETROFIT LADDER (G6) |
| P7 | Displaced-track Run-3 projection + µ–M2 reinterpretation | (i) displaced signature → vanilla Delphes has no displaced-track efficiency; the correct route is **folding the paper's published per-track efficiency maps over truth level** (the SModelS/LLP-recast standard) — a route that doesn't exist in step 4; (ii) 400 fb⁻¹ **projection** = likelihood rescaling with background-scaling assumptions — no track; (iii) **µ–M2 replane** under M1=M2, tanβ=50 = spectrum calculation + mapping published simplified-model limits into a new plane — no machinery | NEW ROUTES NEEDED (G2a, G2c, G2d) |

**Tally: 4/7 need product tracks or routes that do not exist; 2/7 stressed the (new, thin) Option C
and need failure-point attribution; 1/7 sits on the declared paradigm boundary awaiting a decision.**
The pipeline is an excellent *reproduction engine*; the demand is a *reinterpretation practice*:
survey, recast, project, extend, hypothesize. That's the honest capability audit — vs "100% ready".

**The two-layer statement (post-charter sharpening).** The charter's operability work closed the
**intake layer**: `route_prompt.py` already classifies all seven prompts to honest contracts
(P1/P2 → `summary_plot`/`none-survey`, P3/P7 → `projection`/`sensitivity-expected-only`, P4 →
`blocked-shape-fit`), and two of them have real CHECK-IN-1-only run dirs (the 2026-07-06 SVJ survey
— which also RE-OPENED the old signature-unmodelable block: Pythia8's HiddenValley module IS
compiled; the concrete missing piece is a UFO model for the paper's t-channel vertex — and the
dijet+photon named refusal). What does NOT exist is the **capability layer**: the task modes those
contracts name have no execution track behind them. A physicist today gets a correct, honest plan
and then a wall. This roadmap is about the second layer.

## 2. Gap taxonomy

**Architecture gaps** (each traces to prompts above):
- **G1 — Survey/summary product track.** From a signature/model → enumerate candidate analyses
  (HEPData/INSPIRE/recast-DB search), harvest published limits, convert to a common σ×BR basis,
  render the summary plot. No event generation on the base path. (P1, P2; the AD trial's
  `SURVEY.md` is the embryo.)
- **G2 — Route taxonomy incomplete.** (a) **Efficiency-map folding** (truth level × published
  per-object efficiency maps from HEPData resources — LLP/displaced/disappearing standard); (b) the
  **shape-fit statistical paradigm** (~40% of searches; currently a named, correct refusal —
  PRODUCT-CONTRACT §6.1); (c) **luminosity projection** (rescale likelihood, declared bkg-scaling
  assumptions); (d) **parameter-plane transformation** (spectrum calc + σ×BR re-weighting of
  published simplified-model limits; SModelS covers part). (P7, P4.)
- **G3 — Generator-configuration judgment class.** Beyond-SLHA configs (dark showers, interference-
  aware signals, width effects, merging choices) with **truth-level validation gates** (compare
  gen-level shapes to any published gen-level material before spending detector/scan compute). (P3, P2.)
- **G4 — Basis manifest.** Generalize the σ-comparison-basis rule (the Fig-44 incident) to a
  required artifact: before ANY published-vs-produced number comparison, write both sides' basis
  (states summed, order, PDF, charge, expected/observed, inclusive-vs-channel) into the run and
  refuse the comparison until the manifest matches. (P1, P2, P7, and our own history.)
- **G5 — Physics-trap sweep.** A pre-routing checklist of DOMAIN traps (interference with large SM
  amplitudes; long-lived/displaced; non-standard objects; trigger floors vs mass range; shape-fit
  stats; ISR-dependence of compressed SRs), each mapped to a cheap check + route consequence +
  CHECK-IN-1 flag. FAILURE-CATALOGUE holds OUR incidents; this is its domain-physics sibling.
- **G6 — Attributable verification** (§5): per-run published-checkpoint ladder so gap claims are
  *localized by bracketing*, not asserted.

**Process gaps:**
- **M1 — Resource sweep** (the missed-RRR-repo failure, generalized): mandatory step-2 sweep —
  paper availability section → HEPData record **incl. the resources tab** (efficiency maps, full
  likelihoods live there) → collaboration GitHub org + glance/twiki public pages → Zenodo DOIs →
  recast DBs (Rivet/SA/SModelS/CheckMATE/MA5-PAD) → INSPIRE forward-citations (theses carry
  cutflows). Emit `inputs/resource_census.json`; surface found/missing + fidelity consequences in
  CHECK-IN 1. Chrome-MCP browser control is the declared fallback rung for JS-walled pages (CMS
  public results, some twiki) where APIs stop.
- **M2 — Known-limitations triage headers** (§6): mechanism, not verdicts.
- **M3 — Audit v2 rescope**: readiness = coverage of the capability matrix (prompt classes ×
  G1–G6), not punch-list completion. README/STATUS rewritten to the same bar.
- **M4 — Visualization two-tier** (§7): (a) machine lint gate; (b) figure-spec + critique loop.
- **M5 — Transcript mining** (§8): the workspace JSONLs → recurring-pattern → mechanism proposals.
- **M6 — External skills survey** (§8): fragments from public skill repos/plugins/connectors.

## 3. The waves

**W1 — Engineering hardening + perishable capture** (no physics compute; = the charter REMAINDER + addenda).
Finish `OPERABILITY-CHARTER.md`: **P4 live cheap-model routing evals** (the empty Verdicts section
of `ROUTING-EVALS.md`; genuinely fresh subject sessions, transcripts saved, ≥6/7 target) and P5.
This roadmap ADDS the addenda:
1. `resource-sweep` skill + step-2 wiring (M1).
2. `plot_lint.py` machine gate (M4a): post-render, fail on legend/annotation bbox ∩ data-artist
   bboxes, tick-label overlap, axis-title collisions; wire into step 5/8 + benchmark provenance.
   First known target: the fig3 annotation box clipping the ATLAS dotted contour tail (the
   2026-07-06 legend fix, CR-007, closed the legend half of this).
3. **Judgment-protocol skills** (§9) — capture NOW, in W1, not in the physics wave: the content is
   writing, not compute, and it is the perishable asset (it exists only while a frontier model is
   in the loop; MEMORY does not ship).
4. Skills-survey fragments folded into the above as authoring patterns (M6, half-day, §8).
5. README/STATUS rewrite + audit-v2 rescope (M3) — the audit measures the §1 matrix from now on.
Launch: `Development session: finish framework/OPERABILITY-CHARTER.md (P4 live evals, P5), then
execute the CAPABILITY-ROADMAP W1 addenda (§3).`

**W2 — Evidence** (parallel, compute-free, bounded sessions; none blocks W1):
- **W2a Census** (§4): does the demand fall into few categories? Output: the coverage matrix +
  rigid-routine candidates. Launch: `Development session: run the route/product census per
  framework/CAPABILITY-ROADMAP.md §4.`
- **W2b Ladder retrofit** (§5) on the four existing records (slepton scan, CMS trial, AD trial,
  2408 audit). Launch: `Development session: build VERIFICATION-LADDER.md for the four completed
  runs per CAPABILITY-ROADMAP §5.`
- **W2c Limitations triage** (§6). Launch: `Development session: triage framework/KNOWN-LIMITATIONS.md
  per CAPABILITY-ROADMAP §6 — fill headers, rank the re-investigation queue, NO re-investigation.`
- **W2d Transcript mining** (§8). Launch: `Development session: mine the workspace transcripts per
  CAPABILITY-ROADMAP §8 — extraction schema, recurrence counts, mechanism proposals.`

**W3 — Capability builds** (each gated on named evidence or a supervisor/physicist decision):
| Build | Gate |
|---|---|
| Efficiency-map folding route (G2a) | none — P7 proves demand; standard practice; build after W1 |
| Survey/summary track (G1) + basis manifest (G4) | census confirms product-class mass (expected: yes — 2 of 7 prompts already) |
| Projection + replane modules (G2c/d) | census; SModelS-first spike to bound scope |
| Figure-spec + critique loop (M4b, §7) | after plot-lint lands (mechanical layer first) |
| Category playbooks (rigid routines) | ONLY for census-certified categories |
| Shape-fit engine vs stay-blocked (G2b) | **physicist/supervisor decision** — present costed options; the 40% number is the stake |
| Trap-sweep checklist (G5) | drafted in W1 with the judgment skills; extended by census findings |
| CR-004 rescan, CR-005 native generalization | standing registry work, unchanged |

**Sequencing rationale.** The supervisor's instinct — engineering/workflow/skills first — is
endorsed: those failures compound fastest and have documented fixes. Two amendments: (1) judgment
capture moves INTO W1 (perishable, cheap); (2) "the physics-judgment wall" decomposes on inspection
into two buildable routes + one costed decision + one catalogue + one survey — i.e. mostly
engineering once specified. The wall is smaller than it looks; W2 exists to prove where.

**Standing acceptance suite.** The 7 prompts are the capability evals (superset of charter P4's
routing evals): every W3 build must flip ≥1 prompt from blocked/new-track-needed to plannable, and
the audit-v2 board reports exactly that per prompt.

## 4. The census (W2a) — testing the "small number of categories" hypothesis

**Hypothesis** (supervisor's): most target analyses fall into few categories admitting more rigid,
less-judgment routines. **Priors from our own data:** figure archetypes — 4 cover ~94% (registered
census, `figure_manifest.py`); stat paradigm — ~60% counting / ~40% shape (pre-registered 20-analysis
census). So "few categories" is plausible for the *supply* side; the §1 audit shows the *demand*
side adds product types (summary, projection, replane, extension, hypothetical-upgrade) — themselves
few.
- **Supply substrate:** Rivet BSM routine list; SimpleAnalysis routine list; SModelS / CheckMATE /
  MadAnalysis5-PAD databases (each literally enumerates recast-ready analyses); the ATLAS full-
  likelihood list on HEPData; our 20-analysis census.
- **Demand substrate:** the 7 prompts; Collider-Bench tasks (arXiv:2605.13950 — on disk); LHC
  Reinterpretation Forum report examples.
- **Axes:** signature class × routine availability × stat paradigm × detector-standardness (prompt
  objects vs LLP/substructure/AD) × generator-config class × product type asked.
- **Output contract:** `framework/interrogations/capability-census.md` — the matrix, category mass,
  per-category existing-machinery map, and the ranked rigid-routine candidates (mass × machinery ÷
  judgment-fork count).
- **Expected honest conclusion (to be tested, not assumed):** O(10) categories; "rigid" applies to
  each category's procedural spine while every category retains NAMED judgment forks handled by the
  [judgment] policy — the goal is judgment *localization*, not judgment elimination.

## 5. Verification ladder (G6, W2b) — how we KNOW a recorded gap was the failure point

Per run, `VERIFICATION-LADDER.md`: one row per rung, status ∈ {checked-pass, checked-fail,
unavailable-published, **not-checked**}. Rungs, in pipeline order:
- **R0** toolchain sanity (benchmark fast gate)
- **R1** generation: σ vs published/independent value; truth-level shapes vs any gen-level material
- **R2** objects: reconstructed-object spectra vs paper figures (digitized)
- **R3** selection: cutflow vs published tables (`validate_cutflow.py`); else per-cut relative
  efficiencies vs any quoted acceptances
- **R4** SR yields: A×ε vs published maps (`certify_acceptance.py`)
- **R5** statistics: reproduce THEIR limit at THEIR point from THEIR inputs (slepton precedent:
  µ95 = 6.36594, exact)
- **R6** figure: form + numbers side-by-side (figure contract)

**Attribution rule (bracketing):** a claimed gap is CONFIRMED as a failure point iff the rung above
it passes and the rung at/below fails — or the gap demonstrably made a rung unevaluable. Anything
else stays "plausible, unattributed". **"not-checked" is loud:** RESULT.md must carry the ladder
table; unchecked rungs are named, not implied. Retrofit: the four completed records; forward rule:
every new run writes the ladder at close (postmortem-capture extends to include it).

## 6. Known-limitations triage (M2, W2c) — mechanism, deliberately no verdicts here

The file's entries currently record wildly different investigation depths (some carry full sagas,
some a sentence) with no uniform record — that structural fact, plus the HEPData precedent (a
"limitation" that fell to a second look; memorialized in the file's Resolved section), is the case
for triage. Each entry gains a header:
`investigated-to: none|brief|thorough (date, evidence link)` ·
`falsification-test: <the cheap experiment that would show this is actually easy>` ·
`reopen-cost: <estimate>` · `confidence: <low|med|high>`.
One session fills headers by INSPECTING existing evidence only (no re-investigation), then ranks
the re-investigation queue by payoff × ease. **Separate deep-dive sessions are opened only for
queue heads, per the triage's own recorded reasoning** — that is the non-premature answer to
"are separate sessions necessary": the triage decides, item by item, in writing. Standing rule
afterwards: no entry may sit in the file without a dated investigation record.

## 7. Visualization: two tiers (M4)

**Tier 1 — mechanical invariants, machine-enforced (W1).** The 2026-07-06 finding: the house style
already had a collision-aware `smart_legend` (mass-plane overlay + data overlay used it) while
`scan_contour.py` bypassed it with four raw `ax.legend()` calls — a pure ENFORCEMENT gap, now fixed
(CR-007) and re-render-verified. The durable fix is `plot_lint.py` (W1 addendum 2): render → measure
legend/annotation/text bboxes against data-artist bboxes and tick labels → nonzero exit on overlap →
wired as a step-5/8 gate. Checklists don't prevent; gates do.

**Tier 2 — publication nuance (W3, after Tier 1).** The generalizable mechanism replacing "a strong
model eyeballs it": extend the figure contract with a **figure-spec block** (extracted by LOOKING at
the published figure, per its checklist: scales, error-band style, marker/color conventions,
annotation set — experiment label, lumi, √s, region labels — hatching, legend order, panel
structure); render to spec; then a **bounded visual-critique loop**: fresh-context agent compares
the side-by-side and emits STRUCTURAL mismatches (never aesthetics), ≤2 fix iterations, surviving
diffs become caption'd deviations. The critic protocol is analysis-agnostic — that is what makes it
a mechanism rather than taste.

## 8. Mining + external references (M5, M6)

**Transcript mining (W2d).** Substrate: the workspace session JSONLs (3+ long sessions) + DEVIATIONS
ledgers + GAPS-notes. Extraction schema per incident: symptom · root cause · caught? by what ·
recurrence count · existing guard? · proposed mechanism class (skill / gate / intermediate artifact /
fail-loud warning / workflow step). Recurrence ≥2 without a guard ⇒ a mechanism proposal. Prior art:
the 2026-06-17 transcript audit (produced the two-session fork + charter) — the method works.
**On driving Opus via the browser to watch it fail:** the charter P4 mechanism (genuinely fresh
cheap-model sessions launched via CLI, transcripts saved, pass criteria) yields the same failure
evidence reproducibly and cheaper; browser-puppeteering adds realism only for interactive check-in
dynamics. Verdict: run P4 evals first; keep browser-driving as a targeted follow-up if eval
transcripts show UI-interaction-specific failures.

**External skills survey (W1 addendum 4, timeboxed ~half-day).** Targets: anthropics/skills;
obra/superpowers (installed — mine its patterns: the rationalization-table format, mandatory-
invocation framing, checklist→todo discipline); the public packs (Matt Pocock, Nate Jones, Kun Chen);
awesome-claude-skills lists; an MCP-registry sweep (Chrome MCP already adopted as the M1 fallback;
check for arXiv/INSPIRE/paper-search servers). Import FRAGMENTS as authoring patterns for OUR
skills — e.g. every judgment skill gets a superpowers-style "thought → reality" table
("'the caption tells me what the figure shows' → captions omit visual grammar; extract and look").
Nothing imported wholesale.

## 9. Judgment-protocol skills (W1 addendum 3) — operationalizing frontier judgment

The supervisor's diagnosis is adopted as the design premise: a weaker model's physics *knowledge* is
not the gap; its *protocol* is. The protocols below are the ones actually exercised in this project's
recorded incidents; each becomes a skill (with its trigger, checklist, and thought→reality table),
wired to the [judgment] tags:
1. **look-first** — never compare against a caption or memory; extract the artifact and look (the
   caption-imagined-figure incident).
2. **basis-manifest** — write both sides' conventions before any comparison; refuse until matched
   (the σ-basis incident → G4 artifact).
3. **trap-sweep** — enumerate domain traps pre-routing (G5 list), each with its cheap check.
4. **anchor-chain** — every produced number gets an independent order-of-magnitude anchor before
   downstream use.
5. **discrepancy-decomposition** — on disagreement: enumerate candidate causes, rank by cheapest
   discriminating test, run in cost order (the 33% → basis + 26% residual decomposition).
6. **source-ladder** — paper → HEPData incl. resources → collaboration GitHub/glance → recast DBs →
   theses/notes via INSPIRE citations → ask-with-named-options (subsumes M1's sweep at the
   judgment level).
7. **conservative-default** — under ambiguity choose the option that WEAKENS the claim, numbered
   flag, reversible (config, not baked into events).
8. **kill-the-result** — pre-delivery, argue the result wrong three ways (basis, acceptance,
   stats); feeds Tier-B.

## 10. Standing rules adopted with this roadmap
1. The 7 prompts are the standing acceptance suite; audit v2 reports per-prompt capability status.
2. A "gap" in any RESULT.md is CONFIRMED only by the §5 bracketing rule; otherwise labeled
   unattributed.
3. No KNOWN-LIMITATIONS entry without a dated investigation record (§6 headers).
4. Figures ship only through the lint gate once it lands; until then `smart_legend` routing is
   mandatory for new renderers.
5. This document is the planning surface; PLAN-OF-RECORD carries the mission; the charter carries
   W1 execution. STATUS/AUDIT/README readiness PROSE is generated from `capability-matrix.json`
   (single source, `gen_status.py`); this roadmap is the planning surface, not the state authority.
