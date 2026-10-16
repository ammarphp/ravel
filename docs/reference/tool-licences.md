# Tool licences

RAVEL fetches the tools below at installation and runs them as separate programs. The copied material that travels with RAVEL is listed in [THIRD-PARTY-NOTICES.md](../../THIRD-PARTY-NOTICES.md).

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
own receipts; an upstream source fetch cannot establish a built image digest.

Fragments use `ravel.setup.licence_policy.licence_entries(keys)` for manifest licence
entries and `load_pin(key)` for install inputs. `load_pin` refuses pending entries;
`licence_entries(..., require_verified=True)` additionally requires verified source
and licence evidence. `check(document, ledger=pins['tools'], containerfiles=...)`
lints assembled groups and recipe text without running an upstream tool.
Manifest validation invokes the group policy; the assembler must also supply the
recipe text to cover Containerfile COPY. Groups that only describe local/site
infrastructure or inherit dependencies acquire no third-party component and need
no new licence entry. Restricted Python tools use separate interpreters; GPL,
LGPL, AGPL, MPL and unconfirmed tools are never imported into RAVEL's environment.

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

Every GPL, LGPL, AGPL and MPL entry below (and every unconfirmed `LicenseRef`) is an
external add-on: fetched at installation, run as a separate program, never vendored,
imported into RAVEL or published in a container (`import_into_ravel: never`,
`container_publish: never`).

All entries below await upstream licence-text hashes. `redistribute` describes
upstream permission, not a plan to vendor code: these integrations acquire tools
at installation. `container_publish: never` also applies to locally built GPL
images. The base image is a package collection whose licences require a package
inventory; no blanket licence is asserted.

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
