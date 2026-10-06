# Step 1 — Environment · [agent]

Run commands from the repository root in Bash. The Python replay installation is
separate from the native HEP toolchain. Native execution is the default for a
supported simulation; a passing prerequisite check does not authorize generation.

## Inspect the host and existing installation

```bash
source native/scripts/paths.sh
python -B scripts/run.py ravel.validation.native_doctor --json --require-rjr
```

Use the Ravel Python environment for this command. The doctor distinguishes Intel,
Apple Silicon and Rosetta processes, checks exact environment prefixes and native
libraries, and reports missing prerequisites without installing anything. For a
non-RJR routine omit `--require-rjr`. Inspect the declared native capability plan
for analysis-specific requirements too.

The [macOS portability reference](../../reference/native-portability.md) records
supported host assumptions, the checks performed, and remaining clean-install
validation gaps. A working installation on one Mac is not a universal portability
or physics claim. Use absolute `RAVEL_NATIVE_BUILD` and `RAVEL_NATIVE_BIN` overrides
for a user-owned installation elsewhere; do not mix Intel and ARM environments.

## Bootstrap a new native prefix

Preview the applicable steps, in order. Each step needs its predecessor installed:

```bash
bash environment/scripts/00-install-miniforge.sh --dry-run
bash environment/scripts/01-create-env.sh --dry-run
bash environment/scripts/02-get-madgraph.sh --dry-run
```

Remove `--dry-run` when intentionally provisioning. The installer and MadGraph
revision are pinned; existing prefixes are preserved. The MG5 environment recipe
selects Python, compiler and supporting packages and records the resolved package
list. It is not a complete cross-platform native dependency lock. Apple's Command
Line Tools/SDK must already be available for compilation.

The full chain additionally needs the environments below under
`$RAVEL_NATIVE_BUILD/tools/miniforge3/envs/`. Use explicit conda prefixes (`--prefix`)
when creating or invoking them, so a same-named global environment cannot substitute.

| Environment | Required tools or assets |
|---|---|
| `mg5` | Python/compiler used by the pinned MadGraph source |
| `rivet` | Rivet, YODA, Pythia8, HepMC3, Python analysis/statistics dependencies |
| `recast` | Compatible ROOT, FastJet, DelphesHepMC3 and libDelphes, converter dependencies |
| `pipeline` | mapyde cards, process/parameter templates, converter and likelihood assets |
| `reinterp` | Optional HEPData and reinterpretation clients used by the selected workflow |

See the [environment inventory](../../reference/environment.md) and
[portability reference](../../reference/native-portability.md) for recorded versions
and unresolved provisioning steps. Creating a conda environment containing ROOT
and FastJet does not also install Delphes. Do not proceed until its executable,
headers and library agree with that environment and the doctor passes.

## Build the applicable bridges

```bash
bash native/scripts/pythia-shower-build.sh --dry-run
bash native/scripts/restframes-native-build.sh --dry-run
bash native/scripts/rjr-resolve-build.sh --dry-run
```

These helpers inspect the installed compiler/SDK and produce explicit build plans.
Remove `--dry-run` only for the applicable intentional build. RestFrames source and
its dependencies must already be acquired at the declared paths. The compressed
analysis needs the RJR resolver; other registered routines have their own declared
requirements. Existing outputs are preserved until a successful staged build can
replace them. Rerun the doctor after provisioning or building.

For execution, follow the [native pipeline reference](../reference/native-pipeline.md)
and the approved task's cards, detector adapter, routine and statistical mapping.
Do not use a working but different analysis to bypass a missing dependency.

## Paper-PDF tooling

The figure extractor's PDF-page route needs Poppler's `pdftoppm`; the arXiv-source
route can avoid that renderer. Check the selected extraction route before fetching
and processing figures. Native HEP readiness does not imply PDF-tool readiness.

**Next:** [Step 2 — Inputs](02-inputs.md).
