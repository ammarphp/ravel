# Model transports

The Claude login route checks owner-provided file metadata and the CLI's prompt-free
status before each attempt. Renew the dedicated login with
`CLAUDE_CONFIG_DIR=/absolute/login-directory claude`, then `/login`. Use the owner's
own setup step to make that login available as a private regular file in the worker's
configuration home. The typed refusal names the required worker file. Worker failures
retain bounded, redacted error tails and the renewal remedy in their receipt and
qualification output.

A transport is a declared route from a RAVEL role to a model. RAVEL ships one JSON declaration per
route in `src/ravel/data/transports/`. You can add your own in `.ravel/transports/` in the project, or
in any directory named by `RAVEL_TRANSPORT_PATH`. A user declaration that reuses a built-in id is refused, and a user
declaration claims neither blind review nor isolation above `cli-policy`: those need a shipped declaration.

```bash
ravel transport list              # every declaration, its billing, auth and probe state
ravel transport show claude-cli-worker
ravel transport probe --all       # probe every installed CLI
```

The default host configuration for the agent CLIs ships as
`src/ravel/data/transports/hosts/agent-cli.json` (`{"type": "agent-cli", "agent": "auto"}`); pass it
to any `--host-config` option to answer model requests with an installed agent CLI. `auto` resolves
when the host is configured: by the run preferences given as `"preferences"`, otherwise the first
installed CLI in the order claude, codex, antigravity, gemini. The host then carries that CLI's
one-shot transport and its declaration digest.

## Choosing models

Retain a passed transport qualification with `ravel transport qualify TRANSPORT
--rundir EMPTY_DIRECTORY --model MODEL --for-operator`. Each new controller run
adopts the authenticated operator record against the current declaration and
transport code identity. CLI routes bind their executable; loop routes bind the
interpreter and enforcing modules. Seat selection verifies the current probe
against that protected record.

Choose a spending preset with `ravel setup-models`. The `premium` preset favors
capability, `balanced` mixes capability and cost, and `economy` favors lower
cost. `ravel setup-models --yes` picks the balanced default; `ravel setup-models`
is also available as an alias.

```bash
ravel models detect --adopt --yes
ravel setup-models
ravel models estimate --preset balanced
```

Detection can adopt the available local configuration. Review model identifiers,
capabilities and prices in the local catalogue overlay at
`.ravel/models/catalogue.json`, or select an overlay with `RAVEL_MODEL_CATALOGUE`.
The overlay lets you maintain model information without editing shipped data.

The estimate is an uncached upper bound for the stated workload, not a bill or a
spending authorization. Actual usage can differ. Unknown prices stay unknown;
a missing price is never treated as zero. Model selection does not replace
transport probes, qualification or run cost ceilings.

## What a declaration says

| Field | Meaning |
|---|---|
| `transport_kind` | `cli-oneshot` (one judgment, no tools), `cli-worker` (tools in a workspace), `http-model`, `ravel-loop`, `external-relay`, `host-subagent` or `stub` |
| `launcher`, `argv_template` | The program and its exact arguments, with `{model}`, `{effort}`, `{schema}` and other placeholders |
| `models` | The model identifiers (or `{configured}`), their family and the tiers they serve |
| `auth` | `login` (the CLI's own login, no key), `env` (named variables), `command` (a token program run per request) or `none`; HTTP routes also name the header style |
| `pass_env` | The extra environment variable names visible to the child |
| `billing` | `subscription`, `api`, `local` or `none`; every `api` route needs a USD cap in the run ceilings |
| `capabilities` | Tools, structured output, isolation, attestation, blind capability, effort control, session id and usage report |
| `qualification` | `declared`, `stub_tested`, `probed` or `live_qualified`, with the record that shows it |

Declarations hold variable names, never values. A child process sees only the base environment
(home, path, locale, proxy settings) and the declared names. Every other `*_API_KEY`, `*_TOKEN`,
`*_SECRET`, `ANTHROPIC_*` and `OPENAI_*` variable is removed, as are `PYTHONPATH` and
`XDG_CONFIG_HOME`. Proxy URLs lose any embedded user name and password. Receipts record the names
that passed. `ravel agent-cli detect` runs each CLI's `--version` with that CLI's own environment.

## Probing

`ravel transport probe <id>` runs the CLI's `--version` and the `--help` of the subcommand the
template uses, and confirms every flag in the template. It never sends a prompt. The record is
written to `$RAVEL_STATE_DIR/transports/<id>.probe.json` with the CLI version, a digest of the help
text, the help exit status and the executable's resolved path and sha256. A CLI transport counts only
when a probe of its current declaration found every flag and both commands exited with status 0. A
missing flag makes the transport unusable, and selection names the flag.

The probe binds one executable. If the launcher on `PATH` is replaced or upgraded, its sha256 no
longer matches and the transport is refused as `probe:stale-executable` until you probe again. A
record that lacks any field of the probe shape is ignored. This also applies to an explicit
`executable` override at invocation.

Before executing even `--version`, probes refuse executables whose resolved path is under the run
(directory defaults to the current working directory), a project root, the system temporary directory,
or `$TMPDIR`. The refusal names the location class. Symlink targets are checked. The Python wrapper
requires `PYTHONPATH` to equal the source root exactly, or to be absent for an installed package.
The unit-test harness alone designates `RAVEL_TEST_TRUSTED_BIN`; it is ignored outside a test lock
domain (which only the test harness selects) and is not an operator trust mechanism.

A same-user process can still write the probe record. Operator-path separation, including host and
receipt registration, is not provided yet. These checks do not establish separation from other
processes running under the same account. The same holds for the dispatch evidence behind
independent review credit (`review_dispatch`): the worker dispatcher's launch custody and the graph
runner's completion records lie outside the run tree and every worker sandbox, so neither a reviewer
nor an agent editing run files can write them, but an unsandboxed process of the same account can. A
host controller with a stronger boundary installs its own resolver with
`review_independence.authority_session`.

Help text shows that a flag exists, not what it does. A probe confirms structured output and effort
control only when the flag carrying `{schema}` or `{effort}` is present. It never confirms tools,
isolation, attestation or blind capability. A `ravel-sandbox` or `os-sandbox` claim counts only for a
shipped, `live_qualified` declaration on a host with a sandbox backend; until then it counts as
`cli-policy`. A declaration is `live_qualified` when it ships that status, or when a stored
qualification record (below) matches its current declaration, probe and executable.

A CLI worker route needs its adapter and a sandbox backend (`sandbox-exec` on macOS, `bwrap` on
Linux); without the backend it is refused as `sandbox_unavailable`. The adapter covers the Claude
Code routes (`claude-cli-worker` and its `-apikey`, `-bedrock` and `-vertex` variants) and
`codex-cli-worker`. Other worker declarations are refused by name: `codex-cli-worker-apikey` and
`gemini-cli-worker` as `cost_unenforceable:<id>` (an API-billed route needs a cost ceiling, and only
Claude Code enforces one), `codex-cli-worker-azure` until its Azure provider configuration is generated,
`antigravity-cli-worker` as `worker_surface.mcp:probe_required` (its MCP loading is unconfirmed),
`opencode-worker` and `qwen-worker` as `adapter:<launcher>`, and `codex-oss-worker` as
`worker_surface`. The RAVEL HTTP loop has a worker adapter on the same governed path.
Its declaration must supply an endpoint, supported authentication and a wire format; an API
loop also needs catalogue limits/prices and an explicit cost ceiling. Controller admission,
host executor availability and current qualification remain separate checks; inspect the
code-generated `controller.step.seats.wired_transports()` inventory for exact exclusions.

## Selection

The run's preferences (`inputs/agent_preferences.json`, fingerprinted at CHECK-IN 1) list
transports in order for each role family and name the model per tier:

```json
{"schema_version": 1, "kind": "agent-preferences",
 "families": {"specialist-review": ["claude-cli-worker", "http-responses"]},
 "tier_models": {"judgment": {"claude-cli-worker": "<model id>", "http-responses": "<model id>"}}}
```

RAVEL takes the first transport whose declared and probed capabilities meet the role card's
`requires`. When none does, it refuses before any process starts and names what is missing:
`tools`, `structured_output`, `isolation`, `attestation`, `blind`, `tier:<tier>`, `model:<tier>`,
`probe`, `local_only` or `local_models`, and also `qualification`,
`effort`, `model:family`, `model:family-unbound`, `probe:<flag>`, `probe:stale-executable`,
`unimplemented:<kind>` or `local_only:cloud-model`. Nothing is downgraded: a card that asks for an
effort on a route that carries no effort setting is refused with `effort`.

The model comes from `tier_models` for the role card's tier. A card whose `model.cheap_ok` is true
(mechanical roles such as encoding, naming, sanitising, document compilation and convention
translation) uses the `cheap` tier instead whenever `tier_models.cheap` names a model for that
transport; otherwise it keeps its own tier, and every other card ignores the cheap mapping. The
selection records the effective `tier`, the card's own `card_tier`, and a `catalogue` label:
`catalogued` when the model catalogue (`src/ravel/data/models/catalogue.json` plus any overlay)
lists the model, `uncatalogued` when it does not, `unavailable` when the build has no catalogue.
The label never refuses a selection.

A model named in `tier_models` must be a declared id, or fit a `{configured}` entry of the same
family. It must also be a row of the model catalogue: `ravel operator init|set --agent-preferences`
refuses a model the catalogue does not list, with one remedy line per model and exit status 2,
before writing. `ravel models detect --adopt` or a row in the catalogue overlay admits a new model.
A model whose identifier does not reveal its family needs an explicit binding in
`"model_families": {"<model id>": "<family>"}`. Review roles (critic, verifier, decider, plan critic,
or any blind card) run with the route's full tools in an isolated workspace. Their independence comes
from the sandbox and the isolation of user configuration, not from withholding tools. On a CLI or
host route a voting role therefore needs a sandbox-isolated worker: a one-shot or host subagent under
the CLI's own tool policy (`cli-policy`) is refused with `isolation`. A shipped sandbox worker that
lacks only its live qualification is refused with `qualification`. Stateless HTTP routes remain
admissible. A voting role also refuses a route whose qualification is still `declared`.
`local_only` admits only locally billed HTTP routes with a loopback endpoint; CLI routes have no
verified local destination, and a `:cloud` model id is refused.

A blind role runs only on a stateless HTTP route, the RAVEL loop, the external relay, or a CLI
worker isolated to its workspace (`ravel-sandbox` or `os-sandbox`). A CLI one-shot relies on the CLI's
own tool policy (`cli-policy`), so blind roles go to the routes above.

Selection never compares model families. Any family serves any role, including a reviewer of the
author's own family: review independence rests on separate observed sessions and artifact-only RAVEL
packets, which the credit decision verifies on the delivered roles. The selection records the chosen
model's family, and a credited review seat carries a label stating that the sessions were separate
and whether the two families coincide, differ or are unknown. `check_distinct_families` returns that
label and never refuses. The card field `model.distinct_family_from` is retired: every shipped card leaves it
empty, and nothing reads it as a requirement.

A seat of a run the controller owns is selected in controller mode. Only the installed package's
declarations count (`$RAVEL_TRANSPORT_PATH` and a project's `.ravel/transports` add nothing); the
external relay, host subagents and one-shot CLIs never fill a seat (`controller:<kind>`); and a CLI
worker's live qualification counts only with protected controller evidence. The operator-run
qualifier appends its full successful observation with `record_qualification(store, record)`;
selection receives `store_qualifications(store)` through its `qualifications` argument. Review
preflight reads the same store. This path never reads the same-user qualification file, and a
declaration labelled `live_qualified` alone grants nothing. A digest register
(`register_qualification`, `registered_qualifications`) is a narrower alternative: a qualification
file in the same-user state counts only while the operator's register names its exact digest.
Incomplete or failed conformance steps, changed probes or executables, and absent confinement
keep the seat unfilled. A software control with synthetic observations does not qualify a host.

### Review seats on a host without the OS worker sandbox (operator fallback)

Without `sandbox-exec` or `bwrap` a review seat holds (`worker_sandbox_unavailable`, labelled
`INDEPENDENT REVIEW INCOMPLETE`); the driver never reviews its own work instead. The operator can
configure one fallback for later runs: `ravel operator set --review-sandbox-fallback
restricted-unsandboxed` (default `none`). It is frozen into each run at intake, and a child run can
only keep or drop it. Under it, and only for a review seat on a host with no sandbox:

- selection admits the restricted Claude CLI worker (no built-in tools, the broker's toolbelt only)
  with isolation `cli-policy` and no blind capability. Only the requirements the sandbox enforces
  (`isolation`, `blind`) are relaxed, and the selection names them under `sandbox_fallback`. Every
  other requirement still applies, including the controller-recorded live qualification;
- the worker starts without the OS wrapper. Its inventory probe runs the same way and compares the
  served tools and the environment. The writable set and the network are recorded as `unconfined`,
  with what the probe actually reached kept beside them. The issuer-key exposure of a same-account
  process is recorded, not treated as denied;
- the store records each such seat (`review-sandbox-fallback`). The receipt's isolation evidence is
  unconfirmed, so the blind-confinement row (V04) stays unmet. The sink labels the delivery
  `REVIEW WITHOUT OS SANDBOX (OPERATOR-CONFIGURED FALLBACK)` and refuses acceptance
  (`review_unsandboxed`), so the delivery is qualified.

A fallback review is machine review whose only confinement was the CLI's own policy. It is never
recorded or labelled as human review. Producer and other non-review seats still hold without the
sandbox.

## CLI workers

`ravel.workflow.transports.cli_worker.prepare_launch(rundir, spec, workspace)` builds the launch
descriptor the worker dispatcher runs. It selects the route from the spec's preference list and the
run's `inputs/agent_preferences.json`. It refuses any route that is not a `cli-worker` and never falls
back to a one-shot. Every refusal names what is missing, and the dispatcher writes a `refused` receipt
without starting a process. The descriptor holds:

- the declaration's argv filled with the selected model, effort and the code-owned final-record
  schema, and the executable path from a current probe whose sha256 still matches;
- the broker MCP configuration from the declaration's `worker_surface.mcp` row. The CLI's only tools
  are the card's toolbelt served by `ravel work mcp`, so every tool call is a broker call with a
  receipt. Claude runs with `--tools ''` and `--allowedTools` naming only the `mcp__ravel__*` tools.
  Codex runs with `--sandbox read-only`, so its native shell and file tools are read-only. Review roles
  get the route's full toolbelt; blind roles keep only the workspace read and write tools;
- the toolbelt pinned by its manifest digest. The supervisor's broker comes from
  `tool_gate.production_broker`, the one factory every real worker broker uses (the host-subagent
  broker too). It allowlists exactly the toolbelt's actions, serves only its knowledge ops and installs
  the shared gate (`tool_gate.broker_guard`), so a call no toolbelt tool produces is refused with a
  receipt. A tool name outside the toolbelt reaches the broker as `tool:<name>` and never aliases an
  allowed action; a malformed call (a non-string name, non-object arguments) is refused with a receipt
  too. Knowledge calls have one argument shape, `{"op": <op>, "args": {...}}`, for the toolbelt and
  the handler alike;
- a private `<attempt>.cli-home` beside the workspace. External owner setup supplies its
  login files. RAVEL checks regular-file, owner, permission and link metadata and preserves
  those files during cleanup. The dedicated `CLAUDE_CONFIG_DIR` identifies the operator's
  login for the renewal remedy; the worker uses its own file-backed configuration home.
  The configured login directory retains its instruction, plugin and settings checks;
- for Claude Code, `USER` and `LOGNAME` from the password database;
- for Claude Code, `CLAUDE_CODE_TMPDIR` and `TMPDIR` set to the worker's own `scratch/tmp`. Claude
  Code ignores `TMPDIR` for its own temporary directory (`/tmp/claude-<uid>`), which the sandbox
  denies;
- provider network egress, described below.

### Provider network egress

On macOS the provider profile allows outbound TCP to port 443 only, name resolution through
`mDNSResponder`, and the TLS trust and security services the CLI needs. Every
other port is denied, and listening sockets stay denied. The sandbox denial probe runs under the
exact profile the child launches with (its private CLI home and network mode) and records `network:
tcp-443`. It checks that a listening socket and an outbound connection to a port other than 443 (on
the loopback address, so nothing leaves the machine) are both denied. On Linux, `bwrap --share-net`
leaves ports unfiltered, and the probe records `network: unrestricted`.

Hosts are not filtered. Domain-level filtering needs a RAVEL-owned proxy that only the sandbox can
reach; the shipped sandbox has no such proxy, so a worker can reach any server on port 443, and two workers
running at the same time could still collude through an outside server. RAVEL's isolation guarantees
cover the filesystem, the tools and the broker, not the internet.

### Receipt inputs and credited outputs

The supervisor reads the child's stdout and stderr through pipes into worker custody, outside every
directory the sandbox or the broker can write. The CLI envelope the adapter parses (final record,
session id, usage, turns) comes only from that copy; nothing in the workspace's `scratch/` is read.
Codex runs without `--output-last-message`: its final message is the last agent message in its JSON
event stream.

A declared output is credited only when an `ok` broker receipt of the same attempt pins its path and
its current bytes. A file a native tool wrote, or a pinned file changed afterwards, is never credited.
Generated Codex and Gemini worker configurations exclude native tools; conformance must verify
that the installed version respects the exclusions. Native output files never earn credit.

The workspace and every directory above it must hold no `CLAUDE.md`, `AGENTS.md` or `GEMINI.md`,
with one exception: the run's declared project instruction document and files that only import it
(see [Declared project instructions](#declared-project-instructions)). The
complete prompt is written to worker custody with an audit record (argv, environment names,
schema, toolbelt and MCP configuration digests) and reaches the CLI on standard input.

After the child exits, the adapter parses the CLI's JSON output. The final record, session id,
observed model, tokens, turns and cost go into the worker receipt. A turn count above `max_turns`, a
cost above `max_cost_usd`, or a Claude result without a turn count marks the budget exhausted and
fails the worker. An error envelope leaves no final record and fails it too. A Codex turn is a
`turn.completed` event, not a completed item. An API-billed route needs a cost budget. A route whose CLI
reports no cost (Codex, Gemini CLI) refuses a non-null cost budget as `cost_unenforceable`. The
receipt is `transport_attested` only with exit status 0, a session id unused by any earlier worker of
the run on that route, confirmed sandbox denials, no user configuration loaded and a declared
transport attestation; otherwise it is `host_attested`.

The host-subagent adapter (`transports/host_subagent.py`) serves RAVEL inside a host such as Claude
Code. It writes a brief for the host's own subagent and pins its toolbelt in custody, keeps the
broker open for `ravel work call`, and records the host-reported final record as at most
`host_attested`. The brief lists only tools the broker serves; the broker is the gated production
broker over the pinned toolbelt, and a brief whose tool list changed is refused as `toolbelt:changed`. Host routes are never blind-capable
and never serve a voting or blind role.

Live steering is decided at the handoff. The brief is refused (`steering`) while a pause, a veto
or a hold blocks the node, or when the run has no steering custody. RAVEL does not observe the
host's spawn and does not claim to serialize it. It admits the working window instead: opening the
broker takes the final steering check under the steering lock, writes the start acknowledgement
`<attempt>.host-start.json` in custody and keeps the subagent registered as running work until
the broker closes, so a later pause reports it as `draining`. Completion writes a receipt only for
an attempt with that acknowledgement and the same brief; a subagent the host started outside an
admitted window earns none.

### Live qualification

```bash
CLAUDE_CONFIG_DIR=<login-only dir> ravel transport qualify claude-cli-worker \
    --rundir <empty dir> --model <model id> [--effort <effort>] [--max-cost-usd <usd>]
```

`qualify` runs one fixed, generic conformance task through `prepare_launch` in the sandbox. The worker
reads `inputs/conformance.json` through the broker, writes its nonce to `outputs/conformance.txt`,
answers a fixed request to list every skill and tool available to it in `outputs/surface.txt`, and
returns a structured final record. The record is written only when every step passed: an `ok`
receipt, a valid final record, broker read and write receipts, the nonce in the output, a session id,
confirmed sandbox denials, no user configuration on a blind-capable route, a computed
`transport_attested` label, an unchanged executable and `surface_ravel_only`: the listing names at
least one tool and nothing beyond the RAVEL MCP tools (a toolbelt name, bare or as
`mcp__ravel__<name>`). A synced skill or a built-in tool in the listing fails qualification. The
record's `observed.surface` holds the fixed request, the reply's sha256, the names listed and any
unexpected names. It goes to
`$RAVEL_STATE_DIR/transports/<id>.qualification.json` with status `live_qualified`, the record path, the
executable, declaration and probe digests, the receipt path and digest, the observed model, session,
turns and cost, and the time. A new probe, a changed declaration or a replaced executable voids it.
The controller qualifier must additionally retain that successful observation in its protected
store with `record_qualification`; writing the same-user file alone does not qualify a controller
seat. The operator targets the existing governed run with `--controller-rundir <run>` while
`--rundir` remains a separate empty conformance workspace. Both review preflight and governed
seat selection read the full protected observation. The operator performs this live step on each
run host before admitting blind review work; inert qualification tests do not qualify a host.
Exit status 3 means refused before any process started; 4 means the run happened and named steps failed.
Pass `--rundir` as a real path: on macOS `/tmp` is a symlink, so use `/private/tmp/...`. A path through a
symlink is refused, and the refusal names the real path to use.

## Declared project instructions

A project can require that one instruction file reaches every agent on every prompt. A run declares
that file once, when it starts:

```
ravel project-instructions pin --rundir <run> --path <project>/AGENTS.md
```

The command writes `inputs/project_instructions.json` (the document's real path, sha256 and byte
count) and binds it in the run's custody ledger, outside the run tree. A pin file written or edited
by hand pins nothing: the next launch is refused.

From then on every session RAVEL starts for the run receives the document's text verbatim, ahead of
RAVEL's own instructions:

- **Workers.** The adapter puts the text at the top of the prompt it sends on standard input. The
  worker receipt records it in `transport.project_instructions`: `sha256`, `bytes`, `path`,
  `mechanism`, `flag`, `position` and `ambient`. The prompt audit holds the same record.
- **One-shot reviewers and answers.** A session belongs to the run that owns its graph or request
  file: the nearest directory above it that holds an `inputs` folder. The search stops at that
  directory. `answer` and `answer-graph` resolve the run this way from the request file, and an
  `agent-cli` host resolves it from the graph it executes and sends it to the launcher in the
  request field `project_run`. A request prepared for an external answer carries the same field,
  bound by the request digest, so a copy of the file answered elsewhere still receives the document.
  Every prepared request is checked against its own digest before a session starts; a copy with a
  field added, changed or removed is refused. Preparing a request is refused while the run's pin is
  invalid (`project_instructions:pin-removed`, `pin-changed`, `pin-not-in-custody`): an invalid pin
  is never read as a run that declares nothing. `ravel agent-cli serve|answer|answer-graph --rundir <run>` and the
  host config key `"rundir"` name the run for a graph or request that lies in no run. A configured
  run that differs from the graph's own run is refused. A run nested under another run's tree that
  pins nothing is refused with `project_instructions:run-ambiguous` until `--rundir` or the host
  config key `"rundir"` names it; the outer run's document never reaches it. A request prepared in
  such a run carries the field `project_run_unresolved` with that run's directory, and it is
  answered only when `--rundir` names the same run. The session receipt names the run the session
  was started for in `configuration.project_run`, and the isolation block carries it as
  `project_run`. The graph's receipt check uses that name the same way the dispatch did: it settles
  the nested run only when it is the graph's nearest run. The session receipt records the delivery in
  `configuration.project_instructions`, and the isolation block carries `project_instructions`
  (`sha256`, `bytes`, `mechanism`) and says in `basis` that RAVEL supplied one declared document. The
  document is declared project text. It is not user configuration, and `user_configuration_loaded`
  keeps its meaning. The launcher reads the run's declaration again immediately before it creates
  the CLI process: a pin resolved earlier, a document changed while the launch was assembled, or a
  run pinned in the meantime refuses the launch and nothing starts.
- **Host subagents.** RAVEL writes no prompt for a worker the host starts. The brief
  (`inputs/host-brief.json`) carries the text in `project_instructions.text` with the line that
  tells the subagent to read it first and to report the document's sha256 with the final record.
  The worker receipt records the brief with the mechanism `work_packet` and the reported sha256 in
  `host_acknowledged_sha256`. Writing the brief is not delivery: RAVEL starts no process and sees
  no prompt. The host passes the report to `host_subagent.complete(..., instructions_sha256=...)`,
  and the receipt shows delivery only when that sha256 is the pinned one. Without it the check
  answers `project_instructions:unobserved` and the session is not credited.

Only the RAVEL `agent-cli` launcher delivers the document; an HTTP model route and any other command
host leave it undelivered. For a graph whose run pins a document, such a host refuses every model node before any
request is sent. The RAVEL loop also leaves the document undelivered: it reads the declaration before
every model turn and sends nothing for a run that pins a document. Workers of such a run go through
a CLI worker transport.

**Mechanism.** `mechanism` is `prompt_first_block` for every shipped CLI route. A route whose
`argv_template` carries the placeholder `{project_instructions_file}` behind a flag, and whose probe
confirmed that flag, gets `system_prompt_append_flag` instead: the text is written to a read-only
file and the flag names it. Without a pin, the flag and its value are dropped from the argv.

**A run inside the project.** When the worker workspace sits under the folder that holds the
declared file, the launch accepts two kinds of instruction file above the workspace: the declared
document itself, with the pinned sha256, and a file whose whole content is one import of it (for
example a `CLAUDE.md` that holds only `@AGENTS.md`). `ambient.ancestor_files` lists each accepted
file with its relation (`declared` or `import`) and sha256. `ambient.cli_reported_loaded` is `true`
or `false` when the CLI's own configuration report says whether it loaded an instruction file, and
`null` when the CLI's output carries no such report. Every other instruction file, a companion file
with any text besides the import, a symbolic link and every project configuration directory
(`.claude`, `.codex`, `.gemini`, `.agents`) are refused as before.

**A run that declares nothing.** Without a pin, an instruction file above the workspace is refused
when it exists. A symbolic link that points to nothing supplies no text and is ignored, as before.
Under a pin every instruction file above the workspace, a dangling link included, must be the
declared document or an import of it.

**The document is fixed for the run.** When the file's sha256 differs from the pin, the next launch
is refused with `project_instructions:changed` and the message names the command that re-pins it:

```
ravel project-instructions repin --rundir <run> --approved-by <who approves> --statement "<why the text changed>"
```

Preparing a launch does not fix the document. The dispatcher reads the declaration again before it
starts the supervisor, and the supervisor reads it once more immediately before the worker process
starts. A document changed in between, a re-pin in between, or a prepared launch without the
delivery record is refused (`transport_refused`, with the item in `failure.missing`) and no process
starts. Both checks also read the instruction files above the workspace again and compare them with
`ambient.ancestor_files`: a companion file edited after preparation, a new instruction file or a
removed one refuses the launch with `project_instructions:ancestors-changed`. A session that never started has `transport.project_instructions` equal to
`{"status": "not_started"}`: its receipt does not say the document was delivered.

A re-pin needs both the approver and the statement. The approval and the sha256 it replaces are kept
in the pin and in the custody ledger. `ravel project-instructions show --rundir <run>` prints the
pin and whether the document still matches it.

**Kept prompt and kept text.** A successful one-shot session keeps its exact prompt beside its
receipt: `answer` and `answer-graph` write `<response name>.receipt.prompt.txt` next to
`<response name>.receipt.json`, and an `agent-cli` host writes `<record name>.prompt.txt` next to the
session record under `transport-receipts/`. The file is created once and holds the text that hashes
to `content.prompt_sha256` of the receipt; a text with another digest is never written. Each pin
also copies the document's bytes into the run's custody folder as
`project-instructions.<sha256>.md`. A re-pin or an edited file therefore removes neither an earlier
prompt nor an earlier document text; `project_instructions.retained_text(run, sha256)` returns the
text of any document the run pinned.

**Live qualification with a document.** `ravel transport qualify <id> --rundir <empty dir> --model
<model> --project-instructions <document>` pins the document for the conformance run and adds the
step `project_instructions_recorded`, which passes only when the worker receipt shows its delivery.

**Credit.** A run that pins a document credits only sessions whose receipt shows the pinned sha256.
The worker dispatcher adds the computed check `project_instructions` to the receipt outcome, and a
receipt that fails it has no credited outputs. The review-credit check refuses such a receipt with
`project_instructions`. `project_instructions.receipt_problem(receipt, pin)` gives the same answer
for a worker receipt and for a one-shot session receipt. The same comparison runs on the two
one-shot paths. The `agent-cli` host keeps the session record and fails the node when the
launcher's receipt lacks the record or names another document. `agent_graph.role_receipt` and
`model_receipt` refuse a completed review of a graph whose run pins a document when the session's
isolation evidence does not name that document. A review answered before the pin, or under a pin
that was replaced afterwards, therefore earns no receipt. A run without a pin has no such check,
and its receipts keep their earlier bytes.

## User configuration and independence

| CLI | How RAVEL keeps your own configuration out | Model tools | `user_configuration_loaded` |
|---|---|---|---|
| Claude Code | One-shot: `--setting-sources project --safe-mode --strict-mcp-config --tools ''`. Worker: `--setting-sources project --restricted --strict-mcp-config --tools ''` plus `--allowedTools` for RAVEL's tools, in an empty directory. Not `--bare`, which drops the subscription login. Admin-managed settings stay in force; their digest is recorded | none | `false` |
| Codex | A fresh `CODEX_HOME` per call holding a copy of `auth.json` and a generated `config.toml`. Workers additionally disable native shell, patch, collaboration, app, image and web tools; the read-only sandbox refuses native writes | workers: broker tools after qualification; one-shots: native read tools | `false` |
| Antigravity (`agy`) | A fresh `HOME` holding only the Google login files; the working directory is empty. No flag excludes other configuration | read tools | `true` |
| Gemini CLI | A fresh `HOME` holding authentication material; `~/.env` and `~/.gemini/.env` are excluded. Workers generate core-tool exclusions and an empty context-file list | workers: broker tools after qualification; one-shots: native read tools | workers: `false` when exclusion is established; one-shots: `true` |

Extra arguments come from a closed allowlist (for Claude, `--verbose`; for the others, none). Any
other argument is refused before launch, naming whether it repeats a template flag or can re-enable
tools, permissions or configuration. The model id must match `^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$`
and the effort must be one the CLI accepts; anything else is refused, never dropped. Gemini CLI has
no effort flag, so its receipts record `effort.transmitted: false`.

A CLI that reports loaded memory, plugins or MCP servers (Claude's `stream-json` init event, Codex
configuration events) sets `user_configuration_loaded: true`. Claude's plain `json` result carries no
such report, so its value there derives from the isolation flags, and the receipt says so. An answer
with `user_configuration_loaded: true` is not a fresh context and is never counted as independent
review. `ravel agent-cli answer` refuses a critic or verifier on a route with model tools or without
transport attestation (the Codex, Gemini CLI and Antigravity one-shots) before any process starts.

External owner setup manages login files and renewal for each private configuration home.
The launcher generates the CLI configuration and records its identity.

Antigravity takes the prompt as an argument, where other local users can read it in the process list.
The prompt must fit in what `ARG_MAX` leaves after the environment; the receipt records
`prompt_in_argv: true` and the prompt's digest, never the prompt.

CLI errors name an error code, the exit status and the size and digest of stderr. The CLI's own
error text is never shown, because it can echo credentials. Output above the byte bound stops the
CLI and every member of its process group.

## Session receipts and attestation

The agent-cli launcher (`ravel.workflow.cli_agent_host serve`, the command the `agent-cli` host
config builds) writes a session receipt for every call. It holds what the launcher itself observed:

- the transport id, declaration digest and origin, qualification status and probe digest;
- the executable's path, sha256 and `--version` from this run;
- the digest of the exact argv including the executable (the prompt is replaced by its digest), the
  environment names, the HOME mode, the dotenv files left out and the working directory;
- the process id and group, start and finish times, exit status and stdout/stderr digests;
- the request, prompt and value digests, the requested effort and whether argv carried it;
- the effective tools and isolation, refused overrides and the managed-settings digest.

What the CLI says about itself (session id, model, usage, configuration events, the Codex rollout
digest) is kept apart under `cli_reported`. A missing session id is `null`; the launcher's own
`host_invocation_id` is a separate field.

AgentHost accepts a receipt only when its command is exactly that launcher for the host's own
transport, and refuses one whose transport, declaration, request, value or writer digest differs.
It writes the verified record create-only to `<graph>/transport-receipts/<request>-<attempt>.json`
and pins it in the node result. The CLI runs in the launcher's process group, so cancelling the host
call stops the CLI and anything it started. The attestation is computed, never copied:

| Attestation | When |
|---|---|
| `transport_attested` | A verified launcher receipt with a current probe of the executable that ran, transport attestation declared, no user configuration, no overrides, tools within the requested role policy, and a CLI session id used by no other session in the graph. The graph receipt's `execution_observation` is `transport_attested_cli` |
| `host_attested` | A verified launcher receipt that fails one of those conditions |
| `self_attested` | Every relay response, including schema 3 with a matching declaration digest, evidence printed by any other command, and receipts that fail verification |

A transport label must describe the executor: a `command` host carries only the label of the
launcher it runs, and an HTTP host only an `http-model` label whose endpoint and credential variable
match its own. The relay retains the full schema-3 evidence in the node result and refuses a second
critic or verifier that reuses an earlier CLI session id, whatever actor it names. The graph's agent
model receipt carries `attestation` and `session` (transport, CLI session id and receipt pin); it
re-reads and re-checks the pinned record each time. Relay labels are recomputed from the stored
response schema and evidence, never copied from `transport.attestation`. A declaration digest records
which transport was claimed; it does not authenticate response authorship. Relay isolation therefore
always records `independent: false`.

Scientific judgment rejects computed `self_attested` receipts for critic, verifier and synthesizer
votes: "self-attested review is advisory; it does not count as independent". Explicit `allow_control`
software controls and nonvoting context/evidence requests retain their advisory paths. A relay is
not a human-review channel, and no transport label records human review.

A request can carry `role_requires: {"tools": "broker-readonly"}` (default `none`). The launcher
records `configuration.tools_required` beside `effective_tools`, and AgentHost checks the recorded
requirement against the request before computing attestation. Effective tools above the requested
policy add a downgrade reason; equal tools do not. The order is `none`, `broker-readonly`,
`broker-full`. The caller supplies this policy; role cards leave it unset, so a caller that omits it gets
`none`. Voting status uses
`independence.kind == "voting"`; legacy voting/blind/name tests apply only without `independence`.

`research-cycle discussion-run` records the resolved absolute host-config path and digest in a
create-only `host-config-receipt.json` next to the discussion report, with that report's pin.
Host configs inside the research cycle remain refused.

Consumers bind to these fields, not to actor names:

- `agent_graph.role_receipt` returns `attestation`, `execution_observation` and `session`
  (`transport_id`, `cli_session_id`, `session_receipt_pin`). Read `attestation` directly; an
  observation-to-attestation table maps `transport_attested_cli` to `transport_attested` only when the computed label verifies.
- A session is identified by `<transport_id>:<cli_session_id>`. Count distinct sessions from these
  values, and treat a null session id as not distinct.
- The pinned record (`<graph>/<session_receipt_pin.path>`, sha256 in the pin) is a regular file inside
  the graph, so a run-level registry can register it by path and digest, as it does a worker receipt.

All processes run as you. A receipt detects forgery by a model or agent through the transport; it
does not stop your own processes from editing files. A machine receipt is never human or physicist
review.

## HTTP authentication

An HTTP host config names its credential in an `auth` block:

```json
{"type": "chat_completions", "endpoint": "https://<host>/v1/chat/completions",
 "auth": {"kind": "command", "command": ["/usr/local/bin/gcloud", "auth", "print-access-token"], "header_style": "bearer"},
 "capabilities": {"...": "..."}}
```

- `{"kind": "env", "env_name": "<NAME>", "header_style": "api-key"}` reads one named variable.
- `{"kind": "command", ...}` runs the token program once per request. Name the program by absolute
  path; a program that its group or others can write is refused. It runs without other providers'
  credential variables, and its output, read with a byte bound, goes only into the request header;
  errors report its exit status and nothing else.
- Endpoints carry no query string. Azure OpenAI works through its `/openai/v1/` endpoint; classic
  deployment URLs with `?api-version=` are refused with that guidance.
- A research cycle refuses a host config stored inside the cycle directory.
- Header styles: `bearer`, `x-api-key`, `x-goog-api-key`, `api-key`. A Bedrock mantle endpoint uses
  the `anthropic` adapter at its own path with `x-api-key`.
- `local_only` refuses a token command and any non-loopback destination.

## Model classes

`src/ravel/data/transports/index/model-classes.json` lists the worker and judgment routes for each
model class: Claude (login or key), GPT (login or key), Gemini (Google login through Antigravity, or
an AI Studio key), Vertex AI, Amazon Bedrock, Azure OpenAI, xAI Grok, OpenRouter and other clouds,
local tool-calling servers, local text-only models and custom fine-tuned models. A route's
qualification status says what has been shown; only `live_qualified` routes are called supported.

Token programs must be absolute regular files. Every ancestor through `/` is checked for group or
world write access, including the supplied symlink path and resolved target. Only root-owned sticky
directories are exempt; the program file itself must never be group/world writable.

## Why Claude workers use `--restricted`, not `--safe-mode`

`--safe-mode` starts Claude Code with every customization disabled, MCP servers included. A worker
reaches the workspace only through RAVEL's own MCP server (`mcp__ravel__ws_read`, `ws_write`), so
under `--safe-mode` the worker saw only `StructuredOutput` and live qualification failed
`broker_read`, `broker_write`, `output_nonce`, `surface_ravel_only` and `receipt_ok`.
`--restricted` removes the code-running tools (Bash, PowerShell, REPL) and WebFetch, ignores user,
project and local settings files, and keeps the MCP servers named by `--mcp-config` when
`--strict-mcp-config` is set. Claude worker declarations (`claude-cli-worker` and its API-key,
Bedrock and Vertex variants) therefore use `--restricted`. One-shot declarations have no tools and
stay on `--safe-mode`. The probe confirms each template flag in `claude --help`, so it requires
`--restricted`; changing a declaration changes its digest and stored probes must be re-probed.

Live evidence (Claude Code 2.1.296, real login): with `--restricted --setting-sources project
--strict-mcp-config --no-session-persistence --tools '' --allowedTools mcp__ravel__ping` and a
throwaway stdio MCP server named `ravel`, the worker reported "Tools: mcp__ravel__ping. No other
tools are loaded. Skills: none." and returned the tool's output. The account-synced skills in
`CLAUDE_CONFIG_DIR` did not load.


## Governed worker wiring

The controller selects from `controller.step.seats.wired_transports()`. Model setup and doctor
use that same inventory. A declaration, installed CLI, provider model listing and successful
model qualification are separate observations. A controller run still needs current protected
qualification evidence; only that protected record supplies it, never local discovery state.

Claude and Codex CLI workers use fresh homes, a code-generated broker configuration and native-tool
restrictions. Codex model identity is read from its fresh session's CLI rollout when its JSON
stream omits it. Gemini worker wiring supports a login/subscription declaration with owner-provided login
material, generated core-tool exclusions and excluded context files. The shipped Gemini API CLI
route remains refused because its CLI has no monetary ceiling enforcement; the Gemini HTTP loop
provides the budgeted API route. Qualify every installed CLI version before use; ignoring a
configuration key or exposing any extra tool must fail the conformance surface check.

Subscription workers validate CLI authentication status and nonsecret settings before launch. A Codex API-key login or a
Gemini API/Vertex authentication mode refuses with `subscription_auth:<cli>`; use a subscription
login or a budgeted HTTP route. Explicitly passed API credential selectors refuse on those
subscription routes too. Gemini workers select personal OAuth. The owner supplies login files through their own setup
step. Login lifecycle stays with the owner, and diagnostics retain redacted error text.

HTTP and local models run as sandboxed RAVEL workers under the same worker spec, broker, budget,
instruction packet and receipt path. Their LangGraph nodes obtain steering admission from the
supervisor over a connection that lasts exactly as long as the node. Admission and release are
recorded in supervisor custody against the original step and attempt. The worker never reads that
custody. Cards with an explicit zero broker-call contract and no tool requirement receive only the
final-record channel, with no executable broker actions. A minimum requirement of no tools does
not remove an ordinary reviewer's workspace tools. Model calls, including these one-call nodes,
keep checkpoint and effect receipts.

API loop calls require catalogue prices and context/output limits plus an explicit authorised cap.
Before each request, the loop reserves the price of a full context and maximum output. It stops
before the next call if complete provider usage or a matching model identity is absent. This
conservative reservation does not lower the requested model or effort. Token usage is measured;
catalogue-priced dollars and provider-reported billed dollars retain their distinct basis.

Local HTTP endpoints get a dedicated port grant. On Linux the OS filter restricts the destination
port; the code-owned sender fixes the configured host and refuses redirects. The inventory records
the actual TCP-port grant. No native execution tool is exposed by the HTTP worker. On hosts without
the required local port filter, selection refuses the local route.

`ravel setup-models --verify` opts into the existing conformance qualification command. It displays
a cost scenario and the API reservation first; `--verification-cost-cap-usd` supplies a finite API
ceiling. Subscription qualification uses the operator login and has no monetary cap. Setup never
runs a separate ungoverned verification prompt. A failed or unreported model identity remains
unqualified for setup. No live call is necessary for ordinary discovery and configuration.
