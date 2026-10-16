---
name: mcfm-amplitudes
description: Use when integrating a source-pinned MCFM amplitude basis, recombining complex helicity members, predicting signed differences to a measurement reference, exporting named weighted events, or interpreting amplitude closure and independent matrix-element cross-checks in RAVEL.
license: Apache-2.0
compatibility: MCFM 10.2.1 amplitude program is an external GPL-3.0-or-later program; RAVEL retains only its source contract and records. NumPy 1.26.4 handles Gram algebra. No upstream code is included in this handbook.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "amplitude-integration amplitude-predictions weighted-events"
  upstream-version: "mcfm-amplitudes:MCFM=10.2.1 pypi:numpy=1.26.4"
  last-reviewed: "2026-10-13"
---

# MCFM amplitudes

## RAVEL's path

`ravel amplitudes example --mode <mode>` prints a synthetic document.
`check --mode <mode> --input doc.json` inventories its inputs; `spec` writes the
ordinary study specification. Integration, prediction, event export and
cross-check run through `ravel plan`, approval and `ravel run`.

`amplitude-integration` uses a pinned external program protocol and execution
backend. It warms up a channel's grid before independent equal-exposure blocks.
`amplitude_records` parses the capture format and compares recombined amplitudes
with the program's own squares. `amplitude_store` retains completed blocks,
point counts, attempted/accepted/rejected/failed census and completion digests.
No new mass hypothesis warrants rerunning the captured fixed basis by default;
first check whether it lies in that basis and input domain.

The external MCFM overlay is separately installed. Its manifest pin is MCFM
10.2.1. RAVEL verifies the component files and protocol; a matching executable name
alone does not establish compatibility. No GPL source is copied into this Apache
handbook or the Python package.

## Installed runtime

The installer builds, checks and records the per-point helicity-amplitude
program for interfering resonances. Its Linux x86_64 native route is qualified
from a clean-prefix build, a passing doctor check and the numerical qualification
recorded in the manifest; the macOS container route stays built-unqualified until
its own build and checks are recorded. For this group alone run
`bash scripts/setup/install.sh --only mcfm-amplitudes --jobs 4 --accept-licenses`,
then `ravel doctor --group mcfm-amplitudes`. Source, overlay and the upstream
files the overlay relies on are verified on the host. On macOS compilation runs
in a pinned linux/amd64 image with no network; Apple
silicon uses Rosetta in the Podman machine. Start a stopped machine with
`ravel-podman machine start ravel`. On Linux x86_64 the program is compiled on
the host with the GNU compilers of the compiler-bootstrap group and runs
through the `native` backend. The installer's prefix lock serializes either build;
the machine lease admits approved study stages only.

An integration backend supplies kind and resources. Omitted image, program,
read-only trees and runtime environment come from
the prefix record installations/mcfm-amplitudes.json found by `ravel.paths.native_build_root()`;
a native installation fills only the program and its environment. Every stage
receives pinned copies of MCFM's runtime files (process.DAT, br.sm1, br.sm2).
The program reads its inputs in its card's directory and writes its outputs to
`RAVEL_OUTPUT_DIR`. The program declares MCFM's own safety cuts in its manifest
(`protocol.safety_cuts`: the 0.1 GeV Z transverse-momentum cut and lowint's 1e-9
small-invariant cut) and applies them when it makes each draw: a draw below one is
excluded, stays in the exposure and contributes zero,
so every integral covers the restricted phase space. The study document must accept
exactly the declared cuts in `safety_cuts`; RAVEL refuses an undeclared cut,
rechecks every point from its momenta, records the cut in the store header and
assumptions, and measures the excluded share of draws and weight per stage.
Explicit fields retain their values. The record is pinned in the
study inputs and every backend stage, so changes invalidate prepared work. Installation authority
covers compilation and the binary check; it grants no study approval, and
installation is never a human review. Numerical qualification requires a
separate approved point-oracle study. See [checks](references/checks.md).

## Complex amplitudes are the reusable object

For amplitudes a[point, helicity, member] and coefficients c[point, member], the
weight is the helicity sum of the squared complex amplitude sum. RAVEL stores
the Hermitian Gram matrix G and evaluates real(c-dagger G c). Relative phases
and off-diagonal entries carry interference; summing separate member squares
loses them. Coefficients include the declared couplings and propagators.

```python ravel-block=recombine-amplitudes
from ravel.physics import amplitude_basis

def recombine(amplitudes, coefficients):
    """Distinct-particle algebra; identical-particle pairing needs its full protocol."""
    gram = amplitude_basis.point_grams(amplitudes)
    return gram, amplitude_basis.evaluate(gram, coefficients)
```

```python ravel-block=read-completed-block
from ravel.physics import amplitude_store

def read_completed_block(path):
    """Read only a completed block whose bytes still match the recorded digest."""
    return amplitude_store.read_block(path)
```

Use chunked reading for production stores. Resume checks the original header,
schedule and every completed block; a changed contract needs a new study.

## Signed predictions and uncertainty

`amplitude-predictions` applies declared stored-point cuts and bin edges, writes
`binned_values`, joint block covariance and a `differential-likelihood` input.
Coefficients and propagator laws define the actual supported hypotheses.
A difference-to-reference can be negative; keep both its sign and covariance.
For declared coupling powers, interference and pure-signal terms have different
powers, while the width stays under its own declaration.

`weighted-events` writes HepMC3 or LHE named streams. These event weights are
absolute; divide RAW histogram sums by attempted draws of each block. Ordinary
crossSection/sumOfWeights normalization is invalid for cancelling differences.
Independent cohorts add; equal-exposure block estimates give a covariance of the
mean. Failed draws are not zeros. Preserve input hashes, reference definition,
block census, representation, normalization source and statistical uncertainty.
Read `docs/reference/amplitude-reweighting.md` before choosing the estimator.

## Pitfalls

- Nonfinite amplitudes or missing swapped amplitudes for identical particles are
  treated as valid points. Caught by `ravel.physics.amplitude_basis.point_grams`.
- A capture recombination disagrees with the external program's own square.
  Caught by `ravel.physics.amplitude_records.oracle_check`; its returned pass flag
  checks only this internal consistency.
- A partial block, changed file or changed resume schedule is reused. Caught by
  `ravel.physics.amplitude_store.read_block` and
  `ravel.physics.amplitude_store.run_schedule`.
- Failed native draws are counted as zero accepted weight. Caught by
  `ravel.physics.amplitude_predictions.block_vectors`.
- New spin-0 members use incompatible helicity phases. Caught by
  `ravel.physics.spin0_amplitudes.closure` within its declared alignment tolerance.
- Advisory: RAW/attempted-draw normalization must remain correct through any new
  shower or routine path. Candidate check AM-A1 in `references/checks.md` compares
  absolute signed stream estimators through the complete chain.

## Wrong versus right

| Wrong | Right | RAVEL check |
|---|---|---|
| Drop a swapped identical-particle pairing | Capture both with fixed-reference partition flags | `amplitude_basis.point_grams` |
| Accept captured amplitudes without their program-square oracle | Retain same-point residuals and fail mismatches | `amplitude_records.oracle_check` |
| Read a file without its completion digest | Verify the completed block and resume identity | `amplitude_store.read_block` |
| Turn failed draws into zero-weight draws | Keep the failure census and refuse prediction | `amplitude_predictions.block_vectors` |
| Append unaligned helicity amplitudes | Require same-point phase closure | `spin0_amplitudes.closure` |

More: `references/checks.md` and `references/review.md`. Upstream references:
MCFM manual, version 10.2.1; NumPy 1.26 reference; HepMC3 user manual
(Buckley et al., arXiv:1912.08005, 2020). RAVEL's capture format is its component
contract, not a claimed standard upstream MCFM API.
