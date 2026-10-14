# Checks and evidence: model-authoring

The static block validates the supported ModelSpec tier and reports charge,
hermiticity, quadratic and source-lint checks. Its Python tests use a generic
neutral scalar with synthetic mass and width: rendering and static checks,
unsupported weak representation refusal and charged real-field refusal.
The UFO block is tested on a deliberately incomplete directory containing a
Python side-effect statement: parsing must report failure without executing it.
No kernel, FeynRules model, MadGraph process or site job runs.

Scope boundaries: `validate_spec` checks declared structure;
`charge_census` checks supplied field occurrences;
`hermiticity_census` is static bookkeeping;
`adjudicate_gauge_checks` interprets actual native verdicts;
`ufo_check.check` parses declarations. A requested two-body width checks only its
selected channel. The generated model card records these scopes and unexecuted
checks. An upstream pin does not imply a successful export at that version.

| Advisory ID | Candidate check | Evidence needed | Current enforcement |
|---|---|---|---|
| MA-A1 | Compare the typed source reading with independent Lagrangian/vertex/width or amplitude witnesses over the requested parameter domain | Original source spans, all sectors and couplings, gauge/restriction settings, declared approximations, actual native export and independent predictions | Partial: static censuses, bridge mass/restriction witnesses and selected physical checks cover individual obligations; complete model admission and source interpretation require the model-admission review |

Read-only sources: `src/ravel/physics/model_authoring.py`, `fr_lint.py`,
`ufo_check.py`, `model_physical_checks.py`, `model_derivation_bridge.py`,
`model_provider_bridge.py` and `ufo_interop.py`. Re-review this handbook when the
model-admission contract changes.
