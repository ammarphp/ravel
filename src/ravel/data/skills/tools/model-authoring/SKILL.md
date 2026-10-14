---
name: model-authoring
description: Use when translating a supplied Lagrangian into a typed ModelSpec, rendering and linting a FeynRules extension, checking exact charges and canonical quadratic terms, preserving two-gauge verdicts, or inspecting an exported UFO before model admission in RAVEL.
license: Apache-2.0
compatibility: FeynRules 2.3.49 requires a separately licensed Wolfram kernel. Static ModelSpec, source lint and UFO parsing run in Python; they neither execute FeynRules nor admit an unreviewed physical model.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "model-authoring model-sources model-derivation-bridge model-provider-bridge"
  upstream-version: "wolfram:feynrules=2.3.49"
  last-reviewed: "2026-10-11"
---

# Model authoring

## RAVEL's path

`model-authoring` turns a confirmed ModelSpec into a FeynRules extension of
`SM.fr`, lint reports, native run scripts and a model card. `ravel model templates`
lists supported inputs; `instantiate --template <id> --values values.json` builds
a spec from supplied values. `render --spec spec.json` prints source;
`lint --fr model.fr --spec spec.json` checks it. `check-ufo --ufo <dir> --spec spec.json`
parses an export without importing its Python code.

`author --spec spec.json --out model-run` writes preparation files without
running FeynRules. For native work, use `ravel model plan` and the approved
ordinary study lifecycle. A generated script or static pass is not permission
to launch a kernel or generator. Provider startup, derivation and physical checks
have their own evidence through `model-provider-bridge`, `model-sources` and
`model-derivation-bridge`.

The automatic authoring tier supports new SU(2)-singlet scalar,
vector and fermion fields in colour representations 1, 3 or 8 in the SM gauge
basis. Other representations, multiplets and new gauge groups raise
`UnsupportedModel`. Retain the original requirement and choose a source-backed
SARAH or derivation route; do not rewrite it as a singlet to fit the template.
Masses, widths, couplings and physical approximations come from declared input.

## Translate before generating

A ModelSpec records fields, rational charges, PDGs, mass/width symbols,
parameters and LHA indices, Lagrangian source spans and operators, conjugation,
required and optional couplings. Exact-rational charge accounting tests declared
monomials. Lint checks source structure and agreement with the spec; it does not
prove that the spec reads the original Lagrangian correctly.

```python ravel-block=static-model-census
from ravel.physics import model_authoring, fr_lint

def static_model_census(spec):
    """Return rendered source and scoped static reports, with no native execution."""
    model_authoring.validate_spec(spec)
    source = model_authoring.render_fr(spec)
    checks = {
        'charge': model_authoring.charge_census(spec),
        'hermiticity': model_authoring.hermiticity_census(spec),
        'quadratic': model_authoring.quadratic_census(spec),
        'lint': fr_lint.lint(source, spec=spec),
    }
    return source, checks
```

Inspect each report's `passed`, errors and warnings before proceeding.
Generated canonical kinetic/mass terms and declared interaction operators remain
separate. A token inventory of fields does not inspect every mathematical
meaning of an arbitrary operator.

## Native checks and UFO inspection

FeynRules scripts request hermiticity, diagonal quadratic/mass terms and kinetic
normalization in both gauges. The adjudicator retains typed verdicts. Unitary
gauge decides; a Feynman-gauge exception requires an explicit source-reported
Goldstone mixing pattern and a passing unitary check. It is not a general waiver.
The derivation bridge's mass/restriction witnesses and selected two-body widths
remain separate claims.

```python ravel-block=inspect-ufo
from ravel.physics import ufo_check

def inspect_ufo(directory, spec=None):
    """Parse UFO literals without importing the model; return the static verdict."""
    return ufo_check.check(directory, spec=spec)
```

UFO checks include Python syntax, symbolic leaks, vertices and Lorentz structures,
PDG uniqueness and spec field/coupling survival. Python 2 error forms require the
narrow journalled `ufo_interop` conversion, as described in feynrules. MadGraph
import-and-generate evidence, when requested, is another native check and must
retain the actual process and nonempty diagrams. A parseable export is not a
unitarity, anomaly, loop or UV-completion proof.

Outputs stay `generated_contract_checked`. Keep the generated model-card.json and
model-card.md, sources, conventions, approximations, checks and the trust record.
Promotion requires the applicable admission/review record.
See `docs/reference/models-and-normalization.md`, `model-sources.md` and the
feynrules and madgraph-model-import handbooks.

## Pitfalls

- A weak multiplet or unsupported gauge structure is silently squeezed into a
  template. Caught by `ravel.physics.model_authoring.validate_spec`.
- A real field has a nonzero charge, or a declared interaction monomial is charged.
  Caught by `ravel.physics.model_authoring.validate_spec` and
  `ravel.physics.model_authoring.charge_census` respectively.
- The rendered file clashes with SM identifiers, omits parameter declarations or
  contains forbidden file/process access. Caught by `ravel.physics.fr_lint.lint`.
- Any Feynman-gauge failure is waived without its explicit Goldstone evidence.
  Caught by `ravel.physics.model_authoring.adjudicate_gauge_checks`.
- A Python-2 or symbolic-leaking UFO, missing spec field or unused required coupling
  reaches the next stage. Caught by `ravel.physics.ufo_check.check`.
- Advisory: an internally consistent ModelSpec can still misread the original
  Lagrangian or omit a physically required sector. Candidate check MA-A1 in
  `references/checks.md` compares source definitions and independent predictions.

## Wrong versus right

| Wrong | Right | RAVEL check |
|---|---|---|
| Replace an unsupported multiplet by a singlet | Preserve the requirement and route the unsupported feature | `model_authoring.validate_spec` |
| Use floating charges or omit conjugation bookkeeping | Declare exact rational charges and every field occurrence | `model_authoring.charge_census` |
| Accept rendered text without lint | Check structure and spec agreement before native execution | `fr_lint.lint` |
| Ignore all failures in one gauge | Require the typed allowed Goldstone pattern and passing unitary check | `model_authoring.adjudicate_gauge_checks` |
| Import the UFO to see whether it works | Parse it statically, then request the separate native import witness | `ufo_check.check` |

More: `references/checks.md` and `references/review.md`. Upstream references:
Alloul et al., FeynRules 2.0 manual, arXiv:1310.1921 (2014), with the installed
2.3.49 pin; Degrande et al., UFO - The Universal FeynRules Output,
arXiv:1108.2040 (2012). No novel upstream API is assumed here.
