# Supplied generated spectrum and decay transport

The generated-spectrum scientific-study adapter builds supplied FlexibleSUSY 2.9.0
CMSSM source in a fresh private directory and retains the solver's original SLHA.
It accepts a complete pregenerated source bundle, Boost 1.85.0 and Eigen 3.4.0
headers, canonical compiler/GSL tool pins and explicitly declared runtime inputs.
New symbolic generation, engine activation, installation, event generation and
partial main-object reuse are absent from this operation.

Prepare a study using the [scientific-study intake](../start.md). After binding
an exact source package and configuration, the module's preparation command is:

    python -m ravel.physics.generated_spectrum \
      --config generated-spectrum.json --rundir <fresh study> \
      --review-policy <scoped actual-actor policy>

Preparation creates a plan. The actual CHECK-IN 1 and admitted supervision are
required before any configure, compilation or solver process. A first qualification
has a zero-redo policy; a failed attempt does not authorize a retry.

The configuration requires exactly schema_version=1,
operation=flexiblesusy-2.9.0-generated-CMSSM, source attribution,
trusted_generated_source=true, source_capsule, boost_capsule, eigen_capsule, tools,
runtime_inputs and max_ram_mib. Every capsule/tool/runtime fact binds a path and
SHA256. Source capsules use the complete regular ZIP_STORED representation described
by model-sources, including per-member hashes and modes. The source prefix is
cmssm/. Header capsules use baseline_kind=supplied-build-headers and preserve the
complete supplied header distribution plus metadata. Boost/Eigen version tokens
and core/unsupported roles are checked in the actual archive. Source/runtime trust,
provenance and selected-input coverage must be reviewed; a name is not qualification.

The operation preserves executable source modes and empty files in its private
restore, refuses archived prebuilt/configured main state, disables meta generation,
LibraryLink and threads, and performs one compile job. Configure binds C++17/O2/fPIC.
A regular clang-22 driver is invoked with the explicit clang++-22 argv0; compatibility
must be established by the actual feature/link checks. The original solver input
is used without replacing masses, flags or branching settings. Ambient build
overrides are removed, while CC, the C locale and five one-thread limits are fixed.

Phase ceilings are 120s configure, 1200s compile and 60s solver inside a 1440s
supervised stage including source restoration. The caller must separately bind
the actual ordinary/outer envelope, process ownership, cleanup and resources.
Source code and portable fixtures do not qualify a compiler, solver or runtime.

A passing delivery establishes configure/build/solver transport and raw source
retention only. It retains actual phase receipts, the fresh binary hash, original
input SHA, full SLHA and static diagnosis. Signed masses and all SPINFO/DCINFO rows
are preserved. Unknown or truncated decay channels remain unknown; a minimum
printing threshold does not establish zero omitted branching fractions. Static
parser refusal is retained rather than converted into a physical model judgment.

A complete recast additionally needs independently reviewed convergence, spectrum,
mixing, decay conventions and uncertainty, compatible supplied-UFO external-card
mapping, actual production cross sections and lifetime applicability, and suitable
response/likelihood inputs. A supplied SM UFO or accepted different simplified
model is not a compatible MSSM substitute. Optional FeynRules/SARAH symbolic work
requires its own declared provider/runtime/license and scoped qualification.


Original declared package/source/tool/runtime inputs and restored source/header bytes/modes are rechecked before and after every native phase. Configure and compile may add derived source-tree files; header membership remains closed. The original LesHouches source input stays immutable. The exact fresh compiled executable is retained within ordinary scientific output, bound before solver and rechecked after it; a changed original or retained target refuses transport completion.
