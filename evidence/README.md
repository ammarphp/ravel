# Evidence

This directory contains curated historical measurements, benchmark inputs, and
the metadata needed to check public claims. A checksum establishes file
integrity. It does not establish scientific correctness or a successful fresh
simulation.

| Collection | What it records |
|---|---|
| [ATLAS squark benchmark](benchmarks/atlas-2016-squark-pair/) | Cached inputs for the installed statistical replay |
| [Slepton figure 3 scan](scans/slepton-bino-figure-3/) | Scan aggregates and comparison figures |
| [Slepton PDF rescan](scans/slepton-bino-pdf-rescan/) | A paired rescan summary |
| [Native slepton point](native-validation/slepton-200-150/) | Native yields, exclusion result, and timing |
| [Compressed electroweak comparison](native-validation/compressed-electroweak/) | Native and container oracle outputs |
| [Three-lepton electroweak comparison](native-validation/three-lepton-electroweak/) | Routine comparison and the recorded later pipeline failure |
| [Zero-lepton squark comparison](native-validation/zero-lepton-squark/) | Routine comparison and the recorded later pipeline failure |
| [ARM64 container timing](case-studies/arm64-container-slepton-200-150/) | The emulated-container timing record |
| [HVT low-mass summary](case-studies/hvt-zprime-ww-low-mass-summary/) | Published-limit summary inputs and checks |

The [validation pages](../docs/validation/README.md) retain failed and unscorable
cases. These collections contain selected files, not every input needed for a
fresh complete analysis.

## Registry and provenance

[collections.json](collections.json) is the single selection and relocation
registry used by export, evidence checks, and packaged replay. Each collection
names its original source directory and run ID, public destination, purpose,
and explicit include/exclude patterns. `*` matches within one path segment;
only `**` recurses. Unlisted source archives and event dumps do not ship.

Original archive directories and record bytes remain unchanged in the
development checkout. Public copies use descriptive directory names while
retaining archival filenames, embedded original paths, and recorded failures.
The shared resolver finds those inputs in either layout without rewriting
benchmark registries or historical records.

[manifest.json](manifest.json) binds claims to artifact hashes and byte counts.
[claims.json](claims.json) registers the scoped values quoted in the
[results page](../docs/validation/results.md). Uncited historical claims may
refer to private archives; every published verified claim requires its named
evidence in the public tree.

Exports verify the source pins before accepting mapped public copies. The only
permitted record-content changes are the declared home-directory and repository
URL redactions. Export provenance records original/public paths and hashes;
the public directory and evidence indexes have named deterministic generators.
Missing files, altered registries, changed measurements, unexpected files,
symlinks, and destination collisions stop the export.

```bash
python3 scripts/check_evidence.py --check
python3 scripts/check_publication.py
```
