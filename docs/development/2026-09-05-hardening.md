# Ravel-HEP reliability audit and development plan

The pipeline has substantial working infrastructure and authentic scientific failure records.
It is not yet close to a point where improvements are hard to find. The most valuable work
is to close scientific validation gaps and demonstrate reliable independent execution, while
making the enforcement and distribution layers trustworthy enough to support those experiments.
This update addresses concrete software failures. It does not claim improved physics fidelity
or a causal benefit from governance.

## Local workspace versus GitHub

The development baseline is `b7b07de`; GitHub was the independent curated snapshot `d25084f`,
published August 17, 2026. These are different commit histories. A Git ahead/behind count would
not describe their relationship. [The complete content comparison](local-public-gap.json)
records the full revisions, file counts, changed common files, normalization-only differences,
and intentionally private development material. The source had 6,275 tracked files and the
public snapshot 544; all public paths existed in the source, with 42 substantive changes and
eight path/URL-redaction-only differences among shared files. The published update retains GitHub history.

Important later local changes include robust pyhf optimizer checks, more reliable HEPData
retrieval, input routing, cross-section-basis checks, and explicit failed acceptance
certifications. They are carried into the reviewed distribution. Local settings, raw development
conversations, untracked prior research reports, and heavy regenerable event files are outside
the curated export. Original run inputs and historical baselines are preserved.

## What the existing trials establish

The initial local test run collected 378 tests: 376 passed and two failed. One failure was a
stale hard-coded 95% inventory score; the live inventory gave a different value. The other was
a stale evidence checksum for STATUS.md. A score change must remain visible instead of being
forced back to its old value. Public prose now reports reference-task coverage without calling
an inventory percentage scientific correctness.

A fresh full cached benchmark replay held regression floors in seven of nine cases and breached
two provenance checks. The retained [full replay result](2026-09-05-local-benchmark-replay.json)
is separate from the historical accepted baseline:

| Case | Fresh result | Meaning |
|---|---|---|
| `ins1676551_c1n2_300_100` | BREACH | Required `build/analysis.yoda` is missing. The observed cross-section-limit discrepancy remains about 5 times the published value. |
| `conf2016037_gluino_2step_sleptons_1400_60` | BREACH | Required `outputs/analysis_patched.yoda` is missing. |
| `ins2182381_gbb_1900_1` | Regression OK; certification FAIL | The 26.5% acceptance residual meets the locked Acceptable floor, but it does not become a certification PASS. |

A bounded recovery search of the DSRLab development/public checkouts, two worktrees, five
backup archives, reachable Git history and reflogs found no replacement for either missing
YODA artifact. None of 41 accessible YODA files, including decompressed gzip contents,
matched the C1N2 result record's MD5 `4c7c5ed79b005335a71d45910b65855b` or contained
either target analysis path. A July 12 ignored-file inventory lists both exact missing paths,
but the inspected archives contain provenance records without the YODA bytes. No expected
CONF037 YODA digest was found in the inspected records. This was a bounded local search,
not proof that no external backup exists; neither artifact was substituted or regenerated.

All nine [generated validation pages](../validation/README.md) distinguish observed
model-independent S95 recovery, acceptance certification, numerical repeatability, and
cross-section limits. Seven S95 comparisons within 8.6% validate the statistical/data-input
layer across four searches. They are not seven end-to-end physics reproductions. Six baseline
acceptance comparisons contain four PASS, one WARN and one FAIL; three further cases are
unscorable. Two newer native ports also completed their later acceptance certifications with
FAIL verdicts. Implementation parity against the same container inputs did not establish
agreement with experimental acceptance.

The flagship 52-point scan retains its 24.9% median same-basis cross-section-limit residual over
50 reference-matched cells, and two legacy cells remain bounds. The paired PDF-choice rescan
and historical correction records are evidence about specific mechanisms. They do not fully
explain the remaining residual. No fresh event generation was performed during this update.

## Implemented changes

1. **Strict contracts at live entry points.** Exact schema version, nested structures, finite
   numeric inputs, nonnegative ranges, explicit compute budgets, refusal reasons, and strict JSON
   are validated. Approval, first-stage advancement, lifecycle evaluation and the scoped Bash
   generation guard now call the strict validator. The
   [schema reference](../../framework/validation/task-contract-schema.md) records every accepted
   field and the explicit archive-only compatibility policy. Historical contracts are preserved.
   Version-2 approval records bind the contract, CHECK-IN 1 and cost artifact; malformed or
   stale records cannot authorize live generation. Old unbound approvals must be re-recorded.
2. **Usable Python distribution.** `ravel validate` and the bundled `ravel replay` work after
   wheel installation outside a checkout. Diagnostic `ravel audit` explicitly requires the
   source tree. [The CLI guide](../CLI.md) documents scopes, errors, output retention, exact
   environment locks, and build verification. Package engines come from the existing source
   allowlist, avoiding a separately maintained copy of scientific logic.
3. **Evidence integrity and completeness.** Malformed metadata, duplicate IDs/JSON keys,
   unknown statuses, escaping paths, missing mandatory shipped artifacts, source-claim deletion,
   status downgrades and altered staged manifests fail. Source evidence is checked before
   exact permitted text redactions are rebound to staged hashes. A registry surrogate is
   explicitly described as a historical reference, not a substitute physics measurement.
4. **Documentation checks.** All registered benchmark cases are generated, including unscorable
   cases and failures. Statistical ratios are derived from observed S95 and the registry's
   published reference, with stored-ratio consistency checks. Removing an eligible result cannot
   improve the headline. Generated-page freshness and public claims are checked in CI.
5. **Safe distribution updates.** Export refuses a nonempty or symlink staging path. It does
   not delete existing contents. Public updates use normal fast-forward commits; concurrent
   remote changes cause rejection. Portably sanitized exports retain transformation provenance.
6. **Comparative experiment infrastructure.** The
   [source-pinned competitive review](../research/2026-09-05-competitive-design-and-validation.md)
   specifies a prospective crossed experiment. Its registry/scorer accounts for every planned
   assignment and preserves missingness, failures, independently scored outcomes, useful
   completions, valid refusals and cost. No fabricated comparative results are supplied.

The second iteration also closed the observed CR-147/N20 plotting failure. The old legend
occupancy sampler considered line vertices, so a legend covering the middle of a sparse line
could pass. Sampling now follows visible transformed segments with bounded display-space
spacing and preserves log axes, steps, path breaks, marker-only artists and clipping. Four
crossing scenarios failed before the fix; eleven focused regressions and the plot-lint selftest
passed afterward. This changes visual validation, not physics data or previously recorded results.

## Final local verification

The implementation was frozen at source revision `921ab61`, with the evidence-binding
follow-up at `bc4188f`. Checks ran in the hash-locked Python 3.12.13 replay environment.
These results precede the documentation-only addition of this verification record.

| Check | Result | Scope |
|---|---|---|
| Complete research-workspace test suite | 639 passed, 1 skipped | The skipped installed-wheel release check ran separately below. |
| Complete sanitized public-export test suite | 627 passed, 13 skipped | Development-only state/fixture checks are omitted; the installed-wheel check ran separately. |
| Adversarial gate board | 29 passed, 1 skipped, 0 failed | The live fresh-agent gate G21 remains unexecuted. |
| Served-claim evidence checks | 14 passed, 0 warnings, 0 failures | Artifact integrity and required evidence coverage, not scientific certification. |
| Publication checks | Passed | Eight marked claims, all nine validation pages, generated status and version consistency. |
| Installed-wheel package checks | 25 passed | Includes execution outside the checkout and exact matching of the 119-file curated payload. |
| Extracted source-distribution checks | 16 passed | Package and benchmark checks rerun from the extracted source archive. |

The installed replay recovered observed/expected mu95 values of 0.219143/0.275714 and
observed/expected S95 reference ratios of 0.997857/1.022960. It explicitly used cached acceptance.
Dependency consistency passed. The full suites emitted 216 Matplotlib/Pyparsing deprecation
warnings each. No test result above repairs the two missing benchmark artifacts or changes a
failed acceptance certification. Remote Linux CI is a separate verification step and is not
claimed by these local results.

## The next work, in order

| Priority | Work | Evidence required to call it complete |
|---|---|---|
| 1 | Recover the two missing benchmark artifacts from a verified archive, or regenerate under a separately approved scientific plan. | Original provenance and checksums, followed by all nine fresh replay outcomes; no relaxed file requirements. |
| 2 | Diagnose the failed native-port acceptance closures and the flagship residual with bracketed interventions. | Published intermediate cutflows, object definitions and normalization bases; paired tests that distinguish generator, shower, detector, selection and statistical causes. |
| 3 | Run an unhinted fresh-agent pilot under the frozen crossed protocol. | Hidden expected answers, identical resource allowances, an independent scorer, retained transcripts, and complete denominators. A pilot informs a separately frozen confirmatory design. |
| 4 | Execute the confirmatory reliability experiment. | Lower silent-invalid-claim rate without hiding costs in blanket refusal, extra interventions, unsupported completion or worse physics fidelity. Interval estimates and missingness sensitivity are required. |
| 5 | Extend environment reproducibility beyond cached Python replay. | Exact native compiler/HEP-tool/data identities, a cold-host build test, and a verified Linux OCI route where appropriate. Native remains the default on the current host. |
| 6 | Expand supported analysis families only after per-analysis closure. | Published likelihood/selection binding, independent cutflow and end-to-end comparisons, and explicit unsupported-region coverage. |

More unit tests alone will not establish these outcomes. Additional changes should follow a
reproduced failure or a discriminating scientific experiment. No threshold, statistical basis,
selection or oracle should be changed to make an observed discrepancy disappear.

## Remaining limits of the enforcement model

JSON validity does not prove a physics input is true. Digests do not prove that a result is
scientifically valid or that a protocol was registered before an experiment. Local editable
approval artifacts are not an authenticated human identity service. Explicit known scan drivers require a bound scan approval. A generic native-runner command
does not expose its event count, so smoke-versus-full statistics and actual event, point or
walltime consumption are not enforced from that command alone. Shell-command recognition
is heuristic, not an operating-system sandbox; arbitrary wrappers can evade it. The prospective scorer validates accounting
and declared evidence references; human/scientific adjudication still has to inspect the
actual retained evidence. These boundaries remain explicit.
