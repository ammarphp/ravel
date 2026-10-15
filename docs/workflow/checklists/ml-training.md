# Governed ML method studies

Use science mode `ml-training` for a binary classifier comparison on supplied,
pinned data. The executor trains every baseline and model with every seed before
opening the withheld test payload. It produces checkpoints, a receipt, a result
document, and ROC and reliability figures in the house style.

Create a science/v2 specification with one attempt, a prospective review policy,
and an immutable task. Use the existing `ravel plan`, `ravel approve`, `ravel run`,
and `ravel status` commands. CHECK-IN 1 authorizes the complete study. The mode requires
a version 2 review policy; training never grants scientific acceptance.

The task contains these fields:

- `objective`: `classification`.
- `dataset`: three `{path, sha256}` pins, ordered feature names, `label: y`,
  `weights: weight`, `id_column: event_id`, and `manifest_sha256`. Compute the
  manifest digest with `ml_training.digest` on the dataset without the digest field.
- `splits`: `method` (`explicit` or `hash`), an integer `seed`, positive `fractions`
  for train/val/test summing to one, three separately pinned `files`,
  `test_withheld: true`, and `split_sha256` from `ml_training.split_digest`.
- `baselines` and `models`: nonempty lists of unique arm IDs, `architecture`,
  `backend`, and fixed `config`. NumPy supports `logistic` with `learning_rate`, or
  `mlp` with `learning_rate` and `hidden_units`. No arbitrary code is imported from
  an arm configuration. The receipt also pins the executed implementation.
- `seeds`: at least three distinct nonnegative integer seeds.
- `budget`: positive integer `epochs` and `wall_seconds`, `max_trials: 1`, and
  `equal_across_arms: true`. Every arm and seed receives the same full-dataset epoch
  count and wall ceiling. This definition does not assert equal FLOPs or runtime.
  An arm that reaches its ceiling fails the study; it is not silently truncated.
- `metrics`: `primary: background_rejection_at_signal_eff`, `operating_point`
  between zero and one, `secondary: [roc_auc]`, `uncertainty: seed_spread`, and
  `calibration: {method: reliability, bins: 15, report: [ece, brier]}`.
- `placement`: a pinned `execution_backend.prepare` native plan for stage
  `ml-training` and `device: cpu`. Its inputs include all three dataset files;
  its wall limit covers all arm/seed ceilings plus 30 seconds for evaluation and
  output. The ordinary science supervisor supplies process admission and the hard
  stage wall. The adapter consumes the plan and takes `execution_backend.capacity`
  for its local computation. Remote and accelerator placement are not implemented.

Each NPZ split contains `x` (event × feature matrix; graph tensors below), binary `y`, nonnegative
`weight`, unique integer or string `event_id`, and `group_id`. Each split needs positive
weighted populations for both classes. Files and expanded arrays are bounded
at 64 MiB; matrices have at most 100,000 rows and 256 columns. Signed weights are
refused. Feature order is exactly the declared order. Standardization is fitted
only on training data. Missing values are refused.

Every supervised task pins `dataset.population_index`, a JSON list of `{event_id, group_id}`
records for the complete population. Explicit splits add `partition` (`train`, `val` or `test`)
to each record. For hash splitting, prepare shards using `hash_partition(group_id, seed, fractions)`;
the partition follows from the hash. Admission checks exact train and validation membership against
that census. The test identity comes from the census alone: the test file is not decoded before the
freeze and the charged read. After that read, its identifiers must equal the census, or the attempt
fails and stays spent. Splits require disjoint events and groups. A population whose every normalized
feature/region/weight row appears in another is a relabelled copy and counts as overlap. Independent
events that share some measured values are recorded as `value_collisions`, not refused. The producer
must not receive the withheld arrays. The supervised test scoring occurs after all arms freeze.

The authoritative exposure ledger is `<default RAVEL state>/ml-exposure/`.
Population keys hash sorted event IDs. Event, group and value indices reject
re-encoding, reordering, subsets and renamed identities. Byte hashes remain
secondary provenance. One atomic claim covers train, validation, test, cross-fit,
null-toy, oracle-training, signal-evaluation and reference populations. Every read
must match the registered context schedule and a freeze record of the same spec.
Closed studies reject reads. A withheld test split takes one scheduled context and one evaluation
read in total. An unread failed claim can be replaced with an audit record. Train and validation
populations may be reread by later train or validation roles (`adaptive_reuse` in the record); a
read population can never become a withheld one. A claim token persisted by its study lets a resumed
run continue its own unread claim. Local and global ledgers pin the completed receipt. Never remove
these records to obtain another attempt.

The exposure ledger lives under the machine state root (`machine_state_root()/ml-exposure`), so two
`RAVEL_STATE_DIR` values share one ledger; `RAVEL_STATE_DIR` never relocates it. Only the marked test-only
machine-domain override of the machine lease does; receipts mark this as a test namespace. It is not production
authority. The decision-gate authority owns approved namespace protection; the native-job machine lease must share that authority.

The receipt is at `<attempt-output>/ml/receipt.json`, with complete task and
input pins, per-arm/seed checkpoints, package versions and code identities,
validation/test metrics, reliability records, placement, and `test_reads: 1`.
`validate_receipt` verifies both ledger receipt pins, records one `replay` entry against the
frozen test read, and then recomputes metrics, ROC, reliability and summaries from the
pinned checkpoints and test data. The executor's own pre-write check reuses the arrays of
its one charged read. Seed spread is the sample standard deviation across
seeds, not a confidence interval or a test-sample uncertainty estimate.

ROC construction groups tied scores and uses positive event weights. Rejection
uses the first empirical threshold reaching the requested signal efficiency;
the achieved efficiency is reported. If no background survives, rejection and
its across-seed mean/spread are null, with `zero_background_observed`. The output
does not invent a finite rejection, a confidence bound, or infinite sensitivity.
ECE uses fixed equal-width probability bins; empty bins remain empty. ECE and
Brier score measure calibration and do not establish calibrated uncertainties.

The installed NumPy reference backend is the supported execution path. The
small `ml_backends.fit`/`predict` interface admits installed sklearn logistic
and torch logistic/MLP implementations with numeric NPZ checkpoints. Those paths
need separate installed-runtime qualification. Backend `torch-geometric` supports
architecture `gnn`: one GCN layer, tanh activation, mean graph pooling and a linear
binary head. Its fixed configuration requires `learning_rate`, `hidden_units`,
`nodes`, and a caller-supplied directed `edge_index` (two equal-length integer
lists). GCN normalization and added self-loops are fixed implementation choices.
The executor never invents a graph topology.

Graph NPZ inputs have shape event × node × feature. Every event uses the supplied
fixed topology, with no implicit padding or dynamic edges. Dense baselines flatten
the same tensor in node-major order. The GCN fits shared feature normalization
across training events and nodes; dense arms fit their own training coordinates.
Graph hidden expansions are limited to four million entries, and batched edge
expansions to two million edges. Variable-node or variable-topology graphs require
a separate backend extension. All selected implementations refuse when their
libraries are absent; schema/dispatch tests do not qualify their numerical runtime.

For the required torch and torch-geometric runtimes, use
`ml_runtime.available(details=True)` to inspect the manifest-bound ML interpreter,
versions and installation command. The `ml_backends` binding seam sends fit and
predict calls through that interpreter inside the admitted science worker. Fit
accepts training arrays and a complete validation triplet only; prediction accepts
unlabeled features after the executor's exposure decision. Array names do not prove
population provenance. A complete probe response is retained per interpreter file;
an absent, partial or failed installation is probed again.

The executor does not yet pin the runtime and worker sources at approval or record
the bound interpreter's package versions in its receipt. Until it does, do not admit
a study with torch or torch-geometric arms: receipt construction reads the host's
package metadata, which fails after the test split has been read when the host lacks
these packages. Standalone receipt replay cannot run these arms.

## Production card: ml-trainer

Family: `production`. Operation: `ml-training`. Inputs: an approved immutable
science task, source-backed dataset and split pins, all baseline/model settings,
seeds, metric definitions, equal budgets, and a pinned placement plan.

The role prepares and executes this one declared study through the science
worker. It checks the split and package requirements before admission, preserves
failed attempts, and returns the receipt, result document, checkpoints and
figures. It cannot expand a search, inspect test data early, change a baseline,
raise a ceiling, approve itself, select a model using test scores, or certify
physics. Missing packages, unsupported architectures, contaminated splits,
exhausted budgets and failed postconditions return a concrete failed or blocked
study to the research loop. A follow-up needs a new prospectively reviewed
protocol and a genuinely unexposed test population.

The role registry carries `ml-trainer` and its specialist reviewer `ml-reviewer`.
The reviewer is blind and spec-denied, and runs in a model family distinct from the
trainer's. The trainer has no launch action: in `ml.study` it designs the models at S7,
and training starts only through the graph's spend and launch gates.

## Planning card: ml-planner

Family: `research`. Graph node: `planner`, the first node of `ml.study`, before S1.
Inputs: the study spec without its confirmation population (`inputs/ml-spec/`).

The role writes the plan record before any training or evaluator response:
claim kind, estimand, the single primary metric, comparison margins, arms with the
oracle labelled as a ceiling, paired replicate seeds, equal budgets, the hypothesis
family, the stopping rule and the precision-based sizing. It may add ablation arms
but never remove a generated one. It cannot read the confirmation population,
evaluator-owned columns, published numbers or any selection score, choose a metric
after a result, launch training, approve a gate or mark a check not applicable. Its
must-check list is the S1, S2, S5, S6, S9 and S13 checks those choices govern. The
plan critic reviews it at CHECK-IN 1.

## Cross-fitted weak-supervision studies

Set `splits.method: kfold_crossfit` and use `objective: method_study`,
`anomaly_search`, or `classification`. The three-file task remains supported.
The CPU executor is `ravel.physics.ml_crossfit`, dispatched by `ml_training`.
The executable synthetic schema is in `tests/unit/test_ml_crossfit.py::fixture`.
This is a supplied-data method study, not an event-generation route.

Before CHECK-IN 1, call `ml_training.size_study(spec) -> dict`. It accepts either
an outer science spec or its task. It performs no training or data decoding.
The return fields are `admissible`, `refusal_reasons`, `cells`, `trainings`,
`trainings_per_arm`, `training_arms`, `injection_points`, `toys`, `windows`,
`fold_salts`, `projected_wall_seconds`, and `projected_cpu_seconds`.
A malformed or missing count/timing contract returns `admissible: false`.
Intake and the research planner must consume this result before approval; that
merge integration is outside this executor. Do not use a generation smoke's
size as a statistical precision claim.

Each cell reports expected independent counts per signal/sideband region and
held-out fold, expected selected counts, and
`sqrt((1 - efficiency) / (N * efficiency))`. The task's `statistics` block
sets `region_counts` (signal, lower sideband, upper sideband),
`min_selected_per_fold`, `max_relative_error`, and the exact `claim`.
The declared region counts are exact nominal row counts and are reconciled at
admission. Precision uses effective counts from per-group summed weights.
Replicate seeds do not multiply them. Every window and fold is checked before
exposure; achieved sideband selections are checked again after scoring.
An undersized plan needs a changed claim or more independent data, followed by
a new frozen spec. It cannot acquire result status by being called a smoke.

The training count per trained arm is
`windows * k * (k - 1) * initializations * (1 + strengths * samplings + toys)
* seeds * fold_salts`. Inclusive baselines contribute zero trainings. Multiply
by the number of trained arms for the complete count. `budget.unit_seconds`
is the measured smoke wall per training. `budget.unit_timing` contains `rung:
smoke`, `trainings`, `wall_seconds`, `cpu_seconds`, and a `source` pin to the
executor smoke receipt with the same four values. The pinned backend plan must bind
that measurement and every dataset, reference, model configuration and training
pool. The timing source must represent the proposed training workload; pinning
a measurement does not establish that an extrapolation to a different workload
is valid. Create the timing with `ml_crossfit.measure_smoke(task, path)`. Its authority
record binds backend, architecture, feature count, configuration and epochs.
Handwritten timing JSON is refused. The 64-row computational pilot is a sizing
reference; it does not qualify extrapolation to a different data size.

`budget` also freezes `epochs`, `patience`, per-training `wall_seconds`,
`ceiling_seconds`, `max_trials: 1`, and `equal_across_arms: true`.
The producer ceiling comes from `run_ceilings.resolve(rundir)`; until that
provider lands the fixed section-13 default is 2700 seconds. A spec cannot raise
it. The preflight is printed before launch. A projection above the ceiling requests
`spend_above_ceiling`; even after approval, update and freeze the authorized
ceiling before launching. The ordinary stage supervisor supplies the hard wall.
The projection prices trainings. The hard ceiling also covers scoring, checks,
fits and I/O. Receipts report actual wall and CPU seconds, including failures.

Use one pinned NPZ population with `x`, `region`, `weight`, `event_id`,
`group_id`. Truth is forbidden in this NPZ. Declare feature names, `synthetic`,
`truth_column` (`truth` or null), and a separate `dataset.truth_pin` when labels
are available. The truth file contains only `event_id` and `truth`, covers all
declared populations, and lives outside the producer-readable `inputs/` tree. The feature matrix has
at most 100,000 rows and 64 columns; compressed and expanded inputs stay below
64 MiB. Combined ensemble scores are bounded at four million entries.
The producer role reads `inputs/ml-spec/` only. Worker dispatch must enforce that boundary
and evaluator access. Real-data cross-fitting is refused until that isolation is
qualified. A truth-supervised study cannot be an anomaly search; trained arms
are labelled ceilings and have no search statistic.

The split declaration freezes `k` (3–10), `group_column: group_id`, `salt`,
`fold_salts` (distinct; nominal salt first), `test_withheld: true`, and
`split_sha256`. Outer seeds vary initialization with folds fixed. Separate
salts measure fold-assignment variation. There are at least three outer seeds,
including small engineering fixtures. Each test fold uses every other fold as
validation in turn. Train and preprocessing folds exclude both. Every model's
group scope is pinned in a shared scope artifact; the receipt binds model,
rotation, initialization, history, checkpoint and scope. The audit recomputes
group intersections and minimum-validation-loss selection.

`inner_selection: {initializations: n, criterion: validation_loss}` is part of
the method. Every initialization's executed loss history survives, including
unselected candidates and completed trainings in a failed toy. NumPy supports
`logistic`, `quadratic_logistic` (linear features and all pairwise products),
and `mlp` with `widths` (one to four ReLU layers, at most 128 units each),
`learning_rate`, and a sigmoid head. Early stopping uses validation loss and
retains the best epoch. The equal-budget check compares actual training and epoch counts, and reports
measured wall and CPU totals per arm. Unequal executed epochs fail that check.
Arms may declare a `family`; its configuration count must respect `max_trials`.
The default family is the architecture. This does not assert equal FLOPs.

`supervision` declares `kind: truth | weak_region | mixture`,
`region_variable: region`, `derived_features`,
`regions: {signal: [lo, hi], sidebands: [[lo, hi], [lo, hi]]}`, and
`sideband_weighting: equal | population`. Intervals are half-open and disjoint.
Every event must belong to a declared region. The region variable, truth,
identity, weight and every declared derivative are forbidden features. Equal
weighting gives the two sidebands equal total training weight; population
weighting preserves their relative counts. A `mixture` also declares two
`fractions`; equal fractions produce `unidentifiable` with no performance claim.
`additional_windows` is an optional list of additional region dictionaries.
Their overlapping events remain the same independent population, and every
window enters the maximum-statistic trials accounting.

Preprocessing is `standardize` or `region_quantile`, always with
`scope: train_folds`. A quantile map declares feature indices in `features`
and `pool_features: true | false`. With pooling, the declared coordinates
share one empirical marginal reference within each region. The transform
artifact contains its actual training reference. Signal contamination changes
that reference; the fixture demonstrates this effect. No validation or test
group enters the transform fit.

`scoring` freezes `map: rank_on_reference`,
`reference: signal_region_test_events`, `aggregate: mean_over_rotations`,
`rerank: true`, and the full `working_points` list of data efficiencies.
Midranks keep tied scores together. Rotation ranks are averaged and reranked
against the same held-out signal-region population. The threshold `1 - efficiency`
is applied over the entire range, including sidebands; there are no per-bin
thresholds. An independent evaluation event is group-hashed to one test-fold
ensemble and averaged over that ensemble's validation rotations. Averaging
across all test folds would change its score distribution and is not used.
Ties can change achieved efficiencies; the receipt retains the scored population.

Baselines include `inclusive` (alias `inclusive_bump_hunt`, efficiency one,
no training), `supervised_oracle`, and synthetic-only `idealized_anomaly`.
Oracle rows always say "labelled ceiling; unavailable to a real search" and
never enter the search statistic. An oracle can declare an independent pinned
`training_pool` with both truth classes; this supports an oracle ceiling even
when the search dataset is background-only. Its groups must be disjoint from
the search population. Without that pool, both classes must exist in its train
and validation folds. The idealized arm removes truth signal from its sideband
reference and is explicitly a synthetic truth-reference arm.

`injection` declares `signal_pool`,
`partition: {method: group_hash, salt, injection_fraction}`, integer exact-count
`strengths`, at least three `samplings`, `draw: exact_count_by_weight`, and
`median_rule: median_signal_efficiency`. Draw without replacement; do not
invent additional independent events. Positive signal-pool weights enter the
draw probabilities and independent evaluation efficiencies. Sampled training
rows have the background's common unit-relative weight, so weights are not
applied twice. Unequal training weights and signed weights remain refused.
Every strength/sampling retrains every arm and fold. The evaluator accesses the
disjoint signal partition once per frozen model set. A pool contributes no
training rows from its evaluation groups. `localization_min` is a declared operational policy parameter, default 0.95;
it is not a physics constant. That fraction of supplied signal must lie inside
the frozen reconstructed window. A failure refuses admission before exposure.
The receipt reports each sampling, zero acceptance, median efficiency and,
when an independent background reference is supplied, efficiency improvement
`epsilon_signal / sqrt(epsilon_background)`, with both efficiencies measured
inside the same signal window. Medians are kept separate by window. Zero background acceptance gives
an undefined improvement, not infinite sensitivity. Correlated samplings and
repeated seeds are not independent power trials.

`null_calibration` freezes `toys`, `scope: whole_procedure`, a `datasets` pin
for each independent toy, optional `claim_below`, and `unblind`. The executor
supplies no invented null law: the study supplies and justifies these toys.
Every toy receives new folds, fitted transforms, trainings, rank references,
thresholds and the declared sideband fit. Failed toys are retained as extreme.
Use `(1 + extreme_toys) / (N + 1)` and refuse a requested claim below `1/(N+1)`.
The test suite contains independent synthetic ensembles with a declared
one-sided false-fail probability; it does not certify an experimental null law.

The bounded fit is `log_linear` with explicit bin edges aligned to all region
edges. It integrates an exponential density over bins, fits Poisson sideband
counts, and computes a signal-region residual including fitted-background
variance. That residual is a diagnostic statistic, not a Gaussian significance.
Null toys calibrate the maximum over all declared non-oracle arms, seeds,
salts, windows and working points. More complex fit families require a new
executor extension and their own calibration.

`checks` declares `permutations`, `alpha`, `sideband_bins`,
`max_spurious_z`, and an optional independent background `reference` pin.
Computed receipts contain sideband feature separability (mean and quadratic
moments), per-fold efficiency-flatness permutations combined by Bonferroni on
the minimum p-value, followed by the declared trial correction. Insufficient
permutation resolution is unresolved. Checks include independent-reference spurious
signal, joint feature/resonance sideband fidelity, and sideband fit adequacy.
Score/resonance correlation is computed in the sidebands and is diagnostic only. The permutation controls
require one independent row per group; grouped repeats yield unresolved checks.
Finite moment checks cannot prove arbitrary distributional independence, and
no sideband-only check can exclude a signal-region-only shift. A missing or
mismatched reference limits the claim.

The spec freezes every configuration before exposure. Admission checks the full
pairwise identity matrix, pool purity and size, localization, counts, fold
support, cost provenance and required active gate providers. Missing providers
for `unblind`, `spend_above_ceiling` or `bespoke_calibration` refuse before claims.
The current read-only decision-gate interface supplies no authenticated record writer.
Unblind requests therefore finish with a blocked gate and `complete_blinded`;
no self-authored verdict dictionary can authorize a statistic. Failed or
unresolved blocking checks also prevent an unblind request.

Cross-fit checkpoints, transforms, rank references, nominal scores and injection
inference arrays remain in `ml_custody` evaluator memory. They are never written
to outputs. Receipts contain opaque sealed pins, no rank values, no observed
statistic and no pre-unblind truth AUC. `unidentifiable` suppresses injections,
medians, summaries and every performance field. Real-data truth AUC is unavailable.
The sealed store has a 256 MiB bound. A process exit loses it: external validation
then refuses rather than accepting an unreconstructible receipt. Worker dispatch owns a
future durable store the producer cannot read; directory naming is not isolation.

The schema-2 validator replays frozen checkpoints and recomputes nominal scores,
fold maps from pinned identities, check verdicts, disposition, complete toy
statistics, injection metrics, window medians and summary fields. It checks
receipt pins in both ledgers; a receipt without its written, ledger-pinned file refuses. Missing artifacts or incomplete failed-toy model
populations refuse validation. `resume_frozen(task, base, output_dir)` re-scores
completed freezes as ledger class `replay`, without training or incrementing the
original exposure count. Unfinished folds remain unresolved. This supports
interruption diagnostics within the evaluator process; it cannot resume training
or survive process loss without durable evaluator custody.

`check:ml-null-execution` records toy completion. Null calibration stays unresolved
until the research-protocol record supplies pinned toy-law provenance and accepted nominal/toy
exchangeability evidence, with at least `ceil(1/alpha)` toys. A reference spurious
signal alarm uses a trial-corrected threshold and the declared bound of four;
The executor also calibrates the maximum absolute reference residual across
all rows using whole-procedure toys, with failed toys counted as extreme.
Insufficient resolution or missing toy-law acceptance stays unresolved.
Near-exact truth proxies raise the noise-ceiling alarm; absence of that alarm is
not a leakage certificate. Constructed invariants are labelled
`asserted_by_construction`, never a measured pass.

Optional `injection.closure` uses `estimand: conditional_fixed_background`,
`alpha`, `false_fail_probability`, `min_power_gain` and `max_null_rejection`.
Admission computes the minimum sampling count needed even for perfect separation
and refuses unreachable precision; the reference cap is 1024 samplings. Exact
binomial intervals condition on the background, signal pool **and toy ensemble**.
They do not include toy-threshold uncertainty or establish unconditional power.
The executor accepts only `claim_kind: diagnostic` (the default).
`method_performance` refuses until the research-protocol claim contract is implemented.

Dispositions remain `assumption_violated`, `limited`, `supported_synthetic`, or
`unidentifiable`. `status: passed` means the operation completed. It does not
accept its assumptions or scientific claim. Current provider boundaries prevent
claim-bearing or real-data operation.

## Review corrections and integration boundaries

An untrained three-file baseline is
`{id, kind: cut_based, spec: {feature, threshold, direction: above | below}}`.
It does not call `fit`; its receipt records zero epochs. Trained configurations
accept either inline JSON or a configuration pin. Optional `code` pins must
match the installed allowlisted backend. Arbitrary custom code, accelerator
execution (`mps`, `cuda`) and remote placement are refused: these need qualified
backends and isolation. This is an explicit narrower device/code policy than
the broad agent interface.

The three-file receipt retains its arm-first `summary` for existing consumers
and adds `summary_by_metric` to expose the metric-first view. Cross-fit summaries
are metric → arm → window, with seed and fold-salt spreads separately named.
Three-file calibration is to truth labels; weak cross-fit ECE/Brier calibrate
region labels, not signal probability. Over signal-region scores they measure
the search itself, so they stay `blinded` (null values) until the unblind gate
passes. Truth AUC remains withheld until an authenticated reveal on synthetic data.

A failed attempt can retry only when every claimed role has zero reads.
A training read already spends its population even if the test remains unopened. Backend-plan input paths resolve relative to the spec
directory. ROC/reliability curves sit above the frame and run the house figure
lint before saving.

`src/ravel/data/ml/ml-traps.json`, `role-cards.json`,
`research-protocol-ml.json`, and `handbooks.json` began as merge fragments; file
presence registers no capability. The role registry now holds the three ML cards
(the trainer and reviewer converted from `role-cards.json`, which stays as the
original record). The knowledge atlas indexes the five `hb:ml-*` handbooks, the
`ml.study` stage checks and the cross-fit receipt checks as `check:ml-*` rows.
The `trap:ml-*` and study premises and the research-protocol stages are not yet in
their central registries, so no premise fires from them. Observable support, trigger plateau, independent physics review,
formal injection closure and mechanism ablations remain required external
checks for their claims. The executor supplies no evidence for those facts.

The adapter's `run_in_worker` hook supplies the admitted run root to decision
gates and checks its attempt number. Dataset and configuration pins still resolve
against the original specification directory. These directories need not be the
same; a gate must never search the external spec directory for run approval.

## Governed method-study graph

`ml.study` v2 is registered with run scope and instance `{"study": "<family-id>"}`.
Its S1–S16 nodes require the named protocol checks. The planner and designer use
`graph_nodes.agent`; the host supplies their governed worker specifications. Role
doubles from `ml_role_factory` are honoured only in the test lease domain.

Verdicts are computed, never taken from the executor. The graph computes the checks it
owns from its records and the exposure ledger: estimand, partition purpose, equal budget,
replicate count, test-once, query ledger, confirmation set, freeze order, confirm scope and
ablation arms. Every other check is recomputed by a registered validator
(`BuildContext.extras["ml_validators"]`, with an `identity` and `validate(check, artifact_bytes,
context)`) from the artifact the executor pins for it inside the study scope. A literal verdict
without a pinned artifact, or a check without a validator, is `missing` and blocks. Only the
versioned requirement matrix (`ml-requirement-matrix-1`, keyed on task class, claim kinds,
split method and arm roles) marks a check `not_applicable`, with its reason. Stage results with
missing, failed or unresolved checks cannot open confirmation.

The graph contract declares `study_id`, `synthetic`, `task_class` (`supervised_tagger`,
`weakly_supervised_search`, `regression_calibration`, `surrogate` or `method_study`),
`claim_kind`, `claims` with estimands, exactly one `metrics.primary`, `arms` with
baseline/candidate roles and component definitions and no arm-level budget, paired `seeds`,
`rung`, an equal `budget` with `max_select_queries` and `cpu_seconds_per_replicate`, the pinned
`split_manifest` whose digest is `split_sha256`, the pinned `confirm` population and
`placement.local: true`. Attribution (`scope: joint_confirm`) is required for a mechanism claim
and optional otherwise. Performance claims need at least five paired replicates. Three are
admitted only for a diagnostic smoke rung. Interval and coverage claims are refused. Remote
placement holds until the owner decides where remote work runs. Separately reserved
attribution samples are refused until the staged executor supports them.

The split manifest is JSON with `kind: ml-split-manifest`, `method`, `provenance.class`
(`synthetic` or `observed`, which must equal the declared `synthetic` flag) and partitions
`train`, `validation` and `confirm`, each with its file `pin`, `event_ids` and `group_ids`.
Partition identities come from these lists; no partition file is read to compute them.
The `confirm` partition pin must be the study's `confirm` pin.

The graph generates remove-one, controls-only, declared remove-set and optional
add-one descriptors. The staged executor compiles them into model specifications.
They train with the study budget before selection freezes. Before training,
`training_start` claims train, validation and confirm in one ledger transaction under a
token persisted in the study's `exposure-claim.json` record, charges one `train` read for the
train and validation populations against the study's `training-freeze.json` record, and appends
the spec digest to the hypothesis family's trials record under the machine state root.
A re-run of the same specification resumes its own unread claim. Arms × seeds fan out
through `map_node` into `ml.study_item`; each request carries the study budget. Training
and attribution items take the process lock and the shared machine lease; production lease
acquisition requires the actual supervised stage binding. A launch-gate refusal is a hold
that names the provider and its cause, never a training failure.

The replicate census after training requires, for every arm, one `ok` replicate per seed
whose receipt reports `cpu_seconds` within the cap. Otherwise the study reports its failures
and does not select. Selection names whole arms, includes every baseline arm, never a
ceiling, and pins a query ledger with one entry per evaluator response; its `queries` must
equal the ledger length within `max_select_queries`. The graph expands each selected arm to
all its replicates.

Selection records precede the spec freeze. S4–S11 validation and the spec freeze precede the
`unblind` request. The unblind action carries the spec digest, the validation pin, the
freeze, the selected arms, the unblinded batch and whether the data are observed. The
confirmation effect rechecks the gate, resumes the pre-training claim and charges the single
confirm read before anything decodes the confirm file; the file's identifiers must then
equal the manifest, or the attempt fails and stays spent. The batch is the selected arms'
and ablation arms' checkpoints only. The evaluator result has a closed schema and scores
exactly that batch. S13 consumes the returned joint scores and never opens confirmation
again. S15 declares its `withheld_reads`; each is recorded as a replay. A spent or
unresolved exposure produces a typed hold. Completed graph effects reuse their original
receipts. S16 for `method_performance` needs R3 evidence: on synthetic manifests a machine
R3 case suffices; on observed data the RDJ receipt authorizing the final action must be R3
with a recorded human approver.

Host integration uses `BuildContext.extras["ml_executor"]`, a trusted executable
interface with an implementation/environment `identity` and these methods:

- `stage(stage, request, required_checks)` pins one artifact per check under `artifacts`; its verdicts are not read.
- `worker_spec(role, request)` returns the governed worker specification for the planner or designer.
- `binding(scope_root, item)` returns the verified supervised-stage lease binding.
- `train(request)` trains only; it receives no confirmation pin. A known failed execution returns a failed receipt.
- `select(request)` returns the selected arm IDs, `queries` and the pinned `query_ledger`.
- `confirm(request)` is evaluator-owned and returns `test_reads`, `reported`, `verdict` and `scores` for exactly the frozen batch.
- `attribute(request)` consumes the joint scores without another read.

These objects are supplied by the host, never by checkpoint or request data.
They must preserve producer/evaluator credentials, read scopes, environment locks,
all-role exposure accounting, query journal custody and the protocol's R2/R3
receipts. Synthetic controls may supply inert role and evaluator doubles.

The merged `ml_training.run` trains and opens its test population in one atomic
call. It supplies no training-only or staged evaluation interface and must never
be used as the per-arm fan-out operation. Without the staged host interface,
`ravel graph run --scope-root <run> --graph ml.study --instance <instance-json>
--input <input-json>` holds before dispatch. The graph does not manufacture
missing checks, query-journal evidence or statistical acceptance. Its synthetic
suite qualifies graph control flow; native method-study execution remains a
consumer handoff until the staged interface is provided.
