# Sealed-run fixtures (SYNTHETIC)

Everything here is a **synthetic software-test fixture** for the independent evaluator
(`benchmarks/governance/audit.py`, WP11). Nothing is agent evidence, an empirical record or an
approval; no model was called and no event was generated.

`builder.py` assembles, by hand and in a temporary directory, a synthetic campaign (fake host,
the four `likelihood_freshness` development tasks, one seed, four arms) through
`campaign_manifest.write_campaign`, and sealed runs in the layout binding for the runner and the
evaluator:

```text
<store>/synthetic/<campaign_id>/
  evaluator/<run_id>/oracle.json, task_definition.json
  runs/<run_id>/sealed/run.json, prompt.txt, treatment_manifest.json, adapter_result.json,
                       stdout.jsonl, stderr.txt, final_text.txt, launch.json,
                       broker/custody.jsonl, broker/artifacts/<handle>.json, subject_output/...
  runs/<run_id>/evidence_manifest.json   canonical.tree_manifest(sealed/)
```

Custody lines and artifact records follow `broker.py` (coordinator `register_inputs` and
`create_prior` lines, then subject operations; handles are an HMAC with a fixed synthetic
secret). The guard record of every `submit` line is produced by `guard.evaluate` and applied as
the broker applies it; a scenario may override the diagnostics (the synthetic false block).
Stage artifact values are the oracle's values times a synthetic kernel skew of 2e-5 (inside the
kernel's root-precision contract), so every supported claim exercises the match tolerance.
Oracle numbers come from the family's own oracle records.

`Run.seal_interrupted` reproduces the in-progress runner's seal of a coordinator-interrupted run
(`runner._seal`/`_host_files` on branch eval/runner): `status_hint: interrupted`, no
`adapter_result.json` (unless the host wrote one before the coordinator died), empty raw streams
flagged `raw_streams_missing`, `launch.json` with null exit code, timing and wall time (and null
argv, environment names, working directory and timeout when the launch call was not recorded),
and variants without a custody log or with a torn last custody line.
