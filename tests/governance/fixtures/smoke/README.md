# Smoke regression fixtures (derived from the real-host smoke)

The minimal inputs of the 8 sealed runs of the real-host engineering smoke `smoke-claude-2.1.281-a`
(docs/development/evaluation-study/smoke-record.md), for the evaluator regression cases in
`tests/governance/test_audit_smoke.py` (decision E-188). The store itself is ignored and was read, never modified.
The model outputs (final messages, report texts, claims) and the sealed verdicts are the real ones from
those runs; the evaluator canary, the broker secret and the artifact handles are synthetic.

| File | What it holds |
|---|---|
| `run-<n>-<task>-<arm>.json` | One run in launch order. `steps`: the subject's broker operations after the fixture setup (inputs, show, fit, convert, report, status, note, rejected and recorded submits), with every artifact handle replaced by a symbol (`current:<kind>`, `prior:<kind>`, `made:<custody seq>`); each recorded submission's claims, report text, refusal and final flag, and the guard diagnostics recorded for it; `final_text`, the subject's final message. `sealed_verdicts`: the sealed judge report's cells and findings (scorer `bfc208b33ef1`), kept as the smoke's record. |
| `tasks.json` | Per task (lf-b, lf-d): the smoke's version 1 task definition and oracle, with the evaluator canary replaced by a synthetic one (and the definition's `oracle_sha256` recomputed); the current title text; the kernel's recorded stage contents (fit, conversion, report) by input digests. |
| `replay.py` | `campaign()` builds a synthetic builder campaign (fixtures/sealed/builder.py, its own synthetic broker secret) from these tasks and the development family's input bytes; `replay()` rebuilds and seals one run. |

Kept out: host configuration and host state, streams, stderr, proxy logs, prompts, the campaign secret, custody MACs,
the subject's other output files (notes, report copies) and anything credential-shaped. Every file is under 200 KB.
The note operations are replayed without their text (the evaluator reads none).

With the pre-repair evaluator (scorer `053dc6d3cde6`, the merged evaluator at 950ede1, whose verdicts on the smoke
equal the sealed ones), the replay reproduced every sealed judge report exactly: the same findings in order, status,
unsupported_claim, refusal_valid and unresolved counts, for all 8 runs. This was checked once, before the E-188 repair
(recorded in that commit's message).
