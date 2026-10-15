# Run approved stages through Snakemake

RAVEL keeps scientific planning, approval, source custody and result checks.
Snakemake schedules registered approved stages. A project declaring
workflow-manager-first policy uses `ravel wms launch` for execution. Plan and
approve retain their check-ins; never approve through the workflow manager.

## Install agent guidance

Run `ravel agent-surface install --project PROJECT`. The installer preserves
existing project instruction documents byte for byte and writes guidance to
`.ravel/agent-guidance.md`. Load this file into the host session alongside the
project instructions. The software skill records the Snakemake version from
`.ravel-site/wms.json`, the toolchain manifest, or the current environment, in
that order. A declared version does not prove local availability.

The site-wms record is `.ravel-site/wms.json` under the project, or under the
site prefix named by `RAVEL_SITE_PREFIX` or `RAVEL_NATIVE_BUILD`. Guidance reads
only its schema version 1 and its declared `version`. The paths in the record
stay local; generated guidance names the `ravel-snakemake` resolver shim. The
site installation validates the record and resolves the shim before native
execution. A record without a declared version is refused.

Generated guidance, skills and hook commands contain no machine interpreter or
home paths. Interpreter and source locations live in ignored local runtime
files. Keep these local files untracked; refresh them after moving a checkout.
Existing hook groups and foreign skills are preserved. Older RAVEL audit hook
commands are refreshed to use the runtime resolver.

The shell guard is on by default when policy requires the workflow manager.
`--wms-guard` also installs it in other projects, where it remains inert until
policy requires it. It refuses common direct `ravel run`, science-module run,
and manual `run-step` spellings, and names the `ravel wms` route. A command it
cannot split into words is refused only when it spells a direct launch. It is agent
discipline, not a security boundary. Arbitrary scripts or aliases can evade
lexical inspection; the execution owner's admission and launch guard remains
the authority.

To record an opt-out, supply `--no-wms-guard --guard-approval FILE`.
The JSON record has `schema_version: 1`, `action: "wms-guard-opt-out"`,
`approved: true`, the absolute `project`, a nonempty `approved_by` and `reason`.
Keep the record local. The installer pins its digest and checks that it still
matches; a Boolean flag alone cannot disable a policy-required guard. This
record documents approval and does not authenticate a reviewer identity.

## Initialize and register

The workflow-manager launch interfaces must be installed before using the
following commands. This checkout's agent-surface fixtures do not establish
their availability. Inspect each command's `--help` from the installed version.

```sh
ravel wms init --project PROJECT --audit AUDIT.json --profile local
ravel wms add --project PROJECT --rundir APPROVED_RUN --task TASK
ravel wms status --project PROJECT
```

Supply the audit document, identities, dependency edges, resources, parameter
grid, dataset population and output format for the actual study. Register
predecessors with `--after` as required by the installed add interface. Do not
infer approval from registration or drop unresolved tasks from the DAG.

## Inspect and launch

Use the generated Snakefile and directory for the project's selected profile:

```sh
ravel-snakemake --snakefile PROJECT/workflow/Snakefile --directory PROJECT/workflow --cores 1 --dry-run
ravel wms launch --project PROJECT --task TASK --cores 1
ravel wms status --project PROJECT
```

Read the dry-run for missing inputs, rule selection, complete dependencies and
resource declarations. Launch only after actual CHECK-IN 1 approval and method
admission. The manager cannot approve tasks, widen scope or renew budgets.

## Retry, replay and export

Use `ravel wms retry --help` from the installed retry interface to select the
failed registered task and its permitted bounded attempt. Preserve original
logs and failed receipts. Scheduler retries do not create fresh scientific
admission; follow RAVEL's retry accounting and source checks.

For retained procedure evidence:

```sh
ravel procedure export --rundir RECORDED_RUN --into FRESH_DIRECTORY
ravel procedure verify --package FRESH_DIRECTORY
```

Export requires a fresh destination. Verification rechecks retained record
pins; evidence replay does not execute recorded shell commands or establish a
successful result. Re-execution needs its own admitted workflow and current
inputs. See [site workflows](../reference/site-workflows.md) for the exact
recorded procedure contract.

## Qualification

Synthetic tests cover guidance selection, project-instruction preservation,
portable generated content, hook refusal, consult routing and the handbook
example. Native parsing, site resolver availability, scheduler behavior,
scientific admission across retries and numerical physics qualification require
separate executed evidence with supplied inputs and references. No such native
or remote qualification is claimed by these fixtures.
