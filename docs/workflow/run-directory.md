# Run directories

Keep one isolated directory per physics run. New runs use
`trial-runs/<YYYY-MM-DD>_<analysis-or-model>_<point-or-scan>_<event-budget>/`.
Choose a date and descriptive label when planning the run, and retain that identity
through resumption and review. A fresh public checkout need not contain the
local `trial-runs/` directory before its first run.

A controller run creates its directory itself: `ravel drive --request-file request.txt
--rundir <new-run>` (or `ravel ask`; without `--rundir` the run goes to `./ravel-runs/<run-id>`).
The directory must be new. Start a legacy run through [physicist intake](start.md); after routing,
the `new-analysis` skill creates the skeleton. Acquire ownership before editing a legacy run:

```bash
python3 scripts/run.py ravel.workflow.session_lock acquire <rundir> --owner <session-label>
```

A live foreign lock requires coordination; do not silently share its directory.
The lock is cooperative, not an operating-system security boundary. Release it
at run close. Scaffolding and schema validation grant no compute approval; the
[check-in protocol](checklists/check-ins.md) still governs execution.

## Controller runs and their store

A controller run keeps what decides its next action outside the run directory, in the run's
store: by default `~/.local/state/ravel-controller/runs/<run-id>` (mode 0700), or under the root the
operator configured. The store holds the request bytes, the record journal (obligation ledger,
authority, custody, budgets, judgments and receipts), the graph checkpoints and the stop flag.
No environment variable moves it. The run directory holds `controller-run.json` (the marker
naming the run), the reading copies (`request.txt`, `inputs/`), step outputs and `delivery/`.

- Read a run with `ravel status --run <run-id>` and continue it with `ravel drive --resume <run-id>`.
- Never edit the store; a changed or truncated journal is detected and refuses resumption.
- Copying, moving or renaming the run directory does not move the run: the copy is refused as a
  run of its own, and resumption requires the original directory.
- Commands that would write approvals, responses, steering, a stop or custody for a
  controller-owned run are refused; read-only commands stay available.

## Private runs and sharing

```bash
ravel drive --request-file request.txt --rundir <new-run>
```

Controller run and staging directories start at `0700`; generated intake, packet and delivery
files start at `0600`. Supplied copies preserve stricter owner permissions. Child processes use umask `0077`.

```bash
ravel share group <run-id> <new-destination> --group <group> --audience "<audience>"
```

As the operator, copy a completed delivery for an existing group you belong to.
The copy uses directory/file modes `0750`/`0640` and retains its receipt and audience manifest.

```bash
ravel share public <run-id> <new-destination> --audience "<audience>"
```

Publish a delivery from a run whose frozen classification explicitly declares `public`.
The copy uses `0755`/`0644`; the source run stays private.

Choose a new ordinary destination outside the run and store. Sharing copies the delivery;
use the [run export](#export-and-restore) for a backup of execution state.

## Resume across upgrades

```bash
ravel status --run <run-id>
ravel drive --resume <run-id>
```

Resume with the original installation and environment. The first drive pins source,
installed dependencies, Python, graph and checkpoint identity; resume checks those identities.

For `execution_environment_mismatch`, restore the pinned environment and run the exact interpreter
command shown in `next_action`. Finish older executed runs under their original installation.
Normal resume recovers a verified interrupted journal append and preserves its trailing bytes as evidence.

## Export and restore

```bash
ravel operator export-run --run <run-id> --out <new-private-bundle>
```

As the operator, snapshot a quiescent run with its protected store, checkpoints, receipts and
signed authority history. Export pauses the source; keep the issuer key in a separate secure backup.

```bash
ravel operator export-run --run <run-id> --out <new-evidence-bundle> --share-only
```

Create read-only evidence for inspection. Authority restoration uses the full private bundle above.
Verify the origin with the original issuer or a separately trusted manifest digest.

```bash
ravel operator restore-run --bundle <private-bundle>
ravel operator resume --run <run-id> --reason restored
ravel drive --resume <run-id>
```

Restore at the original absolute run and store paths, with both destinations absent and the
original `store_root` configured. A replacement filesystem can be mounted at those paths.

Restore verifies the signed inventory, journal, blobs, checkpoints and authority history,
then fences prior process handles. An interrupted restore retains a pending marker;
preserve the partial state separately and restore the verified bundle into absent original paths.
Do not remove its pending marker manually. A conflicting newer authority history refuses a stale backup.

## Labels on delivered artifacts

```bash
ravel status --run <run-id>
```

Read the delivery label and `RECEIPT.json` in the run’s delivery directory with its qualifications.
Delivered documents and figures carry a visible receipt reference; qualified copies also show their qualification notice.

PDF, PNG, JPEG, TIFF, inert SVG and complete TeX support visible notices.
For other presentation encodings, export a supported format and deliver again.
Scientific data retains its original bytes with a hashed provenance sidecar; forward both files together.

Use the [outcome and exit codes](../../cli.md#work-command-outcomes) for automated delivery checks.

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

Each governed worker receives only the run files declared in its step's `inputs`,
plus its controller-built instruction and role packets. This also applies to
projected planning and review seats: packet membership follows declared inputs. Declare any required context on the consuming
step. Earlier content-addressed planning contexts remain in the run for custody,
but a later round receives only its own declared context.

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

Run directories are local working state and are never tracked. Reconcile
[DIRECTORY.md](../../DIRECTORY.md) when the repository layout changes.
