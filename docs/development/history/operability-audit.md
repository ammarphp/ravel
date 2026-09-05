# AUDIT-OPERABILITY — the P1 findings register (severity-ranked) + the P2 worklist

> Deliverable of `docs/development/history/operability-charter.md` §5-P1, produced 2026-07-06 by six parallel
> read-only auditors over disjoint surfaces (A1 routing/export · A2 workflow docs · A3 framework
> state · A4 git hygiene · A5 skills+trial-gaps · A6 code bugs+memory), each finding verified on
> disk. Severity: **S0** blocks the charter §8 success criterion (a fresh cheap-model session
> routing itself); **S1** misroutes/misleads an agent or corrupts results; **S2** stale or
> contradictory state; **S3** low / already-fixed closures. IDs are stable — cite them in commits.

## Verdict (one paragraph)

The physics layer is healthy: native-default, per-point timing, scan-reuse, step-8/9 tool naming,
verify_pack + lhe_check prose wiring, PLAN-OF-RECORD currency, and the registry/catalogue seeding
all verify on disk (closures in §5). The **agent control layer** is where the charter feared:
routing dead-ends for the executing agent (S0-1), no weak-model policy behind 62 [Opus] tags
(S0-2), a shipped skill that steers cheap sessions around the intake/scan/verify gates (S0-3), and
a distribution whose orientation docs are ~half dangling references (S0-4). Both result-quality
bugs (CR-001/CR-002) are confirmed live with precise minimal fixes; git tracking inverts the
curation policy on three axes (~87 MB junk tracked, the flagship scan's per-point evidence
untracked); and all four §4d memory-only facts are confirmed homeless on disk.

## 1. S0 — blocks the §8 success criterion

- **S0-1 = A2-01** INITIATE.md routes the physicist but dead-ends the AGENT: no pointer to
  WORKFLOW.md/steps/check-in composition (INITIATE.md:3; CLAUDE.md:12 "read INITIATE.md and
  NOTHING else"). A cheap session must guess the procedure — failure F1 live.
  → Owner: `physicist-intake` skill + INITIATE.md "AGENT EXECUTING THIS" block + route_prompt.py.
- **S0-2 = A2-02** 62 `[Opus]` tags in 23 workflow files, zero defined weak-model behavior (F3
  live). Full per-tag classification (escalate / script-assisted / proceed-with-flag) is in the
  A2 transcript and drives the §6 policy rewrite.
  → Owner: model-tier policy rewrite ([judgment] tags) + skills carry escalation criteria.
- **S0-3 = A5-01** `new-analysis` skill routes steps 3→7 (omits scan + verification), never
  mentions CHECK-IN 1 at its own firing boundary (SKILL.md:29), and its trigger matches the P4
  physicist prompts — it actively reinstalls failure F4 and bypasses the compute block.
  → Owner: P2c skill fix + upstream physicist-intake/route-analysis skills.
- **S0-4 = A1-01** The shipped dist's routing docs are riddled with dangling refs: CLAUDE.md dev
  route reads ORCHESTRATION.md (not shipped); DIRECTORY.md is ~half dead rows in the dist;
  README points at unshipped trees. A dist dev session dead-ends on its first mandated read.
  → Owner: check_agent_surface.py `--stage` dead-ref assertion + export-script + doc edits.

## 2. S1 — misroutes agents or corrupts results (29)

**Code / result quality**
- **A6-01** CR-001 verified: `pyhf_exclude.py` brackets µ upward only (:139-144); `_cross()`
  no-crossing fallback returns the grid **ceiling** (:108) — wrong end for hyper-excluded points;
  `at_cap` misses it (:171) so the floor is **silent**. Proof: `sleptonscan_fig3_m60_dm5`
  exclusion.json (obs=1.0, flat band, at_poi_cap=false). Fix: downward bracket + low-end
  fallback + `at_mu_floor` flag + regression case.
- **A6-02** CR-002 verified: `prepare_native_slepton.py` applies exactly six run-card keys
  (:70-75); no code path reads `[madgraph.run.options]` → ptj1min 50→0, the measured ×2.14
  σ_tag drift. Fix: apply the block fail-loud (setkey miss = die).
- **A6-08** The floor **propagates unchecked**: `scan_orchestrator.py harvest_point` (:521-528)
  ingests floored/capped limits with no quality tag; renorm/rebase scaled a floored 1.0 into a
  plausible 0.86. Fix with CR-001: harvest refuses/tags `at_poi_cap|at_mu_floor` points;
  scan_contour hatches them.
- **A6-03** Both pipeline drivers skip the mandatory pre-shower lhe_check gate (§4b): zero
  `lhe_check` hits in `run-pipeline-native.sh` / `run-pipeline.sh` — the gate exists only in
  prose. Fix: insert the gate stage between madgraph and pythia in both drivers.
- **A5-06** Five recorded trial gaps are harness-CODE fixes with **no owner and no registry
  entry**: lhe_check width-aware tolerance (G-CMS-05), hepdata_fetch figure_index regex can't
  match `fig_01`-style names (G-AD-04, verified live at :123), result_pack `--stat-mode` lacks
  sensitivity/expected-only enum (G-AD-11b), figure_target multi-panel enumeration (G-CMS-04
  code half), internal-process pre-shower guard (G-AD-10b). → Register CR-007..CR-011; fix the
  first three now, defer the two design items.

**Routing / policy surfaces**
- **A1-02** Environment bootstrap does not ship: step-01, drivers, CLAUDE.md all point at
  unshipped `stages/` (scripts/ is small tracked code; build/ is the regenerable 10 GB).
- **A1-03 = A3-01** Shipped benchmark gate can never run: 18/84 cases.json inputs untracked
  (~1.4 MB); BENCHMARK.md's fresh-clone recipe requires hours of MC. → Ship the minimal
  cert-input subset (gitignore exceptions) in the dev repo; dist presents the gate as recorded
  evidence + export smoke-run.
- **A1-04** CLAUDE.md vs AGENTS.md dev read-list disagreement (ORCHESTRATION-first vs
  DIRECTORY-first) though AGENTS.md pledges they never disagree. → Canonical dist-safe order:
  **DIRECTORY.md → docs/development/status.md → docs/development/history/mission-and-plan.md** (+ optional dev-only
  ORCHESTRATION.md), asserted by check_agent_surface.py.
- **A1-05 = A3-03** Readiness numbers disagree on disk NOW: regenerated AUDIT.md 97% vs 100%
  claims in README:24 / STATUS:9 / DIRECTORY:65 / CLAUDE.md; "8 steps" survives in STATUS:28 +
  docs/workflow/orchestration.md. → Fix the audit instrument (A3-02), regenerate, update all,
  then assert agreement mechanically.
- **A3-02** audit.py mis-scores survey-mode runs (R2 0.77 / R5 0.85 WARNs) and its `20*` glob
  makes the flagship fig3 scan invisible (:49). Precise rule change (stricter, no inflation):
  widen glob to RESULT.md-bearing dirs; survey bucket gated on an explicit
  `Deliverable: survey — no exclusion claimed` header AND no stat artifact AND no exclusion
  claim; R5 σ-source denominator = runs that generated signal MC. Requires Deliverable headers
  in 3 RESULT.mds.
- **A1-06** DISTRIBUTION.md ↔ export script drift both directions: `shared/` publishable but
  never copied; the .claude skills-EXPORT flip unrecorded (still "decide at publication",
  :41-42); framework rows unclassified; PRODUCT-CONTRACT/ROUTING-EVALS/AUDIT-OPERABILITY not
  pre-registered (will silently not ship).
- **A2-06** verification-panel.md requires FAILURE-CATALOGUE.md but DISTRIBUTION.md's framework
  whitelist row omits it (the export *script* ships it — policy doc lags).
- **A1-07 = A5-08** Export hygiene grep scans only staged docs/workflow/ — the dated dev-style
  example in shipped new-analysis (`2026-06-10_CMS_2017_I1594909_gluino-pair`, a fabricated
  dev-NAMING leak) sails through. → Extend grep to $STAGE/.claude + neutral placeholder.
- **A2-03** SESSION-MANUAL.md is a second physicist entrypoint whose paste-ready prompt stops at
  step 7 (single point, no panel, no check-ins) — reinstalls F4.
- **A2-04** CHECK-IN 1 cost estimate is prose-only; cost_preflight.py absent (F5 live).
- **A2-05** No disk-budget/cleanup rule in step 8; native driver keeps multi-GB HepMC/LHE per
  point — a parallel scan can exhaust the disk. → run-scan skill + 08-scan/scan-and-contour
  lines (+ optional driver --cleanup).
- **A5-02** `.agents/skills` mirror does not exist; AGENTS.md points at it; no sync script.
- **A5-03** run-stage skill: Rivet-only analyze; hand-read-the-LHE instead of lhe_check.py.
- **A5-04** certify skill routes per-run certification to validate_cutflow.py (one-time-per-
  routine tool); never mentions certify_acceptance.py / detector-fidelity gate / verify_pack.
- **A5-05** embed-and-commit lacks the CHANGES-REGISTRY step though the registry names it as its
  enforcement point — §7 is prose-only until this lands.
- **A5-07** The 23 trial gaps extracted + owner-mapped (full map §6 below).
- **A3-04** KNOWN-LIMITATIONS.md stale: zero native-backend mention, presents the container as
  THE SimpleAnalysis path (:124-125), no shape-fit boundary, no CR-001/002 cross-refs.
- **A4-01** All 59 scan-point dirs' curated outputs 100% untracked — the native backend writes
  `output/` (singular) which `.gitignore:47` dir-excludes; RESULT.md numbers are one
  `git clean -fd` from unverifiable.
- **A4-02** Inverted tracking: 75.2 MB regenerable feature CSVs tracked; the 11 hand-written
  build/ analysis sources that regenerate them ignored.
- **A4-03** Unscoped `*.log/*.out` (LaTeX block) swallow the trial-run logs the .gitignore:38
  comment says to keep — comment and rules must agree.
- **A4-04** The consolidated gitignore remediation spec (diff + untrack ~87 MB + track ~7 MB) —
  execute as ONE commit so regeneration paths never lapse.
- **A6-04** §4d-a homeless: the arXiv:2408.00049 BLOCKED(statistical-paradigm) precedent exists
  only in operator memory — P4 prompt 4 targets that exact paper. → `framework/interrogations/
  generality.md` (note: export ships `framework/interrogations/`).
- **A6-05** §4d-c homeless: publication remote + gh identity nowhere on disk; `git remote -v`
  EMPTY; export --push takes the URL as an argument with no recorded default. → dev-only
  `framework/OPS-PUBLISHING.md` + DISTRIBUTION.md dev-only row.

## 3. S2 — stale/contradictory state (30, condensed)

- **A1-08** Placeholder LICENSE + `example.invalid` CITATION URL ship verbatim; export needs a
  fail-loud placeholder guard (publication decision stays with the maintainer).
- **A1-09** docs/workflow/orchestration.md: "8 steps" ×2 + describes SA path as containerized.
- **A1-10** Root ORCHESTRATION.md is a 2026-06-09-era session map (only Session 0 done, no
  charter/PLAN-OF-RECORD, contradicts the session fork). → dated CURRENT block + demote from
  first-read (A1-04).
- **A1-11** AGENTS.md promises `.agents/skills` "where present" — never exists anywhere.
- **A1-12** STATUS.md staleness cluster: "8 steps" (:28), dangling dev-only refs, self-owed
  session-log entries (:89-90), 25-day-stale "+3j parting job".
- **A1-13** pedagogical/design-review (the 140-pp design review) entirely untracked while
  DIRECTORY/STATUS present it as a principal artifact. → track .tex sources.
- **A1-14** DIRECTORY.md missing rows for 4 on-disk run dirs + docs/workflow/reference/native-pipeline.md.
- **A2-07** No checkpoint/RESUME rule anywhere in docs/workflow/ (§4c gap) despite hours-scale scans.
- **A2-08** DISTRIBUTION.md still offers "exclude .claude/ entirely" — contradicts the taken
  export decision.
- **A2-09** Context cost: ~15k tokens before first action, ~49k full path (table §7); heaviest
  files are mostly movable to skills/scripts.
- **A2-10** `$CONDA` used in every step but defined only in step 01.
- **A3-05** STATUS session log missing the four landmark commits; both 2026-07-06 physicist-trial
  run dirs fully untracked (one feeds AUDIT.md's own R2/R5 lists).
- **A3-06** The "+3j parting job" died 2026-06-11 22:19 (log mtimes; no live process); STATUS
  still queues it; PLAN.json says ALIVE. → disposition line.
- **A3-07** `2026-07-06_ttthreshold…` run dir has NO RESULT.md (convention violation; invisible
  to audit). → stub with Deliverable header.
- **A3-08** Confirmed: fig3 SCAN-dir artifacts tracked; per-point curated trio untracked (fix
  via A4-04).
- **A3-09/A3-10/A3-11** CR-001/002/003 registry statuses accurate (all OPEN); CR-003's cited
  line is 96 not 95; the leased push's `2>/dev/null` hides failure reasons — drop it.
- **A4-05** `published/` ignore patterns are single-level: 77 fetchable PDFs (8.8 MB) tracked;
  same class in subdirs is status noise. → `**`-ify + untrack.
- **A4-06** 35 files >1 MB carry 69% of tracked payload; all but ~4 MB regenerable/fetchable;
  KEEP the 19 HEPData patchset JSONs (21.9 MB) — they pin recorded exclusions (decision).
- **A4-07** The native-backend validation run (2026-06-16_slepton_200-150_native) has NO
  RESULT.md and one tracked file — the run that established "bit-for-bit" is uncurated.
  → author RESULT.md + track its logs/output evidence chain.
- **A4-08** All 66 untracked paths categorized: 62 missing-commit/mixed, 4 missing-ignore,
  0 quarantine. The repo is under-tracked, not over-dirty.
- **A4-09** The two curation-policy statements (CLAUDE.md vs .gitignore:38 comment) disagree
  with each other AND with reality — rewrite both in the gitignore commit.
- **A5-09** new-analysis skeleton creates no DEVIATIONS.md (nor RESUME.md) stub though the
  ledger is mandatory and verify_pack checks it.
- **A5-10** run-stage's primary MadGraph idiom is a broken path (`$CONDA_PREFIX/../mg5amcnlo`
  does not exist; correct absolute path is in 03-generate.md).
- **A5-11** run-stage bare "R5" tag — defect confirmed but charter's "dangling once exported"
  overstated (STATUS.md + audit.py ship); fix = spell out inline.
- **A5-14** Trigger quality: run-stage description omits SA/Delphes/native keywords;
  new-analysis description collides with the INITIATE physicist route.
- **A6-06** §4d-b homeless: Delphes2SA writes el/mu_id=0x7FFFFFFF so every SA lepton-ID cut is a
  deliberate no-op — rationale nowhere in repo files; a maintainer would "fix in" ID cuts and
  silently break the 141/141 parity. → native_simpleanalysis.py docstring + native-pipeline.md.
- **A6-07** §4d-d homeless: the archetype census (4 archetypes / 94% coverage, 2026-06-15) —
  the number that settled the design — recorded nowhere. → docs/reference/scope.md + one-line
  figure_manifest.py docstring pointer.
- **A6-09** native-pipeline.md presents the native card prep as parity-complete — no CR-002
  deviation note (until the fix lands, then state run.options is applied fail-loud).

## 4. S3 + notable arithmetic (17, condensed)

- **A4-10** No secrets/credentials tracked; /Users paths only in dev-only or SANITIZE-listed files.
- **A4-11** Corrections for the registry: **53** (not 52) fig3 point dirs (+6 m150 = 59; the
  extra is m150_dm25p7, the reference-crossing rebase point — include it in the track list);
  75.196 MB CSVs exact; 66 untracked exact.
- **A2-12** Timing claims fixed everywhere except one bullet: 08-scan.md:66-67 "a point is
  minutes" → "~30–50 min".
- **A2-14** Prompt-form drift: INITIATE mandates "Initiate:" prefix; CLAUDE.md routes without
  it — the intake skill trigger must match prefix-less physics asks.
- **A3-12** PLAN-OF-RECORD drift list is present-tense for now-guarded drifts (optional tag).

## 5. Charter claims CLOSED by this audit (already fixed on disk — do not rebuild)

- Native is THE default at every SimpleAnalysis entrypoint; no surviving "podman (required)"
  language (A2-11; commit 29e09c4).
- Per-point timing ~30–50 min full-chain everywhere except the one 08-scan bullet (A2-12).
- verify_pack.py explicitly wired into step 9 + panel checklist, fail-loud (A6-10).
- lhe_check.py wired as mandatory pre-shower gate in the PROSE layer (A6-11; script layer open
  as A6-03).
- PLAN-OF-RECORD currency: dated supersession block + critical-path items 1-3 verified on disk
  (A3-12).
- CHANGES-REGISTRY + FAILURE-CATALOGUE exist, seeded per v1.1; CR statuses accurate (A3-13).
- README "9 steps", AUDIT.md regenerated "9 step files", registry+catalogue in export whitelist,
  skills/rules export flip live (A1-15).
- figure_target same-role merge bug (G-CMS-03) fixed in ad638d6 — regression test + registry
  entry still owed (A5-12).
- Dead-path scan of docs/workflow/ clean: all 35 referenced infra scripts/specs/templates exist
  (A2-13). directory-keeper + evaluate-suggestion materially current (A5-13).
- Harness inventory complete; the four P2 scripts cleanly absent (A6-12); native-pipeline.md ↔
  driver parity confirmed (A6-13).

## 6. The 23 recorded trial gaps → owners (A5-07)

| Gap | One line | Owner |
|---|---|---|
| G-CMS-01 | No no-routine path anywhere (custom particle-level improvised) | route-analysis skill + PRODUCT-CONTRACT `no_routine` + embed Option C |
| G-CMS-02 | routine_fetch 0/0 dead end; podman hint | route-analysis skill + 02-inputs.md edit |
| G-CMS-03 | figure_target same-role merge | FIXED ad638d6; test+CR entry owed |
| G-CMS-04 | Multi-panel figures not first-class | figure-contract skill (code half → CR, deferred) |
| G-CMS-05 | lhe_check false-FAIL on wide resonances | CR + width-aware --tolerance fix |
| G-CMS-06 | No continuum-background generation recipe (the cost driver) | 03-generate.md edit + cost-preflight skill |
| G-CMS-07 | figure_manifest lacks sensitivity-comparison archetype | figure-contract skill |
| G-CMS-08 | plot-naming/criteria assume routine+HEPData ids | plot-naming/plot-criteria edits |
| G-CMS-09 | Step-7 stats pyhf-only; no S/√B recipe | PRODUCT-CONTRACT stat modes + 07-exclude.md edit |
| G-CMS-10 | poppler/pdftoppm unprovisioned | 01-environment.md edit |
| G-CMS-11 | arXiv→Inspire resolution hole | physicist-intake skill (+02-inputs.md) |
| G-AD-01 | No entry point for interest-level prompts | physicist-intake skill |
| G-AD-02 | routine_fetch 0/0 reconfirmed | = G-CMS-02 |
| G-AD-03 | new-analysis can't scaffold an unresolved run | new-analysis skill fix |
| G-AD-04 | hepdata_fetch figure_index regex misses `fig_01` style | CR + regex fix |
| G-AD-05 | No-HEPData digitized-anchor degraded mode | PRODUCT-CONTRACT fidelity labels + 06-acquire-data.md |
| G-AD-06 | No literature-survey tooling | physicist-intake skill |
| G-AD-07 | No-routine method only a dev-trial precedent | route-analysis skill + 04-analyze.md (Option C) |
| G-AD-08 | figure_manifest ESCAPE reconfirmed | = G-CMS-07 |
| G-AD-09 | Plot naming/criteria reconfirmed | = G-CMS-08 |
| G-AD-10 | Internal-process generation undocumented; no pre-shower guard | 03-generate.md edit + run-stage skill (guard half → CR, deferred) |
| G-AD-11 | Stats beyond pyhf improvised; result_pack enum gap | PRODUCT-CONTRACT + CR + enum fix |
| G-AD-12 | MG procdir generate_events exit-0 failure outside env | run-stage skill fix + 03-generate.md |

## 7. Context-cost audit (A2-09; bytes → est. tokens at /4)

Minimum before first action (CLAUDE.md + auto rules + INITIATE + WORKFLOW + steps 01-02 +
check-ins + choosing-routine + model-cards + figure-contract) = **59.4 KB ≈ 14.9k tokens**;
full inner loop through step 7 ≈ 160 KB ≈ 40k; full path incl. scan+verify ≈ **196 KB ≈ 49k**.
Heaviest: 05-visualize.md 17.8 KB (renderer blocks → already encoded in scripts; skill),
detector-fidelity.md 14.7 KB (census rationale + hand-digitize recipe → reference),
08-scan.md 14.4 KB (two-spaces essay + normalization physics duplicated in scan-and-contour.md
→ run-scan skill). Doc slimming is P3-optional; the skills carry the movable content first.

## 8. The P2 worklist (ordered; registry entry per commit)

1. ~~This file~~ (P1 deliverable).
2. **P2d code fixes**: CR-001 (pyhf_exclude downward bracket + `at_mu_floor` + harvest guard +
   contour flagging + benchmark regression case) · CR-002 (prep applies run.options fail-loud +
   native-pipeline.md note) · CR-003 (export push fetch-before-lease, drop 2>/dev/null) ·
   CR-007..CR-011 registrations (lhe_check tolerance, hepdata_fetch regex, result_pack enum —
   fixed now; figure-panel enumeration, internal-process guard — deferred) · lhe_check gate into
   both drivers (A6-03).
3. **docs/reference/scope.md** (charter §4.2 + archetype census + stat/fidelity taxonomy).
4. **P2a harness**: task_contract schema + route_prompt.py + validate_task_contract.py +
   cost_preflight.py + check_agent_surface.py (assertions per S0-4/A1-04/A1-05/A5-02/step-count/
   hygiene/staged-tree modes).
5. **P2c skills**: seven new (physicist-intake, route-analysis, run-scan, figure-contract,
   verification-panel, cost-preflight, postmortem-capture) + six fixed per §2/§3 + sync script +
   .agents mirror.
6. **Model-tier policy**: [Opus] → [judgment]+behavior across docs/workflow/ (A2-02 classification).
7. **Memory landings**: docs/research/reviews/generality.md · 0x7FFFFFFF rationale (docstring
   + native-pipeline.md) · framework/OPS-PUBLISHING.md (dev-only).
8. **Gitignore remediation** (A4-04 spec, one commit) + curation statements + RESULT.md stubs
   (ttthreshold A3-07, native-validation run A4-07) + design-review sources + 07-06 run records.
9. **Audit instrument**: audit.py survey bucket + glob widen + R5 denominator (A3-02) +
   Deliverable headers ×3 + regenerate AUDIT.md + readiness/step-count agreement everywhere +
   benchmark cert-input subset + BENCHMARK.md fresh-clone rewrite (A1-03/A3-01).
10. **State docs**: STATUS.md (session log + +3j disposition + refs) · KNOWN-LIMITATIONS.md ·
    ORCHESTRATION.md ×2 (dated block; 9 steps) · CLAUDE/AGENTS canonical read order ·
    SESSION-MANUAL.md rewrite · INITIATE.md agent block · DISTRIBUTION.md + export script
    (hygiene scope, placeholder guard, smoke-run, .agents, new-file whitelist) · 08-scan
    disk/RESUME/minutes lines · $CONDA lines · DIRECTORY.md (directory-keeper).

P3 then reruns: check_agent_surface.py green → benchmark --fast green → reconciliation greps
(podman|VM|container|emulat|amd64 tagged legacy; hygiene grep incl. .claude) → export dry-run.
