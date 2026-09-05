# Distribution and publication

The public repository contains the runnable source, workflow instructions,
regression tests, and curated evidence. The source checkout also contains
private development history and large simulation outputs. Export selects the
public files explicitly; it never copies the whole workspace.

[evidence/collections.json](../../evidence/collections.json) is the machine-readable
selection policy. The shared implementation is
[src/ravel/evidence_layout.py](../../src/ravel/evidence_layout.py). The exporter,
evidence checks, and installed replay use that registry rather than maintaining
separate lists of historical paths.

## What ships

| Area | Public content |
|---|---|
| Root files | README, contributor instructions, agent instructions, directory index, citation, license, changelog, build metadata, and locked dependencies |
| `src/ravel/` | Physics, workflow, validation, plotting, and package modules, with their selected reference data |
| `tests/` | Unit regressions, adversarial scenarios, and required historical test fixtures |
| `benchmarks/` | Case, capability, and scan-spec registries and recorded baselines |
| `native/` | README, C++ source, and build/execution scripts |
| `environment/` | Environment setup instructions and scripts |
| `docs/` | Onboarding, reference, workflow, validation, research, guides, and explicitly labeled development history |
| `evidence/` | Claim and integrity manifests plus the selected public evidence collections |
| `scripts/` | Maintenance commands, documentation generators, audit tools, and export checks |
| Hidden configuration | CI, agent skills/rules, enforcement hooks, portable settings, and mirrored skills |

Tests, evidence tooling, hooks, and portable agent settings ship because they
are needed to exercise the advertised behavior. Machine-specific
`.claude/settings.local.json` does not ship.

## What remains local

Unselected trial records, private session/control archives, old framework
planning directories, untracked research notes, local simulation toolchains,
and generated event dumps remain in the source workspace. Cache and build
intermediates are excluded by the registry. The public root contains no
`framework/`, `trial-runs/`, `stages/`, `shared/`, `pedagogical/`, or `results/`
trees.

Curated evidence is selected by file patterns from nine original run
collections. Public copies have descriptive names under `evidence/benchmarks/`,
`evidence/scans/`, `evidence/native-validation/`, and `evidence/case-studies/`.
The registry retains the original IDs and source paths. Original archive bytes
and paths remain unchanged in the development checkout; record filenames,
embedded historical references, and recorded failures are preserved.

The public navigation uses public evidence destinations. Runtime compatibility
with an old source path does not make that old path a valid browser link.

## Export checks

Use a new or empty staging directory outside the source checkout:

```bash
python3 scripts/check_evidence.py --check
python3 scripts/check_publication.py
bash scripts/maintenance/export-distribution.sh /tmp/ravel-review
```

The exporter refuses a populated directory, the source tree, repository
ancestors, the home directory, or symlinked staging paths. It copies the registry
selection and then permits only the declared home-directory and repository-URL
redactions. The public directory index is generated from the selected files.

Before publishing, the exporter verifies the original source evidence pins,
compares every selected staged file with its declared source transformation,
and rejects unexpected or missing files. It records original/public paths and
hashes in export provenance and regenerates the public evidence index. It then
runs artifact integrity, agent-surface, publication, repository-layout,
filename, and exact local-link checks against the staged tree. Files larger
than 5 MB stop the export.

The link check uses literal browser destinations in a public tree. In source,
it permits explicit public-evidence aliases backed by the registry and rejects
links to files that will not ship. Immutable historical record text is exempt
from navigation checks. Remote availability and non-Markdown renderer fragments
are outside this check.

The source directory map and the generated public map describe their respective
trees. Neither uses missing development-only rows to excuse a broken public
reference. After changing the layout or evidence selection, run the source
checks and review a fresh export; source checks alone do not replace staged
validation.

## Publishing

Passing `--push <remote-url>` explicitly requests publication of the validated
stage. The publisher clones the remote main branch, applies the reviewed tree,
and appends a normal commit. It verifies the remote revision afterward. A
concurrent update causes rejection; there is no force-push fallback.

An export demonstrates the checked software and artifact properties. It does
not establish fresh event generation, detector validation, scientific
certification, or complete anonymity of an independently published copy.
