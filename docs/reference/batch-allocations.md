# Running studies in batch allocations

On a Slurm cluster RAVEL runs one complete study per batch allocation. The driving agent and
RAVEL both run inside one Slurm job, and inside it RAVEL behaves as on a laptop: a local stage
supervisor, local custody and the allocation's CPUs. Many studies run in parallel as separate
jobs. Nothing heavy runs on the login node.

This page uses one university Slurm cluster as the example. The commands are the same on any
Slurm site; only the account, partition, modules and paths change.

## What the allocation changes

- **The machine lease is per allocation.** The home directory on a cluster is shared by every
  node, so an unscoped lease in it would allow one native scientific job on the whole cluster.
  Inside a Slurm job the lease lives in `~/.local/state/ravel/machine/scopes/slurm-<cluster>-<job id>/`
  (`slurm-<job id>/` where Slurm sets no cluster name).
  RAVEL selects that location only when `SLURM_JOB_ID` is set and the process's cgroup names that
  job. On a Linux host whose home is on a network file system and that is outside an allocation,
  the lease is per host (`scopes/host-<host name>/`). Each scope still runs one native scientific
  job at a time. `python -m ravel.workflow.machine_lease` prints the holder and the current
  `scope`.
- **User-wide records stay user-wide.** Custody and the ML exposure ledger stay in
  `~/.local/state/ravel/machine/` (`machine_lease.machine_state_root()`). They are shared by every
  allocation, so a withheld test split read in one job counts in every other job.
- **Receipts name the allocation.** Every stage attempt under an allocation's lease records
  `allocation` (cluster, job id, node list, partition, account, CPUs) in its execution record.
  The launcher writes `logs/allocations/slurm-<cluster>-<job id>/allocation.json` in the run.

## Approval stays a human step between allocations

The launcher never records an approval. A study normally takes two allocations:

1. **Planning** (`--rung none`): the agent runs intake, resource sweep and the plan, then stops
   at CHECK-IN 1. The run has no approval, so the machine lease refuses every heavy stage.
2. The physicist reads CHECK-IN 1 and approves it on the login node (`ravel approve ...`), as on a
   laptop.
3. **Execution** (`--rung smoke|full|scan`): the launcher verifies the approval for that rung
   through its route (`--route checkin1`, `native-plan`, `science` or `likelihood`). It verifies it
   when it writes the request and again when the job starts. The request carries digests of the
   approval files, so an approval that changes or is withdrawn while the job waits in the queue
   refuses the job before the agent starts.

## One-time human steps on the cluster

Agents never handle credentials. These steps are done by the owner, interactively:

1. Install the agent CLI under your own account on the cluster, for example Claude Code with
   its native installer from a login node: `curl -fsSL https://claude.ai/install.sh | bash`.
2. Choose a configuration directory on the shared home, for example
   `export CLAUDE_CONFIG_DIR=$HOME/.claude-ravel`. Run `claude` once in that shell and log in.
   Compute nodes see the same home, so every allocation reuses this login.
3. Confirm that compute nodes reach the provider. On the example cluster, compute nodes reach
   `api.anthropic.com`, `pypi.org` and `github.com` without a proxy.
4. Install RAVEL and its native toolchain once into project space (`scripts/setup/install.sh`
   with `--jobs` equal to the CPUs of the install job). A checkout for a new commit can reuse an
   existing native prefix with `--prefix`.

## Submitting a study

From a login node, in the RAVEL checkout's virtual environment, and with the study directory
already created (`ravel initiate ...`):

```sh
ravel site study-job submit --rundir /vast/projects/<project>/<me>/runs/<run> \
  --account <account> --partition genoa-std-mem --cpus 16 --time 720 \
  --rung none --prefix /vast/projects/<project>/<me>/ravel-native/<build>/prefix \
  --module apptainer/1.4.1 --claude-config-dir $HOME/.claude-ravel \
  --collect-to /vast/projects/<project>/<me>/collected \
  -- claude -p "$(cat prompt.md)" --model claude-opus-5-5 --permission-mode acceptEdits
```

- `--rundir` must exist. The request carries its run id: the task contract's or identity
  record's `run_id`, or the custody path key for a run without one.
- `--cpus` and `--time` (minutes) form the resource request. The example cluster derives memory from CPUs, so
  the script passes no `--mem`. `RAVEL_JOBS` is set to the allocation's CPUs, so builds never
  oversubscribe the slot.
- `--prefix`, `--module`, `--venv` and `--checkout` set up the environment. `--env NAME=VALUE`
  passes ordinary variables and refuses names that look like credentials.
- `--collect-to` copies the run directory there, as `<run directory name>-<run id>`, when the agent ends.
- `--dry-run` writes `logs/allocations/requests/<id>/request.json` and `study.sbatch` without
  submitting them.

Inside the job, `ravel site study-job run --request ...` checks that it is inside the allocation.
It re-verifies the run and the approval, writes the allocation receipt, and runs the agent
command in the study directory with its output in `agent.log`. It forwards Slurm's termination
signal to the agent's process group. At the end it copies this allocation's lease records into
`lease-scope/`, removes the finished scope and collects the run. The job's exit status is the
agent's.

Watch and stop studies with Slurm itself (`squeue -u $USER`, `sacct -j <id>`, `scancel <id>`).
Cancel only jobs you submitted, by id.

## Limits

- The lease scope separates allocations, not processes the scheduler did not place. A process
  started on a compute node outside any job uses the host scope.
- The allocation is one node (`--nodes=1`). Studies that need many nodes use the `site` backend
  from inside the allocation (see [execution backends](execution-backends.md)). Those jobs are
  remote slots, not this lease.
- `ravel doctor --profile site` checks lxplus requirements (CVMFS, grid proxy, HTCondor) and
  does not pass on a Slurm facility without them. Use `ravel site doctor --profile generic` there.
