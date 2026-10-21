# Supplied AgentRivet candidate interchange

```python
from ravel.physics.agentrivet_candidate import import_candidate
result = import_candidate(request, base_dir=source_directory,
                          output_dir=fresh_candidate_directory)
```

`request` has exactly `schema_version` (integer 1), `routine` (literal canonical name), `translation_unit`, `memory`, `paper`, and `assets`. The three source pins have exactly `path` and lowercase SHA256. `paper` is the exact cached UTF-8 `Memory.paper_text` component of upstream Analyst input, including any upstream truncation; HEPData URL/map and other framing can additionally occur in that prompt. It is not the entire provider payload and is not automatically a complete or authentic publication. `memory` uses released Memory's Pydantic serialization for `AnalysisModel`. Code must equal `accepted_code` when present/nonempty, otherwise the last `code_draft`. Every raw draft/review and any retained HEPData context remain inside the copied Memory JSON. The importer authenticates supplied cached bytes, without claiming exact full provider-message or call identity.

Each optional asset has exactly `path` (relative destination), `role`, and `input` (path/SHA pin). Supported roles are header, reference, configuration, model, preprocessing, data and license. Assets remain actual caller-supplied bytes; no HEPData mapping, `.info`/`.plot` generation, source rewrite, credential lookup or generated-code execution occurs.

Regular source files are limited to 8 MiB each and 32 MiB aggregate; C++ is limited to 2,000,000 bytes, assets to 32, cuts/histograms to 256 each. Initially or finally symlinked inputs/ancestors, symlinked output ancestry, changed descriptor/path identity, duplicate JSON keys and nonfinite numbers refuse. The snapshot's authenticated bytes are used for parsing and copying. An output directory must be fresh.

Return value has exactly three document pins: `capsule`, `inventory`, `proposal`. The directory holds `candidate-capsule.json`, `source-inventory.json`, `source-proposal.json`, and the exact source/provenance tree. The capsule is an ordinary analysis-source-capsule with unresolved dependency review. Inventory/registration observations have their existing public scope; registration observation is lexical rather than C++ type checking. All execution/acceptance/provider-authentication flags are false. Failures after materialization can leave a partial fresh directory for inspection; callers must retain it rather than reuse/overwrite it as a successful result.

Next actions use existing APIs: independently establish source/header/metadata/reference/runtime closure, create and seal a new routine-build configuration, perform ordinary approval/build/role review, then prepare a source-specific rivet-built event study. The importer does not fabricate the `AgentGraph` call/response receipts required by `native_construction.materialize_agent_candidate`, nor inherit any review or launch authority.

V2 explicitly maps `/analysis_model/data/hepdata_url` even when null. A null declaration means no URL was supplied; a non-null string remains an unverified supplier declaration, without table-access, mapping or paper-fidelity inference. V1 source, failed independent controls and SEND_BACK receipt remain immutable beside it.
