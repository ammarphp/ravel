---
name: snakemake-workflows
description: Use when designing a supplied RAVEL workflow DAG, selecting a scheduler profile, reading a Snakemake dry-run, or diagnosing approved-stage failures and bounded retries.
license: Apache-2.0
compatibility: Snakemake 9.27.0 in the required site workflow environment; workflow-manager commands require their installed launch interfaces.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: ""
  upstream-version: "site-root-wms:snakemake=9.27.0"
  ravel-parameters: ""
  last-reviewed: "2026-10-13"
---

# Approved stages through Snakemake

Read project policy and the complete supplied task population before designing
the DAG. RAVEL owns scientific admission, source pins and attempt receipts;
Snakemake schedules approved dependencies. Use the required separate environment
through `ravel-snakemake`, resolved locally, without recording machine paths here.

Initialize with `ravel wms init`, register approved stages with `ravel wms add`,
and inspect `ravel-snakemake --dry-run` with the generated Snakefile and selected
profile before `ravel wms launch`. Keep plan and approve check-ins;
never approve through the workflow manager. Read `ravel wms status` and use
`ravel wms retry` for recorded bounded retries. Preserve every failed attempt.
Profiles express resources and scheduler settings, not scientific authority.

The shell discipline hook can inspect common direct-launch spellings:

```python ravel-block=workflow-route-check
from ravel.workflow.agent_surface import guard_command

def direct_launch_refusal(project, command):
    return guard_command(project, command)
```

Read a dry-run for missing inputs, unresolved rules, complete dependencies and
resource requests. Inspect original worker logs and receipts before proposing a
retry. Supplied identities, grids, datasets and output formats remain supplied
inputs. No successful shell exit implies complete scientific delivery.

## Pitfalls

- Direct launch in a policy-required project. Caught by `ravel.workflow.agent_surface.guard_command` for common shell spellings; the execution owner's launch guard remains authoritative.
- Advisory: the shell hook is discipline, not a security boundary; arbitrary programs and aliases can bypass lexical inspection.
- Advisory: parser success and a dry-run establish no native execution or physics qualification.
- Advisory: scheduler retries do not renew scientific admission, budgets or attempt claims. Use RAVEL's recorded retry route.
- Advisory: recorded procedure exports verify evidence; they do not rerun recorded commands or approve new work.

See `references/review.md` and the approved-stage how-to in the user guides.
