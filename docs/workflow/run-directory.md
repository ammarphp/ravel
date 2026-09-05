# Run directories

Keep one isolated directory per physics run. New runs use
`trial-runs/<YYYY-MM-DD>_<analysis-or-model>_<point-or-scan>_<event-budget>/`.
Choose a date and descriptive label when planning the run, and retain that identity
through resumption and review. A fresh public checkout need not contain the
local `trial-runs/` directory before its first run.

Start through [physicist intake](start.md). After routing, the
`new-analysis` skill creates the skeleton. Acquire ownership before editing:

```bash
python3 scripts/run.py ravel.workflow.session_lock acquire <rundir> --owner <session-label>
```

A live foreign lock requires coordination; do not silently share its directory.
The lock is cooperative, not an operating-system security boundary. Release it
at run close. Scaffolding and schema validation grant no compute approval; the
[check-in protocol](checklists/check-ins.md) still governs execution.

## Layout

| Path within the run | Contents |
|---|---|
| `RESULT.md` | Status, configuration, results, validation, and unresolved gaps |
| `DEVIATIONS.md` | Changes of course, recorded when they occur with reasons and impact |
| `RESUME.md` | Current state, running jobs and logs, exact resume commands, remaining work |
| `run_state.json` | Lifecycle ledger written by the workflow tools and read by the gates |
| `config/` | Exact steering configuration and tool settings used |
| `inputs/` | Task contract, input-card copies, figure target, check-ins, and required reference inputs |
| `logs/` | Per-stage logs, failures, timings, and producer-completion evidence |
| `outputs/` | Rivet/workflow summaries, validation artifacts, and statistical results |
| `output/` | Native/mapyde stage products, including yields, signal patches, and exclusion results |
| `build/` | Local build products and intermediate analysis work |
| `plots/` | Figures, their index, captions, and plot-quality records |
| `result.json`, `figures.json`, or `scan.json` | Machine-readable summaries produced by the relevant workflow stage |

The two output conventions belong to different execution paths. Preserve the
chosen engine's layout and record the actual paths; do not rename completed
artifacts merely to make a run look uniform. Create each required artifact when
its stage produces it. Empty placeholders never establish completion.

## Result record

The final `RESULT.md` must identify:

1. Which stages passed, failed, or remain blocked.
2. The analysis, model, point or scan coverage, event counts, tool versions, and backend.
3. Each headline value and its source artifact, including cross-section basis and statistical mode.
4. The published reference used for validation, its tolerance, the observed agreement, and the verification verdict.
5. Missing evidence, substitutions, unresolved failures, and deviations.

Keep failures and unscorable points visible. Use a labeled partial result when
the requested scope is incomplete; a successful software gate alone does not
certify the physics. See [verification](steps/09-verify.md).

## Preservation and publication

Work on copies of supplied cards and preserve original inputs. Retain logs,
provenance, small results, and the records needed to reproduce the analysis.
Heavy event files and other generated intermediates are generally gitignored;
being ignored does not make them disposable evidence.

Historical research runs retain their original identities and artifact bytes.
The public `evidence/` collection is a curated, provenance-linked export of
selected records. It is not a directory for new mutable runs. Use the
[distribution policy](../development/distribution.md) when publishing a subset,
and reconcile [DIRECTORY.md](../../DIRECTORY.md) when the workspace layout changes.
