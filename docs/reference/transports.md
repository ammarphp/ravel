# Model transports

A transport is a declared route from a RAVEL role to a model. RAVEL ships one JSON declaration per
route in `src/ravel/data/transports/`. You can add your own in `.ravel/transports/` in the project, or
in any directory named by `RAVEL_TRANSPORT_PATH`. A user declaration cannot reuse a built-in id, and it
cannot claim blind review or isolation above `cli-policy`: those need a shipped declaration.

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

## What a declaration says

| Field | Meaning |
|---|---|
| `transport_kind` | `cli-oneshot` (one judgment, no tools), `cli-worker` (tools in a workspace), `http-model`, `ravel-loop`, `external-relay`, `host-subagent` or `stub` |
| `launcher`, `argv_template` | The program and its exact arguments, with `{model}`, `{effort}`, `{schema}` and other placeholders |
| `models` | The model identifiers (or `{configured}`), their family and the tiers they serve |
| `auth` | `login` (the CLI's own login, no key), `env` (named variables), `command` (a token program run per request) or `none`; HTTP routes also name the header style |
| `pass_env` | The extra environment variable names the child may see |
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
The unit-test harness may designate `RAVEL_TEST_TRUSTED_BIN`; it is ignored outside a test lock
domain (which only the test harness selects) and is not an operator trust mechanism.

A same-user process can still write the probe record. Operator-path separation, including host and
receipt registration, is not provided yet. These checks do not establish separation from other
processes running under the same account.

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
`worker_surface`. RAVEL-loop routes are refused as `unimplemented:ravel-loop`.

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
`probe`, `local_only`, `local_models` or `distinct_family_from:<role>`, and also `qualification`,
`effort`, `model:family`, `model:family-unbound`, `probe:<flag>`, `probe:stale-executable`,
`unimplemented:<kind>` or `local_only:cloud-model`. Nothing is downgraded: a card that asks for an
effort on a route that cannot carry one is refused with `effort`.

A model named in `tier_models` must be a declared id, or fit a `{configured}` entry of the same
family. A model whose identifier does not reveal its family needs an explicit binding in
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
own tool policy (`cli-policy`) and cannot serve a blind role.

When a card sets `distinct_family_from`, the selected model's family must differ from those roles'
families. A named role with no assignment yet, or a family that cannot be read, refuses. The same
check, `check_distinct_families`, runs on the observed models in the receipts.

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
  Codex runs with `--sandbox read-only`, so its native shell and file tools cannot write. Review roles
  get the route's full toolbelt; blind roles keep only the workspace read and write tools;
- the toolbelt pinned by its manifest digest. The supervisor's broker comes from
  `tool_gate.production_broker`, the one factory every real worker broker uses (the host-subagent
  broker too). It allowlists exactly the toolbelt's actions, serves only its knowledge ops and installs
  the shared gate (`tool_gate.broker_guard`), so a call no toolbelt tool produces is refused with a
  receipt. A tool name outside the toolbelt reaches the broker as `tool:<name>` and never aliases an
  allowed action; a malformed call (a non-string name, non-object arguments) is refused with a receipt
  too. Knowledge calls have one argument shape, `{"op": <op>, "args": {...}}`, for the toolbelt and
  the handler alike;
- a CLI home the sandbox lets the child read and write. Codex, Gemini CLI and the Claude key, Bedrock
  and Vertex routes get a fresh `<attempt>.cli-home` beside the workspace, holding a copy of the
  login file and any credential file a declared variable names. It is removed when the child is
  gone. The Claude login route uses `CLAUDE_CONFIG_DIR`, which must name a dedicated login-only
  directory: the route refuses an unset variable, `~/.claude`, and a directory that holds
  `CLAUDE.md`, skills, agents, commands, hooks, output styles, installed or enabled plugins, or a
  `settings.json` with any key besides the display keys (`theme`, `preferredNotifChannel`,
  `spinnerTipsEnabled`, `terminalProgressBarEnabled`). It admits what every real login creates: a
  display-only `settings.json`, a `plugins/` folder holding only `known_marketplaces.json`,
  `marketplaces/` catalogs and account-synced `synced/<org>/` content, plus at most a top-level
  `installed_plugins.json` whose `plugins` map is empty (an interactive login writes it with
  nothing installed; any listed plugin, or the file anywhere else, is refused), and a `skills/` folder holding only account-synced `synced/<org>/<skill>/` content.
  Nothing in these folders may be a symbolic link. Any other entry under `skills/` or `plugins/` is
  refused. The synced folders are admitted on measured evidence: Claude Code's account sync creates
  them on every real login, and a Claude Code 2.1.296 login with these folders reported no available
  skills under RAVEL's launch flags (`--restricted --setting-sources project --strict-mcp-config
  --tools ''`). With default flags the same login listed about 25 skills, including the synced ones.
  Live qualification repeats this check on every route (see below);
- for Claude Code, `USER` and `LOGNAME` listed in `pass_env_names` and set by the supervisor from the
  password database, never copied from the parent environment. Claude Code reads its stored login by
  running `/usr/bin/security find-generic-password -a $USER`; without these names it reports "Not
  logged in". Both are reserved names: no other route can pass them;
- for Claude Code, `CLAUDE_CODE_TMPDIR` and `TMPDIR` set to the worker's own `scratch/tmp`. Claude
  Code ignores `TMPDIR` for its own temporary directory (`/tmp/claude-<uid>`), which the sandbox
  denies;
- for Claude Code on macOS, a login keychain home, described below;
- provider network egress, described below.

### The login keychain for Claude workers on macOS

Claude Code stores its login in the macOS login keychain and finds it through
`$HOME/Library/Keychains`. With any other `HOME` it reports "Not logged in". So each Claude worker on
macOS gets an adapter-owned `<attempt>.home` beside the workspace as its `HOME`. That home holds one
entry: `Library/Keychains`, a symbolic link to the invoking account's keychain directory, read from
the password database. Nothing else from the account home is linked or copied. This link is the one
exception to RAVEL's no-symlink path rule: the adapter creates it, in a home the adapter owns, and
removes the home when the child is gone. The supervisor accepts only the workspace's own
`<attempt>.home`. The adapter refuses an existing home that holds anything else.

The sandbox profile for these workers:

- reads the real keychain directory. Writes to it are denied, including writes through the link;
- reads the system Module Directory Service database (`/private/var/db/mds`). It also reaches the
  Security services `com.apple.securityd`, `com.apple.security.agent`, `com.apple.ocspd` and
  `com.apple.system.opendirectoryd.membership`, which the Security framework needs before it opens
  any keychain;
- reads and executes `/usr/bin/security`, the tool Claude Code runs to read its stored login. The
  base profile already allows process execution for every worker; the keychain block names this tool
  so the grant does not depend on the read roots. Run inside the profile, `security
  show-keychain-info` on the linked login keychain succeeds, and a lookup of an absent item reaches
  the keychain search and reports it not found. The tool needs nothing beyond the grants above;
- leaves every other path in the account home denied.

Codex and Gemini CLI workers get none of this. Their profiles never name the keychain directory or
these services, and the denial probe records `login_keychain: false` for them.

Reading the keychain directory does not expose its contents. The keychain files are encrypted.
macOS decides through each item's access control list which program may read a secret, and asks the
user when the list does not already allow that program. The worker cannot query the keychain itself.
Claude runs with `--tools ''`, so it has no shell, file or other native tool. Its only tools are the
broker MCP tools, and no toolbelt tool reads the keychain.

### Provider network egress

On macOS the provider profile allows outbound TCP to port 443 only, name resolution through
`mDNSResponder`, and the TLS trust and security services the CLI needs. Every
other port is denied, and listening sockets stay denied. The sandbox denial probe runs under the
exact profile the child launches with (its CLI home, its keychain home and its network mode) and records `network:
tcp-443`. It checks that a listening socket and an outbound connection to a port other than 443 (on
the loopback address, so nothing leaves the machine) are both denied. On Linux, `bwrap --share-net`
cannot filter ports, and the probe records `network: unrestricted`.

Hosts are not filtered. Domain-level filtering needs a RAVEL-owned proxy that only the sandbox can
reach, which is future work. Until then a worker can reach any server on port 443, and two workers
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
Gemini CLI cannot turn its native file tools off, so on that route only broker output pins would count.

The workspace and every directory above it must hold no `CLAUDE.md`, `AGENTS.md` or `GEMINI.md`. The
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
Exit status 3 means refused before any process started; 4 means the run happened and named steps failed.
Pass `--rundir` as a real path: on macOS `/tmp` is a symlink, so use `/private/tmp/...`. A path through a
symlink is refused, and the refusal names the real path to use.

## User configuration and independence

| CLI | How RAVEL keeps your own configuration out | Model tools | `user_configuration_loaded` |
|---|---|---|---|
| Claude Code | One-shot: `--setting-sources project --safe-mode --strict-mcp-config --tools ''`. Worker: `--setting-sources project --restricted --strict-mcp-config --tools ''` plus `--allowedTools` for RAVEL's tools, in an empty directory. Not `--bare`, which drops the subscription login. Admin-managed settings stay in force; their digest is recorded | none | `false` |
| Codex | A fresh `CODEX_HOME` per call holding a copy of `auth.json` and a generated `config.toml`. The read-only sandbox refuses native writes | a shell that can read files | `false` |
| Antigravity (`agy`) | A fresh `HOME` holding only the Google login files; the working directory is empty. No flag excludes other configuration | read tools | `true` |
| Gemini CLI | A fresh `HOME` holding only the Vertex AI application-default credentials; `~/.env` and `~/.gemini/.env` are left out and listed in the receipt | read tools | `true` |

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

Codex refreshes its login token inside the per-call copy of `auth.json`. The copy is deleted after the
call and your own `~/.codex/auth.json` is not updated, so a refresh made during a call is lost; run
`codex login` again if Codex later reports an expired refresh token.

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

A transport label must describe the executor: a `command` host may carry only the label of the
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

A request may carry `role_requires: {"tools": "broker-readonly"}` (default `none`). The launcher
records `configuration.tools_required` beside `effective_tools`, and AgentHost checks the recorded
requirement against the request before computing attestation. Effective tools above the requested
policy add a downgrade reason; equal tools do not. The order is `none`, `broker-readonly`,
`broker-full`. Role cards do not yet supply this policy automatically; a caller that omits it gets
`none`. Voting status uses
`independence.kind == "voting"`; legacy voting/blind/name tests apply only without `independence`.

`research-cycle discussion-run` records the resolved absolute host-config path and digest in a
create-only `host-config-receipt.json` next to the discussion report, with that report's pin.
Host configs inside the research cycle remain refused.

Consumers bind to these fields, not to actor names:

- `agent_graph.role_receipt` returns `attestation`, `execution_observation` and `session`
  (`transport_id`, `cli_session_id`, `session_receipt_pin`). Read `attestation` directly; an
  observation-to-attestation table may map `transport_attested_cli` to `transport_attested` only when the computed label verifies.
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
