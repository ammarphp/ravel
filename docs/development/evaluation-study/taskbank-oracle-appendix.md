# Review appendix: WP12 task-bank oracle cross-checks

**Status: unreviewed engineering evidence.** This appendix belongs with the
[oracle review packet](oracle-review-packet.md) (PKT-D02). It records how the two WP12 oracles
compare with the RAVEL kernel and with stock pyhf. It is plan step 3 of the WP12 task-bank design
revision of 2026-09-26; the design itself stays outside the repository until its human review.
No agent ran and no event was generated. None of the numbers below is a physics result.

The oracles under test:

- `benchmarks/governance/oracle/counting.py`: single-bin asymptotic q̃ CLs limits, `cls_at` and the
  `above_cap` status for cap-bounded models.
- `benchmarks/governance/oracle/lhe_census.py`: the LHE sample census.

Both are standard-library code and import neither pyhf nor `ravel`. The cross-check tests import
both on purpose, because they measure agreement with the code being scored.

**Review round 1 (2026-09-26).** An engineering review of plan steps 2–3 raised one major and
thirteen minor findings, two of which make the same edge-margin point. The fixes are in revision `6dce22f`, and this appendix now reports its
numbers. The main change is to §4a: toy CLs with 10⁸ toys per hypothesis resolves a
toy-asymptotic offset of −0.3 to +0.6 % of S95. The earlier suggestion that the design say
"consistent with no bias" is withdrawn. §5 lists what this means for the design. No finding was
judged wrong. Two were refined with further measurement: the selection-edge margin (§3a) and the
kernel's `below_scan` floor (§1a).

## Inputs

| Input | Kind | Source |
|---|---|---|
| 2jl: n = 263, b = 283 ± 24 events | derived from published values | ATLAS arXiv:1605.03814, SR 2jl (Table 6, as cited in `evidence/audits/2026-09-08-statistical-fidelity/README.md`), in a single-bin gamma/Poisson approximation. Record: `benchmarks/scoped/atlas-2jl-counting.json`. No HEPData record is used |
| 2jl with POI range [0, 10] | synthetic perturbation | Same counts with a smaller cap. The 2026-09-09 `unresolved-bound` control used the same cap |
| hv: n = 73, b = 58.0 ± 7.0 events | synthetic | WP12 task-bank design |
| LF prior (42, 38.0 ± 5.0) and LF V1 (42, 44.0 ± 5.0) | synthetic | `likelihood_freshness` family |
| Drell–Yan LHE, seeds 1729 and 1730 | RAVEL-generated development samples | `evidence/audits/2026-09-09-scoped-workflows/{drell-yan,drell-yan-replica}/events.lhe.gz`. These are redacted public copies pinned in `tests/governance/fixtures/lhe/fixtures.json` |
| Content-truncated DY 1730 | `ravel_generated_development`, with the truncation and recompression listed under `modifications` | `benchmarks/governance/tasks/data/dy-1730-content-truncated.lhe.gz` (moved from `tests/governance/fixtures/lhe/` on 2026-09-27, decision E-152; its record and builder stay there): 10,462 bytes, sha256 `c45eea92…`, 41 of 100 events |

## Revision, environment and commands

| Item | Value |
|---|---|
| Revision | `6dce22f37a82e82ff1b1c4a99ed27dce6d90bf11` (branch `eval/taskbank`). The oracles come from `55b07e3`, and `aa8b7e8` adds the cross-check tests. `6dce22f` changes the counting oracle's docstrings only, adds the `opened_event_blocks` diagnostic to the census, and adds the review's tests. Every number below was printed at this revision |
| Host | macOS 15.5, arm64 |
| Interpreter | `.venv-dev`: CPython 3.12.13, pyhf 0.7.6, NumPy 1.26.4, SciPy 1.14.1, iminuit 2.32.0 |
| Date | 2026-09-26 |
| Suites | `tests/governance/test_oracle_crosscheck.py`: 20 passed. `test_oracle_counting.py`, `test_oracle_lhe.py`, `test_oracle_crosscheck.py`, `test_family.py` and `test_v1_contract_lock.py` together: 455 passed. The full `tests/governance` suite at `6dce22f`, run under the shared test lock: 2747 passed and 0 failed in 696 s |

The source digests at that revision are printed by `test_record_crosscheck_environment`:

| File | sha256 |
|---|---|
| `benchmarks/governance/oracle/counting.py` | `809c25f66bad6d95bdb08f6f10a954cb5a8cdb1bc6e068a3d7a7e1b3f6e3ee55` |
| `benchmarks/governance/oracle/lhe_census.py` | `7b62f0721d890b0ff99e5a6c2ee1dc5068cd8b6b675f5b1b4f11642086eabfde` |
| `src/ravel/physics/pyhf_exclude.py` | `a85206eee4c40c18e893d1ea93c4ede9c741a782c3b0d367a53fa7011bc0e466` |
| `src/ravel/physics/scoped.py` | `e6329d78e589dd4e92d4312170e1bc94a613f5d616bf8a443f004a958ce4ea84` |
| `src/ravel/physics/native_normalization.py` | `2da98923f592807e2f409531c7f13061da820b8c056fbacc8ff09825a2e3d185` |

Each test in `tests/governance/test_oracle_crosscheck.py` that measures a number prints a
`CROSSCHECK <name> <json>` line with it. The tables below copy those lines. Run the tests from the checkout
root:

```sh
PY=.venv-dev/bin/python
$PY -m pytest tests/governance/test_oracle_crosscheck.py -q -s -p no:cacheprovider | grep CROSSCHECK
$PY -m pytest tests/governance/test_oracle_crosscheck.py -m kernel_crosscheck -q   # kernel and stock pyhf only
$PY -m pytest tests/governance/test_oracle_crosscheck.py -m diagnostic -q          # toys and level sensitivity
RAVEL_ORACLE_TOY_CHUNKS=50 $PY -m pytest tests/governance/test_oracle_crosscheck.py -q -s \
    -k large_n -p no:cacheprovider | grep CROSSCHECK                               # the 10^8-toy record (~2 min)
$PY -m pytest tests/governance/test_oracle_counting.py tests/governance/test_oracle_lhe.py -q
```

Two pytest marks label the tests:

- `kernel_crosscheck` tests import the kernel or stock pyhf. They skip when pyhf 0.7.6, SciPy or
  the kernel is missing.
- `diagnostic` tests record measurements. They are not correctness criteria.

The one unmarked test reads kernel results already recorded in the repository.

The test run takes about 13 s, of which the default large-N toy run takes about 5 s.

## 1. Counting oracle against the RAVEL kernel

The kernel runs exactly as the scoped likelihood worker runs it:

- `ravel.physics.scoped.prepare_workspace` builds the workspace from the counting spec.
- `pyhf_exclude.compute(model, data, poi_cap=…)` computes the limits, with `robust_optimizer(tolerance=1e-9)` at 64-bit precision.

The oracle parses that same workspace and returns (263, 283, 24, cap 10), (263, 283, 24, cap 256) and
(73, 58.0, 7.0, cap 256).

### 1a. 2jl with POI cap 10: statuses

| Curve | Oracle status | Kernel status | Kernel value |
|---|---|---|---|
| Observed | `above_cap` (value null) | `above_scan` | 10.0 (bound) |
| Expected −2σ … +2σ | `above_cap` ×5 (values null) | `above_scan` ×5 | 10.0 ×5 (bounds) |

- The kernel status is exactly the oracle status mapped through `KERNEL_LIMIT_STATUS`.
- The kernel sets `at_poi_cap` and `median_at_cap`. It does not set `at_mu_floor`.
- The kernel evaluated CLs at 15 points (its `n_fits`), and its scan ends at μ = 10.

How far `above_cap` is proved (counting.py docstring, corrected in review):

- The five expected curves are monotone analytically: CLs_exp = Φ(−(k + √q̃_A)) / Φ(−k), and q̃_A
  increases with μ. For them, CLs(cap) > 0.05 proves that no crossing lies in (0, cap].
- The observed curve is not monotone by construction. The oracle only verifies it on its 64-point
  grid, which supports "no crossing" but does not prove it. A seeded 400-point check of 399 random
  models found no rise on any observed curve (`test_observed_curve_has_no_rise_on_a_fine_grid`).

The kernel's `below_scan` has no oracle status, and the two floors differ. The kernel's first scan
point lies at or below 10⁻³ events, while the oracle resolves roots down to 10⁻⁹ events. The gap
cannot matter for a unit-signal model, because q̃ and q̃_A are at most 2μ. At μ = 10⁻³ every
CLs therefore exceeds Φ(−2.045)/Φ(−2) = 0.898, the bound for the −2σ expected curve. In a scratch
survey of 840 models (38 of them raise `ContractError`), the smallest value was 0.942. `test_no_crossing_below_the_kernel_first_scan_point`
checks seven extreme models against that bound.

### 1b. 2jl with POI cap 10: CLs at μ = 10

| Curve | Oracle `cls_at(10)` | Kernel `scan_cls_*[-1]` | Absolute difference | Stock pyhf `hypotest(10)` | Absolute difference |
|---|---|---|---|---|---|
| Observed | 0.6059060100 | 0.6059060066 | 3.4 × 10⁻⁹ | 0.6059060132 | 3.2 × 10⁻⁹ |
| Expected −2σ | 0.4114517384 | 0.4114517299 | 8.5 × 10⁻⁹ | 0.4114517464 | 8.0 × 10⁻⁹ |
| Expected −1σ | 0.5568158502 | 0.5568158425 | 7.8 × 10⁻⁹ | 0.5568158575 | 7.3 × 10⁻⁹ |
| Expected median | 0.7255604490 | 0.7255604433 | 5.8 × 10⁻⁹ | 0.7255604544 | 5.4 × 10⁻⁹ |
| Expected +1σ | 0.8817060979 | 0.8817060950 | 3.0 × 10⁻⁹ | 0.8817061007 | 2.8 × 10⁻⁹ |
| Expected +2σ | 0.9725479677 | 0.9725479669 | 8.1 × 10⁻¹⁰ | 0.9725479685 | 7.5 × 10⁻¹⁰ |

- All six CLs values exceed 0.05, so no crossing lies inside [0, 10].
- Over all 15 kernel scan points the worst difference is 8.5 × 10⁻⁹.
- The oracle's value lies between the kernel's and stock pyhf's. Both of those fit to an objective
  tolerance of 10⁻⁹.
- Stock pyhf gives bit-identical CLs(10) on the cap-10 and cap-256 workspaces.
- These match the design's quoted values: 0.6059060100 against 0.6059060066 (3.4 × 10⁻⁹), and the
  expected values within 10⁻⁸.
- `limits()` returns these six values as `cls_at_cap`. `oracle_record` does not carry them yet,
  because the new field would change the digest of every `likelihood_freshness` oracle record, and
  that family is outside plan steps 2–3. Plan step 7 adds `cls_at_cap` to each side of the record,
  rounded to 10 significant digits and null when every curve is resolved. Until then an evaluator
  that scores the kx-b CLs diagnostic calls `cls_at` on the same input bytes.

### 1c. Resolved limits: hv and 2jl with cap 256

| Model | Curve | Oracle S95 (events) | Kernel S95 (events) | Relative difference |
|---|---|---|---|---|
| hv | Observed | 34.014202 | 34.014744 | 1.6 × 10⁻⁵ |
| hv | −2σ | 11.585294 | 11.585320 | 2.2 × 10⁻⁶ |
| hv | −1σ | 15.603377 | 15.603397 | 1.3 × 10⁻⁶ |
| hv | Median | 21.782240 | 21.782326 | 3.9 × 10⁻⁶ |
| hv | +1σ | 30.597166 | 30.596435 | 2.4 × 10⁻⁵ |
| hv | +2σ | 41.578841 | 41.578853 | 2.8 × 10⁻⁷ |
| 2jl cap 256 | Observed | 43.651292 | 43.651372 | 1.8 × 10⁻⁶ |
| 2jl cap 256 | −2σ | 29.727002 | 29.727474 | 1.6 × 10⁻⁵ |
| 2jl cap 256 | −1σ | 39.757153 | 39.757020 | 3.4 × 10⁻⁶ |
| 2jl cap 256 | Median | 54.885751 | 54.884401 | 2.5 × 10⁻⁵ |
| 2jl cap 256 | +1σ | 75.840097 | 75.840133 | 4.7 × 10⁻⁷ |
| 2jl cap 256 | +2σ | 100.923444 | 100.923552 | 1.1 × 10⁻⁶ |

| Model | Kernel CLs evaluations (`n_fits`) | Worst \|ΔCLs\| over the kernel's scan points | Kernel `root_cls_max_error` |
|---|---|---|---|
| hv | 44 | 2.7 × 10⁻⁹ | 6.7 × 10⁻⁶ |
| 2jl cap 256 | 41 | 2.0 × 10⁻⁸ | 5.7 × 10⁻⁶ |

- The hv kernel cross-check was **pending** in the design, which expected agreement within 10⁻⁴.
  The measured agreement is 2.4 × 10⁻⁵ at worst, so that item is now resolved.
- At every point the kernel evaluated, the CLs values agree to about 10⁻⁸. The limits differ more,
  by up to 2.5 × 10⁻⁵. That difference comes from where the kernel's Brent search stops
  (`root_rtol` 10⁻⁴), which leaves |CLs(root) − 0.05| up to 6.7 × 10⁻⁶. It is not a difference in
  the CLs function itself.

### 1d. Recorded controls and `MODIFIER_SETTINGS`

- **Fresh run against the recorded controls.** A fresh kernel run reproduces both recorded
  2026-09-09 controls bit for bit: `unresolved-bound` (cap 10) and `counting` (cap 256). The scan
  grids, CLs arrays and limits are identical, with worst difference 0.0. The design's quoted kernel
  figures are therefore current.
- **Oracle against the recorded controls.** The unmarked test reads the recorded result files
  directly, without importing the kernel. The oracle agrees with them as in 1b and 1c: worst ΔCLs
  8.5 × 10⁻⁹ and 2.0 × 10⁻⁸, and limits within 2.5 × 10⁻⁵.
- **`MODIFIER_SETTINGS`.** Building the pyhf model with the kernel's `MODIFIER_SETTINGS` (normsys
  code4, histosys code4p) leaves every result bit-identical, for both 2jl cap 10 and hv.
  Design §3.3 has the generalized fit stage pass these settings explicitly, and that does not change
  counting results.

## 2. Stock pyhf `hypotest` (implementation evidence only)

pyhf is the library the kernel wraps, so agreement with it does not validate the oracle
independently. The tests evaluate `pyhf.infer.hypotest(root, …, test_stat="qtilde")` at each of the
six oracle roots. The design's workspace has POI range [0, 256], and the fits use the SciPy
optimizer.

Each residual is converted to the relative root offset it implies:
|CLs(root) − 0.05| / (|dCLs/dμ| × root). The slope comes from the oracle by a central difference.

| Model | Optimizer tolerance | Max \|CLs(root) − 0.05\| | Max implied relative root offset | Test bound |
|---|---|---|---|---|
| 2jl | 10⁻⁹ | 8.1 × 10⁻⁹ | 2.1 × 10⁻⁸ | 10⁻⁶ |
| 2jl | 10⁻¹² | 9.7 × 10⁻¹⁰ | 4.1 × 10⁻⁹ | 10⁻⁷ |
| hv | 10⁻⁹ | 1.4 × 10⁻⁷ | 4.2 × 10⁻⁷ | 10⁻⁶ |
| hv | 10⁻¹² | 3.0 × 10⁻⁹ | 8.8 × 10⁻⁹ | 10⁻⁷ |

The hv residual at tolerance 10⁻⁹ is about 50 times smaller at 10⁻¹². So it comes from stock
pyhf's fit tolerance, not from the oracle. It sits mostly in the expected curves (7 × 10⁻⁸ to
1.4 × 10⁻⁷, against 1.1 × 10⁻⁸ observed), which depend on the Asimov data that the conditional μ = 0
fit sets. The CLs values at μ = 10 are in the last two columns of table 1b.

## 3. LHE census against the kernel's LHE readers

The kernel has two LHE readers:

- `ravel.physics.scoped.audit_lhe(path, generation)`: an ElementTree reader that also enforces the
  generation plan.
- `ravel.physics.native_normalization.read_lhe(path)`: a line reader for normalization.

The generation plan is the `generation` block of each control's `spec.json`, which is the manifest
plan. The oracle uses the design's selection: status-1 e⁺ (−11) and e⁻ (11), exactly one of each,
with the pair mass in the open window (81, 101) GeV.

### 3a. The complete public files

| Quantity | DY seed 1729 | DY seed 1730 | Agreement |
|---|---|---|---|
| `audit_lhe` against the manifest plan | passed | passed | — |
| `audit_lhe` against the plan without `runtime` | identical result | identical result | The task-bank `manifest.json` omits `runtime`; `audit_lhe` does not read it |
| Complete events: oracle, `audit_lhe`, `read_lhe`, header | 100, 100, 100, 100 | 100, 100, 100, 100 | equal |
| σ (XSECUP, pb): oracle exact, `audit_lhe`, `read_lhe` | 760.535 | 761.52 | equal floats |
| Integration error (pb) | 6.492428 | 6.525022 | equal |
| Σw: oracle against `read_lhe` | 76,053.5 | 76,152 | relative difference 0 |
| Σw²: oracle against `read_lhe` | 57,841,348.6225 | 57,991,271.04 | relative difference 0 |
| Negative weights (`read_lhe`) | 0 | 0 | — |
| Per-event pair mass: oracle `pair_masses` against `audit_lhe` `masses_gev`, max relative difference | 3.7 × 10⁻¹⁵ | 3.7 × 10⁻¹⁵ | design requires ≤ 10⁻⁹ |
| Selected in (81, 101) GeV: oracle, and the same window on the kernel's masses | 87, 87 | 89, 89 | equal |
| Nearest mass to a window edge (GeV) | 0.8091 | 0.0357 | — |
| Edge margin against the printed decimals, nearest-edge event | 3.9 × 10⁸ | 1.8 × 10⁷ | — |
| Edge margin against the printed decimals, minimum over the 100 events | 4.1 × 10⁷ (event 68) | 1.5 × 10⁷ (event 29) | — |
| Edge margin against oracle–kernel float disagreement | 2.4 × 10¹² | 1.0 × 10¹¹ | — |

The three margin rows measure different things:

- **Printed-decimal margin.** Each event's distance from the nearer window edge, divided by the
  largest change in its pair mass that the half-units of the printed e⁺e⁻ momentum components allow.
  This bounds how far the unprinted generator value could lie from the printed one, so it is the
  relevant robustness of the selection to the input precision. For the DY 1730 nearest-edge event
  (81.0357 GeV) the mass bound is 2.0 × 10⁻⁹ GeV, which gives 1.8 × 10⁷, the design's "about 10⁷".
  Boosted pairs have larger bounds, up to 1.0 × 10⁻⁷ GeV. The smallest margin is therefore at DY
  1730 event 29, 0.30 GeV above 101 GeV, at 1.5 × 10⁷. For DY 1729 it is event 68, 4.1 GeV above
  101 GeV, at 4.1 × 10⁷. `test_selection_edges_are_robust_to_the_printed_precision` computes these
  margins without oracle code.
- **Reader-arithmetic margin.** The nearest-edge distance divided by the worst oracle–kernel mass
  disagreement. It shows that two double-precision readers of the same printed decimals cannot
  disagree on the selection. It says nothing about readers of other precision.

The kernel's mass is taken over all status-1 particles, and the oracle's over the selected pair.
They coincide here only because `audit_lhe` requires each event's final state to equal the plan's
`final_state_pdg`, and here that is [−11, 11], the selection's `pdg_ids`. The cross-check now
asserts that condition. **For step 4:** the census stage must require the selection's `pdg_ids`
to equal the plan's final state, or compute the pair mass from the selected particles, before it
applies a selection to the kernel's masses. It should add a test on a synthetic file with an
extra status-1 particle.

The public copies' provenance, as the tests now check it:

- The recorded `event_blocks_sha256` recomputes from the public files, so the event bytes are
  unchanged.
- That hash does not cover the init block, which carries XSECUP. σ is corroborated separately: the
  run-time `result.json` recorded 760.535 and 761.52 pb, `verify.py` checks them against the init
  block, and every weight equals XSECUP.
- That the redaction changed only the home-directory prefix is the exporter's statement. The
  original files are not in the public tree, so their hashes cannot be checked here.

### 3b. The content-truncated fixture

The gzip stream is intact, and the content ends inside event 42.

| Reader or counting rule | Exact outcome |
|---|---|
| Byte-level decompressors: zlib streaming, `gzip.decompress`, line iteration, `gzip -dc` (exit 0) | Identical content with 41 closed event blocks |
| Counting opening tags (`gzip -dc … \| grep -c '<event>'`) | 42 |
| `ElementTree.fromstring` | Raises `ParseError: no element found: line 738, column 32` |
| `ElementTree.iterparse` | Yields 41 `event` elements, then raises the same `ParseError` |
| `scoped.audit_lhe` | Raises `xml.etree.ElementTree.ParseError: no element found: line 738, column 32` (expat code 3). Position (738, 32) is the end of the 54,179-byte content: its last partial line is 32 characters long. No count is returned |
| `native_normalization.read_lhe` | Raises `ValueError: truncated LHE document`. No count is returned |
| Oracle `census` | `gzip_complete` true, 41 complete events, `document_complete` false, `header_nevents` 100, `sha256_matches_record` false. Physics withheld (`document_incomplete`, `event_count_mismatch`) |
| Oracle `prefix_selection` (fault-value diagnostic) | 41 complete events, 37 selected, `opened_event_blocks` 42 |

The oracle's count is the closed blocks. The opening-tag count of 42 is a plausible naive answer,
so the census exposes it as a fault-value diagnostic only (`opened_event_blocks`).

### 3c. A gzip-level cut (documentation only)

The test takes the first 10,528 compressed bytes of DY 1730.

- Both kernel readers raise `EOFError: Compressed file ended before the end-of-stream marker was
  reached`.
- The oracle reports `stream_error = truncated_stream` and withholds physics.

This is the construction the design keeps only as a categorical reserve (§8).

Neither kernel reader reports any count or physics for either truncation. So on a truncated file
the census stage (plan step 4) cannot take `complete_events` from `audit_lhe`. It needs its own
integrity pass first, as design §3.3 already specifies. The kernel also offers no prefix physics,
which is consistent with the provisional D-CP.

## 4. Diagnostics (design §7.3; not correctness criteria)

### 4a. Toy CLs at the asymptotic observed root

The toys use the oracle's q̃ and follow the usual LHC prescription:

- s+b toys are drawn at (μ = S95, ĝ(μ)).
- b-only toys are drawn at (0, ĝ(0)).
- The main count and an integer auxiliary count are Poisson draws. The observed auxiliary count
  stays the continuous a = τ.
- q̃ is computed once per distinct (count, auxiliary count) pair. That gives exactly the per-toy
  result at a small fraction of the cost.
- The MC standard error comes from the delta method on the two binomial fractions.
- The implied S95 offset is (toy CLs − 0.05) / (|dCLs/dμ| × S95). A positive offset means a
  toy-based observed limit would be larger by about that fraction.

**The 10⁸-toy record.** This is `test_toy_cls_large_n` with `RAVEL_ORACLE_TOY_CHUNKS=50`: 50 chunks
of 2,000,000 toys per hypothesis, chunk i drawn from `numpy.random.default_rng(20260926 + i)`. The
test stores these values as `TOY_REFERENCE`.

| Model | Asymptotic S95 (events) | CLs+b | CLb | Toy CLs | MC SE | Implied S95 offset |
|---|---|---|---|---|---|---|
| LF prior | 19.46172 | 0.035475 | 0.693675 | 0.051141 | 0.000027 | +0.468 ± 0.011 % |
| LF V1 | 15.48984 | 0.021015 | 0.409711 | 0.051293 | 0.000036 | +0.619 ± 0.017 % |
| 2jl | 43.65129 | 0.011942 | 0.241714 | 0.049405 | 0.000046 | −0.290 ± 0.022 % |
| hv | 34.01420 | 0.045980 | 0.913480 | 0.050335 | 0.000023 | +0.108 ± 0.007 % |

Consistency checks on that record:

- A separate 10⁸-toy run with seeds 1–50, a scratch measurement not in the suite, gave +0.478,
  +0.615, −0.252 and +0.108 %, each with the same standard errors. It agrees within 1.2 combined SE.
- The review's own code gave the same picture at 2 × 10⁶ toys per run.
- The default test run (3 chunks, 6 × 10⁶ toys) gives +0.37 ± 0.04, +0.58 ± 0.07, −0.40 ± 0.09
  and +0.13 ± 0.03 %. The test checks each offset against the record within 4 combined SE. It also
  checks that both LF offsets are positive at more than 4 SE.
- No toy of this ensemble tied q̃_obs in any run. The observed auxiliary count a = τ is not an
  integer (57.76, 77.44, 139.04 and 68.65), so the ≥ and > tail rules give the same CLs here.

**The 20,000-toy values.** These are the design's scratch setup, and they reproduce exactly under
NumPy 1.26.4. At this N the offsets carry standard errors of 0.5–1.6 % of S95, so they do not
resolve the offsets above. The hv excess of 1.3 SE was a fluctuation.

| Model | CLs+b | CLb | Toy CLs | MC SE | Implied S95 offset | Its SE |
|---|---|---|---|---|---|---|
| LF prior | 0.03490 | 0.69505 | 0.05021 | 0.0019 | +0.09 % | 0.77 % |
| LF V1 | 0.02070 | 0.40700 | 0.05086 | 0.0025 | +0.41 % | 1.20 % |
| 2jl | 0.01215 | 0.23905 | 0.05083 | 0.0033 | +0.40 % | 1.61 % |
| hv | 0.04760 | 0.91230 | 0.05218 | 0.0017 | +0.70 % | 0.53 % |

Under any NumPy version, the 20,000-toy test now checks each toy CLs within 4 MC SE of the
10⁸-toy value, not of 0.05.

**Toy CLs is not one value.** Besides seed and N, it depends on the ensemble. A hand-rolled
ensemble that keeps the auxiliary count fixed at τ is not the LHC prescription; it appears here
only to size this dependence. In a scratch run with 2 × 10⁷ toys it gives toy CLs of 0.10–0.24
at these roots. Many toys then tie q̃_obs, and in a 2 × 10⁶-toy run the ≥ and > rules differ by
0.011–0.019 in CLs.
Toy-based CLs therefore cannot be tabulated as a single convention value.

What the record establishes:

- At these counts the asymptotic observed limit differs from the toy-based one by −0.3 to
  +0.6 % of S95. The design's original "adequate to about 1 %" is right. "Consistent with no
  bias" would be false.
- For LF V1 the offset, +0.62 %, lies outside the 0.005 relative scoring tolerance. For LF prior,
  +0.47 %, it lies just inside. For 2jl and hv it lies well inside.
- Only the observed limit was measured. The LF families also score the expected median, and no
  toy measurement of the median was made.

### 4b. Sensitivity of S95 to the CLs level

This is the relative change of the observed limit when the level moves from 0.05 to 0.048 or 0.052.

| Model | Level 0.048 | Level 0.052 |
|---|---|---|
| LF prior | +0.84 % | −0.81 % |
| LF V1 | +0.97 % | −0.94 % |
| 2jl | +0.99 % | −0.96 % |
| hv | +0.65 % | −0.63 % |

A CLs shift of ±0.002 at the root therefore moves S95 by 0.63–0.99 %, which confirms the design's
"0.6–1.0 %".

## 5. Differences from the design and items for its review

The design file is outside the repository, so it is unchanged. These are the corrections and
decisions its human review needs.

1. **MC standard error (§7.3, §2 P6).** The design quotes "about 0.002–0.003", and "about 0.003" for
   hv. At 20,000 toys the delta-method values are 0.0017–0.0033, and 0.0017 for hv.
2. **Toy CLs (§7.3) and convention rule 4 (§1.4).** Keep "adequate to about 1 %" and add the
   measured offsets: −0.3 to +0.6 % of S95 at these counts (§4a). Do not adopt "consistent with no
   bias", which this appendix suggested before review. The decision to pin the asymptotic estimand
   stands, and the record justifies it better.

   The record opens a gap in §1.4 rule 4. That rule says every known legitimate convention
   alternative, naming toy-based CLs, is either within tolerance or listed in `convention_values`,
   but only pre-fit Asimov values are listed. The toy alternative for LF V1 (+0.62 %) is outside
   the 0.005 tolerance, and LF prior (+0.47 %) is close to it. Two resolutions are available:

   - **(a) Recommended.** Declare toy-based CLs excluded by the pinned estimand clause of rule 1
     ("asymptotic q-tilde, computed with the task tool"), and drop it from rule 4's list of known
     alternatives. It then needs no `convention_values` entry. A subject who substitutes toys has
     not computed the requested estimand, so `wrong_value` on LF V1 is the intended reading. This
     also avoids tabulating a quantity that depends on seed, N and ensemble (§4a).
   - **(b)** Add a toy-convention band that maps to `unresolved` for LF V1 and LF prior. The band
     would have to be defined for one ensemble and N, and it would not cover the expected median,
     which was not measured.
3. **Edge margin (§2 P5, §7.4).** Keep the design's "about 10⁷" and name it: the margin against the
   printed-decimal precision of the momenta. It is 1.8 × 10⁷ for the DY 1730 nearest-edge event, and
   1.5 × 10⁷ as the minimum over all its events (§3a). Report separately the reader-arithmetic
   margin of about 10¹¹, which applies only to double-precision readers of the same printed
   decimals. This appendix previously called the design's figure conservative; it is not.
4. **Reader claim (§2 P5, §7.5).** Replace "every reader tested gives 41" with "every byte-level
   decompressor gives the same content, which has 41 closed blocks". Counting opening tags gives
   42, ElementTree's `fromstring` and both kernel readers raise, and `iterparse` yields 41 and then
   raises (§3b). Step 4 has to account for the kernel readers giving no count.
5. **tz `fault_values` (§2 P5).** Add `open_block_counted` = 42, with verdict `wrong_value`. Give
   `extrapolated_selection` a tolerance of about 0.5 events, so that the unrounded 37/41 × 100 =
   90.24 matches it as well as 90.
6. **mq margins (§0 table, §2 P4).** The nearest fault is "both errors", 3,308.32725 = Y × 10⁻¹: a
   90 % effect, 90 times the 0.01 tolerance, not "×10² (99 %) = 99×". `pb_as_fb` is Y × 10⁻³
   (99.9 %, 99.9×), and `weight_sum_misread` is Y × 10² (9,900 %). The table's "3,308.327" is
   exactly 3,308.32725. These follow exactly from Fraction arithmetic on Y = 33,083.2725, and
   `test_dy_1729_yield_identity_is_exact` checks them. The step-7 builder's effect-floor check
   should compute effects from `fault_values`, not from design prose. The 3× floor holds either
   way.
7. **Sources and licences (§1.3).**
   - The mq and tz LHE files keep MG5_aMC@NLO banner and card-template text in their headers.
     `docs/reference/third-party.md` lists MG5_aMC under a UoI/NCSA-style licence. So "Licence:
     Apache-2.0" should read "Apache-2.0 for the RAVEL-generated content; the header keeps
     MG5_aMC@NLO banner and card text under its own licence". The reviewer confirms this. The
     citation request is preserved. The fixture record now says this.
   - "Redaction touched only the home-directory prefix" is the exporter's statement. The event-block
     hashes show the event bytes unchanged, and σ is corroborated separately (§3a).
   - The truncated fixture's source kind is now `ravel_generated_development`, with the truncation
     listed under `modifications`. The earlier `derived_from_ravel_generated_development` was not
     in the design's vocabulary. The step-1/7 contract should accept `modifications` for this kind.
   - kx: no HEPData record is used for the 2jl counts. The source is the paper's Table 6. The
     reviewer confirms the table and whether a HEPData record should be cited.
   - Outside this workflow's scope: `NOTICE` points to a `THIRD_PARTY.md` that does not exist; the
     file is `docs/reference/third-party.md`. This predates the task.
8. **`cls_at_cap` in the oracle record (§2 P3).** It comes at plan step 7 (§1b). Done at step 7
   (`6637950`, decisions.md E-129): each side carries it, null when every curve is resolved; the kx fault
   record holds 0.60590601 and the expected values above, and the kernel's fit on the kx fault
   workspace agrees within 10⁻⁷ (`tests/governance/test_bank_families.py`).

Everything else quoted in the design and checked here matches to the half-unit of its last printed
digit:

- the 2jl CLs at 10;
- the oracle–kernel agreement of 2.5 × 10⁻⁵ for 2jl;
- the hv limits;
- the DY σ, counts and selections;
- the 20,000-toy CLs values.

## 6. Tolerances in the tests

| Check | Bound | Measured worst |
|---|---|---|
| CLs at one μ: oracle against every kernel scan point (2jl cap 10, 2jl cap 256, hv) | 10⁻⁷ absolute | 2.0 × 10⁻⁸ |
| CLs at μ = 10: oracle against stock pyhf | 10⁻⁷ absolute | 8.0 × 10⁻⁹ |
| Stock pyhf CLs(10), cap 10 against cap 256 | 10⁻¹² | 0 |
| Kernel limits (hv, 2jl cap 256, recorded 2jl control) | 1.5 × 10⁻⁴ relative | 2.5 × 10⁻⁵ |
| Fresh kernel run against the recorded controls | 10⁻⁷ CLs; 1.5 × 10⁻⁴ limits | 0; 0 |
| Stock pyhf implied root offset, tolerance 10⁻⁹ / 10⁻¹² | 10⁻⁶ / 10⁻⁷ | 4.2 × 10⁻⁷ / 8.8 × 10⁻⁹ |
| LHE per-event masses | 10⁻⁹ relative | 3.7 × 10⁻¹⁵ |
| Σw, Σw² | 10⁻¹² relative | 0 |
| σ, counts, selection, exceptions | exact | exact |
| Selection-edge margin against the printed decimals | > 4.0 × 10⁷ (DY 1729), > 1.5 × 10⁷ (DY 1730) | 4.1 × 10⁷, 1.5 × 10⁷ |
| Toy CLs, 20,000 toys (diagnostic) | within 4 MC SE of the 10⁸-toy value | 1.1 SE (hv) |
| Toy offsets, default large-N run (diagnostic) | within 4 combined SE of the 10⁸-toy record; LF offsets > 4 SE; no ties | 2.2 SE (LF prior); 8.2 and 8.4 SE; 0 |
| Level sensitivity (diagnostic) | 0.5–1.1 % | 0.63–0.99 % |

The kernel-limit bound was 10⁻⁴, equal to the kernel's Brent `root_rtol`, and had no structural
headroom. `brentq(xtol=1e-10, rtol=1e-4)` guarantees that tolerance only against the root of the
kernel's own CLs function. That root moves from the oracle's by up to CLS_ATOL / (|dCLs/dμ| × μ)
relative. The bound is now 1.5 × 10⁻⁴. The test checks that the extra 5 × 10⁻⁵ covers the xtol
term plus that shift at every root; it needs at most 5.8 × 10⁻⁷ (hv). The bound sits inside the
kernel's own contract, which allows up to about 0.3 % on S95 through `root_rtol` plus
`root_cls_atol`. A kernel change that stays inside that contract can still trip this test. If
that happens, review the change rather than widen the bound.

**Mutation check.** The cross-checks were run against deliberately broken copies of the oracles in
a scratch tree. Three counting mutants were each killed by a kernel cross-check:

- pre-fit Asimov data;
- a γ upper bound of 1.05;
- a shifted expected quantile.

On the LHE side, a mass rounded to 10⁻⁶ GeV was killed by the mass comparison. Three LHE mutants
survived both the cross-checks and the step-2 tests:

- dropping px from the pair mass;
- reading σ from XMAXUP;
- a widened window.

Each of these is equivalent on the public files. LO pairs carry no transverse momentum, MadGraph
writes XMAXUP = XSECUP for unweighted events, and no mass lies within 0.005 GeV above 101 GeV. Two
synthetic tests now kill the first two: a recoiling pair, and XMAXUP ≠ XSECUP. The existing edge
test in `test_oracle_lhe.py` kills the third.

**Fixture reproducibility.** Under zlib 1.2.12, 1.3.1 and 1.3.2 the builder gives byte-identical
fixture bytes, with sha256 `c45eea92…`. It was run with CPython 3.11–3.13 interpreters on this host,
and `reproduced_with_zlib` records those versions. `build_fixture.py --write` no longer rewrites
`fixtures.json` when the stored fixture already matches, so a rerun cannot silently change
`built_with_zlib`.

## 7. What this does not establish

- **Independence.** The kernel and stock pyhf share the pyhf library, so their agreement with each
  other adds nothing. The oracle's agreement with both is agreement of separate code that
  implements the same definitions. It is not a validation of those definitions; that is the PKT-D02
  review.
- **Coverage and toy calibration.** §4a resolves the toy-asymptotic difference of the observed
  limit for the four models, under one toy ensemble. It does not measure coverage, the expected
  limits, or other ensembles.
- **Scope.** The two LHE comparisons cover two 100-event LO files with a two-lepton final state.
  Weighted, negative-weight or multi-process files were not tested against the kernel; the oracle
  withholds physics for most of them anyway.
- **Provisional decisions.** D-V, D-KX, D-MC and D-CP were adopted provisionally on 2026-09-26 for
  the deferred human review. They are recorded in [decisions.md](decisions.md) (E-110, E-115 to
  E-117; questions H-40 to H-44), and the [task-bank review packet](taskbank-review-packet.md) puts
  them to the reviewers. This appendix does not decide them.
