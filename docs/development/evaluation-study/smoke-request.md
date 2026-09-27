# Authorization request: 8-assignment real-host engineering smoke (WP15)

**Status: authorized on 2026-09-26 ([decisions.md](decisions.md) E-34); not launched, and not yet
launchable.** This request asked Ammar (budget owner, PKT-D07) to authorize one small paid
engineering run, and he authorized a smoke test. The per-run cap c and the model are fixed in the
smoke campaign's approval record (E-34). Its purpose is to test the runner, isolation, treatment
delivery and scoring against a real host. It is **not** a pilot and produces no treatment-effect
estimate. Every number below is a ceiling or a planning figure; no
provider price is assumed. The harness cannot run it yet: the items under "Not implemented" below
must exist first, and the request is re-checked against the code once they do.

## What would run

| Item | Value |
|---|---|
| Tasks | `lf-b` (V1, numerical dependency changed; completion control) and `lf-d` (V3, no authorized luminosity; refusal control) from the synthetic development family |
| Repeats | 1 seed |
| Arms | `baseline`, `instructions`, `enforcement`, `full` |
| System | Claude Code CLI, one pinned binary and one model (to be chosen at approval; see decisions below) |
| Assignments | 2 × 1 × 4 × 1 = **8**, frozen in one v1 registry before launch; every assignment keeps a v1 row |
| Per-run wall limit | proposed 900 s, set as the campaign's `seconds_per_run` (the runner's default is 600 s); the coordinator enforces it |
| Per-run model spend | `--max-budget-usd c`, enforced by the host. The coordinator refuses a launch unless c equals the campaign's `usd_per_run` exactly (`runner.host_binding`), and a run whose cost is unknown is charged c |
| Broker limits | identical in every arm: the runner's defaults, 40 operations and 4 fits per run (`runner.DEFAULT_BUDGET`, as in the synthetic campaigns) |
| Retry policy | none; a failure stays in the cohort |

**Planned ceilings:** model spend ≤ 8c USD (the default global cap is 8 × `usd_per_run`; for example
c = 2 gives a 16 USD ceiling); wall time ≤ 2 h (8 × 900 s); review about 8 × 5 min of human
inspection of transcripts and judge reports. Setup, failed launches and any rerun of a repaired
revision are separate and need their own approval.

## Configuration: what exists and what does not

### Implemented, tested only against mocked executables

- **Claude adapter** (`adapters/claude_cli.py`). Launch: `claude -p --output-format stream-json
  --verbose --model <M> --max-turns <N> --max-budget-usd <c> --permission-mode <P>
  --setting-sources <S> --strict-mcp-config --disallowedTools WebSearch WebFetch … --session-id
  <uuid>`, prompt on stdin (never in argv). Before each launch it checks the pinned binary's version
  and sha256. It creates a fresh per-run `CLAUDE_CONFIG_DIR` (never the user's `~/.claude`), sets the
  isolation environment (auto-memory, nonessential traffic, the autoupdater and claude.ai MCP servers
  disabled; credential scrubbing for the host's child processes on by default), loads no user
  settings (setting sources are limited to `project` and `local`) and passes no setting that would
  enable the host's own sandbox (E-09). Its stream parser records the session, tools, usage,
  permission denials and the invocation's own cost.
- **Runner real-host path** (`runner.run_campaign`, never run end to end with any real or mocked
  host). A campaign with a non-fake host loads only with `RAVEL_EVAL_LIVE=1`; it launches only after
  a passing behavioral treatment check of its exact campaign.json is on record (`cli.py
  treatment-diff --behavioral`, slice §4.3). Every launch must match the host binding: the pinned
  executable, its sha256, version and model; the executor id; the sandbox; a fresh session; the
  campaign's synthetic label; and `max_budget_usd` equal to `usd_per_run`. The first launch's binding
  is written to `coordinator/host_binding.json` and every later run must launch identically. The
  recording launcher refuses a launch call that changes the coordinator's environment or carries
  evaluator material, or whose added environment values name an arm.
- **Campaign identity** (`campaign_manifest.verify`). A synthetic real-host smoke declares
  `spec.runtime = "synthetic claude_cli <version>"` and `spec.model = "synthetic <model>"`; an
  empirical campaign declares both exactly (`claude_cli <version>` and the pinned model). An
  authorization whose `reference_sha256` is set must name the approval bytes frozen with the campaign
  as `approval_record`; a `synthetic_engineering` authorization may leave it null, in which case the code reads
  no approval record. E-34 requires this smoke to set it, so that the approved cap and model are
  frozen with the campaign.
- **Workspace and admission** (`isolation.py`). The subject workspace is outside the DSRLab tree, has
  no `.git`, `CLAUDE.md` or `AGENTS.md` above it, and holds only the request, the neutral tool guide,
  the current inputs, the task client and its own `output/`, `tmp/` and `home/`.
- **Sandbox pieces** (`isolation.py`, `allowlist_proxy.py`). The deny-default Seatbelt profile
  (no terminals, no POSIX shared memory or named semaphores, System V objects listed and removed
  around each launch; slice §8) accepts localhost ports (`SandboxPolicy.localhost_ports`), and the
  allowlist proxy class forwards only listed hosts (tested with local targets).

### Not implemented: required before a live smoke

1. **A real-host campaign builder.** `runner.build_synthetic_campaign` builds the fake host only.
   Nothing writes a `claude_cli` host configuration (pinned executable, sha256, version, model), the
   `spec_identity` labels, the `synthetic_engineering` authorization, or the coordinator's
   configuration and environment manifest for a real host.
2. **A `claude_cli` adapter factory and a way to call it.** The runner has only
   `fake_adapter_factory`; nothing chooses the per-run config directory and session id. `cli.py run`
   refuses every non-fake host, so a separate launcher or CLI path is needed.
3. **A real-host launch policy.** `runner.launch_policy` is the fake host's: reads of the workspace
   and the subject interpreter prefix, writes to `output/`, `tmp/` and `home/`, and the broker port
   only. The pinned binary's install root needs a read root, the per-run config directory a write
   root, and the proxy a localhost port.
4. **Starting the allowlist proxy.** Nothing starts `AllowlistProxy` for a launch or sets the host's
   proxy environment, so a host could not reach the provider API; the provider host list must be
   confirmed.
5. **A path for the host's credential.** None exists. The coordinator's subject environment is
   admission-checked, and every secret-looking name in it except `RAVEL_TASK_TOKEN` and
   `RAVEL_TASK_ENDPOINT` fails admission; the Claude adapter has no credential input. A declared
   per-campaign credential exception (where the credential enters, how admission treats it, and that
   `launch.json` keeps only its name) must be added and tested.
6. **Path naming.** The recording launcher refuses a real host's added environment value that names
   an arm or treatment word (for example "full", "audit", "block", "arm"), and it scans the whole
   absolute path of the per-run config directory. The store and config roots must avoid such words.
7. **Live checks** (B-05, H-04). The task-tool token must reach the host's shell under its
   credential scrubbing; the init tool list must contain no web tools; no server-side web search may
   run; and the host's shell tool and a multiprocessing script must work under the production profile,
   which has no tty or pty and no named semaphores (slice §8). Any capability a host needs beyond it is
   a reviewed profile change with its residual recorded.

## Prerequisites before launch (each must be checked and recorded)

1. **Decisions,** recorded in the approval record (E-34): Claude binary pin (CLI 2.1.233 or
   Desktop-bundled 2.1.281, H-04; resumed-cost semantics differ), model identifier resolved on the
   execution date, per-run cap c, permission mode, and how the subject authenticates (a Console API key or a subscription setup-token, supplied only to the
   host process through the per-campaign credential exception above).
2. **Engineering items:** every item under "Not implemented" exists, is tested, and this request is
   updated to match it.
3. **Frozen revision:** the campaign is built from a committed revision; receipts bind the kernel
   source, interpreter and environment, and the coordinator refuses to launch a run whose code,
   treatment texts or campaign.json changed after the freeze, so any change forces a new campaign.
4. **Campaign identity and spend:** the spec labels as above and the `approval_record` bytes that
   the authorization's `reference_sha256` names (set for this smoke, E-34); `usd_per_run` equal to the
   approved c; and `seconds_per_run` set to the approved wall limit.
5. **Behavioral check:** `cli.py treatment-diff --behavioral --campaign <campaign>` passes for the
   frozen campaign.json. The launch gate accepts any passing record of that campaign.json, even when
   a later check failed (open, runner review minor 1), so confirm by hand that the most recent record
   under `coordinator/behavioral/` passed.
6. **Environment:** a campaign with a real host loads only with `RAVEL_EVAL_LIVE=1`, the behavioral
   check included; set it only in the shell that checks and launches the approved campaign.

## Stop rules

Stop and preserve the cohort, without relaunching, on any isolation breach (a subject reads a
denied path or reaches a non-allowlisted host), a broken oracle or kernel mismatch, a treatment
implementation error (arms not distinct as declared), a global spend or time ceiling, or a host
authentication failure. A repaired run is a new campaign with a new identifier.

## What the smoke can and cannot show

It can show whether a real host can use the tool surface, whether the treatment reaches the
subject as declared, whether costs and streams are captured, and whether every assignment is
scored and accounted for. It cannot show any treatment effect, reliability, or generalization:
eight runs of two synthetic development tasks on one system are an operational test only.
