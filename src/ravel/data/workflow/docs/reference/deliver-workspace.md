# Deliver into a supplied workspace

After a study has a current accepted review, deliver its reviewed artifacts into
requester-supplied paths:

```bash
ravel deliver-workspace --rundir RUN --layout LAYOUT.json --into WORKSPACE
ravel deliver-workspace verify --into WORKSPACE
```

The layout is a JSON object. Every key is independent and can be omitted.
No requester directory layout ships with the command.

| Key | Meaning |
|---|---|
| `analysis_code` | Destination directory for reviewed Python, C/C++ sources and typed columnar recipes |
| `selected_events` | Destination directory for reviewed ROOT, Parquet, NPZ and Arrow event files |
| `cards` | Destination directory for reviewed `.dat`, `.tcl` and `.card` inputs |
| `templates` | List of relative glob patterns selecting filled templates inside the run; relative paths are retained in the workspace |
| `report` | Requester's report path; existing bytes are preserved and a provenance block is appended |
| `copy_limit_mb` | Per-event-file copy ceiling in MiB, default 500; zero references every nonempty event file |

Unknown keys, absolute paths, parent traversal, symlinks, destination collisions
and existing delivery files are refused. Template patterns must match. The
command writes no replacement of existing delivered files. A workspace with an
existing delivery index must use a new destination. A report can exist already.

Ordinary category files come only from the current review's captured artifacts;
file suffixes identify eligible types, and the recorded recipe kind identifies
columnar recipes. Filled templates need their adjacent `.provenance.json`
records and the current review must capture their original result bytes. Filled
output hashes and review scope/sequence must match. Template provenance and the
accepted result bytes travel beside each delivered template. The exporter reads
existing records and runs no simulation or authored analysis.

Large event files are references with original paths, size and SHA-256, explicitly
marked `reference` in the report. They remain external dependencies; verification
requires the original bytes to remain accessible. Copied files, filled result
bytes, fill provenance and receipt copies can be checked without the original run.

`.ravel-delivery.json` lists delivered files and references. Receipt copies live
beside the index in `.ravel-delivery.json.evidence/`. The report's JSON fence lists
run identity, source code version, recorded generator/shower/detector information,
card hashes, event counts, cross-section convention, PDF/source table,
luminosity, recomputed ledger total, review sequence/verdict and recorded actor
kind, file hashes and fill lineage. Missing records remain `null`; actor kinds
absent from the review journal remain `unrecorded`, never inferred as human.
Canonical normalization ledgers are recomputed with the existing comparator;
this does not certify the scientific result. Full receipt bytes remain available
for details. A block larger than 6 KiB is refused before writing; no provenance
rows are silently dropped. If `report` is omitted, provenance remains in the index.

Verification refuses missing or changed files and reports `hand-edited`, the
relative template path, expected fill hash and observed hash for modified filled
templates. It also hashes the complete report. The index is an unsigned integrity
record: it detects accidental edits, not coordinated malicious replacement of
all artifacts and their recorded hashes.

`literal_scan(paths, table_lengths=...)` reports numeric Python list/tuple literals
and C/C++ brace initializers matching a delivered table's bin count. Signed values
are included; computed comprehensions are excluded. Findings include file, line
and length. Review each flagged literal against its source and intended use, including legitimate constants. It neither executes nor edits authored code.

The delivery label follows the current review scope. A diagnostic scope delivers with the
`diagnostic` label, and filled-template result bytes are listed as `diagnostic_result`. Any
other scope requests the `accepted` label: every delivered result and selected-event file must
be the exact output of a stage with current supervisor custody and a matching approval-bound
launch, required roles must be credited and the current review must cover those bytes;
otherwise nothing is written. A delivery with no result or selected-event file must not carry
the accepted label. The index and report carry the architecture receipt and its plain-language
notices. `verify` rechecks the receipt's integrity, refuses a diagnostic index listing an
accepted result and recomputes a non-diagnostic label against the source run's live custody,
so verifying an accepted delivery needs the source run. An index without an architecture
receipt, including one written before this change, is refused.
