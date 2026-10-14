# Supplied model sources and symbolic providers

<a id="supplied-model-sources-and-optional-symbolic-providers"></a>

The `model-sources` scientific-study mode binds, exports and reuses declared model
source bytes. It supports a supplied UFO or pregenerated spectrum-source baseline
without a kernel call. The configured symbolic provider reports the presence of
explicitly pinned files without starting the kernel, changing activation or
importing a model. The full setup includes the licensed kernel and provider tools
required by the selected derivation workflows. A completed source capsule establishes provenance;
it does not derive a model, calculate a spectrum or certify its physics.

Use the ordinary version 2 [scientific-study lifecycle](../workflow/reference/scientific-studies.md)
with an explicit prospective review policy. The task is
`{"config": "model-sources.json"}`. The configuration has exactly these fields:

```json
{
  "schema_version": 1,
  "source": "Exact supplied model provenance and intended source-only operation",
  "baseline_kind": "supplied-ufo",
  "assets": [{
    "id": "model",
    "kind": "ufo-source",
    "source": "Upstream model, version, restrictions and provenance",
    "license": "Retained source notice and scope of permitted private use",
    "file": null,
    "tree": {
      "root": "supplied-ufo",
      "manifest": {"path": "ufo-source.json", "sha256": "<64 hex digits>"}
    }
  }],
  "symbolic_provider": null,
  "export_policy": "private_source_cache_only",
  "reuse": null
}
```

`baseline_kind` is `supplied-ufo` or `pregenerated-spectrum`, and an asset of the
corresponding `ufo-source` or `generated-spectrum-source` kind must actually be
present. Other asset kinds are `parameter-card`, `slha` and `model-reference`.
Every asset needs a unique identifier, attribution and a licence note, and exactly
one file pin or closed tree manifest. A file uses
`{"path": "input.dat", "sha256": "<64 hex digits>"}`. A tree manifest has
`{"schema_version": 1, "files": {"relative/name": "<64 hex digits>"}}`.

The closed source-tree scope excludes Git internals, bytecode, Python caches,
pickle caches and macOS metadata, matching the existing model-tool bridge.
Included aliases and special files are refused. The export has at most 16 assets,
20,000 files and 512 MiB of source bytes. Its original inputs, membership and
modes are checked again after copying. All regular source files, including
legitimate empty files, are represented in `source-assets.zip`. This is a
deterministic, uncompressed `ZIP_STORED` bundle with exact member names, bytes
and regular-file permission modes. No source member is silently omitted to
satisfy the ordinary output rules. Every public output file remains nonempty.
Version 2 `source-capsule.json` binds the complete file/mode inventory and bundle
identity. `asset-inputs.json` supplies a capsule pin, member prefix and exact
per-asset source manifest, with `restore_required: true`. It never copies the
configured symbolic engine.
Common engine and credential names are refused as assets; this guard is not a
general licence or content classifier.

Before a separate source-bound model or build operation, use
`ravel.physics.model_sources.restore_source_bundle(capsule_pin, base, output)`
to restore into a fresh canonical private source directory. The bounded reader
refuses changed bytes, extra or missing members, duplicates, traversal, aliases,
nonregular members and compression. It writes only individually checked regular
files and restores their recorded modes. Legitimate empty members remain empty
source inputs. Bind the restored asset prefix and its per-asset manifest to the
model-tool bridge or subsequent build operation; a bundle reference by itself
is not an unpacked UFO or a qualified spectrum. Restoration imports no model
source, launches no tool and inherits no approval or scientific acceptance.

To reuse an export, put an exact pin to its `source-capsule.json` in `reuse`.
The source contract, attribution, original asset bytes, modes and closed cached
bundle membership must agree. Changes, additions, deletions, aliases and mode
changes refuse reuse. Other output metadata is regenerated from the current
configuration. A source cache does not transfer workflow approval or grant
redistribution rights. Earlier version 1 raw source capsules are preserved as
historical evidence and are refused by this complete bundle contract.

An optional `symbolic_provider` has exactly:

```json
{
  "kind": "wolfram-feynrules",
  "kernel": {"path": "/explicit/path/WolframKernel", "sha256": "<64 hex digits>"},
  "application_metadata": {"path": "/explicit/path/Info.plist", "sha256": "<64 hex digits>"},
  "package_source": {
    "root": "feynrules-source",
    "manifest": {"path": "provider-source.json", "sha256": "<64 hex digits>"}
  },
  "last_attempt": null,
  "license_note": "Current licence and runtime compatibility need separate qualification"
}
```

The other provider kind is `wolfram-sarah`. Missing declared kernel or application
metadata is a capability observation, while present files must match their pins.
The provider package source must be bound. `last_attempt` may pin a historical
completion record; it never proves current availability, compatibility or
licence status. Every result keeps `runtime_qualified` and
`license_rights_qualified` false. Actual provider readiness and symbolic
derivation remain separately approved `model-provider-bridge` and
`model-derivation-bridge` operations.

FeynRules derives vertices from fields, parameters and a Lagrangian and exports
them to generator formats such as UFO. Its primary paper describes checks of
hermiticity, kinetic and mass normalization, alternative gauges and independent
implementations. The paper's Mathematica minimum is a historical prerequisite,
not evidence that any later kernel works with the supplied package version.
A successful fixed-point generator diagnostic also does not prove the original
Lagrangian or all of its processes valid.
[FeynRules 2 paper](https://arxiv.org/html/1310.1921v2)

SARAH's symbolic model derivation and generation of spectrum/model code use
Mathematica. Compiling an already generated spectrum source is a different route:
FlexibleSUSY 2.9.0 documents `--disable-meta` for compiling existing C++ without
Mathematica or SARAH, and `--disable-librarylink` removes its Mathematica
interface. Complete model source and a compatible compiler, Boost, Eigen and GSL
still have to be supplied. A source export is not a successful compile or a
converged spectrum.
[SARAH 4 paper](https://arxiv.org/abs/1309.7223),
[FlexibleSUSY pinned source](https://github.com/FlexibleSUSY/FlexibleSUSY/tree/64276b57499cba6577940c3fc605b9d4b45b3130)

FeynRules, SARAH and HEPTAPOD/FeynCalc workflows require an activated licensed Wolfram kernel and the exact provider sources. Preserve existing activation and user directories. The [installation guide](../installation.md) gives the required toolchain setup; the ordinary runtime binds actual kernel, package and environment versions.

Provider readiness checks the declared kernel and package before the separate Lagrangian-to-UFO derivation and vertex/convention review. Clear or record environment-appended startup options and parallelism in the native proposal.
[WolframKernel documentation](https://reference.wolfram.com/language/ref/program/WolframKernel.html)

Downstream qualification remains concrete: a supplied UFO needs declared
parameter/card and process checks; a generated spectrum needs actual convergence,
masses, mixings, widths and branching-ratio checks and a compatible SLHA-to-UFO
mapping. Numerical robustness and agreement with an independent physical
implementation answer different questions. Generator, decay, response and
likelihood propagation each retain their own scientific obligations.

## SARAH source export through the existing bridges

`ravel model-provider-bridge plan-sarah` prepares schema2 `wolfram-sarah-readiness`; `ravel model-derivation-bridge plan-sarah` prepares schema2 `sarah-source-ufo` only after actual accepted source-bound SARAH readiness. The pinned4.15.4 mirror is a separately trusted source required for SARAH operations; its exact origin remains part of the source contract. Exact model triplet/shared definitions, final eigenstate, all seven UFO choices and fresh tree ModelOutput choices are explicit. `CheckModel` is a symbol action; raw return, messages and stdout remain diagnostics, with no Boolean physics interpretation. Mandatory upstream ASS exclusion remains visible. Full static source/reference/convention census does not evaluate interactions or certify physics. Native NaN mass100/width0 defaults remain diagnostic bytes: choose no parameter point, or supply a byte-preserved complete card covering every exported external address. Only the latter can yield a source-reviewed candidate for a separately approved model-tool operation. Actual SARAH/kernel compatibility, SM export, numerical amplitudes/widths and detector use remain qualification obligations; the existing FeynRules route is preserved.

## Typed structural model proposals

`physics-knowledge` also accepts an explicit schema 2 request. This adds a
source-declared field-signature comparison to the existing located knowledge
index. The implementation independently follows the multiset retrieval mechanism
in [FERMIACC Appendix A.3/A.5](https://arxiv.org/html/2603.22538v1). The retained
source audit identified no runnable FERMIACC framework; no upstream code or
licence is adopted here.

```json
{
  "schema_version": 2,
  "knowledge": {"path": "knowledge.json", "sha256": "<exact SHA256>", "size": 1234},
  "query": {"text": "Compare this source-defined proposal", "tags": [],
            "roots": [], "domain": ["collider"], "max_nodes": 32},
  "structural_query": {
    "library": {"path": "library.json", "sha256": "<exact SHA256>", "size": 1234},
    "proposal": {"path": "proposal.json", "sha256": "<exact SHA256>", "size": 1234}
  }
}
```

The existing schema 1 knowledge index still provides located citations, exact
source excerpts, dependency edges and conflicting assertions. `library.json` has
exactly `schema_version: 1`, `id` and `models`. `proposal.json` is one current
model record. Each record contains exactly `id`, `name`, `kind` (`proposal` or
`prior`), `conventions`, `fields`, `interactions`, `kinetic_terms`, `topologies`,
`processes`, `outcomes`, `ufo` and `node_ids`. Prior annotations need located
evidence in the supplied knowledge index. A new proposal may cite an exploratory
hypothesis node; that remains a hypothesis. The typed JSON files themselves are
committed inputs, and the returned assertion kinds remain visible.

`conventions` contains `gauge_basis`, `phase`, `hypercharge_normalization`,
`cp_convention`, `field_population` and `node_ids`. The explicit CP definition
also prevents comparing incompatible intrinsic-phase conventions. The population identity distinguishes new
fields, a complete theory and a selected subset; none is inferred from a UFO. Use the original explicit convention, such as `Q=T3+Y` or
`Q=T3+Y/2`; these are separate identities. `null` denotes an unknown convention.
The producer does not convert between bases or infer pre-EWSB structure from
broken-phase electric charges.

Each field contains `id`, `twice_spin` (physical 2s), `cp` (`even`, `odd` or
`not-eigenstate`), `color_dynkin` (two explicit SU(3) Dynkin labels),
`weak_dynkin` (one explicit SU(2) Dynkin label), `hypercharge` (an exact integer
or rational string), `self_conjugate`, `conjugation` (`self`, `independent` or
`conjugate`), `conjugate_of` and `node_ids`. Every signature property can be
`null`. A declared conjugate names its original field; do not add an antiparticle
as an independent new field unless the source does so. Representation dimensions,
UFO colour codes, electric charge and arbitrary gauge labels are not automatically
translated into Dynkin labels or hypercharge. Additional gauge/VEV/mixing content
remains in the finer source records and requires its own construction review.

The multiset preserves each field occurrence, including repeated identical
signatures. Field names and ordering do not determine the coarse match. Rational
strings are reduced exactly within the same declared normalization. Unknowns
prevent exactness; incompatible bases make affected quantities incomparable.
The result retains exact, partial, conflicting and different signatures, all
unmatched occurrences and the complete library census. A conflicting signature
is a disagreement between declared representations, not a physics falsification.
An exact signature does not establish equal interactions, physical equivalence,
novelty, executable completeness or validation. Conjugate links are retained for
finer comparison rather than being declared graph-isomorphic by this search.

Each interaction, kinetic, topology or process row has `statement` and
`node_ids`. Outcome rows additionally have `status` (`accepted`, `rejected`,
`failed`, `unresolved` or `unexecuted`). `null` means unknown, whereas `[]` is
an explicitly empty population. Failed and unresolved outcomes stay in the
retrieved context. Outcome labels are retained source assertions; they transfer
no RAVEL scientific acceptance.

An optional `ufo` object has exactly `tree`, `particle_conventions` and
`field_pdgs`. The tree binds its original root and a three-field manifest pin.
Its manifest uses the existing `schema_version: 1, files: {relative: SHA256}`
format and contains every ordinary source member, including empty files and
custom modules. `particle_conventions` uses the existing
[`model_sarah.conventions`](../../src/ravel/physics/model_sarah.py) fields
`pdg`, UFO `spin` (2s+1), `color`, `charge`, `mass_parameter` and `width_parameter`.
`field_pdgs` maps unique `field` IDs to selected signed `pdg` values. The existing
static full Particle/Parameter/Coupling/Vertex/Lorentz census parses source without
importing it or evaluating couplings. Literal spin/name disagreements are retained
as diagnostics; CP, electroweak representation, hypercharge and Dynkin associations
are not inferred from those declarations. No model restrictions, parameter
substitutions, interaction reductions or UFO source rewrites occur.

The finite envelope is 32 library models, 64 fields per model, 256 total query
and library fields, 128 complete input files, 2 MiB per file, 16 MiB total inputs
and the existing 512 KiB knowledge packet. UFO enumeration additionally allows
at most 256 files/directories combined. Empty UFO members are admitted source
inputs, not empty successful output artefacts. Exceeding a bound refuses the
complete operation; it never trims fields, failures or source members. The
ordinary research premise ceiling and source/context budgets remain unchanged.

Use the existing Host `physics-knowledge` action with the request and **all**
`physics_knowledge.input_pins(request, base)` dependencies explicitly bound as
Graph inputs. To connect retrieval to ordinary hypothesis/design preparation,
call `research_tools.prepare_model_proposals(root, request_pin,
premise_map=..., reason=...)`, or supply those exact JSON arguments to:

```bash
ravel research-tools model-proposals --request model-preparation-arguments.json
```

The complete selected-premise map is required. This service invokes the existing
`research_cycle.bind_knowledge`; the normal proposal/design context then carries
the structural packet through `research_tools.prepare`. The original whole
question, source identity, premise reopening, independent review and cumulative
campaign budgets remain authoritative. A coordinating decision calls this service
after its Graph releases the campaign lock. No model turn, new scheduler, kernel
call, approval or native execution is part of structural preparation.
