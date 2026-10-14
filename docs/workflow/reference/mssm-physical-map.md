# MSSM spectrum, decay and lifetime handoff

Use `mssm-observable-map` for a complete supplied MSSM SLHA population. Its task is
`{"request":"/absolute/path/request.json"}`. A normal scientific-study specification
uses schema 2, one attempt, zero review redos, and the single delivery scope
`supplied_mssm_spectrum_observable_delivery`. Plan, approval, execution, review and
parent-task completion use the existing workflow.

The source-only command `ravel mssm-physical-map --request <request>` shows the
ordinary task and complete input inventory. The Graph/Host action
`mssm-spectrum-context` takes `{"request_input":"<Graph input ID>"}`; present every
request, input card, spectrum, decay manifest, provider evidence and API-contract
pin in the ordinary Graph inputs. It uses the existing one-attempt construction
caller and cost ledger. It grants no execution or scientific authority.

The closed request schema is exercised in
`tests/unit/test_mssm_observable_map.py::fixture`. Axes contain literal GeV values
and explicit SLHA block/address/scale selectors. A binding chooses original input
or returned spectrum and one scalar or a two-scalar signed difference. Fixed
parameters can bind, for example, the actual source assertion M1−M2=0 and tanβ=50.
Equal input parameters are not inferred to remain equal after running. Each point
pins its input, complete spectrum, completeness manifest and provider prescription.
Provider names, loop orders and prescriptions remain source assertions.

`population.kind="cartesian"` requires the entire ordered Cartesian population.
`source-listed` requires all points in its pinned source list. The
`rs1-published-limits52-v1` reader preserves all 52 explicitly listed
reference coordinates, their identities and parent−LSP differences.
That list is the retained matched published-reference population, not a claim
that it covers the RS1 author lattice. Subsets, duplicates, changed coordinates
and missing grid points refuse. No interpolation supplies a missing spectrum.

The map preserves signed electroweakino masses, complex mixing entries, the
four-neutralino/two-chargino identities, every original SLHA line and every
MASS/DECAY record. It records the explicit mixing scale and prescription, checks
the complete N/U/V matrix census within a declared engineering band, and retains
other mixing blocks without interpreting or filling them. Squared mixing entries
are basis diagnostics. They do not supply rates, branching models or efficiencies.
The sign and complex-phase conventions follow
[SLHA1](https://arxiv.org/pdf/hep-ph/0311123) and
[SLHA2](https://arxiv.org/pdf/0801.0045). The exact-header QNUMBERS reader preserves
the upstream particle code and rows; a selected charge must agree with the
standard MSSM identity and any explicit three-times-charge row, as defined by
the [BSM Les Houches interface](https://arxiv.org/pdf/0712.3311).

Lifetime is conditional on the supplied **total** width:
`c*tau_mm = 0.1973269804 * 1e-12 / Gamma_total_GeV`, using the rounded
[PDG hbar*c literal](https://pdg.lbl.gov/2024/reviews/rpp2024-rev-phys-constants.pdf).
It never replaces that width with a sum of listed channels. Missing DECAY is
unknown; an explicit zero total width is stable by that card. Missing channels,
missing daughter masses and nonzero channels below a pole threshold remain
visible obligations. A pole-threshold diagnostic does not certify off-shell or
resonant decay phase space.

An `accepted_cmssm_spectrum` origin must pass the existing current accepted-review
gate and bind the genuine generated CMSSM return and original solver-input hash.
It cannot relabel an NMSSM result as a general MSSM solver. Supplied spectra use
`supplied_unqualified`. Neither route certifies spectrum or decay accuracy.

`ravel mssm-physical-map --request <request> --llp-template <template>
--output-dir <fresh-directory>` prepares the existing `llp-plane-recipe` task.
The original complete Cartesian template must have explicit identity and
`spectrum_total_width` lifetime placeholders. Rates, production/decay identities,
luminosities, scenarios, all cells, masks, response/cohort records, child budgets
and original goal binding survive. A prior cohort or response cannot be relabelled
to a new point identity. Missing or stable lifetimes used by an LLP component
produce an explicit blocked handoff without invented finite decay lengths.

The original μ–M2 replane example has 81 points: μ and M2 each run from 100 to 500 GeV in
50 GeV steps, with M1=M2 and tanβ=50. Supply all 81 spectra and the full template.
An optional template `construction_limits={"max_points":128,"max_cells":512}`
admits that complete source handoff; unchanged defaults remain 32/128. Maximum
declared construction allocations are 512 points/2048 cells. These and the map's
512-point/64 MiB interpreted-input bounds are resource validation, not a physical
grid boundary or an all-grid coverage claim. They do not enlarge native child
budgets. Larger tasks require an explicitly resource-engineered adapter extension;
the current adapter refuses rather than silently partitioning the goal.

The new controls use synthetic complete populations, the unchanged historical
RS1 anchor card, and inert accepted-review stand-ins. They exercise actual
ordinary adapter inputs, Graph/Host contexts and LLP source construction, with
zero solver, event, fit or provider calls. A qualified general μ–M2 spectrum/decay
provider, compatible UFO/event conventions, production and detector inputs, and
independent native numerical checks remain necessary for a μ–M2 replane or RS1 result.
