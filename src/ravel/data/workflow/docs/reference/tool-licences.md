# Tool licences

The installers acquire Python distributions and native tools. The generated
[component inventory](component-inventory.md) records every full-profile and package
requirement using installed distribution metadata, and every native manifest group
using its declared licences and installation boundaries. Regenerate it in the full
host environment with `python scripts/maintenance/render_component_inventory.py`;
`--check` exits 1 when the file differs from that environment's observations.
The copied files retained in this tree are listed in
[THIRD-PARTY-NOTICES.md](../../THIRD-PARTY-NOTICES.md).

## Python installation and imports

The full host profile installs distributions whose own metadata includes GPL, LGPL
or MPL terms: `pySecDec` and `hepdata-cli` declare `GPLv3`; `pyslha` has a GPLv3
licence classifier; `iminuit` declares `MIT+LGPL`; `certifi` declares `MPL-2.0`;
`camb` declares `LicenseRef-LGPLv3-arxiv`; and `cobaya` declares
`LGPL-3.0-or-later AND LicenseRef-GFDL-1.3-or-later`. These are the metadata strings
observed in the full-profile generating environment, rather than inferred terms.
`classy` has no licence field or licence classifier there and is recorded as `unknown`.

Installation in the host environment and import in a process are distinct.
`src/ravel/physics/finite_integrals.py` copies the
worker source and launches the pinned `runtime.python` executable with `-I -B`.
`src/ravel/physics/finite_integrals_worker.py` explicitly adds the admitted source
root and runtime site directories to `sys.path`, then imports `pySecDec`,
`pySecDec.integral_interface` and `pySecDecContrib` in that child process.
The native `finite-integrals` group creates the `integrals` environment, but a task
supplies its interpreter and site roots. The host executable is also a valid interpreter
choice when it satisfies the task's declared runtime contract.

The host code also imports full-profile packages: for example,
`src/ravel/physics/reinterpret_db.py` imports `pyslha`. The cosmology solver launches its supplied runtime
interpreter with `-I -B` and imports its selected solver in that child process
(`src/ravel/physics/cosmology_solver.py`).

## Scope-tools add-ons

The machine-readable ledger is `native/setup/tools-pins.json`: each `tools.<key>`
entry carries its upstream candidate, requested version, expected licence file,
permissions and `licence_text_sha256`. Every new entry remains pending until a
reviewed acquisition supplies the exact source pin and licence bytes. Candidate
URLs, versions and licence paths are selection instructions, not fetched evidence.
Unconfirmed terms use conservative permissions. No upstream code or source text
is included here. The source-fetch job must replace candidate URLs with actual
assets and confirm the licence file at the chosen revision. Authored assets are
resolved from the local source tree. Remote and locally built images require their
own receipts; a built image requires its own observed digest.

Fragments use `ravel.setup.licence_policy.licence_entries(keys)` for manifest licence
entries and `load_pin(key)` for install inputs. `load_pin` refuses pending entries;
`licence_entries(..., require_verified=True)` additionally requires verified source
and licence evidence. `check(document, ledger=pins['tools'], containerfiles=...)`
lints assembled groups and recipe text without running an upstream tool.
Manifest validation invokes the group policy; the assembler must also supply the
recipe text to cover Containerfile COPY. Groups that only describe local/site
infrastructure or inherit dependencies acquire no third-party component and need
no new licence entry. These ledger flags apply to the additional source acquisitions described here;
the full host profile and its process boundaries are recorded above.

Run `python -m ravel.setup.licence_policy --containerfile <recipe>` for the offline
pins/schema/ledger and recipe lint. Published comparator stubs and source metadata
live in `src/ravel/data/knowledge/qualification/`; use
`python -m ravel.validation.qualification_rows --source-cache <cache>` to verify
filled rows against byte-pinned extracted text. The cache is external to the
exported tree. Null values are acquisition holds. Consumers resolve
`qual:<tool>:<quantity>` with `resolve`; its default requires a filled row and
verified extraction. `check_knowledge` validates the directory and reads the
optional `RAVEL_SOURCE_CACHE` when filled records are present. Numeric source
values belong only in the cited rows, with an exact table, figure or equation
locator, conditions, units, uncertainty definition and extraction attribution.

The restricted entries below carry `import_into_ravel: never` and
`container_publish: never` in the source-acquisition ledger. These are configured
installer policies, not a description of every Python dependency or every copied
file in this tree. The copied-material table records retained files separately.

All entries below await upstream licence-text hashes. `redistribute` is a ledger
flag; this table records its configured value without establishing permission.
`container_publish: never` also applies to locally built images for these entries.
The base image contains multiple packages; its ledger entry is not a component inventory.

| Pin key | SPDX / licence reference | Redistribute | Import into RAVEL | Publish container | Evidence |
|---|---|---|---|---|---|
| `geant4` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4emlow` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4photonevaporation` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4radioactivedecay` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4particlexs` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4ensdfstate` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4saiddata` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4incl` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4abla` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4pii` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4realsurface` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4ndl` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `geant4-g4tendl` | LicenseRef-Geant4 | true | never | never | pending licence-file sha256 |
| `gdml-geometries` | Apache-2.0 | true | allowed | allowed | pending licence-file sha256 |
| `ravel-g4sim` | Apache-2.0 | true | allowed | allowed | pending licence-file sha256 |
| `dd4hep` | LGPL-3.0-only | true | never | never | pending licence-file sha256 |
| `podio` | Apache-2.0 | true | allowed | allowed | pending licence-file sha256 |
| `edm4hep` | Apache-2.0 | true | allowed | allowed | pending licence-file sha256 |
| `open-data-detector` | MPL-2.0 | true | never | never | pending licence-file sha256 |
| `acts` | MPL-2.0 | true | never | never | pending licence-file sha256 |
| `cms-open-data` | Apache-2.0 | true | allowed | allowed | pending licence-file sha256 |
| `sherpa` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `openloops` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `recola` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `herwig` | GPL-2.0-or-later | true | never | never | pending licence-file sha256 |
| `thepeg` | GPL-2.0-or-later | true | never | never | pending licence-file sha256 |
| `powheg-v2` | LicenseRef-POWHEG-BOX | false | never | never | pending licence-file sha256 |
| `powheg-res` | LicenseRef-POWHEG-BOX | false | never | never | pending licence-file sha256 |
| `madgraph-3` | LicenseRef-MG5aMC | true | never | never | pending licence-file sha256 |
| `luxlep` | LicenseRef-upstream | false | never | never | pending licence-file sha256 |
| `luxqed` | LicenseRef-upstream | false | never | never | pending licence-file sha256 |
| `iregi` | LicenseRef-upstream | false | never | never | pending licence-file sha256 |
| `looptools` | LGPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `form` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `package-x` | LicenseRef-Package-X | false | never | never | pending licence-file sha256 |
| `formcalc` | LGPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `dsixtools` | GPL-3.0-only | true | never | never | pending licence-file sha256 |
| `qgraf` | LicenseRef-QGRAF | false | never | never | pending licence-file sha256 |
| `micromegas` | LicenseRef-micrOMEGAs | false | never | never | pending licence-file sha256 |
| `susyhit` | LicenseRef-SUSY-HIT | false | never | never | pending licence-file sha256 |
| `feynhiggs` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `softsusy` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `multinest` | LicenseRef-MultiNest | false | never | never | pending licence-file sha256 |
| `pymultinest` | GPL-3.0-only | true | never | never | pending licence-file sha256 |
| `feynarts` | LGPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `feyncalc` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `flexiblesusy` | GPL-3.0-only | true | never | never | pending licence-file sha256 |
| `spheno` | LicenseRef-SPheno | true | never | never | pending licence-file sha256 |
| `sarah` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `feynrules` | LicenseRef-FeynRules | true | never | never | pending licence-file sha256 |
| `easyscan` | Apache-2.0 | true | allowed | allowed | pending licence-file sha256 |
| `gm2calc` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `phasetracer` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `checkmate` | GPL-2.0-only | true | never | never | pending licence-file sha256 |
| `root` | LGPL-2.1-or-later | true | never | never | pending licence-file sha256 |
| `torch` | BSD-3-Clause | true | allowed | allowed | pending licence-file sha256 |
| `torch-geometric` | MIT | true | allowed | allowed | pending licence-file sha256 |
| `scikit-learn` | BSD-3-Clause | true | allowed | allowed | pending licence-file sha256 |
| `mcfm-image` | GPL-3.0-or-later | true | never | never | pending licence-file sha256 |
| `container-base` | LicenseRef-Fedora-packages | false | never | never | pending licence-file sha256 |
