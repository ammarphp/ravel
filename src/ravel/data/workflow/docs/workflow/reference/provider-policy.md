# Classified inputs and network access

## Classify supplied inputs

```bash
ravel transport list
ravel transport show <transport-id>
```

Select a transport and account cleared for the supplied data. Record their exact identifiers
in `policy.json` using `level` (`public`, `internal` or `restricted`) and `allowed_providers`:

```json
{
  "level": "restricted",
  "allowed_providers": [
    {"transport_id": "<cleared-transport-id>", "account_class": "<cleared-account-class>"}
  ]
}
```

```bash
ravel drive --request-file request.txt --input <path> --input-classification policy.json --rundir <new-run>
ravel ask --input <path> --input-classification policy.json "<request>"
```

The classification applies to every `--input` in the invocation. Supplied files inherit an
explicit project default; otherwise they start `restricted` with an empty provider allowlist.

Run policy combines supplied-input and project clearances using the strictest level and
provider/account intersection. Derived artifacts and child workers inherit that frozen policy.
An empty allowlist holds all model calls. Runs with zero supplied files and zero explicit defaults retain implicit public policy.

## Set a project default

```bash
ravel agent-surface install --project <project>
ravel agent-surface check --project <project>
```

First save the declaration above as `<project>/.ravel/data_classification.json`.
Installation retains its declaration marker; `check` reports the effective classification and provider clearance.

New runs inherit project defaults. Nested defaults intersect clearances and select the strictest
level. Existing runs retain their frozen restrictions; tighter defaults require a compliant operator amendment.
Keep the original project declaration available throughout the run.

## Network destinations and private-service grants

```bash
ravel doctor
```

Check transport qualification before selecting a route. Trusted acquisition admits public HTTPS
origins with globally routable DNS answers and verified TLS; each redirect receives the same destination checks.

Acquisition connects to an admitted numeric address using the original TLS hostname and bypasses
ambient proxies. Destination admission applies alongside each source's access requirements.

For `DestinationRefused`, use a public HTTPS origin. Private-service acquisition grants require
separate transport qualification with an operator grant scoped to the origin; this release holds that route.

For `provider_endpoint_confinement_unavailable`, use a cleared trusted HTTP transport.
Restricted and internal data require qualified destination confinement; worker CLI probes  establish port scope.

See [private runs and explicit sharing](../run-directory.md#private-runs-and-sharing) for delivery exports.

## Local resource limits

For generic local launches, `memory_mib` limits each Linux process address space, not aggregate RSS.
Requests for `aggregate_memory_mib`, `processes` or `disk_mib` hold with `resource_limit_unsupported`
before staging or execution. Use a qualified adapter that covers descendants, retained failed attempts,
input copies, staging and scratch, with space reserved for receipts. The generic local launcher has no
aggregate sampler or filesystem headroom reservation.
