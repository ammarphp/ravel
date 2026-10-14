# Source-bound symbolic evaluation

`symbolic-evaluation` connects reviewed Wolfram/FeynCalc scripts to the ordinary
schema2 scientific-study plan, review, worker and report lifecycle. The
HEPTAPOD backend uses the parser/converter bytes from observed revision
`705b03cc36d96a79107df28d053a23d3fac1d393`; the original external GPL sources,
license and authors files remain caller-supplied dependencies. The complete Python
setup provides SymPy; bind the actual interpreter and complete SymPy/mpmath package
trees as described by the [installation guide](../installation.md). No dependency is imported during intake.

The task is `{input, input_sha256}`. `ravel symbolic-evaluation inspect --input
request.json --input-sha256 <digest>` authenticates prerequisites without running a
kernel. Supply the same task in `ravel plan` with a schema2 review policy.
The exact closed request fields and validation are in
`ravel.physics.symbolic_evaluation.validate_config`. Every input needs an explicit
source identity: original question, existing kernel executable/application metadata,
complete FeynCalc and script trees, backend files, conversion runtime and dependencies.
The provider tree contains `FeynCalc/FeynCalc.m`. Declared actual kernel/provider
versions must match evaluated observations; installed proprietary libraries and the
OS remain outside this finite source capsule.

Each script declares its complete original marker roster and ordered result roster.
A result declares the source symbol, complete ordered free variables, domains,
units/mass dimensions, explicit physical conventions, assumptions and optional
complete numerical points. Numerical coordinates are `{real, imag}` pairs. Constants
may have no variables. No real-coupling, equal-mass, spin/color average, symmetry
factor or vertex normalization is inferred. For example, the vertex convention
`I gamma(gV-gA gamma5)` and the scalar convention `I(gS+gP gamma5)` have different
chiral basis maps; retain the actual source convention and any extra pseudoscalar
factor explicitly. The adapter does not apply either transformation automatically.

The approved worker stages exact script/provider copies and uses the existing
supervised direct-kernel route. This is a named transport adaptation of HEPTAPOD's
runner. It retains unchanged original stdout and parser records, then extracts
declared symbols into a canonical InputForm sidecar. The package path and both
FeynCalc resolution observations bind the staged provider; no global/user
configuration or license activation is performed. The existing user/license
directory and caller `WOLFRAM_BASE`/`WOLFRAM_USERBASE` values are preserved;
only initialization-program overrides are suppressed. Wolfram documents that `$UserBaseDirectory` cannot be reset
inside a running kernel. Source scripts are trusted executable inputs, not sandboxed
expressions. They must return normally for canonical extraction to complete.

The original lower-level converter emits Python source and optional evaluated
values. Syntax and exact function/coordinate signatures are checked before delivery;
these checks do not establish formula equivalence. Exact free-symbol checks prevent omitted variables. Finite complex outputs
remain real/imaginary pairs, including a zero imaginary component. Unsupported
expressions or numerical branches retain their errors; no replacement physics
formula is supplied. Canonical formula, conversion and numerical statuses are
separate. Missing, duplicate or malformed markers; wrong provider/process identity;
parallel kernels; changed source; nonfinite values and incomplete results prevent
complete delivery. Every requested result and point remains in the denominator.
Canonical bytes are captured once before decoding. Previously emitted artifacts
retain their original byte commitments through conversion and final publication;
later changes cannot be accepted by recomputing their identities.

One aggregate serial deadline covers source staging, all scripts, conversion and
ending checks. Ordinary supervision bounds runtime and sampled memory. The declared
output byte bound is checked at phase/publication boundaries, not enforced as an
OS disk quota. No hidden probes, retries, downloads, installations or new parallel
kernels are launched by the adapter. A failed stage retains its complete partial
artifacts for existing research diagnosis and review.

`symbolic-evaluation.json` and the common `result.json` retain complete formulas,
source pins, physical declarations, Python modules and numerical rows. The ordinary
report links the full symbolic report and all result dispositions. Existing typed
`scientific_artifact.compose` and `scientific_report.compose` accept source-bound
formula strings and scalar real/imaginary fields. For structural formula completion,
use a scientific-context check
`{kind: symbolic-record-census, id_field: id, expected_ids: [...], text_fields:
[formula]}` against the complete results list. It requires every exact ID, a
nonempty formula string and literal delivered status. This establishes structural
delivery only. It does not establish mathematical correctness or physics validity.
Existing artifact/report presentation bounds remain; oversized formulas stay in
the canonical artifact and cannot silently pass a truncated presentation.

The current `diagrammatica-code` generator retains its original supported families
and limitations. Separately reviewed scripts may implement other families, but
executing a batch does not complete the original decay catalogue, gauge/SM checks,
special limits, numerical equivalence or figure obligations. Those require their
original parent task and independent scientific validation. An activated licensed Wolfram kernel is required for this backend. Preserve existing
activation and user directories; Python/SymPy operations use their declared backend.

Primary API references: [Wolfram user directory](https://reference.wolfram.com/language/ref/$UserBaseDirectory.html),
[package file resolution](https://reference.wolfram.com/language/ref/FindFile.html).
