# Run data classification and model transports

Before model dispatch, the trusted run launcher calls
`provider_policy.start(run, data_classification=declaration, input_pins=pins)`.
Alternatively, provision `inputs/data_classification.json` with the declaration
before starting the run. Graph specifications accept it as `data_classification`;
graph creation pins it before any node starts. Existing runs bind the policy on
their first guarded dispatch. Provision it before starting workers or preparing
external answers. Nested graphs inherit their enclosing run's policy.

The declaration has a level (`restricted`, `internal`, or `public`) and an exact
transport/account allowlist. For example, this configuration admits only
Anthropic routes using the account distinctions in the shipped declarations:

```json
{
  "level": "restricted",
  "allowed_providers": [
    {"transport_id": "http-anthropic", "account_class": "env:api"},
    {"transport_id": "claude-cli-worker", "account_class": "login:subscription"},
    {"transport_id": "claude-cli-oneshot", "account_class": "login:subscription"}
  ]
}
```

Each entry admits only that route and account class. An empty list denies all
model calls, including at level `public`. With no declaration, existing public
behavior continues. A boolean `restricted: true` on an input pin requires an
explicit restricted declaration before graph start or worker/model dispatch.
Graph artifact pins and worker input pins preserve this optional field.

Account classes default to `auth.kind:billing`. This distinguishes login and
API routes without asserting tenancy. A custom transport declaration may supply
an explicit `account_class`, such as `organisation-api` or `enterprise-tenant`.
The operator must verify its configured account: RAVEL does not independently
attest the organisation or tenant. Transport identity includes this declaration.
API dispatch also checks that its effective credential kind matches the route.
Unlabelled transports cannot send declared-run material.

`provider_policy.check(run, transport_declaration, account_class)` returns the
admitting entry or raises `PolicyRefused`. Worker preparation, CLI one-shot
invocation and provider/command host dispatch enforce it before process launch,
token commands or network activity. `cli_agent_host.invoke(..., rundir=run)`
binds direct callers; managed host calls and prepared external requests carry
the run location in `context.provider_policy_run`, which the launcher removes
before any prompt, provider body or request digest. A refusal identifies the
classification and the attempted transport. Selection never retries another
provider after this refusal.

`<run>/provider-policy/pin.json` retains the initial declaration and approval history.
Editing or deleting the declaration cannot replace its pin. To change it, an
operator supplies `provider_policy.approve_change(run, declaration, record)`.
The record requires exactly:

```text
kind: provider-policy-approval
approved: true
authority: human
approved_by: <operator identity>
approved_utc: <approval timestamp>
reason: <actual approval reason>
previous_sha256: <digest of the current policy record>
replacement_sha256: <digest of the replacement policy record>
```

A policy record is `{"data_classification": declaration, "declared": true}`;
`provider_policy.start(run)` returns the current record. Hash with
`transport_registry.digest`. The initial implicit record instead has
`declared: false` and `{"level": "public", "allowed_providers": null}`.
Record an actual operator approval; model output does not establish one.
These records use the trusted launcher's filesystem authority, like other
local approvals; they do not authenticate against an operator editing all files.

Receipts carry `data_classification`, `declared`, `admitted_entry`, and
`policy_sha256` together. One-shot receipts store them under
`configuration.provider_policy`; worker and provider model receipts use
`transport.provider_policy`. Worker prompt audits include the same record.
`provider_policy.prompt_log_fields(receipt)` returns the common per-row fields
for prompt-log consumers. Historical receipts without these fields return an
empty projection. Consumers must preserve the distinction between historical
absence and an observed implicit public admission.
