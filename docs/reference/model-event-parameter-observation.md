# Source-defined dependent parameter cards

The optional `parameter_observation` field in a model-events configuration admits one
prospective, source-bound MG5 2.9.27 card-update law through the existing ordinary
science plan, approval, worker and review route. Old configurations retain their
strict complete-value equality gate. Adding this field changes the configuration
hash and requires a fresh ordinary plan/approval; it cannot repair or accept an old
failed attempt.

```json
{
  "schema_version": 1,
  "mode": "mg5_2_9_27_literal_dependent_writer",
  "model_sources": {
    "parameters": "<SHA256 of admitted parameters.py>",
    "particles": "<SHA256 of admitted particles.py>",
    "functions": "<SHA256 of admitted function_library.py>"
  },
  "maximum_relative_error": "0.0000006",
  "complex_mass_scheme": false
}
```

All three files belong to the complete admitted UFO tree. The selected MG tree must
also contain the exact released parser, model-reader, UFO-import and common-run
implementations pinned by `model_event_parameters.PRIMARY_SHA256`. Copied scientific
source remains protected by the existing complete before/after phase census. The
optional renderer explicitly sets real-mass scheme, without saving global options.
No new execution or review authority is introduced.

The original complete card remains the free-input authority. Every literal external
UFO address must be present; model defaults never supply missing values. Only literal
real external parameters and statically declared physical Particle mass/width
references are supported. Internal closure uses bounded scalar arithmetic, explicitly
qualified cmath/math operations and literal Function bodies, without importing or
executing UFO code. Declared Functions precede builtin calls in parameter expressions;
an unqualified `sqrt` is not a convenience alias for `cmath.sqrt`. A declared scalar
used as a callable, or a scalar/function shadowing a qualified module, refuses.
Function arguments have local precedence, while Function bodies use the pinned
ModelReader module globals (including `ZERO=0`) rather than capturing model
parameters or other declared Functions. Unresolved body globals, parameter/Function
name collisions whose evaluation order is unproved, and declarations shadowing
`locals` or `__builtins__` refuse explicitly. Unsupported dynamic declarations,
cyclic references, nonreal physical masses,
automatic widths and complex-mass transforms refuse. Ghosts and Goldstones are
excluded as in the released updater. Model free inputs never acquire zero from an
unknown or missing name; the source-global `ZERO` constant remains distinct from a
declared parameter or a Function argument of the same name.

The supported namespace resolves a binding before interpreting it as a scalar,
module or callable: Function argument → declared parameter/Function in outer
`all_params` → pinned module globals → supported builtins. A declared Function
is never treated as a scalar, even if its name shadows the global `ZERO` constant;
it remains callable at that name. A bare module or builtin function likewise cannot
be converted to a physical mass. Function bodies omit the outer `all_params` step,
so an outer Function named `ZERO` does not replace their module-global `ZERO=0`.
This is the finite admitted expression scope, not a claim to implement arbitrary
Python or every ModelReader global.

`ParamCard.update_dependent` recomputes internal physical masses and physical widths,
then the default whole-card writer serializes native float entries through binary64
and `%.6e`. This mode permits exactly that deterministic projection. It preserves the
full original free and unknown scalar population, block scales, integral MODSEL and
QNUMBERS metadata, all widths and the complete unique decay-channel roster. Decay
daughter order is canonicalized exactly as `Parameter.load_decay` sorts it;
multiplicity is retained. Ambiguous duplicate channels refuse rather than disappearing.
No arbitrary close value, partial mixture of original and written rows, changed
branching fraction, new free row or removed row is accepted. A fully unchanged card
is admissible only when its complete dependent population already agrees exactly at
binary64; a skipped stale or missing dependent update refuses. Generated restriction
rules remain unsupported and block the opt-in route.

The released `ParamCard.read` lowercases text before `Parameter.load_str` tries
Python `float` on a scalar token. A finite Decimal D/d-exponent token that is not
consumed by the model remains a native string, and the writer preserves its exact
lowercase token rather than converting it to E notation. Its original spelling and
native class are retained in the complete row report. Changing the normalized string spelling,
or substituting a numerically equal float, refuses; converting an original native
float to a D string also refuses. Unknown D strings can retain magnitudes beyond the
binary64 domain within the existing bounded Decimal domain because no numerical
conversion is claimed. D strings at actual free UFO addresses or updated physical
mass/width addresses refuse prospectively: the released model reader/updater cannot
consume them as numerical inputs. Scales and branching rows have a direct `float`
parser without a string fallback and refuse such tokens. This is a type/serialization
contract, not a blanket rejection of valid supplied D-exponent unknown entries.

Each prospective free-row conversion and exact writer error is retained using rational
numerators/denominators. The caller's maximum relative representation error is an
additional bound in `(0, 1e-6]`, not a numerical fitting tolerance or authority to change
a physical input. Numerical values that underflow binary64, overflow/nonfinite results,
integer truncation/rounding and excessive representation errors refuse. Source and
card files retain the existing 2 MiB limit; the complete parameter population is
bounded at 32,768 rows, each address at 64 components, source declarations at 4,096,
expression nodes at 512, dependency depth at 64 and total evaluations at 65,536. The complete row-provenance report must fit 8 MiB;
otherwise preflight refuses before native dispatch.

The native worker preserves raw returned cards and the generated artifact census
before semantic comparison. It then writes `parameter-card-observation.json`, including
original and consumed observed-card digests, the whole row census, model/released-source
pins, source-derived versus free-row provenance and exact differences. Mismatches
cannot produce the native-success receipt. The final parameter file is checked again
before success. A malformed card may refuse before this comparison report is built;
its raw returned text remains in `observed-settings.json`.

This establishes literal source consistency and admitted representation, not physics
acceptance. The source calculation uses binary64/cmath rather than a high-precision
amplitude computation. Compiled include consumption, cross-runtime rounding, model
validity, widths, perturbative accuracy, matching and event physics require their own
actual evidence and independent review. The full source-derived update is not a
license to alter external masses, couplings or uncertainty conventions.

The source regression uses the complete original SM card (26 scalar/width rows), its
admitted original model equations and the exact extracted released pure writer. The
projected 47 rows include physical internal zero masses/widths and MW. The supplied
`aEWM1=132.5070` is retained rather than substituted by the UFO default `132.50698`;
for this point MW is written as `8.041900e+01` and the supplied Higgs width
`6.38233934e-03` is written as `6.382339e-03`. These are inert source/writer controls,
not an executed event sample or calibration. Source-law controls also use the exact
released Function/derived-expression loops with inert literal records and the complete
card writer to check name precedence, global scope and D/d string preservation.

Primary implementation: MG5 2.9.27 `models/check_param_card.py` (`Parameter.load_str`,
`load_decay`, `__str__`, `ParamCard.update_dependent`, `write`), `models/model_reader.py`,
`models/import_ufo.py` and `madgraph/interface/common_run_interface.py`
(`update_dependent`). The upstream source copies and exact SHA256 values accompany
this source package. No upstream code is installed or executed as a model by the tests.
