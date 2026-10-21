# Configuration

RAVEL separates operator authority, provider preferences, runtime locations and
scientific inputs. The [generated inventory](documentation-inventory.md) lists
configuration keys from the current schemas and source declarations. Unknown
fields are handled by the validator for that configuration.
Named environment inputs have source and line references. Credential and runtime
records can select environment names dynamically; the inventory records those
extension points separately.

## Operator authority

`ravel operator init` creates the operator ledger. `ravel operator show` displays
the current configuration; `ravel operator set` records an update. Use the
[parser reference](../cli/commands.md) for exact options.
The controller freezes the configuration at intake. Updates apply to later runs.

The ledger lives in the controller home derived from the account database.
`HOME`, `RAVEL_STATE_DIR` and `RAVEL_WORK_ROOT` do not relocate that authority.
A root-owned operator ledger has precedence where configured.

| Setting | Meaning |
|---|---|
| `mode` | `physicist-in-the-loop` or `autonomous` |
| `budgets` | Resource ceilings for the run and its children |
| `bounds.rungs`, `bounds.allowed_stages` | Permitted compute rungs and stage names |
| `machine_checkins` | Delegated `approve_plan`, `go`, `deviation`, `final`; `assumption` requires explicit opt-in |
| `r3_policy`, `r3_delegation` | Escalation/default policy and named delegation for `final_task` |
| `expires_at`, `project_scope`, `deadline` | Grant expiry, allowed project roots and run deadline |
| `wait_bound_seconds`, `notify_command` | Human-wait bound and an explicit notification argument list |
| `allow_unconfined` | Admission policy for unconfined scientific execution |
| `review_sandbox_fallback` | Declared configuration enum: `none` or `restricted-unsandboxed` |
| `allow_request_delegation` | Whether request-stated delegation can be admitted |
| `store_root` | Absolute controller store location |
| `instruction_document` | Pinned project instructions delivered to agents |
| `engagement.minimum_tier` | Operator floor: `lean`, `standard`, `full`, or the policy default |
| `agent_preferences` | Ordered transports, model tiers and family preferences |
| `restricted_sources` | Source-screening policy location |
| `remote_job_ceiling`, `site_resource_ceilings` | Remote submission and site resource bounds |
| `procedure_byte_ceiling`, `disk_free_floor_bytes` | Procedure size and free-space bounds |
| `harness` | Bound executable, model, effort and capture locations for the configured driver |

`budgets` includes `wall_seconds`, `model_calls`, `tokens`, `cost_usd`,
`core_hours`, `events`, `children`, `concurrency`, `review_rounds`, `replans`,
`max_redos`, `input_bytes`, `input_files`, `batch_cpu_hours`, `batch_jobs`,
`stage_wall_seconds` and `recoveries`. Counts use integers; cost and CPU-hour
budgets allow fractions. A nullable unset ceiling is recorded as unbounded.
API-billed execution still requires its applicable finite cost bound.
Installed engagement envelopes provide absent defaults; explicit operator
ceilings take precedence.

The enforcing implementation is
`ravel.controller.authority.operator.validate`. Its schema is
`src/ravel/data/controller/schemas/operator-config.v1.json`.

## Models and transports

Run `ravel setup-models` for guided discovery and preferences.
`ravel models list`, `ravel models estimate` and `ravel models show`
inspect candidates, estimates and catalogue entries.

| Configuration | Location or selector | Contents |
|---|---|---|
| Model catalogue | Shipped catalogue plus `.ravel/models/catalogue.json`; `RAVEL_MODEL_CATALOGUE` selects an overlay | IDs, provider families, classes, tiers, context/output limits, prices and provenance |
| Transport declarations | Shipped declarations, `.ravel/transports/`, `RAVEL_TRANSPORT_PATH` | Executor kind, arguments, authentication names, model candidates, capabilities and qualification |
| Agent preferences | Operator configuration and pinned `inputs/agent_preferences.json` | `transport_preference`, `families`, `tier_models`, `model_families` |
| Host adapter | `.ravel/host.json` or `RAVEL_HOST_CONFIG` | Adapter `type`, endpoint, credential-variable name and wire capabilities |
| Data policy | Study configuration | Input classifications, destination scope and local/remote model policy |

Model overlays retain their origin. Model prices are catalogue facts used for
projections; [measured cost](model-cost.md) comes from captured provider usage.
Transport credentials stay in the named environment variables or the provider's
login store. JSON declarations hold credential names.
See [transports](transports.md) for exact routing and qualification.

## Native tools and site settings

`RAVEL_NATIVE_BUILD` selects the native prefix. Otherwise RAVEL reads
`.ravel/native-prefix`, then looks for an existing checkout prefix and the shared
per-user toolchain. `RAVEL_NATIVE_BIN` selects the native executable directory.
`RAVEL_ROOT` selects a source checkout for commands that require one.

A site profile binds scheduler commands, paths, workflow environment and resource
limits. `ravel site doctor` reports its observed capabilities; `ravel site init`
records the chosen profile. Adopted workflows bind their rules, configuration,
profile and expected outputs before execution. See
[site workflows](site-workflows.md) and [installation](../installation.md).

## Scientific and literature settings

`task_contract.json` records the question's modes, requested quantities,
assumptions and scope. Scientific-study specifications choose a registered
science mode and its typed adapter configuration. A mode's required keys,
units, allowed values and source files are defined by that adapter; use its
linked page in the [inventory](documentation-inventory.md).

Literature settings select `auto`, `off` or `local` retrieval and pin the index,
source root, qualification, cursor key, model root, budgets and excluded origins.
`RAVEL_RETRIEVAL_SETTINGS` selects the trusted settings file. Corpus build and
discovery contracts govern chunking, query limits and source families. The settings validator is
`ravel.workflow.literature_settings`; acquisition and screening retain source
identities through indexing and retrieval.
See [literature discovery](../workflow/reference/literature-discovery.md).

## Changing a running study

Approved runs retain their frozen configuration bytes. Resume validates the
execution identity, current artifacts and authority.
Changes within a study follow its deviation and reapproval path.
[Output records](outputs.md) explains which files hold that evidence.
