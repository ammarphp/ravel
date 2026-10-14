# Source-to-UFO model derivation

The `model_derivation_bridge` adapter binds trusted executable FeynRules model
source, explicitly supplied restrictions and one named Global Lagrangian to a
fresh native UFO export. A separately approved `model-tool-bridge` study can use
the complete export and its explicit source card for sampled MadGraph checks.

The adapter requires a pinned successful provider readiness result and its
original actual execution run and attempt record. It verifies the closed stage,
approval commitments and original config byte snapshot, then matches the
original qualified provider source and kernel/application hashes to the proposed
inputs. Mutable copies or replacing a kernel at the same pathname cannot
establish continuity. Both source trees, the executable, application metadata and
the previous qualification proof become declared scientific inputs. Provider
and model source must each be explicitly trusted. Intake does not evaluate
either source tree or import UFO Python.

Model inputs are one to four relative `.fr` files, zero to eight explicitly
listed relative `.rst` files and one simple Lagrangian symbol. The operation
allows no supplied expression or arbitrary kernel arguments. It preserves the
model's source settings and selects no implicit restrictions. During provider
or combined model loading, messages or aborts fail the attempt before
kinetic checks and export. A valid base model cannot conceal a failed extension
behind aggregate class counts or an echoed file list. This first contract
allows no load-message exceptions; any legitimate message requires explicit
diagnosis and a prospectively reviewed policy.
For every supplied restriction, it clears the previous rule variable, records load errors, requires
valid nonempty rules and compares native processed-rule and registry counts.
The recorded evaluated rules establish registration; a path echo alone cannot
pass. The supervised
worker copies source into a fresh workspace of its own and invokes the installed
Wolfram kernel with `-noinit -noprompt -script`. Parallel kernels remain disabled.

The native script calls the actual `CheckKineticTermNormalisation` API, captures
the warnings it prints, and separately records nonzero kinetic terms to prevent
an empty check from passing. The check passes when the evaluated result is
`True` with no warnings. FeynRules sets a chiral projector to 1/2 before
comparing a Dirac kinetic coefficient with `I`, so a left-handed field written
in Dirac notation (the Standard Model neutrinos) returns `Null` with a warning.
For every Dirac field pair the script records its kinetic monomials, the
projectors in each, the coefficient with the projectors set to 1 and whether
the field has a mass term. A warning is waived only for a massless field whose
every monomial carries one projector of a single kind and whose coefficient is
`I`. Any other warning, including a non-numerical value, fails.

`GetMassSpectrum` warns when a scalar or vector mass term has a positive
coefficient. The script captures these warnings and records the numerical mass
coefficient of every scalar and vector pair. A warning is waived only when the
coefficient is at most 1e-9 times the largest such coefficient: a term that
vanishes at the parameter point, such as a Goldstone term of the Higgs potential
at its minimum, has no sign. A nonzero wrong-sign term fails. `GetMassSpectrum` returns a `TableForm`;
the script exports its particle identities, analytic expressions, numerical
mass values and model-file values as structured rows. Python independently
checks every returned row for real finite nonnegative masses and agreement
within 0.1 percent, with a nonempty massive population. Native `GetMassSpectrum`
can mask negative or imaginary values and omit rows. This unresolved population
is quarantined, and passing returned rows never establishes a complete mass
spectrum or physical model validity. An undefined function, held expression,
printed success message or arbitrary value different from `False` cannot pass.

`WriteUFO` receives explicit `AddDecays -> False`, `DialogBox -> Off` and
`Optimization -> False`, with a fresh fixed output path. The complete regular
export stays inside the declared scientific attempt output and is hashed there.
The model must explicitly define the electric-charge quantum-number symbol;
the native UFO interface otherwise defaults all charges to zero. Python files
are syntax checked without execution. FeynRules 2.3.49 writes one Python-2
form, the literal `raise UFOError, "..."`; plan with
`--ufo-python-compatibility feynrules-2.3.49-literal-UFOError-raise-v1` to
rewrite exactly that form into a converted copy, keeping the raw export. The
refusal names this option when it is the only problem. The exported UFO then
passes static model admission: every vertex conserves each additive quantum
number its particles declare, and every non-ghost vertex has its conjugate
vertex. `plan --pinned-provider` requires the FeynRules source tree to match the
packaged digest for its version at plan time and again in the derivation. Literal
external scalar values are selected from canonical exported `Parameter` records
using `ast.literal_eval`. They become a complete explicit card with source lines,
names and LHA addresses. Dynamic values, complex external parameters, duplicate
addresses, missing external values and negative widths are refused. No UFO
default fallback or width calculation occurs.

Failed checks produce diagnostic export evidence and no handoff candidate.
A passing candidate binds the derivation result, exported tree, explicit card
and external parameter inventory. The `handoff` operation requires the actual
successful unchanged scientific execution and accepted `model_source_derivation`
review before qualifying reuse. It requests a new `model-tool-bridge plan` with
typed processes, seeds and energy, launches no MadGraph job and grants no
execution authority.
Native derivation, effective-card and sampled amplitude consistency, independently
calculated physics, supplied widths, UV validity, generator integration, showers
and detector response remain separate claims. Successful export alone does not
validate a physical model.

The mode is source ready while its central public command is being coordinated.
Mechanical fixtures establish admission and witness controls only. Actual
provider and model execution require their own frozen plans, scripted CHECK-IN 1
approvals, native leases and independent scoped review.
