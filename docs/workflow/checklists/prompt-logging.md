# Prompt logging

Before delivering a run that requires complete prompt accounting, export its
recorded sessions and explicitly supplied interactive transcripts:

```bash
ravel audit prompt-log --rundir RUN --transcripts TRANSCRIPT ... --out OUTPUT
```

Use `--price-table FILE` when estimating cost. Supply a JSON object keyed by the
reported model ID. Each entry has `input_per_million` and `output_per_million`;
`cached_input_per_million` and `cache_creation_input_per_million` select cache
pricing when supplied. All rates use the same caller-declared currency. No rates
ship with the exporter. Missing usage or missing model prices remain unpriced
rows. Totals are reported token sums and summed invocation durations, with
unknown counts; concurrent durations do not measure elapsed run time.

The export writes prompt-log.jsonl and prompt-log.md in the supplied output directory (for example `outputs/prompt-log.md`). Every row carries the
full recorded prompt, reported model identity, timezone-aware timestamp and
token count, alongside requested model, CLI version, source pin, session, role
and the instruction-document hash when present. Aliases without a dated snapshot
are flagged as inexact. Unknown quantities remain null and appear in gaps.

Worker prompts use the hash-pinned CLI stdin bytes. The worker receipt names
that file in the run's custody folder (`$RAVEL_STATE_DIR/workers/<run digest>/`),
outside the run tree. The export reads a regular file directly in that folder
and no other path outside the run. One-shot
receipts are read from standalone response receipts and host transport receipts.
A successful one-shot session keeps its exact prompt beside its receipt file or
session record, in `<file without .json>.prompt.txt`. The export takes that text
when it is a regular file inside the run and hashes to the receipt's prompt
digest; `prompt_source` pins it. A kept file with other bytes is flagged
`kept prompt differs from the receipt prompt digest`.
A one-shot receipt without a kept prompt is rendered with the installed renderer
only when its UTF-8 digest matches the receipt; the export pins both request and
renderer. Missing requests or changed templates prevent claiming exact prompt text.

The instruction-document hash of a row is the `sha256` of the delivery record in
its receipt: `transport.project_instructions` for a worker and
`configuration.project_instructions` for a one-shot session. `instruction_delivery`
holds that record's mechanism. A record without a sha256 digest is flagged
`instruction delivery record malformed`. When the document travelled in the
prompt's first block, a kept prompt already holds it. Without a kept prompt the
export rebuilds that block from the document text and accepts the prompt only
when the whole text matches the receipt's prompt digest. When a flag carried the
document, the prompt digest does not cover it, and the row holds the text in
`system_prompt_append`. The document text is read from the file the record names
while it still holds the recorded bytes, and otherwise from the copy the run's
custody folder keeps for every pinned document
(`project-instructions.<sha256>.md`), so a re-pin does not lose an earlier text.
When neither holds the recorded bytes the row is flagged
`declared document bytes unavailable`. A worker row whose transcript names no
model takes the reported model and CLI version from the worker receipt.
Provider records preserve the exact serialized HTTP request body inside the
existing guarded call. Exclude authentication headers and private response content. Failed calls retain unknown usage.

Loop model turns are collected from effect-ledger records under `calls/`, one
row per call identity even after replay. The loop keeps the serialized request
with the effect before it sends anything, so a turn whose sender failed after
dispatch still has its exact prompt, bound by the effect's request digest.
Completed turns add the reported model and usage; unfinished turns keep unknown
usage, and turns recorded before the request was kept have an unknown prompt.
A caller-supplied dispatcher runs inside a recorded dispatch: the sealed request
handed to it is written under `prompt-receipts/` before the call, with stream
`dispatcher`, and the model and usage its response file reports are added after
it. What the dispatcher itself sends on is outside RAVEL and is not in the row.
Provider dispatch without a run root records under
`$RAVEL_STATE_DIR/prompt-log/<session digest>/prompt-receipts/`, with `rootless`
and `recording_session_id` on each row. The default state directory is
`~/.local/state/ravel`; hosts without a session ID use a process-local identity.
Pass that session folder as `--rundir` to export it. Run exports do not absorb
unrelated session folders. The worker census (`ravel.workflow.worker_audit.build`) records coverage alongside the prompt receipts.

The generated source census accompanies the Markdown export. It extends the
repository AST agent-path checker with host dispatch and process sinks. An
unmapped call site is a gap, and the shipped source has none: every spending
site maps to a collected record. This syntactic inventory must not authenticate
external implementations, prove absent dynamic calls or supply missing telemetry.
Hook-only prompts remain visible with unknown usage; completion notifications
must not establish the original prompt submission time. Zero-gap conformance
requires qualified runtime records, exact reported builds and complete usage.

Programmatic consumers use
`ravel.workflow.prompt_log.build(rundir, transcripts=(), price_table=None)`
and `ravel.workflow.prompt_log.write(log, out)`. The build result has `rows`,
`totals`, `gaps`, `complete` and `call_site_census`. Output creation refuses to
overwrite an existing export.
