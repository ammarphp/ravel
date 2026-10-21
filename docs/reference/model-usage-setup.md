# Usage-aware model setup

Run `ravel setup-models` before preparing a research run. A spending preset supplies
initial candidates from the editable model catalogue. Add a private account snapshot
and measured usage from comparable completed runs to choose a mixed allocation:

```sh
ravel setup-models --preset balanced --usage-context account-usage.json --prior-run prior-run
```

Repeat `--prior-run` for a per-tier envelope of measured demand. Setup reads the
controller's reconciled provider counters and uses the largest observed input,
cache-write, cache-read, output and request counts for each tier. `--prior-usage`
accepts an exported version-1 `model-cost` JSON record. Each record carries its
measurement status, complete disjoint token counts and reconciliation problems.
Partial or absent measurement keeps the selected preset and records an unknown
usage recommendation.

An account snapshot has this closed metadata-only structure:

```json
{
  "schema_version": 1,
  "kind": "model-usage-context",
  "observed_utc": "2030-01-01T00:00:00Z",
  "valid_until_utc": "2030-01-01T00:30:00Z",
  "expected_run_seconds": 3600,
  "accounts": [
    {
      "transports": ["worker-one", "worker-two"],
      "plan": "included",
      "windows": [
        {"unit": "tokens", "remaining": 500000, "resets_utc": "2030-01-01T04:00:00Z"}
      ]
    }
  ]
}
```

Use transport identifiers from the installed declarations, current timestamps and
the provider's reported remaining capacity. Group transports sharing an account
in one row. `plan` is `included`, `metered` or `local`. Window units are `tokens`,
`requests` or `usd`; every simultaneous window applies to the shared account's
aggregate demand. Token and request amounts are whole counts. A null remaining
amount or reset timestamp records unknown capacity. Keep snapshots private and
refresh them within their declared validity interval. Supply plan and quota metadata
through these fields; keep authentication material in its existing credential store.

Setup compares the preset and catalogue-derived alternatives across model tiers.
It checks every account's recorded capacity, then ranks scenarios by known capacity,
reset-window pacing, retention of preset models, projected metered cost and preset
order. Funded preset models retain their priority; catalogue alternatives resolve
capacity pressure. The paced share is
remaining capacity times the smaller of one and the ratio of expected run duration
to time until reset. Resets contribute timing information; capacity comes from the
recorded remaining amount. Included and local plans contribute their recorded
capacity, while metered plans also use catalogue token prices.

Every proposed allocation passes the effective role cards' capability, tier and
effort requirements. Current transport qualifications and protected dispatch checks
remain part of execution admission. The private `models-setup.usage.json` receipt
records input digests, the historical demand envelope, selected candidates, capacity
checks and unknown components. Its amounts are a prospective workload scenario;
actual run cost comes from the run's provider counters.

For installation followed by model setup, run:

```sh
bash scripts/setup/install.sh --setup-models --model-usage-context account-usage.json --model-prior-run prior-run
```

`--model-prior-usage` forwards an exported usage record. `--yes` chooses balanced
defaults, and setup follows a completed installation. Plan and dry-run modes retain
their inspection behavior. `--verify` on `ravel setup-models` remains the separate
operator choice for paid conformance qualification.
