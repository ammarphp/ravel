# Recorded-run diagnostics

Before execution, the controller compiles `build_expected(route_spec, plan, engagement,
obligation_rows=...)`, then calls `pin_expected(store, expected)` and checks
`require_expected(store, plan_sha256)` at every execution boundary. The append-only
`diagnostics-expected` record is the authoritative expected-run document. Compilation
uses the computed engagement seat plan, effective instruction cards and manifests,
consequence classes, obligation instances and envelope bounds. Recompilation is
deterministic. A different design needs a prospective expectation, never a rewrite
of historical expectations.

`project_obligations` invokes the binding ledger interface against a disposable local
store seeded with the run's ledger records. Supply the planned intake, plan, dispatch,
review, check-in event and delivery contexts, including conditional and retry scopes.
The actual run is unchanged. The installed obligation catalogue supplies each row's
discharging node. Unknown applicability stays governed by the ledger's selector.

After or during a run:

```sh
ravel diagnostics report --run example-run
python -m ravel.controller.diagnostics report --run example-run --json
python scripts/diagnostics/report.py report --run example-run
```

The first command requires the shared CLI fragment in the integration record. Every
entry point applies the controller command policy before it opens a store. Reports
and adjacent JSON are content-addressed private files in the run store. Every record
retains its original id. The timeline reads only RunStore records and the store's own
graph event/checkpoint files. A seat's session records link to its dispatch through the
worker node id; instruction receipts and seat outcomes link through the seat key,
attempt and acting step. SQLite is opened read-only; no checkpoint payload is
executed or deserialised. Missing evidence is shown. A skipped row in an unfinished
run is provisional. Tool broker counts and model broker counts are separate; absent
model accounting is unknown. These diagnostics grant no authority or scientific credit.

Transcript capture defaults off. The operator must call `configure(store, canary=True,
capture_transcripts=True)` before execution to enable it. `capture_transcript` accepts
the local worker stream and its seat/role identity, writes private local files, and
returns a store record id. Normal runs refuse this configuration. `receipt_section`
records whether capture was on, its record ids, all enabled/injected faults and their
responses. No transcript text is printed by a report.

Fault injection also requires prospective configuration, for example
`configure(store, canary=True, faults=['missing-input'])`. `inject_fault` sends a bounded
fault descriptor to an explicit local execution-boundary callback. The callback must
exercise the ordinary guard and return a reference to the recorded response. No
callback result or missing response counts as detection by itself. Each fault lists
the typed responses that count: a held step for a missing input, a held step or the
tool broker's refusal for an outside write or a forbidden source, and an escalation
for a stalled tool. The diagnostic module itself never performs the forbidden action
or launches a hanging process. Canary transport qualification remains a separate
coordinator operation. Synthetic tests use inert boundary fakes.

All diagnostic implementation and commands are local and contain no network client.
