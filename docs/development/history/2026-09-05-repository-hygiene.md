# Repository hygiene overhaul

This engineering migration reorganizes the active source and public distribution.
It does not add a new scientific measurement or erase failed validation outcomes.

## Starting state

The source checkout started at `c18739c6dbc8b0c54aeb9831ef42e0fe9833d51a`.
The independent public repository started at `9364dd1a03b02c1d4a0b49ea40147f4ad2d1f142`.
The public history is preserved when exporting the new layout. Original development run
records remain in the research checkout; only explicit collections are exported.

The previous root README combined onboarding, capability accounting, research argument,
and validation claims. Library code lived beside run records, while tests and maintenance
scripts shared an internal framework directory. These locations made package imports,
public navigation, and source/export correspondence unnecessarily difficult to maintain.

## External design references

The following official repositories informed navigation and documentation boundaries.
Only their public organization and documented user journeys were studied; no code was copied.

| Repository | Inspected revision | Lesson applied |
|---|---|---|
| [cabinetry](https://github.com/scikit-hep/cabinetry/tree/0252deed24451e835570619d67e60a674034d9d5) | `0252deed24451e835570619d67e60a674034d9d5` | State the purpose and give installation before detailed research context |
| [pyhf](https://github.com/scikit-hep/pyhf/tree/f19891b2255b9d8327ad0a2fc1d3b49664afbd9d) | `f19891b2255b9d8327ad0a2fc1d3b49664afbd9d` | Put API and scientific detail in focused documentation |
| [MadMiner](https://github.com/madminer-tool/madminer/tree/3e2615d0076c69e2a0e210d2ee15ebc11989e9b7) | `3e2615d0076c69e2a0e210d2ee15ebc11989e9b7` | Separate a usable entry point from extensive methodology |
| [Vector](https://github.com/scikit-hep/vector/tree/131c7d0d33fc30a2fd06d355da840a85e9bd10cc) | `131c7d0d33fc30a2fd06d355da840a85e9bd10cc` | Give readers a clear route into usage and reference material |
| [mapyde](https://github.com/scipp-atlas/mapyde/tree/7cc0afbb52283ea2a8f4375e4063227e8e2f9b8f) | `7cc0afbb52283ea2a8f4375e4063227e8e2f9b8f` | Distinguish lightweight installation from the complete simulation environment |

These are organization lessons, not empirical performance comparisons.

## Resulting organization

The [layout guide](../repository-layout.md) defines the maintained names and boundaries.
`src/ravel/` is the single Python implementation. `native/`, `environment/`, `benchmarks/`,
`tests/`, `scripts/`, `docs/`, and `evidence/` have distinct purposes.

The root README gives purpose, installation, one cached replay, and next steps. Generated
quantitative claims live in the [validation overview](../../validation/results.md); capability
accounting lives in the [reference](../../reference/capabilities.md). Research arguments and
prospective studies remain separately labeled. Older LaTeX/PDF guides are preserved as
[background reading](../../guides/README.md), with pointers to current commands.

The [evidence registry](../../../evidence/collections.json) assigns readable public destinations
to selected historical collections while retaining their original identities and artifact names.
The exporter checks source hashes before applying declared transformations, then verifies
actual staged bytes. A public directory map is generated from the selected tree.

## Defects exposed by the migration

- Fixed parent-depth assumptions in scan orchestration and monitoring. Reference cross-section
  tables now use package-data lookup instead of the script's former directory.
- Removed eager checkout requirements from validators that accept explicit input paths.
- Made CLI/converter import boundaries safe: importing a module must not parse arguments,
  exit, launch tools, or write files.
- Replaced a mutation-capable test fixture's source-directory symlink with an independent copy.
  A test that deliberately removed its fixture validator had followed that symlink into source;
  the validator was restored before final verification, and the fixture is now isolated.
- Updated the installed commit hook, enforcement-path protections, adversarial discovery,
  evidence lookup, source launchers, wheel resource selection, and CI commands together.
- Removed the public directory-map concession that treated absent paths as warnings.
  Both development and public maps must describe real files.
- Added exact local-link and case checks, naming checks, and public-root checks. A similarly
  named file elsewhere cannot satisfy a broken relative link. Historical scientific record
  contents retain their original text and are explicitly outside navigation rewriting.

## Preservation and scope

A before/after SHA-256 inventory verified 5,794 original historical files unchanged. The
original process and parameter card MD5 values remain `110cbdf8bd6360a5105a5fff134bd8c5`
and `8ec86d0f81dc3d300031796d2ebd7df4`. All three relocated native executables retain their
original hashes. The existing native tool installation remains at its original location.

Failed acceptance certifications and missing-artifact provenance breaches remain visible.
Cached statistical replay is not a fresh full-chain reproduction. Remote URL availability,
scientific correctness of arbitrary prose, and previously unmeasured agent performance are
not established by repository-hygiene checks.


## Cached replay after reorganization

A fresh [post-layout replay record](../../../evidence/audits/2026-09-05-post-layout-replay.json)
retains all nine cases: seven regression floors hold and two provenance breaches remain
because the required YODA artifacts are absent. The Gbb case still reports acceptance FAIL
at a 26.5% discrepancy while meeting its separately recorded Acceptable regression floor.
No baseline was relaxed, and the existing missing-artifact cases were not removed.
