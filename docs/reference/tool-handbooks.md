# Runtime tool handbooks

RAVEL ships short handbooks for the external HEP tools its operations use.
An agent loads one when it works with that tool. Each handbook says how
RAVEL's typed path uses the tool, which mistakes RAVEL catches and with which
check, and which mistakes it leaves to the agent.

## Layout

Handbooks live in `src/ravel/data/skills/tools/<tool>/` and ship in the wheel:

- `SKILL.md`: frontmatter and the handbook text, with a `## Pitfalls` section;
- `references/`: longer notes the handbook points to;
- `references/review.md`: one JSON review record.

`ravel.validation.tool_handbooks.handbook_root()` finds the directory in a
checkout or an installed package. An installer copies a whole handbook
directory into an agent's skills directory (`.claude/skills/<tool>` and
`.agents/skills/<tool>`).

First wave: madgraph-launch, madgraph-model-import, feynrules, lhapdf-pdf-sets,
pythia-shower-cards, delphes-cards. Second wave: rivet-routine, ma5-expert,
smodels-input, pyhf-workspace-patching, hepdata-retrieval.

## Frontmatter

Exactly the six Agent Skills keys: `name`, `description`, `license`,
`compatibility`, `allowed-tools`, `metadata`. RAVEL fields are quoted strings
under `metadata`:

- `ravel-requires-modes`: the science modes that use the tool;
- `upstream-version`: space-separated `group:component=version` items for a
  toolchain-manifest group, or `pypi:distribution=version` for a pinned Python
  dependency;
- `ravel-version-unpinned`: items of `upstream-version` the toolchain does not
  pin yet (a mismatch is otherwise an error);
- `ravel-parameters`: the `operation.field` configuration paths the handbook
  tells an agent to set;
- `last-reviewed`: a date.

## The contract

`python -m ravel.validation.check_agent_surface` runs these checks
(`handbooks` line):

- the closed key set and the metadata keys above;
- a token budget for `SKILL.md` and each reference file, 5000 by default
  (`--token-budget`). The estimate is a line proxy: each line costs
  ceil(characters / 4) + 1 tokens;
- every pitfall names a RAVEL check that catches it (``Caught by `module.function` ``
  or a source file) or starts with `Advisory:`;
- every `ravel-parameters` entry, and every `operation.field` path the text
  mentions, is listed in `src/ravel/data/skills/operation-fields.json`; a unit
  test removes each listed field from a valid configuration and requires the
  operation's validator to refuse it;
- `upstream-version` matches `native/setup/toolchain-manifest.json` (either
  manifest version) and the `==` pins in `pyproject.toml`;
- the review record lists every code block marked `ravel-block=<id>` as
  executable or illustrative, and `tests/skills/<tool>/` runs the executable
  ones.

Further lines: `installed` (with `--installed DIR`, repeatable) fails when an
installed copy differs from the packaged handbook; `skill-keys` reports
workflow skills whose frontmatter leaves the six-key set; `collisions` reports
skill descriptions that overlap strongly. The last two only report.

## Unavailable tools

`--doctor-report FILE` reads a `ravel doctor --json` report (or a
`native_doctor` report) and prints, per handbook, whether the toolchain groups
it pins are ready. A handbook for an unavailable tool is illustrative on that
host. `tool_handbooks.doctor_report()` produces a live report, preferring
`ravel doctor` and falling back to `native_doctor`.

## Writing a handbook

Write it from the upstream manual and RAVEL's code; copy no third-party text.
State versions, cite the manual or paper for each upstream fact, and link to
`docs/reference/failure-modes.md` instead of repeating a failure story. Keep
one fact in one place.

## Snakemake workflow handbook

`snakemake-workflows` covers supplied DAGs, profiles, dry-run reading, failure
triage and retries through RAVEL. Its executable example only inspects synthetic
policy and shell-command strings. The version is pinned to the required site
workflow environment; local presence and scientific qualification remain
separate evidence. See [approved stages](../guides/approved-workflow-stages.md).
