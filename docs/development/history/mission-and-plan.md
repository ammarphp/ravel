# PLAN-OF-RECORD — the canonical mission, the trial, and the critical path

<!-- LAST-RECONCILED-AGAINST: capability-matrix.json@2026-07-08 -->
> Durable handoff (written 2026-06-17 from a full transcript audit of sessions ea023a01 / 64fe01b4 /
> 72158dee). Read this FIRST if context was compacted or a session restarted. It is the authority on
> *what we are actually building and why* — above any auto-summary.

## Mission (the user's framing, re-asserted verbatim across the whole arc)
A genuinely useful, **broadly-applicable** agentic LLM harness: a physicist hands **the workflow** a
published ATLAS/CMS analysis + a hypothetical model, and **the workflow ITSELF — not the supervisor
hand-driving it** — organically runs the full RRR/mapyde chain (MadGraph → Pythia → Delphes →
Rivet/SimpleAnalysis → pyhf) and returns the model's signal as a **2-D mass-plane exclusion contour
overlaid on the published figure** + the **(mapyde−ATLAS)/ATLAS relative-difference color map** (RRR Fig 3).

## The canonical proof (non-substitutable)
The workflow self-recreating the **entire EwkCompressed2018** analysis (ATLAS-SUSY-2018-16 / HEPData
ins1767649) end-to-end, **across a full 2-D mass plane**. Three load-bearing constraints (re-asserted by
the user, 72158dee turn ~2424):
1. **NO VM.** SimpleAnalysis runs **natively** on this laptop (proven: native MadGraph 5k evts/44s;
   native SimpleAnalysis 141/141 SRs bit-for-bit; full native run reproduced the container observed
   µ95 to **0.51%**). The docs must present native as **THE default** everywhere, not the VM/container.
2. **The WORKFLOW drives it organically** — find + fix the blockers in
   instructions/skills/guidelines/processes/toolchain, then a *fresh agent* runs it with no operator help.
3. **A COMPLETE 2-D scan** (full mass plane), **never a single point or a 1-D line**. The product is the
   mass-plane exclusion plot a physicist references.

## THE TRIAL (what "done" looks like)
A fresh agent, given only the docs + "reproduce EwkCompressed2018 vs the slepton-bino model," self-drives:
- the FAITHFUL grid = **ATLAS's own published lattice** (HEPData ins1767649 Fig 44ab = 12 slepton masses
  50–300 GeV × 11 Δm 0.3–40 GeV = **75 points**; RRR scans a comparable grid for its Fig-3 plane).
  Spec `benchmarks/specs/slepton-bino-figure-3-full.json` = the **52 on-grid points with Δm ≥ 2**
  (the sensitive region; Δm < 2 has no soft-lepton sensitivity and native gen is degenerate). NOT a coarse
  12-point demo — that earlier sub-grid was only a capability check. Each point is a full native chain
  (MadGraph→Pythia8→DelphesHepMC3→native SimpleAnalysis(EwkCompressed2018)→sa2json→pyhf → exclusion.json);
  scanning the EXACT ATLAS grid makes the difference map point-for-point (no interpolation). Run with
  per-point disk cleanup (52 × ~6 GB intermediates would blow the disk; keep exclusion.json/txt/config).
- `scan_orchestrator.py plan → launch --backend native --max 4 --go → status → assemble → scan.json`;
- fetches ATLAS ins1767649's **observed contour + per-point σ-UL grid** from HEPData (fetch+reader proven);
- `scan_contour.py --layout grid --atlas-contour … --atlas-limit …` → the **two-panel RRR Fig-3 artifact**:
  (a) the mapyde µ95=1 contour overlaid on ATLAS's published contour; (b) the (mapyde−ATLAS)/ATLAS color map.
- **Feasibility (this host):** measured full-chain native point ≈ **30–50 min** wall (NOT the MG-only
  "minutes"); parallel (`--max 4`) + per-point disk cleanup → the **52-point ATLAS grid ≈ ~10–14 h
  (overnight)**, no VM, on this laptop. A coarse subset is hours; a denser-than-published plane is cluster
  work (REANA/batch). The legacy container backend (~9 h/point, sequential) is infeasible here.
- **Success = (1)** the grid runs across ≥2 distinct m_parent (today only m=150 exists); **(2)** the
  two-panel artifact renders with ATLAS overlaid + diff map; **(3)** a clean-room fresh-agent re-run
  reaches it with **zero operator intervention** — that, and only that, flips self-drive "partial → yes".

## STATUS (2026-06-17) — SUPERSEDED 2026-07-06; kept for the record, see the current block below
Built + verified: the native VM-free pipeline; the 2-D grid spec (12 pts, ready); the grid renderer +
difference-map + HEPData contour/limit fetch (all proven **on the 1-D slice today**). NOT done: the 2-D
grid has **never been launched** — only a 1-D m=150 slice (`trial-runs/2026-06-16_sleptonscan_m150_SCAN`)
was assembled. **The single most important correction: stop enabling/diagnosing and RUN THE 2-D TRIAL.**

## STATUS (2026-07-06 — CURRENT)
The 2-D trial is **DONE**: the 52/52-point native fig3 scan completed (launched 2026-06-18; NLO+NLL
renorm + comparison-basis rebase 2026-07-04; `trial-runs/sleptonscan_fig3_SCAN`) — the two-panel RRR
Fig-3 artifact is rendered vs the published ATLAS contour, median same-basis residual
|(mapyde−ATLAS)/ATLAS| = **26%** (→ **24.9%** 2026-07-06 after CR-001 turned the two floored-legacy cells into '×' bounds — 50 honest ref-matched cells; scan DEVIATIONS.md has the entry). Critical-path items 1–3 below are done; items 4 (clean-room
self-drive) and 5 (native generality) remain, tracked as CR-006/CR-005 in `docs/development/change-registry.md`
(the residual's only lever = the deferred CR-004 rescan). The physicist-facing layer (INITIATE/check-ins/
verification panel) has shipped; **the active workstream is `docs/development/history/operability-charter.md` (v1.1)**.

## Critical path (do in order; don't let anything else delay the trial)
1. **Doc reconciliation (concern 1).** Make native the SINGLE default at the step-4 SimpleAnalysis
   entrypoint (not just step-8): rewrite `steps/04-analyze.md` Option B to lead with the native backend
   (`reference/native-pipeline.md`) and demote `analysis-simpleanalysis/` to the legacy/other-analysis
   fallback; banner `analysis-simpleanalysis/README.md` as LEGACY; scope every "engine = podman
   (required)" to "container backend only"; fix `choosing-routine.md:9`, `example-simpleanalysis-path.md:10`,
   `SESSION-MANUAL.md:37`. **Rewrite `checklists/scan-and-contour.md:21-22`** (the stale "amd64 emulation,
   1-D line is the local ceiling" guideline — it reintroduces BOTH the VM cost model AND the 1-D drift) to
   match `08-scan.md` (native, parallel, coarse 2-D grid in hours). Correct `08-scan.md:98` per-point
   timing (MG-only "minutes" → measured full-chain ~30–50 min). Re-grep `docs/workflow/` for
   `podman|VM|container|emulat|amd64` → every remaining hit must be explicitly tagged legacy/fallback.
2. **Wire the ATLAS-grid fetch into the numbered path (concern 3 enablement).** Add an explicit step-6
   sub-task to fetch ins1767649's observed contour + per-point σ-UL grid; bake the exact output paths into
   the fig3_coarse example so `--atlas-contour/--atlas-limit` run with zero operator input.
3. **RUN THE TRIAL (concern 3 — the proof).** Execute the 12-point 2-D grid natively (`--max 4`), assemble,
   render the two-panel artifact, write a dated `RESULT.md` with honest coverage (n_done/n_planned).
4. **Re-run the fresh-agent self-drive audit (concern 2)** from a clean state, zero intervention — the
   genuine "partial → yes". Fix whatever it stalls on (docs only).
5. **DEFERRED, scheduled separately (concern 2b — generality, NOT on the EwkCompressed2018 critical path):**
   generalize `native_simpleanalysis.py` + `prepare_native_slepton.py` beyond slepton so "native default"
   stops silently meaning "this one analysis only." Slepton is already covered for the canonical proof.
   **Trigger recorded 2026-07-08 (CR-005, Task 8.2):** the common cut-based case already generalized
   (`native_sa_generic.py`, BUILT + selftested); the remaining bit-parity validation against a
   container SA run stays deferred until (a) a real physics request routes to a cut-based non-RJR
   SA analysis, or (b) the heavy-gen/container defer lifts generally — either way run the
   LIMITATIONS-TRIAGE #14 falsification test, contract row first.

## Deferred-item triggers (recorded 2026-07-08, Task 8 — doc-only)
Two audit-flagged capabilities are intentionally DEFERRED pending a trigger, not abandoned; full
detail lives in `docs/development/change-registry.md` CR-020 and CR-005. Recorded here per PLAN-OF-RECORD's
role as the intent/trigger record (state itself stays owned by `capability-matrix.json`):
- **LLP effmap D2 truth-event closure (CR-020, I6):** the D2 per-object efficiency-map engine is
  built and its statistics-half validated on real data; the remaining truth-event-maker +
  decay-radius sampler + ≥2 published (m,cτ) point R5 closure is EVENT GENERATION, deferred until
  (a) a dedicated validation-first session, or (b) a real physicist LLP/disappearing-track (T2)
  request — via CHECK-IN 1 + the dry→smoke→full ladder.
- **Native-SA generalization beyond the common cut-based case (CR-005, I9):** see critical-path
  item 5 above.

## Drift to keep corrected (the user flagged these; they are real, verified in the tree)
- VM hedging: native must be the default at EVERY SimpleAnalysis entrypoint, not just step 8.
- 1-D collapse: the deliverable is the 2-D plane; the 1-D line is only a partial PoC.
- "can WE force it" vs "can the WORKFLOW drive it": the bar is organic self-drive by a fresh agent.
- Over-indexing: keep the harness broad; the slepton-only native backend is the generality ceiling (item 5).

## 2026-07-06 — planning surface handoff (supersession block)
The mission above (the EwkCompressed2018 2-D reproduction) is DONE and recorded
(`trial-runs/sleptonscan_fig3_SCAN/`); the charter (operability) is executed through P3 with P4
live evals + P5 remaining. Forward planning — the demand-side capability audit against the seven
real physicist prompts, the gap taxonomy, and the W1/W2/W3 wave sequencing — now lives in
**`docs/development/roadmap.md`**. CURRENT readiness/capability STATE is owned by
`benchmarks/capabilities.json` (via `audit.py`/`AUDIT.md`); this plan and the roadmap carry
MISSION and SEQUENCING, not state.
