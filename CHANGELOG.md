# Changelog

## 1.1.0

Restores the general analysis knowledge removed in 1.0.0 and adds the capabilities below.

**Restored general analysis knowledge**

- Routine catalogue: 633 entries (554 Rivet, 79 SimpleAnalysis) with source and asset identities.
- Native routines, generation recipes, leading-order normalization tables, published-likelihood inputs and channel mappings.
- Bundled routine sources and reference assets, including the cumulant routine and its Rivet and YODA sources.
- Ntuple-analysis selection tables and branch roles.

**Recasting capabilities**

- Yield routing from analysis request to routine, detector and statistics operations.
- Source restriction, delivery into a supplied workspace and generation controls.
- Columnar trust checks and event-level weights.
- 13 TeV NLO+NLL tables for gluino, squark, stop and sbottom pair production with three PDF sets.

**Ntuple-campaign capabilities**

- Workflow-manager-first runs, prompt logs and project instructions delivered to every agent.
- Relocatable submissions, a conformance check and site installation with an HTCondor profile.
- Physics objects from energy and mass, object weights and trigger selection.
- Rucio dataset handling at scale, columnar skims and classifier training.
- Irregular-grid statistics, a provider allowlist and site tool admission.

**General tools**

- Complete executor table, lineshape operations, a Rivet-to-fit link and a general four-lepton workflow.
- One study per batch allocation on Slurm clusters.
- CheckMATE, IRIS and manuscript builds released.

**Documentation and release checks**

- A rewritten README with defined terms, a glossary and a full reference list.
- Methodology pages on the agent architecture, the research loop and Recursive Decision Justification.
- A capability-regression gate: every capability of earlier releases is present, renamed or an approved removal.
- Public CI runs the test suite in parallel shards.

## 1.0.0

First public release.

- Ask a research question in plain words. RAVEL writes the specification and the plan, starts heavy work after your approval, and reviews the evidence.
- Operations for limits and statistics, reinterpretation of published searches, event generation and simulation, model building and theory, studies of your own data, parameter scans and cosmology.
- An installer for the full toolchain, and `ravel doctor` to check it.
- Every reported value links to its inputs, tool versions and decisions.
