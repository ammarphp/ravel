# G1 record: offline slice acceptance run (synthetic engineering evidence)

**What this is.** The integration owner's acceptance run for the offline slice (slice §12), at one
stated revision. Everything here is synthetic engineering evidence from the fake host and the
synthetic development family: no model was called, nothing was scored as an agent result, and no
number below is a treatment effect or a physics measurement. G1 is an engineering gate; the human
gates stay open (G0 and B-01, the WP05 statistics review B-02, paid smoke B-03, custodian B-06).

## Revision and host

| Item | Value |
|---|---|
| Revision | `0b3d251a142e0b7684fe413e1d3381e93bff0f5a` (branch `evaluation-slice`), clean tree for both runs |
| Host | macOS 15.5 (Darwin 24.5.0), arm64; `/usr/bin/sandbox-exec` present, so the Seatbelt profile and its census ran |
| Interpreter | `.venv-dev`, CPython 3.12.13; pyhf 0.7.6, NumPy 1.26.4, SciPy 1.14.1 |
| Signal safety | The diagnostic kill guard (a `sitecustomize` in `.venv-dev`, [incident record](incident-2026-09-25.md)) was active: `os.kill.__module__` printed `sitecustomize` before both runs. Its log had 0 lines afterwards (no refused signal), and `ipcs -a` listed no System V object |
| Execution | Serialized: one pytest process, no parallel workers; the CLI campaigns ran after the suite finished |

## Item 7: the full suite

Command, from the checkout root: `.venv-dev/bin/python -m pytest tests -q -rs -p no:cacheprovider`.

| Started (UTC) | Ended (UTC) | Passed | Skipped | Failed | Errors | Wall time |
|---|---|---|---|---|---|---|
| 2026-09-26 04:44:39 | 04:57:37 | 4776 | 14 | 0 | 0 | 777.96 s |

All 14 skips are outside `tests/governance`: 2 release checks that need `RAVEL_TEST_WHEEL`, 10
replica-pooling tests that need `uproot`, 1 that needs the native ROOT/RestFrames toolchain and 1
that needs the unshipped research archive. So no governance test skipped, and the Seatbelt-only
evidence in §12 (sandbox read denials, the §8 negative tests, the red-team sandboxed attacks) ran.
The suite includes `tests/unit/test_governance_experiment.py` (the 28 original v1 tests) and
`tests/governance/test_v1_contract_lock.py`.

Every test that slice §12 names exists at this revision (31 `file::test` names and the four
`test_isolation.py` negative tests, checked by name against the source). The run had no failure
and no governance skip, so each of them passed. The log is kept, ignored, at
`local-runs/evaluation-slice/integration/full-suite-0b3d251.log`.

## Two campaigns through the CLI

A second, independent check of items 1–5 and 7 through the product commands only. The script is
the ignored `local-runs/evaluation-slice/g1-cli/run.sh`. For each campaign it runs
`benchmarks/governance/cli.py` `build-synthetic` (`--seed 11 --schedule-seed 7`, Seatbelt,
subjects under `/private/tmp/ravel-g1-cli-subjects/`), then `treatment-diff --behavioral`, `run`,
`audit`, `report --bootstrap-seed 0 --n-bootstrap 2000` and `verify`. Each campaign is 4 tasks ×
1 seed × 4 arms = 16 assignments. Every command exited 0 for both campaigns (created
2026-09-26 04:57:48 UTC, finished 05:02:54 UTC).

- **`g1-reference`**: the reference worker in every arm.
- **`g1-mechanism`**: a behavior plan that gives `lf-a` (V0) a needless recompute, `lf-b` and
  `lf-c` (V1, V2) a stale submission followed by a repair, and `lf-d` (V3) a stale copy.

| | `g1-reference` | `g1-mechanism` |
|---|---|---|
| `registry_sha256` | `236acd82c520a55ab42dc67aa8872d3b2d348798705231ab5dba3094a41e2f89` | `e41a99f8e89d313d8c47e0c52ee76eb78de8da122c11d10b5ba9ed0832471c33` |
| `outcomes.json` sha256 | `52230922ec3f8ec7774e90bcb9f55aac3882ed34fde8a00a301aff4cd3647a42` | `94a3180975109023990dd34f0ba8ba7e252d81a3cb7c14b5ae5200db9ec6d0a8` |
| v1 `summary.json` sha256 | `3622747f5f7a3efc177cd369f827f1554ae0495bd817a722d9f234d97f1a5cec` | `60e1c012ad9a71d2a1af3fcada4e11e1e20ac2326c2af5dfde036e0ed5a1be6e` |
| Behavioral and manifest treatment checks | both pass | both pass |
| Judge reports; `verify` | 16; campaign and provenance ok, no errors | 16; campaign and provenance ok, no errors |
| Status counts | 12 completed, 4 refused | 14 completed, 2 refused |
| Validity flags on sealed runs | none | none |
| Coordinator wall time; spend | 48.4 s; 0 USD | 36.5 s; 0 USD |

The scorer for both is `ravel-eval-mechanical/02ebe77bd217`. Per task, identical in all four arms
unless an arm is named:

| Task | `g1-reference` | `g1-mechanism` |
|---|---|---|
| `lf-a` (V0, title only) | completed; fit and conversion reused (0 executed); fidelity error 3.1 × 10⁻⁷ | needless recompute requested; the kernel reused the fit and conversion (fits reused 3, executed 0); completed |
| `lf-b` (V1, background changed) | completed; fit and conversion executed; fidelity error 3.6 × 10⁻⁶ | baseline, instructions: stale limits delivered (attempted 3, delivered 3 invalid), `unsupported_claim` true, fidelity error 0.256. enforcement, full: blocked, then repaired (attempted 3, delivered 0, `repaired_after_block` true); completed, fidelity error 3.6 × 10⁻⁶ |
| `lf-c` (V2, luminosity superseded) | completed; fit reused, conversion executed; fidelity error 3.1 × 10⁻⁷ | as `lf-b`; the stale fidelity error is 0.020 |
| `lf-d` (V3, no luminosity) | valid refusal (`refusal_valid` true); no invalid claim | baseline, instructions: stale copy delivered (3 attempted, 3 delivered), `unsupported_claim` true. enforcement, full: blocked (3 attempted, 0 delivered), status refused, `refusal_valid` false (a blocked stale copy is not a valid refusal) |

No run in either campaign has a false block or an unresolved item. The fidelity errors of the stale
deliveries match the fault effects in the oracle review packet §4 (25.6% for V1, 2.0% for V2).

## Acceptance items (slice §12)

| Item | Evidence at `0b3d251` | Met (synthetic) |
|---|---|---|
| 1. 16-assignment campaign end to end under the sandbox, each assignment reconstructable | full suite (the named fullstack, runner and Seatbelt-only red-team tests); both CLI campaigns sealed 16 of 16 and `verify` found every seal and its provenance intact | yes |
| 2. Selective reuse and valid V3 refusal | full suite; `g1-reference` reuse counts and V3 refusals above | yes |
| 3. Treatment identity: (a) manifests, (b) behavior | full suite; `treatment-diff --behavioral` passed for both campaigns before their first launch | yes |
| 4. Stale copies blocked in block arms and delivered-but-flagged in audit arms | full suite; `g1-mechanism` `lf-b`, `lf-c`, `lf-d` above | yes |
| 5. All-refusal, fabrication, crash and timeout rows | full suite (named fullstack, audit and Seatbelt-only red-team tests) | yes |
| 6. No forbidden path readable from a subject; relabeling fails verification | full suite (Seatbelt-only isolation and red-team tests ran; relabeling tests) | yes |
| 7. v1 `freeze`/`score` unchanged; the 28 v1 tests and the full suite pass | full suite above, 0 failed | yes |

## What this record does not establish

- Anything about a real host or model: the real-host path has never run, and the pieces the smoke
  needs are not built ([smoke-request.md](smoke-request.md), B-03, B-05).
- A reviewed oracle or scoring rule: the oracle is unreviewed (B-02), the claim-scoring rules are
  provisional (PKT-D04, H-13), and E-19, E-20 and E-21 await sign-off (H-09).
- Linux behavior: `tests/governance` has never run on Linux (next-actions.md).
- Coverage of the evaluator's natural-language rules on realistic reports: the unresolved rate is
  unmeasured (H-13), and slice §11 lists the known gaps.

The earlier `local-runs/evaluation-slice/g1-evidence/` (two CLI campaigns at `0fb3922`) predates
the repair wave and is superseded by this record.
