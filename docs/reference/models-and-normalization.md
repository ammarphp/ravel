# Models and normalization

These tools turn a model description into generator inputs and keep every
factor between a cross section and a delivered yield on record. Each one is a
focused command and, where it produces a scientific result, a science mode that
goes through the usual plan, CHECK-IN 1 approval and run.

| Command | Science mode | What it does |
|---|---|---|
| `ravel model` | `model-authoring` | Writes a FeynRules model from a ModelSpec or a template, lints it, runs the FeynRules checks in two gauges, exports, checks and admits a UFO |
| `ravel simplified-spectrum` | `simplified-spectrum` | Writes an SLHA2 card for a simplified-model spectrum and checks decay closure |
| `ravel xsec` | `cross-section` | Looks up a published cross section under a named order, PDF and scale |
| `ravel lineshape` | `resonance-lineshape` | Leading-order partial widths, propagator schemes and width consistency |
| `ravel normalization factors` | | Branching and filter factors from the decay settings actually used |
| `ravel normalization-ledger` | | Checks every normalization factor and recomputes delivered yields |

Plan any of the science modes with `ravel <command> plan --request <request.json> --rundir <run>
--review-policy <policy.json> --source "<source>"`, approve CHECK-IN 1, then `ravel run --rundir <run>`.

## Authoring a model

A ModelSpec is the structured reading of a Lagrangian. It lists:

- new fields: kind (scalar, vector, fermion), whether the field is its own
  antiparticle, colour (1, 3 or 8), hypercharge as an exact fraction, PDG code,
  mass and width parameters;
- parameters: symbol, LHA block and index (or a Generation-indexed matrix), value,
  interaction order;
- Lagrangian terms: the LaTeX span, the FeynRules operator, the fields it contains
  (with conjugation), the couplings it uses, and whether the Hermitian conjugate is
  added;
- the couplings that must survive into the UFO and the optional ones.

The host agent or the person writes the spec from the paper; it is confirmed at
CHECK-IN 1 before anything is generated. Canonical kinetic and mass terms are
generated for every new field. The colour part of the covariant derivative comes
from FeynRules; the hypercharge part is written out, so physical fields carry
only their electric charge (and lepton number where needed).

Templates build specs from supplied values. Masses, widths and couplings have no
defaults.

```bash
ravel model templates                                   # list templates and their inputs
ravel model instantiate --template neutral-vector --values values.json --out spec.json
ravel model author --spec spec.json --out model-run     # model tree, lint, run script; no FeynRules yet
ravel model author --spec spec.json --out model-run --run --mg5 <mg5_aMC> --process "p p > zp"
ravel model admit --ufo <ufo> --spec spec.json --native-checks model-run/native-checks.json \
    --mg5 <mg5_aMC> --process "p p > zp" --workdir admit-mg5 --out admission.json
```

| Template | Contents |
|---|---|
| `scalar-leptoquark` | colour-triplet scalar coupled to one quark type and one lepton type, fermion number 0 or 2, left and right coupling matrices |
| `vector-leptoquark` | the same for a vector, with the non-minimal gluon coupling kappa |
| `neutral-vector` | neutral vector with vector and axial couplings to up quarks, down quarks and charged leptons, a left-handed neutrino coupling and optional kinetic mixing with hypercharge |
| `axion-like-particle` | CP-odd singlet coupled to the gluon, SU(2) and hypercharge field strengths |
| `singlet-scalar`, `singlet-vector`, `vector-like-fermion` | a new field with its kinetic and mass terms; add interaction terms to the spec |

Kinetic mixing in `neutral-vector` is applied to first order in epsilon after the
field redefinition: the new vector couples to minus epsilon times g1 times the
fermion hypercharge current. Z–Z′ mass mixing is not included; the model card
states this.

Checks, in order:

1. Spec checks: exact charge neutrality of every term (hypercharge for
   unbroken-phase fields, electric charge for physical fields, colour triality,
   lepton number when declared); a term without its Hermitian conjugate must
   contain each complex field as often as its conjugate; mass and kinetic terms
   must be diagonal and canonically normalized.
2. Lint of the `.fr` file, without evaluating it: balanced brackets, no file or
   process access (`Get`, `Import`, `Run`, `<<` and similar), ClassNames of at
   least two characters, no clash with SM.fr class names, particle names, PDG
   codes or class indices, complete parameter blocks, and agreement with the spec.
3. FeynRules, in Feynman and unitary gauge: CheckHermiticity and
   CheckKineticTermNormalisation on the new terms, CheckDiagonalQuadraticTerms and
   CheckDiagonalMassTerms on the full Lagrangian. Unitary gauge decides. A
   Feynman-gauge quadratic or mass failure is waived only when FeynRules reported
   the non-diagonal terms, every off-diagonal pair contains a Goldstone boson and
   the same check passes in unitary gauge. Messages while deriving vertices or
   writing the UFO fail the run.
4. The UFO is converted to Python 3 (the FeynRules 2.3.49 `raise` form) and
   checked without importing it: every file parses; no Mathematica leftovers; at
   least one vertex and Lorentz structure; no duplicate PDG codes; no massless
   particle with a width; each spec field present with its charge and spin; each
   required coupling used by a vertex.
5. With `--mg5` and `--process`, MadGraph imports the model and must generate at
   least one diagram.
6. Model admission, the postcondition. The run is `checked` only when the UFO
   is admitted; without `--mg5` and `--process` it is `admission_incomplete`.

### Model admission

`ravel model admit` runs the same checks on any UFO, generated or supplied, and
writes `admission.json` (`kind: model-admission`). Each row records what the
check cannot detect.

| Check | Refuses | Cannot detect |
|---|---|---|
| `ufo-static` | the static UFO problems in step 4 | wrong values or wrong analytic couplings |
| `vertex-quantum-numbers` | a vertex where electric charge or another declared additive quantum number (lepton number, ghost number, `Y`) does not sum to zero | undeclared quantum numbers; hypercharge in a broken-phase UFO, where mass eigenstates carry `Y = 0` |
| `conjugate-vertices` | a non-ghost vertex without the vertex of its conjugate fields: the Lagrangian lacks a Hermitian conjugate | a conjugate vertex with the wrong coupling; ghost vertices are skipped |
| `spec-charge-census` | a ModelSpec term whose hypercharge (gauge basis) or electric charge (physical fields) does not vanish | terms the spec does not list |
| `hermiticity-feynrules` | a FeynRules `CheckHermiticity` failure in the supplied receipt | anything the receipt did not check |
| `mg5-check-gauge`, `mg5-check-lorentz`, `mg5-check-permutation` | a failed MadGraph `check` on the requested process, each in a fresh session | other processes; the gauge check is vacuous without massive vector bosons |

The decision is `refused` when any check fails, `incomplete` when a required
check (static, vertex, conjugate and the three MadGraph checks) has no verdict,
and `admitted` otherwise. The Ward identity on the requested process is not
part of this admission and is recorded as not evaluated.

The output is labelled `generated_contract_checked`. A model card
(`model-card.md`, `model-card.json`) lists fields, parameters, conventions,
approximations, every check verdict and the sha256 of each source file. Treating
a generated model as trusted needs a review record from a person.

Models outside this tier are refused with the reason: SU(2) multiplets of new
fields, a new gauge group, complex parameters, or anything the spec lists under
`unsupported_features`. Those go to the SARAH or derivation route.

`derivation-request.json` holds the arguments for the source-bound FeynRules
route: `ravel model-derivation-bridge plan --model <model> --model-file SM.fr
--model-file <Name>.fr --lagrangian LFull --two-gauge-checks LNew` together with
a qualified FeynRules readiness run.

### Interference with the Standard Model

`ravel model interference --final "e+ e-" --order-in-amplitude 2 --model <Name>` prints
the MadGraph process lines for the Standard Model part (`NP^2==0`), the
interference part (`NP^2==2`), the pure new-physics part (`NP^2==4`) and the full
process. `--order-in-amplitude` is the number of new-coupling vertices in the
new-physics amplitude: 2 for a resonance produced and decaying through its new
couplings. Generate all parts at the same parameter point, PDF and scales, keep
the signed weights of the interference sample, and check that the parts add up
to the full cross section.

## Simplified-model spectra

`ravel simplified-spectrum` writes an SLHA2 card from declared masses (other
sparticles decoupled at a stated mass), mixing matrices and decay tables, and
checks the card:

- branching fractions of each decay table sum to one;
- partial widths agree with the total width;
- every channel is kinematically open;
- every produced particle decays to a declared stable invisible state (for
  example the lightest neutralino 1000022 or the gravitino 1000039) or to SM
  particles;
- the masses in a generated LHE banner match the card.

## Cross sections

`ravel xsec lookup --request request.json` returns a published cross section and
its uncertainty. The request names the production basis (gluino pair,
squark–antisquark with a declared number of degenerate flavours, stop or sbottom
pair, wino C1N2 and C1C1, higgsino N2N3, C1N1, C1N2 and C1C1, left- or
right-handed slepton pairs), the collision energy, the masses and the
convention: `order` (LO, NLO, NLO+NLL, NNLO+NNLL, aNNLO+NNLL), `pdf` and `scale`
(either may be `as-published`). Values between grid points are interpolated in
log sigma against log mass; there is no extrapolation and no fallback to another
order or a flat factor. A table the registry does not hold is reported as a
declared gap.

The tables are those of the LHC SUSY Cross Section Working Group (NNLL-fast and
Resummino results), stored with their source URL, citation and sha256 in
`src/ravel/data/cross_sections/`. `ravel xsec verify` re-hashes them;
`ravel xsec fetch --table <id>` downloads one again and compares. A cross section
computed by MadGraph is recorded as a separate source with its own order, PDF
and scale; a k-factor is accepted only between two records on the same basis,
energy, masses, charge and state count.

Supplied calculation tables and production-basis transformations use the same
[convention service](cross-section-conventions.md), with explicit interpolation,
state populations, component response ratios and justified approximations. Use
`ravel xsec supplied` and `ravel xsec correct` for selected contracts.

## Resonance line shapes and widths

`ravel lineshape` evaluates fixed-width Breit–Wigner, running-width and
complex-pole propagators, converts between on-shell and pole mass and width,
and computes leading-order partial widths for spin-0 states (to fermion pairs,
WW, ZZ, gluons and photons through quark and W loops or effective couplings)
and spin-1 states (to fermion pairs with vector and axial couplings, and to WW).
It compares the declared total width with the sum of the partial widths at a
stated tolerance.

## Branching and filter factors

`ravel normalization factors --settings settings.json --out factors.json` reads
the decay settings actually used — Pythia `onMode`, `onIfAny` and `oneChannel`
commands, MadSpin decay lines, SLHA decay tables — and the generator filters, and
returns the branching factor of each produced particle and the filter efficiency,
each with its source. It refuses double counting: a decay forced in Pythia and
also decayed by MadSpin, branching fractions applied to a cross section that
already contains the decays, or a filter efficiency applied to an already
filtered cross section.

## Normalization ledger

A ledger holds, for one sample: luminosity; cross section with order, tool, PDF,
scales, production basis and pinned source; branching fractions with source
(`slha`, `decay_table`, `generator` or `paper_assumption` with the quoted
statement); filter efficiency; the k-factor with its numerator and denominator
bases (final states, multiplicities, generation cuts, PDF, order); generated
`sumw`, `sumw2` and the fraction of negative weights; selected per-bin `sumw` and
`sumw2`; the bin convention (per bin or per unit width); whether the observable
is shape-normalized; and the normalization order of the target publication.

`ravel normalization-ledger check --ledger ledger.json --delivered yields.json`
recomputes every delivered yield to a relative tolerance of 1e-12 and names the
cause of a disagreement: k applied twice or omitted, a pb/fb swap, a per-GeV
template declared per bin, branching fractions or a filter omitted or applied
twice, or the requested event count used in place of the generated sum of
weights. It also reports mismatched k-factor bases, a product of branching
fractions above one, a k-factor on a cross section already at the k numerator's
order, and a certifier cross section that differs from the one applied. A
uniform k on a shape-normalized observable is reported as having no effect.
Independent cross-section calculations and a normalization order different from
the target publication give warnings; the latter is listed for CHECK-IN 2. The
ledger never rescales anything: inspect it and the uniform efficiency factors
before changing a cut.

`ravel normalization-ledger engine --ledger ledger.json [--receipt production-receipt.json]`
prints the normalization block for the reconstructed-event analysis, pointing at
`/normalization_ledger/applied_sigma_pb` in the production receipt when one is
given. The ledger module's `receipt_block` is what a production receipt embeds
and `check_engine_scale` confirms the scale the analysis applied.
