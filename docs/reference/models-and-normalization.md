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

The governed `model-authoring` worker reports `passed` or `failed`, keeps the complete source record in
`authoring`, and retains executed native checks in `native_result`. Its `scope` and
`native_run_performed` fields identify the evidence produced. Source authoring covers static lint and
the exact charge census. A requested native run passes through the existing `checked` model-admission
outcome. The worker sets `physics_validated` to `false`; scientific acceptance belongs to review of
the retained evidence and the requested claim.

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
check leaves to independent scientific review.

| Check | Refuses | Independent review obligation |
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
(either can be `as-published`). Values between grid points are interpolated in
log sigma against log mass; there is no extrapolation and no fallback to another
order or a flat factor. A table the registry does not hold is reported as a
declared gap.

The tables are those of the LHC SUSY Cross Section Working Group (NNLL-fast and
Resummino results), stored with their source URL, citation and sha256 in
`src/ravel/data/cross_sections/`. `ravel xsec verify` re-hashes them;
`ravel xsec fetch --table <id>` downloads one again and compares. A cross section
computed by MadGraph is recorded as a separate source with its own order, PDF
and scale (three leading-order slepton tables computed with the shipped generation
recipe are registered this way, `source_kind` `mg5-computed`, with their generator,
run card, masses and PDF recorded and no download URL: `slepton_L_pair`,
`slepton_LR_pair` for two degenerate generations and `slepton_LR_pair_with_stau`
for three, all LO with cteq6l1); a k-factor is accepted only between two records on the same basis,
energy, masses, charge and state count.

The 13 TeV NLO+NLL gluino-pair, squark–antisquark, stop-pair and sbottom-pair
tables (decoupled partners) are the NLL-fast 3.1 grids for MSTW2008NLO, CTEQ6.6M and
NNPDF3.0NLO. Their authors state no redistribution terms, so the registry ships
no numbers for them: `cross_sections/acquired-tables.json` pins the public
archive, each member and their sha256, and the first lookup installs the members
into the cache (`RAVEL_XSEC_CACHE`, else `~/.cache/ravel/cross_sections`) after
checking both hashes. `ravel xsec acquire` does it ahead of time;
`--archive <file>` installs a copy fetched elsewhere. The PDF must be named,
because the three sets are different conventions. The grids give the scale
uncertainty in picobarn and the PDF and alpha_s uncertainties in percent; they
publish no total, so `up_pb` and `down_pb` are empty and the components are in
`uncertainty` (`relative_scale_*`, `relative_pdf_*`, `relative_alphas_*`, and
`relative_pdfas_*` for the combined NNPDF3.0 figure).

The squark–antisquark grid has ten states (five flavours, left and right, the
sbottom counted as light). A request must declare `state_count` as 10 or 8
(u, d, s, c only); the 8-state result is the ten-state value times 8/10, valid
only because the gluino is decoupled, and the result reports the basis and the
factor under `state_basis` and `state_rescaling`. Any other count is refused.
Every one-dimensional lookup reports `interpolation_error`: the difference
between the log-log linear value and the four-node cubic interpolation, zero at
a node. It estimates the interpolation step, not the table's own uncertainty.

Supplied calculation tables and production-basis transformations use the same
[convention service](cross-section-conventions.md), with explicit interpolation,
state populations, component response ratios and justified approximations. Use
`ravel xsec supplied` and `ravel xsec correct` for selected contracts.

## Generation recipes

`src/ravel/data/templates/model_recipes.json` lists shipped, hashed generation recipes for
the card renderer (`ravel.physics.prepare_native_slepton`). The entry
`slepton-bino-isrslep` names its process (`p p > chsleptons chsleptons j / susystrong @1`),
its spectrum (six degenerate charged-slepton masses `MSLEP`, a lightest neutralino
`MN1`, everything else decoupled), its explicit decay rows, its unmerged leading-order
treatment (`ickkw` 0) and its PDF choices. The caller binds the two masses, the PDF, the
event count and the seed; `python -m ravel.physics.prepare_native_slepton --library
slepton-bino-isrslep --parameter MSLEP=<GeV> --parameter MN1=<GeV> --nevents <n> --seed <s>
--pdf cteq6l1 --rundir <dir>` writes the cards and the launch script without running a
tool. A native configuration selects the same entry with `[ravel.native] library`, the
masses under `[madgraph.masses]` and the jet cuts under `[madgraph.run.options]`
(`src/ravel/data/templates/slepton_scan_template.toml`); a scan binds the two masses to
its axes through `subst`. A recipe is not an admission of an operation, and generation
still needs CHECK-IN 1 approval.

## Resonance line shapes and widths

`ravel lineshape` evaluates fixed-width Breit–Wigner, running-width and
complex-pole propagators, converts between on-shell and pole mass and width,
and assigns every neutral colour-singlet spin-0, spin-1 and spin-2 two-body
channel one disposition: a leading-order formula, a selection-rule refusal,
or a free-width path. The formula uses the declared real couplings, masses and
constants. Spin 2, Z plus photon, vector plus scalar and scalar-pair decays use
the free-width path. A colour-singlet spin-1 state cannot decay to two identical
on-shell massless vectors (Landau–Yang theorem); this refusal applies to photons
and gluons with every width source.

Generate the complete conventions and formulas with `ravel lineshape table`,
or write JSON with `ravel lineshape table --write channels.json`.
`src/ravel/data/lineshape/channels.json` is generated from the module's single
enumeration; `table_markdown` renders the region below from that JSON.
`ff` rows distinguish zero or positive fermion mass and colour multiplicity
one or three. All vector daughters are on shell.

<!-- BEGIN GENERATED LINESHAPE CHANNELS -->
| Spin | Parity or CP class | ff_massless_colour_1 | ff_massless_colour_3 | ff_massive_colour_1 | ff_massive_colour_3 | ww | zz | zgamma | photons | gluons | vector_scalar | scalar_pair |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | CP-even | formula | formula | formula | formula | formula | formula | free | formula | formula | free | free |
| 0 | CP-odd | formula | formula | formula | formula | formula | formula | free | formula | formula | free | free |
| 0 | mixed | formula | formula | formula | formula | formula | formula | free | formula | formula | free | free |
| 1 | vector | formula | formula | formula | formula | formula | formula | free | forbidden | forbidden | free | free |
| 1 | axial-vector | formula | formula | formula | formula | formula | formula | free | forbidden | forbidden | free | free |
| 1 | mixed chiral | formula | formula | formula | formula | formula | formula | free | forbidden | forbidden | free | free |
| 2 | even | free | free | free | free | free | free | free | free | free | free | free |
<!-- END GENERATED LINESHAPE CHANNELS -->

For spin 0, `scalar` and `pseudoscalar` remain aliases for `CP-even` and `CP-odd`;
`mixed` accepts both real Yukawa couplings `coupling_scalar` and
`coupling_pseudoscalar`. `vv_sm_like` is the CP-even tree tensor and refuses a
CP-odd state with an instruction to use `vv_odd_effective`.
`vv_even_effective`, `vv_odd_effective` and `vv_effective` select the field-strength
tensors for `boson: W` or `boson: Z`. Declare `coupling_even_per_GeV` and/or
`coupling_odd_per_GeV`; a pure class also accepts `coupling_per_GeV`.
The tree tensor is `tree_coupling_GeV`, or `kappa` with the declared Fermi
constant, giving `a = 2 kappa m_V^2/v` and `v = (sqrt(2) GF)^(-1/2)`.

The coupling convention for ZZ is
`L = a phi Z_mu Z^mu/2 - g_e phi Z_mn Z^mn/4 - g_o phi Z_mn Ztilde^mn/4`,
with real `a` in GeV, real `g_e,g_o` in GeV^-1 and
`Ztilde^mn = epsilon^mnrs Z_rs/2`. For W+W-, the three factors become
`1, 1/2, 1/2` with charged conjugate fields. With `x = m_V^2/M^2` and
`beta = sqrt(1-4x)`, pure even and odd field-strength widths are
`S g_e^2 M^3 beta (1-4x+6x^2)/(32 pi)` and
`S g_o^2 M^3 beta^3/(32 pi)`, where `S = 1` for WW and `1/2` for ZZ.
The two transverse even amplitudes are `-(a+g_e d)` and the longitudinal
amplitude is `a d/m_V^2 + g_e m_V^2`, with `d = M^2/2-m_V^2`.
Squaring them retains the same-CP interference `6 a g_e d`; the two odd
transverse amplitudes are `+/- g_o M|p|`, and their total interference with
the even tensors vanishes. The existing photon/gluon loop kinds remain
CP-even form-factor calculations; effective photon/gluon kinds also accept
mixed even and odd couplings.

For spin 1, `ff` uses `g_vector` and `g_axial`. `vector` requires zero axial
coupling; `axial-vector` requires zero vector coupling; `mixed chiral` admits
both. A pure class takes its absent coupling as zero. Legacy `scalar` and
`pseudoscalar` labels retain their previous chiral behavior. `ww` retains the
declared dimensionless triple-gauge coupling; its tensor conserves CP in the
convention below, and with an axial-vector parent it violates P and C separately.
`zz` (also `zz_bose`) declares real dimensionless `g4,g5` through
`L = g4 X_mu Z_nu partial^nu Z^mu + g5 epsilon^munurs X_mu Z_nu partial_r Z_s`.
The vertices are `g4 [(P.e1)(eX.e2)+(P.e2)(eX.e1)]` and
`g5 epsilon(eX,e1,e2,q1-q2)`, with `P = q1+q2` and metric `+---`.
In the neutral-current CP convention `X_mu(t,x) -> -X^mu(t,-x)` and the same
for Z, g4 violates CP and g5 conserves CP for all three coupling classes; an
omitted one is zero.
Both tensors are Bose symmetric; their width is
`M^3 beta^3 (g4^2+g5^2 beta^2)/(96 pi m_V^2)`, including the initial
polarization average and identical-particle factor. Massive longitudinal
polarizations have no massless limit.

`computed` sums the listed partial widths; `declared_free` checks a supplied
`total_width_GeV` against available partial widths at `rel_tol`.
A free row refuses `computed` and names both explicit sources to use.
`free` requires exactly one positive `total_width_GeV` or `width_over_mass`,
allows an empty channel list, and records `width_source: free`.
The total width is a free parameter of this study and is not derived from couplings.
Formula partial widths are reported as information, without branching fractions or a consistency claim.
`ravel lineshape plan --request request.json --rundir run --review-policy policy.json
--source "Declared couplings"` adds the selected rows and that exact free-width
sentence to the numbered CHECK-IN 1 assumptions before approval.

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
