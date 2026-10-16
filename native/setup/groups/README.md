# Toolchain group fragments

Add `native/setup/groups/<group-id>.json` with one wrapper object:

```json
{
 "group": {
  "id": "fictional-tool",
  "title": "Fictional tool",
  "depends_on": ["python-host"],
  "size_gb": 0.25,
  "minutes": 1,
  "steps": [],
  "checks": [{"id": "fictional-ready", "kind": "file", "path": "{P}/fictional"}]
 }
}
```

The filename stem must equal `group.id`. `group.schema.json` describes the wrapper;
the existing inline group validator checks the group itself. Accepted inline fields
remain accepted here. A step's `cleanup` list of path strings and a group's `components`
(named subsets with their own steps, size and checks) pass through unchanged. Their
execution and disk planning belong to the installer implementation.

`ravel.setup.manifest.load(root)` returns the merged manifest and validated PDF-set
catalogue. `ravel.setup.manifest.view(root)` returns the merged document for any tree
without catalogue or full manifest validation; it enforces wrapper, source collision
and dependency ordering rules. Consumers of install groups and release holds use this
view. The main file remains the source of profiles, engine settings, operation rows
and refusal classes. Register operation rows through the operation registration lane.

The main file's `group_order` lists positioned group ids and is consumed by the loader;
it is absent from the returned document. A moved group keeps its original position.
New groups need no main-file edit: they follow positioned groups in filename order.
The assembler repeatedly selects the first group whose dependencies have been emitted,
so a blocked group moves later only until its dependencies are available. Missing
dependencies and cycles are refused.

Every fragment group absent from the main `default.groups` joins the default toolchain
unless withheld by a release row. New members are appended in merged install order;
existing members keep their main-file order. The merged `default.disk_gb` adds their
`size_gb` to the main allowance. Named profiles come exclusively from the main file.

To withhold a group pending qualification, add `unreleased` beside `group`:

```json
"unreleased": {
 "groups": [{"id": "fictional-tool", "check": "fictional-ready", "reason": "Qualification pending"}],
 "operations": [{"mode": "fictional-operation", "groups": ["fictional-tool"]}]
}
```

This block has exactly `groups` and `operations`: one own-group row, with the same
fields as the main release list, and zero or more operation rows naming only that
group. The loader verifies the id relationships; the complete manifest validator
checks the failing check and reason. Withheld groups are excluded from default
selection but remain accessible through the existing explicit `--only` selection.
Release staging deletes withheld fragments and strips their rows and reasons.

The loader refuses wrapper keys beyond `group` and `unreleased`, multiple groups,
profile declarations, duplicate group/check ids, stem mismatches, invalid or non-finite
JSON, duplicate JSON keys, files above 4 MiB, symlinks and unexpected directory entries.
Only regular `.json` fragments, `README.md` and `group.schema.json` belong here.
A missing or empty directory leaves the main-file document unchanged.

To move an existing inline group, preserving its position and main-file release rows:

```bash
python scripts/setup/split_group.py fictional-tool --check
python scripts/setup/split_group.py fictional-tool
python -m ravel.setup.manifest view --canonical-sha256 --root .
```

`--check` reports a proposed move without writing; an already split group reports no
change. The helper compares canonical digests before writing anything and refuses a
move that changes the merged document. It writes only under `native/setup/` and
preserves the original group JSON text in the fragment. Canonical JSON uses sorted
keys and compact separators, so storage layout and whitespace do not affect the digest.
The shell preflight reads the main disk allowance before Python is available; the
installer disk gate must eventually derive its figure from the merged plan.


A group can set `qualification.required_per_platform` to `true` to require matching
platform evidence for implicit installer/doctor selection and operation availability.
The existing `qualification.record` supplies the first successful platform record;
`qualification.additional_records` holds later records in exactly the same format
(`tool`, `version`, `platform`, `date`, `doctor_result: ready`, `evidence_sha256`).
Every record is validated and platform identities must be unique. Adding a successful
record admits that platform without code changes. Platforms without a successful
record stay excluded from implicit selection and operation planning, even if the
group is present in the exported release. Explicit group selection remains possible
for qualification work. Other groups retain their existing selection rules.
