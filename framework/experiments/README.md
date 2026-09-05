# Governance experiment registry

`governance_experiment.py` freezes a complete 2×2 assignment roster and scores
independently adjudicated outcomes. It launches no agents or simulation jobs,
contains no physics oracle, and provides descriptive accounting only. The
prospective scientific protocol is in
[`docs/research/2026-09-05-competitive-design-and-validation.md`](../../docs/research/2026-09-05-competitive-design-and-validation.md).

The four arms are fixed: `baseline` (no additional instructions, no experimental
enforcement), `instructions` (instructions only), `enforcement` (enforcement only),
and `full` (both). Every task × seed appears in every arm. The enforcement arm
still receives the minimal interface contract needed to use the common tools.
Production safeguards are never disabled by this utility.

## Freeze before execution

Create a JSON spec with exactly these fields. Its contents, the protocol, prompt
files, oracle files, and runtime configuration must be approved and sealed before
any scored run starts. Keep scorer-only material inaccessible to subjects.

| Field | Meaning |
|---|---|
| `experiment_id` | Unique, nonempty campaign label |
| `protocol_sha256` | SHA-256 of the finalized protocol file bytes |
| `code_commit` | Full 40-character Git commit for the evaluated code |
| `environment_sha256` | SHA-256 of the frozen environment/configuration manifest |
| `model` | Provider, exact model/revision, reasoning settings, and sampling settings |
| `runtime` | Agent runtime/version and its configuration identity |
| `schedule_seed` | Nonnegative integer for deterministic schedule shuffling |
| `seeds` | Nonempty list of distinct nonnegative integers for repeated assignments |
| `budget` | Object with positive finite `usd_per_run` and `seconds_per_run` |
| `tasks` | Nonempty array of the task objects below |

Each task has exactly `id` (unique string), `expected` (`complete` or `refuse`),
`prompt_sha256`, `oracle_sha256`, and `fidelity_tolerance` (finite nonnegative
number, or null for tasks with no quantitative fidelity endpoint). Refusal tasks
must use null. Include both completion and refusal controls. The oracle defines
what complete means and the units and direction of its error metric. A null
tolerance does not waive correctness review. It means that completion is judged
against the non-numeric oracle. Fidelity summaries are kept per task because
different task oracles may use incompatible metrics or units.

From the repository root:

```sh
python3 framework/experiments/governance_experiment.py freeze spec.json > registry.json
```

Archive the registry and its digest with a timestamp in a write-protected or
independently held record before dispatch. The script's hash detects accidental
changes relative to that record. A hash alone does not prove preregistration,
protect against a malicious person recomputing it, or establish that prompt/oracle
files match their declared hashes. The experiment operator verifies those files
and the running arm configuration independently. Runtime providers that cannot
fix stochastic seeds must record that limitation; these integers still identify
paired repeat blocks, without promising identical random draws across vendors.

## Record every assignment

The outcomes JSON contains exactly `schema_version: 1`, the matching
`registry_sha256`, and an `outcomes` array. Each row contains exactly:

| Field | Meaning |
|---|---|
| `run_id` | Identifier from the frozen roster |
| `status` | `completed`, `refused`, `timeout`, `crash`, or `not_started` |
| `unsupported_claim` | Independent finding of an unretracted, materially unsupported scientific claim in the delivered trajectory; boolean or null if unadjudicated |
| `refusal_valid` | Independent validity finding for a refused outcome only; boolean or null |
| `fidelity_error` | Completed run's nonnegative oracle error, or null if missing/not applicable |
| `cost_usd`, `wall_seconds` | Total attempt resources, including retries and review; finite nonnegative numbers or null if unavailable |
| `interventions` | Count of substantive outside assistance, a nonnegative integer or null |
| `executor_id`, `scorer_id` | Actual session/person identities. Any adjudicated finding needs a scorer different from the executor |
| `evidence_sha256` | SHA-256 of the sealed trajectory/artifact evidence manifest |
| `notes` | Nonempty disposition and explanation of every missing field |

`completed` means the independent reviewer confirms the assigned deliverable is
complete, not merely that a process exited zero. A completed but scientifically
invalid artifact can still have `unsupported_claim: true` or fail fidelity.
Timeouts and crashes can also contain unsupported claims; inspect their delivered
trajectory rather than automatically marking them harmless. Mark a refusal
valid only with a specific verified missing resource, scope constraint, or
predeclared refusal oracle. An unjustified refusal gets `refusal_valid: false`.
A justified environment-related refusal on a completion control still does not
count as a completed useful task.

For `not_started`, all judgment and identity/evidence fields are null and all
three resource fields are explicitly zero. Explain why launch did not occur.
All started rows require executor identity and an evidence digest, even if the
oracle cannot finish. A missing API bill is null, never zero. Identities and
digests are checked syntactically; the tool cannot establish real independence
or independently audit artifact contents.

## Score

```sh
python3 framework/experiments/governance_experiment.py score registry.json outcomes.json > summary.json
```

A missing, duplicate, or unplanned row is a hard error, as is altered registry
content. Each run identifier also includes the complete frozen campaign spec,
so relabeling an old outcomes document cannot silently reuse another campaign's
rows. Record an explicit `not_started` row instead of removing an assignment.
Unknown or unexpected fields are rejected to catch spelling errors. Per arm the
report provides all planned runs, every terminal status, unsupported-claim
counts, unadjudicated counts, completion/refusal controls, fidelity coverage, and
resource totals with known/missing denominators.

If `k` of `N` assigned runs have unsupported claims and `u` are unadjudicated,
the rate bounds are `[k/N, (k+u)/N]`. These are missing-data bounds, not confidence
intervals. The point rate is null unless all assignments are adjudicated. A
verified completion needs `completed`, no unsupported claim, and fidelity within
the frozen tolerance when required. The useful completion rate always divides
by all assigned completion controls; incomplete or unscored cases cannot improve
it. Valid refusal uses all assigned refusal controls as its denominator. The
separate refusal count on completion controls exposes blanket-refusal behavior.

Per-task fidelity medians and mean resource use cover known values only; always
carry their denominators and missing counts when quoting them. A lower median among a
smaller survivor set is not evidence of improvement. Do not use this utility's
output to claim significance, population performance, causality, or autonomous
self-drive. Those require the separate experiment described in the protocol.

## Software verification

Run pytest from outside this checkout to avoid its legacy `py.py` shadowing
pytest's dependency:

```sh
cd /tmp
python3 -m pytest /absolute/path/to/hep-agentic-pipeline/framework/tests/test_governance_experiment.py -q
```

The fixtures are explicitly synthetic tests of accounting failures, not empirical
agent outcomes. No campaign results ship in this directory.
