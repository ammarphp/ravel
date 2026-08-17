# Interrogation — data acquisition (Session 2 / S3, 2026-06-09)

_Defects → fixes → **measured** before/after. Referees: `framework/audit.py` (before: **96%**,
R2 0.67 WARN, R5 0.82 WARN → after: **100%**, 13/13 PASS) and `run_benchmark.py --full`
(exit 0 before and after; all gate metrics unchanged — the tables_dir switch is the same HEPData
record, byte-identical files by md5)._

## Defects found (Wave-1 diagnosis, [Opus]-verified here)

| ID | Sev | Where | Finding | Status |
|---|---|---|---|---|
| D-DA-001 | major | C1N2 run dir | No `provenance.json` — and this is the run whose σ-convention is the known trap: the on-disk `outputs/nlo_xsec.json` records the unphysical single-charge k=0.421, one naive read away from misuse, with no machine-readable stamp saying so | **FIXED**: stamp written from the LHE banner (σ both charges 0.31338±0.00028 pb per-subprocess, pdlabel/lhaid, dynamical scale, k=1.29 + an explicit warning field about the 0.421 artifact, fixed-param-card md5) |
| D-DA-002 | major | squark-merged run dir | No `provenance.json`; RESULT.md cited the *unmerged* run's µ₉₅=0.28 and "k≈1.08" (the flavour-sum trap) — stale after S1 | **FIXED**: stamp (matched σ 0.307 pb + pre-veto banner 0.59933±0.00072 pb, matching check \|0.307/0.3044−1\|≈0.9%≤5%, full MLM settings, k=0.855) + dated addendum |
| D-DA-003 | minor | squark-pair/gluino stamps | Pre-existing stamps under-specify generation: no PDF set (pdlabel/lhaid), no dynamical-scale setting, no MG integration error on σ | **DEFERRED** (outside the approved list; additive backfill, benchmark pins their `sigma_pb`) — the two new stamps set the enriched schema |
| D-DA-004 | major | `cases.json` cert.tables_dir | squark-pair run had NO HEPData tables of its own (manifest only); BOTH squark benchmark cases borrowed the **gluino** run's tables with zero lineage note — moving/regenerating the gluino run would break the squark certs confusingly | **FIXED**: refetched ins1458270 into the squark-pair run (105 tables, verified); squark case → its own copy, merged case → the sibling squark-pair copy with an explicit lineage line in `published.sources`; gluino keeps its own. md5-verified byte-identical → gate numbers cannot move (and didn't) |
| D-DA-005 | major | R2 coverage | merged-squark exclusion existed only as a fresh `.work/` artifact per gate run, never a run deliverable — audit R2 0.67 WARN; the run record pointed at another run's limit | **FIXED**: promoted `outputs/pyhf_exclusion/` (`pyhf_exclude.py counting --srs sr_yields_fitted.json --sigma-scale 0.855`) → µ₉₅(obs) **0.22580**, matching the locked baseline 0.225796 |
| D-DA-006 | major | RESULT.md σ statements | gluino RESULT.md carried NO higher-order σ statement (R5 σ-source miss); squark-pair claimed the LO limit "mildly conservative" — wrong **direction** (k=0.862<1 → mildly aggressive); merged claimed k≈1.08 | **FIXED**: dated `## Session-2 addendum (2026-06-09)` sections appended (existing content never rewritten); each names σ_LO (banner, with error), the WG NLO+NNLL value, k, and where the scored number lives vs the preserved original artifact |
| D-DA-007 | crit | `hepdata_fetch.py --tables` | Silent-failure family: exit 0 on hepdata-cli missing, on download exception, on partial download; no check that `submission.yaml` exists/parses or that declared data_files exist — a corrupt `tables/` dir would feed `validate_cutflow.py` and count in the audit | **FIXED**: 3-step post-download verification (submission.yaml exists → parses + declares tables → every declared data_file non-empty) + classification summary in the manifest; any error → loud stderr block + **exit 1** |
| D-DA-008 | major | `hepdata_fetch.py` discovery | JSON-API failure path wrote a partial manifest and exited 0 ("no silent corruption" violated at the front door) | **FIXED**: loud ERROR + exit 1 (manifest still written for forensics) |
| D-DA-009 | major | workflow hierarchy | The data-source ladder lacked the **rank-2.5** source — published CR-fitted SR backgrounds (the analysis results table, e.g. its Table 6 b±δb) — which S1 *measured* as the entire 1.49×→1.01 squark s95 recovery; `rivet_ref_yields.py --fitted-bkg` existed but was invisible in `workflow/`; the observed-n≡REF cross-check requirement was unstated | **FIXED**: checklist table row + "Preferred b±δb" paragraph (`checklists/data-acquisition.md`) + step-6.2 paragraph (`steps/06-acquire-data.md`); hygiene grep stays clean (DISTRIBUTION.md only) |
| D-DA-010 | minor | `audit.py` c_provenance | σ-source credit was a binary RESULT.md regex: ignored `provenance.json` `sigma_scale_k`, and conflated "σ-source undocumented" with "deliberately LO-only" (both scored 0) | **FIXED**: full credit iff an NLO/NNLL/k statement exists OR the stamp carries k≠1; pure-LO runs get half credit + a named "LO-only" evidence line (honest, not punitive) |
| D-DA-011 | major | `audit.py` c_completedata | Counted ANY file under the tables glob — a corrupt/partial fetch scored identically to a verified one (the audit-side twin of D-DA-007) | **FIXED**: every found `submission.yaml` must `yaml.safe_load_all` + declare tables; unparseable → not counted + WARN evidence; all-corrupt → no complete-data credit. Measured: 4/4 parse, 365 tables; corrupt-file branch unit-tested on a malformed YAML |
| D-DA-012 | minor | input-spec conventions | Naming divergence across certified inputs: `sr_spec.json` counters vs pyhf channel names (`SR3L[SR3L_Low]`) vs fitted-yields names — documented-not-renamed: the certified inputs are **immutable** (renaming would invalidate certified artifacts + locked baselines); `normalize_sr()` in `run_benchmark.py` bridges | **DOCUMENTED** (here); unified spec convention → Session 3 |

Also applied under the audit-honesty umbrella: the **1k slepton smoke test** (superseded by the 50k
run) was polluting the audit's `trial-runs/20*` denominator — `git mv` to
`trial-runs/_archive/2026-06-06_slepton_200-150_1k` (stays tracked; rationale in
`trial-runs/_archive/README.md`; DIRECTORY.md reconciled).

## Fixes applied — measured before/after

| Fix | Before | After | Evidence |
|---|---|---|---|
| Provenance stamps 5/5 + σ-source addenda + merged-exclusion promotion + 1k archive | audit 96%: R2 **0.67** WARN (4/6 runs with exclusion), R5 **0.82** WARN (3/6 stamps; gluino no σ-source) | audit **100%**: R2 **1.00** (5/5), R5 **1.00** (5/5 stamps, σ-source credit 5/5, LO-only: none), all 13 dimensions PASS | `framework/AUDIT.md` |
| Merged exclusion artifact | none in run dir (benchmark recomputed into `.work/` only) | `outputs/pyhf_exclusion/exclusion.json` µ₉₅(obs)=**0.22580** vs locked baseline 0.225796 (Δ<0.01%) | run dir + gate |
| hepdata_fetch hardening + squark refetch | exit 0 on every failure mode; squark-pair: manifest only, 0 tables | ins1458270 → squark-pair: **105 tables, verified parse**, classified (acc-eff:21, acceptance:21, sr-yields:7), exit 0; negative tests: 404 record → **exit 1**, `--tables` without hepdata-cli → **exit 1** (loud) | fetch logs (this file) |
| cases.json tables_dir re-pin | both squark cases on the gluino run's copy (undocumented lineage) | squark → own verified copy; merged → sibling squark-pair copy + lineage note in `published.sources`; files md5-identical to the gluino copy | `cases.json`; benchmark below |
| audit instrument honesty (c_provenance, c_completedata) | leniencies D-DA-010/011 | LO-only half-credit path (currently unexercised: 5/5 full credit, legitimately — slepton names its k=1.18 source); submission.yaml verification 4/4 (365 tables) | `framework/audit.py`, `AUDIT.md` |
| **Benchmark gate (final, single `--full` run)** | committed `results.json` baseline, 4/4 OK | **exit 0, 4/4 OK; every scored metric identical** (only `generated` + `timing` differ) | `framework/benchmark/results.json` |

## Deferred (with why)

- **Unified SR-spec/yields naming convention** (D-DA-012) → Session 3: certified inputs are
  immutable; `normalize_sr` bridges correctly today; a new convention belongs with the Session-3
  breadth analyses where new specs get written anyway.
- **Download-resume / retry logic** for `hepdata_fetch.py`: current contract is fail-loud +
  refetch-from-scratch — acceptable at HEPData record sizes (~MB); resumable fetch + checksum
  manifest is engineering without fidelity payoff now.
- **Enriching the two pre-existing stamps** (D-DA-003) with pdlabel/lhaid/scale/σ-error: additive
  and low-risk but outside the approved list; the two new stamps define the enriched schema to copy.
- **C1N2 run-dir exclusion artifact stays single-SR (2.13)**: the combined-mode scored value (2.7123)
  lives in `cases.json` + gate results by design (k-authority + scored-mode rules); re-promoting a
  combined artifact into the run dir would duplicate the registry's authority — revisit if a
  published likelihood lands (Phase 2).

## KNOWN-LIMITATIONS updates

- "LO cross-sections" entry rewritten → "Higher-order σ is a flat k-factor, not a recomputation"
  (the old gap is closed for all four benchmark cases; the standing trap is grid
  degeneracy/charge conventions, and k<1 means bare-LO is not automatically conservative).
- "Counting model" entry now points at the published CR-fitted b±δb (rank 2.5,
  `--fitted-bkg`) as the preferred background input, with the measured 1.49×→1.01 justification.
- No new entries needed: the merged run's HEPData lineage is recorded in `cases.json` +
  its `provenance.json`; the C1N2 single-charge k artifact was already covered
  (`BENCHMARK.md`, `cases.json` `_doc`, `.claude/rules/statistics.md`) and is now also in the
  run's stamp.
