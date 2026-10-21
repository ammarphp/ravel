# Execution backends

A supervised stage can run in four places:

| Backend | Runs on | Use it for |
|---|---|---|
| `native` | this machine, as a subprocess | tools installed on the host (MadGraph, Pythia, Delphes, Rivet, Python analyses) |
| `oci-local` | this machine, in a podman container | Linux-only tools on macOS (MCFM, Combine, AnalysisBase) |
| `site` | an HTCondor or Slurm cluster | large or many jobs on an analysis facility |

The approval, CHECK-IN and recovery rules are the same for all four. Choose the
backend at CHECK-IN 1 from what the stage needs: the platform the engine
supports, the expected wall time, and the sites you have access to.

## How a backend stage works

1. Write a stage specification (JSON) and pin it as a plan:

   ```sh
   ravel backend prepare --spec stage.json --out inputs/backend-plans/stage-plan.json
   ```

   The plan records the image digest, the source commit, the sha256 of every
   input, the declared outputs and quantities, the resource ceilings, and the
   backend's own identity (client path and sha256, scheduler commands, site).
   Its digest changes when any of these change.

2. Run it as a supervised stage:

   ```sh
   python -m ravel.workflow.stage_supervisor --stage generate --rundir RUN \
     --log logs/generate.log --kill-secs 7200 --required-plan full \
     --backend-plan inputs/backend-plans/stage-plan.json
   ```

   A backend stage launches only with an approval. Under a CHECK-IN 1 rung the
   plan must sit in `inputs/backend-plans/` (or be the placement pin
   `inputs/backend-plan.json`) before approval: these files are approved inputs,
   so a plan written later invalidates the approval. A backend stage driven by
   the worker of an approved stage (`backend_driver.drive_stage`) runs nested in
   that stage's job instead. Everywhere else the supervisor refuses and starts
   nothing.

   The supervised command is the backend worker; the plan file is a pinned
   input. The worker reads the plan's bytes once, refuses them unless they equal
   the attempt's pinned input, and keeps them as the attempt's `plan.json`, which
   the payload's custody chain checks. The stage fingerprint therefore changes when the image, site or
   resources change, and an earlier receipt is not reused. A native execution
   plan or scientific study declares the same worker command
   (`ravel.workflow.stage_supervisor.backend_stage` returns it).

3. The worker writes `backend-handle.json` in
   `logs/execution/<stage>/<attempt>/backend/` before it dispatches anything,
   then follows the job, streams its log into the stage log, and fetches the
   outputs when the job succeeds.

Outputs arrive in a fresh staging directory inside the attempt, are hashed, and
are checked: every declared output must exist and every requested quantity (for
example the number of events or the cross section) must be present. Only then
are they moved to their destinations. An existing destination is never
replaced. A job that exits 0 without its outputs fails the stage.

## Stage specification

```json
{
  "schema_version": 1,
  "backend": "oci-local",
  "stage": "amplitude-points",
  "argv": ["/opt/tool/bin/run", "/ravel/input/card.ini"],
  "inputs": [{"path": "inputs/card.ini", "mount": "/ravel/input/card.ini"}],
  "readonly_trees": [{"path": "/data/lhapdf", "mount": "/opt/lhapdf", "env": "LHAPDF_DATA_PATH"}],
  "outputs": [{"name": "result.json", "destination": "outputs/result.json"}],
  "quantities": [{"name": "cross_section_pb", "output": "result.json", "pointer": "/cross_section_pb"}],
  "resources": {"cpus": 4, "memory_mib": 8192, "wall_seconds": 14400},
  "image": {"reference": "registry.example/tool@sha256:<64 hex>", "platform": "linux/arm64"},
  "env": {"OMP_PROC_BIND": "true"}
}
```

- `argv` writes its outputs to `$RAVEL_OUTPUT_DIR`; each output `name` is
  relative to it. `destination` is relative to the run directory. A `site`
  output can instead name a `remote_uri` (for example an EOS path); the job
  copies it there without overwriting, and the receipt records its size.
- Images must be pinned by digest (`name@sha256:...`) or by a local image id.
  Tags such as `:latest` are refused. A `source` block needs a full commit SHA.
- `env` names that look like credentials (`TOKEN`, `SECRET`, `PASSWORD`, `KEY`)
  are refused. Credentials stay in each tool's own configuration.
- `resources` are ceilings: podman and the batch schedulers enforce CPU and
  memory; the worker enforces the wall time for every backend.

Resource scope is explicit. The local container adapter sets and verifies its
aggregate memory boundary and task limit (`resources.processes`, default 4096)
against the created container. It refuses `disk_mib`: writable bind mounts and
retained input/attempt copies have no cumulative quota or receipt-headroom
reservation. Scheduler `disk_mib` requests concern job scratch and depend on site
policy; they do not bound cumulative retained run storage. An explicit process
limit holds on adapters that lack its enforcement.

Generic local launches and the standalone native backend carry `RESOURCE
PROTECTION INCOMPLETE`. Their default is an explicitly narrowed support contract:
no aggregate memory/process/disk safety or reserved receipt headroom. Linux's
legacy `memory_mib` in a confined launch controls per-process address space;
cooperative thread variables on other hosts are not an aggregate CPU boundary.
The operator can require retained-storage protection with `--budget
retained_disk_bytes=N`; the generic launcher refuses that requirement rather than
discarding it. Select an execution adapter separately qualified for every required
guarantee. These labels stay in place until an enforcing action, such as a generic
aggregate monitor with a filesystem reservation, supplies that evidence.

Publication source payloads stream through acquisition and digest-bound member
adoption. Original logical paths and source bytes are retained, including offline
table/model files. The member index has an 8 MiB metadata ceiling and at most
32768 filesystem entries; it contains no encoded payloads. Record/index metadata
has a separate 16 MiB ceiling. JSON payload validation keeps bounded grammar/key
state and small description/identifier summaries while arrays and skipped strings
stream; explicit parser-limit or malformed-input failures refuse the handoff.
Copy admission is serialized through retained writes, rechecks current authority
and space, and records its accounting. It still supplies no kernel storage quota
or physically reserved receipt headroom.

## Capacity

Every supervised local launch takes the machine lease, so one native scientific
job runs on this machine at a time. A second launch waits for the lease, up to
`RAVEL_LEASE_WAIT_SECONDS` (one day by default) capped by the stage's wall-clock
ceiling, and is then refused.

- **One location per machine.** The lease lives in a fixed per-user directory,
  `~/.local/state/ravel/machine/` resolved from the user database, not from
  `HOME` or `RAVEL_STATE_DIR` (`native-job.lock`, `native-job.json`,
  `native-job-fence.json`). Every worktree, test and placement environment shares this lease. User-wide stores (custody, the ML exposure ledger) use
  that directory through `machine_lease.machine_state_root()`; machine locks use
  the lease root, `machine_lease.machine_dir()` and `machine_lease.machine_lock(name)`.
  On a cluster the lease root is scoped: inside a Slurm allocation (`SLURM_JOB_ID`
  proven by the job's cgroup) it is `scopes/slurm-<cluster>-<job id>/`, and on a
  Linux host whose home is on a network file system it is `scopes/host-<host>/`.
  Each scope runs one native scientific job at a time, and every attempt under a
  cluster scope records its `allocation`. See
  [running studies in batch allocations](batch-allocations.md). A test
  lock domain (a directory carrying the `ravel-test-machine-domain` marker) is
  selected only inside the process of the test harness or a selftest; a child
  process reaches it only through `RAVEL_TEST_DOMAIN_GRANT`, which the issuing
  process validates when the child asks. No variable or marker file selects it.
  The retired `RAVEL_TEST_MACHINE_DIR`, an unvalidated grant and the test
  runner's `PYTEST_CURRENT_TEST` without a grant are refused outright, so such a
  process uses neither a test domain nor the machine directory.
  `python -m ravel.workflow.machine_lease` prints the holder, its lock domain and
  any fenced jobs.
- **Only for an approved stage.** A fresh lease needs the binding of an approved
  stage: the run, the stage and its approval route (CHECK-IN 1 at a compute rung,
  an approved native execution plan, an approved scientific study or a scoped
  likelihood envelope), verified when the lease is taken. A plain command on an
  unapproved directory gets no lease and does not start. Every backend dispatch
  (`execution_backend.submit`, `backend_driver.drive`, `drive_stage`, the
  supervised worker, partitions and the native launcher) needs that lease or a
  proven delegation of it; an injected backend gets no exemption.
- **Approval checked at every dispatch.** Holding the lease is not enough. Each
  dispatch re-verifies the approval the lease was taken for, as it stands now:
  the CHECK-IN 1 approval at its rung, the native execution plan approval, the
  scientific study's approval receipt with its plan and inputs, or the scoped
  plan with its full CHECK-IN 1 approval. A revoked or changed approval stops the
  next dispatch even when the plan file is unchanged. The submitted plan is bound
  to that approval: either its exact bytes are a pinned input of the running
  attempt of the lease's own stage (the supervised backend worker), or the caller
  is the proven worker of an approved supervised stage (partitions and
  sub-stages, which derive their plans). A partition run's specification must be
  the stage's pinned specification file. A sub-stage plan new to its store is
  admitted only when every input lies in that store or is a pinned input of the
  approving stage, and its wall time fits the approved ceiling.
- **Bound to one job.** A process under the holder works under the lease only for
  the same job: the stage worker of the holder's stage (once), or a sub-stage
  nested in that worker's job inside the same run directory, a declared output of
  its stage, or an existing store that belongs to no run (for example an amplitude
  store); never inside another run. Delegations form one chain. A
  request for another run, a sibling, a second request from the same process and
  an unproven request are refused at once.
- **One computation per lease.** Each computation is reserved before it starts.
  A reservation is admitted only when every live computation of the lease is its
  own ancestor job, so two concurrent submissions under one lease are refused, and
  a partition that can still run keeps the next partition from starting.
- **Held for the life of the job.** Each computation is fenced before its first
  process exists, by three ties: its log file, opened and locked before the start
  and inherited by every job process as its output (the lock lasts while any of
  them keeps it, in any session or process group); the job token
  `RAVEL_JOB_TOKEN` in every job process's environment; and its process group with
  the leader's start identity. A new lease is refused while any tie holds, even
  when the holder was killed, so a payload that outlives its supervisor, leaves a
  background process, starts a new session or double-forks keeps the machine until
  that process is gone. A job or supervised stage succeeds only when no tie holds.
  A reused leader pid removes only that pid from the group census.
- **Operator recovery.** An unreadable fence record blocks the machine, and so
  does a row RAVEL did not write (not an object, or without a lease id and a tie).
  A fence entry with unresolved live/dead ownership evidence also blocks: a group
  recorded without a start identity, or a job token while the process census
  (`ps`) is missing. Unknown is not live: an operator clears such an entry
  with a recorded action, `ravel lease clear-fence --token T --reason TEXT
  --operator NAME` (or `--pgid N`, `--unreadable`, `--malformed`). The action is
  appended to `native-job-fence-actions.jsonl` with what was observed. It is
  refused while the entry's log is locked or a live process carries its token.
  Clearing an entry of a backend job also resolves that job's handle as
  `operator-cleared`, so the next launch of the stage is not blocked by it. The
  action is journalled in order: an `intent` row, the handle's resolution, the
  fence removal, then a `completed` row. If writing the handle fails, the
  fence entry stays, a `partial` row records the error, and the same command
  completes the action when run again.
- **Process ownership on macOS.** Native ownership checks use the recorded process group,
  standard streams and job token. A descendant that detaches from that group, replaces
  its streams and removes its token requires kernel containment for a complete census.
  Require that stronger containment when the payload can daemonise. Before each native job, run the read-only preflight:

  ```sh
  ravel lease preflight
  ```

  It lists every live process that carries the job token of a recorded job (a
  current fence entry or one an operator cleared) or belongs to a recorded
  process group, with its command. It signals nothing. It exits 1 when it lists a
  process, when the fence record is unreadable or holds a malformed row
  (`malformed_rows`), or when the process census is missing; stop what it
  lists before you start the next job.
  Cancellation signals only the job's own process group, and only while that group
  is provably the job's (its leader or payload keeps its recorded identity, or,
  with the leader gone, its log is still held and a live group member carries the
  job token or has the log open); a descendant in another session keeps the machine fenced and is
  named in the observation for the operator to stop.
- **Boundary.** The lease, fence and custody records are ordinary files of this
  user. They keep cooperating RAVEL processes from running two jobs or mistaking
  one job for another; they are not a defence against a hostile process of the
  same user.

Remote backends take one slot
under the remote ceiling, which is 1 until the owner sets another number with
`RAVEL_REMOTE_JOB_CEILING` or `~/.local/state/ravel/remote-ceiling.json`
(`{"max_jobs": N}`). Approval is still required for every remote job.

## Placing a science or scoped stage

A science (version 2, one attempt) or scoped specification can place its stage:

```json
"execution": {"backend_plan": {"backend": "native", "resources": {"cpus": 2, "memory_mib": 4096}}}
```

Planning writes `inputs/backend-plan.json`, makes the backend worker the
supervised command and shows the placement in CHECK-IN 1: backend, resources,
plan digest, the placement `env` and `readonly_trees`, and the lease wait bound.
Placement `env` must not set RAVEL control variables, `HOME`, `TMPDIR`, `PYTHON*`
or the runtime keys the payload verifies. A changed placement changes the plan
digest, so it needs a new approval. The wall clock is the
specification's `max_seconds`. The scientific worker runs as the job's payload
and proves its custody before it reads anything: the supervisor registered the
backend worker, the worker's handle records the launcher, the launcher is the
worker's child, and the launcher acknowledged the payload's process identity.
The payload keeps the approved runtime environment and writes into the
attempt's staging; the fetch hashes and moves the result to the declared output.
Placement supports the `native` backend; container and site placement of a
RAVEL worker require an authenticated payload identity before admission.

## Stopping and recovery

Stopping or killing the supervisor sends the worker a termination signal; the
worker cancels the job (`podman stop`, `condor_rm`, `scancel`, or
the native process group) and waits for a terminal observation. Every other exit
after dispatch (an error, the wall clock, a payload that left processes behind)
cancels the job too, and the supervisor cancels the native job itself after it
stops the worker. A job whose cancellation is not observed to finish stays
fenced on the machine lease. Native cancellation signals a process group only
while it is provably the job's (its leader or payload keeps its recorded start
identity, or its log is still held and a group member carries the job token or
has the log open),
and checks again before escalating to SIGKILL; a reused or unproven group id is
never signalled.

If the worker died after dispatch, the next launch of that stage is refused
until the earlier job is resolved:

```sh
ravel backend handles --rundir RUN --stage generate
ravel backend recover --handle RUN/logs/execution/generate/<attempt>/backend
ravel backend status  --handle ...
ravel backend fetch   --handle ... --base RUN     # for a job that finished
ravel backend cancel  --handle ...
```

`recover` finds the job by its tag and adopts it. It never submits again. For a
native launch whose dispatcher died before it recorded the launcher, `recover`
reads the launcher's record, or the identity the launcher's fence recorded, and
adopts the job. A launch that left no launcher record and no live process (no
held log, no process with its job token) never started its payload, because the
launcher starts the payload only after recording itself; `recover` marks it
`never-started` and drops its reservation. A launch that recorded nothing while a
process still holds its log stays unresolved until it ends or an operator clears
its fence entry, which resolves the handle. A submission that fails after the
launcher recorded itself keeps the launcher's identity in the handle, so the
worker cancels the job and recovery can observe it. The in-process driver and
partitioned execution do the same: a submission that fails after writing a job
identity is cancelled, and a partition whose cancellation is not observed to
finish stays unresolved instead of being retried.

Partitioned execution first checks that an existing work directory belongs to
the supplied specification (its digest and every partition's `inputs.json`);
nothing is fetched or saved before that check passes. It then reconciles
partitions an earlier run left running or unresolved before it selects work: a
job that ended is adopted (a success is fetched), a launch that started nothing
does not count as an attempt, a job an operator cleared is settled whether or
not its identity is known, and a job that can still run stays unresolved and is
never submitted over. A remote job that can still run is observed by the new
run with the deadline it started with, and its remaining wall time counts
against the approved ceiling before anything is admitted; a local one keeps
every other local partition from starting.

If the dispatch reservation outlived a launch that never started (the launcher
refused, or `submit` stopped a launcher that did not record itself in time), the
reservation is dropped once nothing holds the job's log or token. An entry that
stays unproven is cleared with the recorded `clear-fence` operator action
described under Capacity.

## Backend notes

**oci-local.** Podman runs with its own `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and
`CONTAINERS_CONF` inside `RAVEL_CONTAINER_HOME` (default
`<native build>/containers`), so your global podman setup is untouched.
Containers run with `--network none`, `--pull never`, all capabilities dropped,
and CPU, memory and PID limits. Inputs and declared trees are mounted read-only;
only the attempt's output directory is writable. An image for another
architecture is refused unless the plan sets `"emulation": true`.

```sh
ravel backend doctor --backend oci-local
ravel backend machine init --cpus 4 --memory-mib 8192 --disk-gib 40 [--execute]
ravel backend machine start [--execute]
ravel backend image-build --containerfile F --context DIR --tag localhost/name --receipt R.json [--execute]
```

Machine and image commands print what they would run until `--execute` is
given. Container recipes live in `native/containers/`
([MCFM](../../native/containers/mcfm/README.md)).

**Container launcher for native adapters.** An adapter that already owns its
native process can declare
`runtime.launcher`, written by `ravel backend launcher`. The same argv then runs
in the pinned image with the runtime trees mounted read-only at identical paths
and the working directory writable, so receipts and census stay valid on the
host. `ravel backend launch` runs one command the same way, for example an
in-container build. Without `--execute` it prints the command. With
`--execute` it runs only as a supervised stage of an approved run
(`--rundir RUN --stage NAME`, with the launcher pinned as a stage input) whose
approval still holds, and holds that stage's machine lease.

**site.** The job directory must be on a file system the batch nodes share
(for example, a shared filesystem). RAVEL writes `job.sh`, which runs the argv and records the
exit code, and `job.sub` (HTCondor) or `job.sbatch` (SLURM) with the resource
requests, the wall limit and the RAVEL tag. `site.options` adds scheduler
settings such as `+JobFlavour` or `partition`; RAVEL-controlled fields must not be
replaced. `ravel backend site-submit-file --plan P --job-dir D` prints the
submission for review. Check the site first with `ravel site doctor`.

## Partitioned execution

Large inputs (many ROOT files, many scan points) can run as partitions:

```sh
ravel partitions plan --spec partitions.json
# as the command of a supervised stage that pins partitions.json as an input:
ravel partitions run --rundir RUN --stage parts --spec partitions.json --workdir W --only p00000   # pilot
ravel partitions forecast --workdir W                                  # wall and core-hours
ravel partitions run --rundir RUN --stage parts --spec partitions.json --workdir W --merge
```

The specification lists the population (`members` with `path` or `uri`, and
optionally `entries` and `size_bytes`; a local `path` member needs
`checksum: "sha256:<hex>"`), the partitioning
(`members_per_partition` or `partitions`), a stage template whose `argv`
contains `{partition_inputs}` (a JSON file with the partition's members), the
outputs with their merge rule, `max_concurrent` and `max_attempts`.

Each partition is its own backend job with its own fetch receipt. A failed
partition does not stop the others and is retried up to `max_attempts`, each
attempt kept in its own directory. Merging requires every partition to have
succeeded and checks each output against its receipt. Merge rules:
`binned_values` (equal edges and units; values, `sumw2`, overflow and underflow
add; uncertainties add in quadrature), `cutflow` (equal region and cut order;
counts add), `counts` (equal keys; values add) and `none` (kept per partition).
Partition outputs must be unnormalized sums of weights; apply cross section,
luminosity and the full sum of weights after the merge.

`ravel partitions run` (and `run()` in Python) runs only as a supervised stage
of an approved run: it refuses unless it is the stage's registered worker, the
stage launch has its launch-authorization receipt, the approval still holds, and
the stage inputs pin the specification with the same bytes. The authority is
written into the partition ledger. In Python, `authority` names the run, the
stage and `spec`, the pinned specification file; the supplied specification must
match it. The approval bounds the work: the entries of attempts already spent in
the work directory plus the selected partitions times their remaining attempts
must not exceed the stage's approved events, and the selected partitions plus any
adopted remote job must fit its wall-clock ceiling. Each member checksum is verified before its partition is
submitted, and a resumed work directory's `inputs.json` files must match the
specification. With a local backend the partitions run one at a time under the
stage's machine lease; with `site` they use up to `max_concurrent` remote slots.
A partition whose cancellation is not observed to finish is marked `unresolved`
and is never resubmitted.

## Residual limits

These limits remain after the placement review and are accepted for this release:

- **Per-user lock domain.** The machine lease lives in the current user's state
  directory. Two different user accounts on one host each get their own lease.
- **Status probe and acquisition share a lock.** `ravel lease` (status) briefly
  takes a shared lock on the lease file. Even a no-wait acquisition waits at
  least 0.5 s for a probe to finish; a probe held longer than its wait makes the
  acquisition report the lease busy, and the caller retries.
- **Ancestor jobs are exempt from the one-computation check.** A reservation is
  admitted while its ancestor jobs are live. RAVEL does not prove that an
  ancestor only orchestrates and computes nothing itself.
- **A supervisor record with no child pid.** A stage record left `running`
  without a `child_pid` (the supervisor died between its record and the spawn)
  blocks the stage's next launch until an operator resolves it; backend-handle
  recovery does not resolve it.
- **Derived inputs are the worker's own.** A sub-stage plan whose inputs lie in
  the store is trusted as the approved worker's computation; RAVEL does not
  recompute those files from the approved inputs.
- **Wall-clock is not cumulative across partition runs.** Spent attempts count
  against the approved events; the wall-clock ceiling applies to each run's
  selected work and adopted jobs.
- **Test lock domain.** Selected in process by the test harness or a selftest and
  handed to children as a grant their issuer validates live. A same-user process
  that runs its own grant server can still answer a forged token; this is the
  same-user boundary of every record here, not authenticated isolation.
- **macOS detached daemons.** See the known limit under Capacity.
