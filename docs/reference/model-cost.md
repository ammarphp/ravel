# Measured model costs and envelope recalibration

The controller status and receipt evidence expose `model_cost`, attributed by
role, selected tier and observed model from the latest `provider-counter` census.
Missing prices or incomplete census coverage leave totals unknown; the priced
part remains separately labelled. These views do not refresh the counter or
write a cost record. Explicit `model_cost.record(store)` persists a changed view.

After collecting completed runs, inspect proposed envelope calibration with
`ravel models calibrate --runs <run-id> ... --check`. This prints the measurement
and diff and exits 1 when an update is proposed. Categories require five valid
sessions; smaller populations retain the installed values. Percentiles use
linear interpolation at positions `(N - 1) * p` for 20%, 50% and 80%, rounded up.
Output per call requires a positive observed call count. Price rates use token-weighted
catalogue means and retain the installed reference if any session is unpriced.

Run the same command with `--write` only in a source checkout, then run
`scripts/maintenance/build_engagement_envelopes.py` followed by
`scripts/maintenance/build_engagement_envelopes.py --check`. The command reads
run ids from the operator's controller store and creates no run state.

Per-category measured output rates and the installed scalar format both feed
the envelope projection. Missing census coverage and catalogue prices remain
explicit; reservations and forecast ceilings are separate from measured usage.

Missing observed model identities remain unpriced even when the requested model is known.
Mixed-model session totals also remain unpriced until the provider supplies attributable
per-model usage. Token counts come from supervisor captures; catalogue-priced dollar amounts
are list-price calculations on those measurements, not provider invoices. Unrecognized or
missing actual counters remain unknown. Protocols without an inference cache-write category
retain a typed basis for that zero; actual cache-read counters are still required.
