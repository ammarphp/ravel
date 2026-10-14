# Supplied-UFO two-gluon Ward diagnostic

The proposed `model-ward` scientific-study mode connects the installed MG5 Python
gauge-check implementation to observed source, card, phase-space and external-leg
records. It admits only tree `g g > t t~` with QCD order two, QED order zero, no
forbidden particles and the supplied complete, unrestricted UFO. The first
planned case uses the retained official SM UFO from installed MG5 2.9.27.
Source readiness and synthetic controls establish no native Ward result.

The original finite-width parameter card remains unchanged. A separate diagnostic
copy must have the same scalar parameter addresses and values, with every
explicit width zero. At least one original positive width must differ. This
diagnostic does not replace the separate finite-width Lorentz/permutation study.

For each admitted seed, MG5 supplies one on-shell point. The diagnostic runs the
original leg order and the incoming-leg exchange, applying the identical point
under the corresponding local-to-original mapping. For each case it observes
the actual generated `vxxxxx(p[slot], ZERO, 4, ...)` replacement, records which
original gluon was replaced, and requires each original incoming gluon once.
This tests the permutation hypothesis; failure to observe both original slots
is a refusal rather than inferred all-leg coverage.

Installed Python HELAS uses momentum divided by energy for its massless-vector
`nhel=4` diagnostic. The operation preserves this convention. It retains the
full physical and BRS matrix element, 16 helicity rows and all colour columns.
The installed tree total ratio limit is `1e-10`, and the installed per-colour
squared-amplitude ratio limit is `1e-15`. All physical colour denominators must
be nonzero; this explicit admission is stricter than MG5's skip of zero columns.
Incoming-exchange consistency retains the existing `1e-8` numerical limit.

Both BRS and physical calls must expose exactly the same external parameters,
internal parameters and couplings as the card-initialized model snapshot.
Actual process, masses, on-shell/conservation/energy checks and helicity/colour
bases remain part of admission. Generated matrix reuse is disabled; a fresh
evaluator is created per leg order, and newly generated process globals are
discarded after each case. The original runtime, MG5 source, UFO and both cards
are checked again after execution, with imported-source provenance retained.

Execution requires its own ordinary approved supervised science worker. A new
source freeze and exact science plan must precede native qualification. The
private `model-ward.json` references the first retained SM/card study assets.
Portable tests use explicit synthetic arrays and no MG5 or UFO execution.

Passing this study would support only these two incoming massless-vector Ward
diagnostics at retained points and the explicit zero-width card. It supplies no
model-wide, massive-vector, loop, UV, event, decay, shower, detector, independent
generator, or exclusion validity. Later supplied models and processes require
their own applicable scientific scope and evidence.
