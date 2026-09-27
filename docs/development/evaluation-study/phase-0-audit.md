# Evaluation study: Phase 0 audit (WP00, WP01)

Date: 2026-09-25. Branch `evaluation-slice`, created from `89273dfc928917fa43c64d236666679ab3b5efcb`
without source changes. This audit reconciles the external *RAVEL research and implementation
packet* (prepared 2026-09-25 against public commit `79c7aab`) with the actual research checkout.
The packet is a proposed design, not evidence. Nothing in this document is an agent-performance
result. No paid model call, event generation, training, download of physics data or push occurred.

Nine read-only auditors wrote the underlying reports. Each report was then checked by one or two
independent refute-first verifiers. Corrections from verification are folded in below. The raw
reports, verifier verdicts, baseline logs and their SHA-256 values are kept outside the repository
in the private planning area (`research-planning/2026-09-25-ravel-evaluation-phase0/` in the DSRLab
workspace). Scratch experiments are under the ignored `local-runs/evaluation-slice/phase0/`.

## 1. Baseline inventory

| Item | Verified state |
|---|---|
| Active source | `ravel-development` worktree, HEAD `89273df` (2026-09-09), clean; new branch `evaluation-slice` |
| Public distribution | `ravel-public` `79c7aab`, exported **from source `89273df`** (`evidence/export-provenance.json` records the source commit; all 1,161 file bindings match `89273df` blobs) |
| Source identity vs packet baseline | `src/ravel/` identical (105/105 blobs); `benchmarks/governance/` identical (2/2); `scripts/` identical; four other files differ only by declared home-path redaction. All 72 repository paths the packet cites resolve identically. The packet's file-level observations therefore transfer to `89273df`. |
| Runtime differences | The research checkout additionally holds `trial-runs/`, `framework/`, `stages/` and the `ORCHESTRATION.md` sentinel that `tests/unit/conftest.py` uses to select development-only tests. Test counts and evidence resolution must be taken from this checkout, not inferred from the public tree. |
| Historical checkout | `hep-agentic-pipeline` `60b1478`, an ancestor 8 commits behind, with 4 modified and 5 untracked user paths. Untouched. |
| Other branches | No branch has commits newer than `89273df`. `repo-hardening` (`6d01bcb`) diverged in July and carries five unique commits touching export/custody policy; not reconciled here (decision H-07). |
| Host | An Apple-silicon Mac running macOS 15.5. `sandbox-exec` present; no docker/podman on PATH. A Claude Code CLI on PATH (which build to pin is H-04); no standalone Codex CLI on PATH (B-04). |
| Development environment | New ignored `.venv-dev` (Python 3.12.13) from the hash-locked `requirements-replay.lock` plus an editable install, per `CONTRIBUTING.md`. No uproot, torch or native HEP stack. The native toolchain exists only under the historical checkout's ignored build tree. |

## 2. Verified command map and baseline disposition

All commands ran from the research checkout in `.venv-dev` at `89273df`, 2026-09-25.

| Command | Result |
|---|---|
| `python -m pytest tests -q` | **2153 passed, 14 skipped**, exit 0 (4 min 11 s). Skips: 10 need `uproot`; 2 are release checks needing `RAVEL_TEST_WHEEL`; 1 needs the native ROOT/RestFrames toolchain; 1 needs an unshipped RRR archive. All are prerequisite-related, none is a failure. |
| `python scripts/check_publication.py` | OK (9 cases, index, scoped summary; generated status blocks fresh) |
| `python scripts/check_evidence.py --check` | 17 PASS / 0 WARN / 0 FAIL |
| `python scripts/run.py ravel.validation.benchmark --fast` | GATE OK (cached replay of one registered case; not a fresh reproduction) |
| `python tests/adversarial/run_suite.py --require-all` | 29 PASS / 0 FAIL / 1 SKIP (G21, the labeled live-client self-drive case) |
| `pytest tests/unit/test_governance_experiment.py` from `/tmp` **and** from the repository root | 28 passed in both. The README's `py.py` shadowing workaround is obsolete: no `py.py` exists or was ever tracked. |
| Scoped supplied-likelihood route, `initiate → plan --spec → approve --scripted → run → status → run --resume` | Drivable end-to-end without prompts in a scratch directory in about 7.5 s; result bit-identical to the Sep 9 control (S95 obs 43.65137159 events). |
| `benchmarks/governance/experiment.py freeze` on the packet's synthetic spec | Accepted (16 runs). The packet never ran it. |
| Packet helper tests (`tools/`) | 49 pass with a non-symlinked `TMPDIR`; 16 error under macOS's default symlinked `/var` temporary path because the helper rejects symlinked parents. |

These are software and cached-replay checks. They are not agent experiments and do not certify
physics.

## 3. Gap table

Classification uses exactly one label per proposal. "Missing" means no implementation exists in
any branch. Evidence pointers are to the research checkout.

| Packet proposal | Label | Evidence and consequence |
|---|---|---|
| v1 registry/scorer (`benchmarks/governance/experiment.py`) | implemented | Exact-key validation everywhere (`keys()` uses set equality), one scalar model and runtime per spec, `run_id` = SHA-256 of `{spec digest, task, seed, arm}`, deterministic shuffle, sharp unsupported-claim missingness bounds. Byte-identical to `79c7aab`. |
| WP03 regression lock | partial | 28 tests cover accounting. Missing: pinned golden registry digest, CLI round trip, unknown/missing-field rejection at every level, one-model assertion. Found: a registry with `seed` 11.0 or arm flags written as `1` still validates (value equality), and a 401-digit seed raises an uncaught `OverflowError` (exit 1, not the documented 2). `score()` never reads `budget`; v1 cannot mark synthetic versus empirical outcomes; a spec without a refusal task cannot be frozen. |
| Governance README prose | obsolete (stale) | Refers to `governance_experiment.py`, a `/tmp` workaround and an old checkout path. |
| `runner.py`, `campaign_manifest.py`, `adapters/*`, `observations.py`, `treatment.py`, `audit.py`, `analysis.py`, `tasks/development/`, `schemas/` | missing | None exist in any branch. CI has no evaluation job. |
| Execution/state authority (`workflow/execution.py`, `state_io.py`, `current_state.py`) | partial (reusable) | Stage receipts, dependency checks, process-group cleanup and selective DAG invalidation exist and work (an experimental fit→convert→report DAG under `stage_supervisor --resume --depends-on` reused the fit after a luminosity change and reran only the report after a title change). Receipts bind every `src/ravel/**/*.py`, the interpreter, the absolute run path, eight environment variables, the platform string and the installed-package list, so they verify only in place and in the same environment. They are drift checks, not custody: a writer with Python access forged a lifecycle-PASS run without launching the worker. |
| Scoped supplied-likelihood route (`workflow/scoped.py`, `physics/scoped.py`) as the tool surface | partial | One supervised stage fuses fit, luminosity conversion, plot lint and report. Any in-run change forces a new run; re-planning in place is refused; upstream source changes after planning are **not** detected; intake is keyword-routed and refuses neutral V0/V1/V2 phrasings; the subject can author `approval_mode` and call `ravel approve --scripted` itself; spec `source`/`assumptions` text enters `RESULT.md` unchecked. Usable as the numerical kernel, not as the experimental tool surface. |
| Luminosity-only conversion (packet V2) | missing | Conversion exists only inside the fused fit stage and only for a unit-signal counting model. |
| `result_pack.py` / `verify_pack.py` claim checks | missing for scoped runs | `verify_pack` FAILs a valid scoped run (no bound limit source; looks for `RESULT.md` at the run root). Prose checks cover only μ95 values, verdict words and coverage in `RESULT.md`. No per-run machine-readable claim record exists. |
| Typed limit transport (`limits.py`) | implemented | Six statuses with bracket invariants; "a bound is not a root" is structural. |
| Likelihood oracle | missing (prototype only) | A pyhf-free prototype (closed-form profiles, hand-coded asymptotic q̃ formulas, own conditional Asimov) agreed with stock pyhf to 6.1–9.5 significant digits. It also showed that two routes calling the same library can agree and both be wrong (stock SLSQP stopped at a local Asimov minimum on a normsys fixture; relative error 2.95×10⁻³). Unreviewed; not an approved oracle. |
| "2jl approximation" (D02) | implemented, open | `benchmarks/scoped/atlas-2jl-counting.json` (n = 263, b = 283 ± 24, L = 3.2 fb⁻¹). Its answers are public, so it is development/regression material only. `benchmarks/cases.json` records ⟨εσ⟩₉₅ = 16 fb next to S95 = 44 (44/3.2 = 13.75 fb). The 16 fb value is in the source paper itself; annotate it as source-inconsistent rather than "fix" it. |
| `method_study` | implemented as zero-compute proposal | Confirmed not a training executor. `src/ravel/research/` does not exist. |
| WP24–WP27 (a separate method-development track) | not audited | Outside this study; its dataset and method choices are PKT-D09 and PKT-D10 (E-37). |
| `capabilities.json` separation from empirical performance | partial | Fields are inventory, but prose cites agent evaluations and `scripts/audit.py` derives a readiness percentage partly from it. The evaluation layer must neither consume nor feed it. |
| Subject/evaluator isolation | missing | The Sep 9 pilot ran Codex with `--sandbox danger-full-access`, `approval_policy never` and a near-complete environment copy; its runner is untracked and its original copy is deleted. `tests/adversarial/clean_room.py` uses `--setting-sources user` and `bypassPermissions`, and its verdict engine reads keys the real CLI output does not contain, so it cannot PASS on real output. |

The packet's dependency graph gates WP04–WP14 and WP35 behind WP02 (G0 charter) and WP05 (human
statistics review), contradicting its own instruction to continue local deterministic work while
decisions are pending. This audit resolves the conflict by splitting each gated package into a
**provisional local implementation** (proceeding now, marked provisional, producing no scored or
empirical result) and an **approval step** that remains with the named humans (decisions.md E-01).

## 4. Guard inventory ruling

The full row-level inventory (85 checks across specification, approval, launch, supervisor,
numerical kernel, worker delivery policy, post-run evaluation and host hooks, each with location,
trigger, information content, blocked action, separability and category) is in the private
`guard-inventory.md` report. The consequential findings:

1. **No-op ablation trap confirmed.** The arm flag exists only as a registry label. Nothing in
   `src/ravel` reads a treatment switch, and every scientific and freshness check on the scoped
   path blocks in every arm. Setting `enforcement=false` would change nothing.
2. **Host hooks are nearly inert on this path** but add arm-independent confounds: a Stop-hook
   fallback resolves the newest unrelated trial run and can block delivery; CLI-created runs block
   subagents for the whole session; hooks call whichever `python3` is first on `PATH`.
3. **V1 and V2 in-run mutations fail closed identically** ("stage likelihood inputs changed"),
   V0 report edits fail as "outputs changed", and recovery is always a new run with a full refit.
   A new run costs about 5–6 s (57 hypotest evaluations) and reproduces S95 bit-for-bit.
4. **Upstream-source staleness is invisible to the kernel.** After a result existed, mutating the
   original lab-supplied workspace or spec left `status` PASS.
5. **Design B is not available without a new reviewed broker.** `physics.scoped.main`,
   `physics.scoped.likelihood` and `scoped.run/evaluate` fuse delivery policy with numerics or
   authorization with freshness.

**Ruling (engineering, provisional): Design A.** Keep the RAVEL numerical kernel identical in all
arms, give every arm the same selective fit→convert→report operation surface (built on the existing
execution DAG), and study one new, separable mechanism at the delivery boundary, where the kernel is
blind: a claim-freshness and evidence-support guard with identical diagnostic content in audit and
blocking modes. The resulting claim concerns this incremental mechanism on top of a common kernel,
not "RAVEL versus no RAVEL". Details and alternatives are in [slice design](slice-design.md).

## 5. Related work

WP01 compared the study design with published and preprint work on agent evaluation in high-energy
physics and on evidence-bound research agents. That comparison, and what it implies for the scope
and naming of any publication of the study (H-01, H-02), is not published: it is in the private
Phase 0 reports and in this record's earlier version (`917c049`, E-37). One consequence is an
engineering requirement and is adopted here: the analysis reports claim *counts* per run alongside
rates, so that a mechanism that yields fewer claims rather than better ones (claim suppression) is
visible.

## 6. Design corrections adopted

- The packet's V0/V1/V2 slice cannot be frozen in v1 without a refusal task (E-11).
- Packet task identifiers such as `DEVxx_VALID`/`FAULT` would leak labels through the v1 `task_id`
  (E-12).
- The ID "D02" is both a decision and a data source; packet IDs also collide with local IDs
  (D1–D18 failure modes, G-gates, P1–P7 prompts). This workspace prefixes packet decisions as
  `PKT-Dxx` and its own engineering decisions as `E-xx`.
- A 139→140 fb⁻¹ luminosity change moves σ_vis by 0.714%, inside a factor of three of the kernel's
  root precision contract (0.13–0.32% on S95). The slice uses a larger, scientifically explicit
  luminosity change instead (slice design §5).

## 7. Open decisions

Human decisions (packet D01–D12 plus items raised here) and the provisional engineering rulings
that let local work continue are in [decisions.md](decisions.md). Blockers are in
[blockers.md](blockers.md).
