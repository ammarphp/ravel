# Install RAVEL

The installer prepares the complete toolchain. The doctor reports installed components,
configuration requirements and runtime admission. Scientific qualification belongs to each study.

## Before you start

- **macOS** (Apple silicon or Intel, macOS 11 or newer): install the Xcode Command Line Tools with
  `xcode-select --install`. On Apple silicon, also install Rosetta 2 with
  `softwareupdate --install-rosetta`; the Combine and SimpleAnalysis images need it.
- **Linux** (x86-64 or aarch64): `curl`, `git` 2.19 or newer and `tar`. For the container tools, rootless
  `podman`, `docker` or `apptainer`.
- **Git on every platform**: git 2.19 or newer. The installer checks the first git on PATH.
  On macOS, use `PATH=/usr/bin:$PATH bash scripts/setup/install.sh` to put Apple's git first,
  or install a newer git.
- **Agent command line**: Claude Code 2.1.296 or newer, or the Codex CLI, on PATH. The doctor
  reports the worker transport's stored host qualification. Follow its `ravel transport qualify`
  command when qualification is missing. Update older Claude Code with `claude update`.
- **Disk and time**: the [README](../README.md#install) states the default installation's disk space,
  and `--dry-run` prints the size and time of each part of the target you choose. Put the tools on
  another volume with `--prefix /path/on/that/volume`.
- You do not need Python, conda or administrator rights. The installer brings its own Python.

## Install

```bash
git clone https://github.com/ammarphp/ravel.git
cd ravel
bash scripts/setup/install.sh
.venv/bin/ravel doctor
```

The default installs the complete released toolchain. Sources are pinned by commit,
archives by checksum and container images by digest. The installer shows the licences of
the tools it fetches and asks once before it continues (`--accept-licenses` answers for you).
A failed group blocks its dependent groups; every independent group continues. Licence
refusal and the install lock stop the whole run.

Useful options:

| Option | What it does |
|---|---|
| `--plan` | Print the ordered steps and change nothing. Before Miniforge is installed, the full list needs a Python 3.11 or newer on `PATH`; without one only the Miniforge step is printed |
| `--dry-run` | Print every action, the prefix, the size estimate and each network fetch, and change nothing (`--json` for a machine-readable list); it has the same Python requirement as `--plan` |
| `--profile site` | Install the Linux analysis-facility target instead of the default toolchain |
| `--only madgraph,lhapdf-sets` | Install these groups and what they need |
| `--prefix PATH` | Install the tools somewhere else (default: `native/build` in the checkout) |
| `--lcg-view PATH` | For `site`, choose an explicit LCG view path or `none`; `auto` lists candidates and refuses |
| `--adopt` | Keep existing conda environments and Git checkouts in the prefix instead of creating them |
| `--offline` | Take Miniforge and every archive from the download cache and refuse any that is missing; conda, pip and Git steps still use the network |
| `--jobs N` | Build with N parallel jobs (default: half the cores) |

| Target | Contents | Disk and time |
|---|---|---|
| `default` | Every released tool and its dependencies | Printed by `--dry-run` |
| `site` | Python host, isolated hash-locked Snakemake and cluster-generic, facility checks, PDF/graph tools; pyhf statistics | Printed by `--profile site --dry-run`; caches and both site environments sit under the chosen work prefix |

`site` is the only named profile. On a Linux analysis site, install it in a
work area with enough space:

```bash
bash scripts/setup/install.sh --profile site --prefix /path/to/work/area/ravel-tools --lcg-view none
```

## What gets installed

The installer prepares Python environments, native scientific programs, source-bound
agent tools, PDF, graph and SVG tools. AgentRivet and SFitterAgents are part of that
installation. RAVEL calls separately licensed GPL programs across process and file
boundaries; their sources and attribution remain separate from the Apache Python package.

Some tools run on Linux. On a Mac the installer uses a Podman virtual machine inside
the prefix for the Combine and SimpleAnalysis images and the MCFM amplitude program;
on Linux x86_64 the MCFM program is compiled on the host.
Facility environments run on the facility itself. Use `--prefix /path/to/volume/ravel`
for a larger volume or `--adopt --prefix /path/to/existing/toolchain` to retain installed tools.

## The governed runtime

The controller (`ravel ask` and `ravel drive --request-file`) runs only RAVEL code that your user
has read-only access to: a read-only installation or a sealed copy. A user-writable installation such as `.venv`
is neither, so the installer ends by sealing the installed package with
`.venv/bin/python -I -m ravel governed-runtime seal`. The seal copies the package into a read-only
runtime in the controller home, `~/.local/state/ravel-controller/runtime/<id>/`, named by the first
16 hex digits of the package's tree digest. It byte-compiles the copy and records its digests,
version, source, distribution and interpreter in `SEAL.json`. It writes the launcher `bin/ravel`
beside the copy, removes every write bit and names the runtime in `runtime/CURRENT`. When
`.venv/bin/ravel ask` or `.venv/bin/ravel drive` finds that the current runtime holds the same bytes,
it re-executes itself through that launcher with the same arguments. Otherwise it refuses before it
creates a run and names the fix.

After upgrading or reinstalling the package (for example with
`python -m pip install -r requirements-full.txt`), run `.venv/bin/ravel governed-runtime seal` again.
Sealing the same bytes again reuses their runtime. `ravel governed-runtime status` shows the current
runtime, whether it holds the installed package and what controller admission decides; `ravel doctor`
reports the same decision as `controller_admission`.

What the seal protects against: the controller home lies outside every worker's sandbox, so worker
writes stay outside the sealed copy, its seal record and the pointer to it. Every controller admission
recomputes the copy's source and bytecode digests and compares them with the seal before a run starts
or resumes. The removed write bits guard against accidental edits only: a process that runs
unconfined as your user can restore them, and the next admission then refuses the changed copy.

## Check the installation

```bash
.venv/bin/ravel doctor
```

The doctor checks every tool in the default toolchain (use `--profile site` on a facility or `--group madgraph` for one group)
and prints one line per problem with the exact command that fixes it. `--json` gives a
machine-readable report and a failed requirement exits with status 1. `--strict` is accepted for existing scripts.
Every report also runs the controller's identity check on the code `ravel ask` would run (the
[governed runtime](#the-governed-runtime) when it holds the installed bytes) and reports it as
`controller_admission`: `ready`, or `not-ready` with its fix. A refusal makes the report not ready.

| Status | Meaning |
|---|---|
| `ready` | Installed and the right version |
| `missing` | Run the fix command to install the component |
| `version_mismatch` | Installed, but a different version from the pin |
| `unconfigured` | Needs your configuration or credentials (for example an API key) |
| `manual_required` | Needs something you install yourself (see below) |
| `remote_route` | Runs on a Linux facility, not on this machine |
| `conflict` | Two tools that must stay separate point to the same file |

With `--json`, the report names the `profile` and its `expected_groups`, counts groups per label in
`summary`, and every group also carries a `label` (`ready`, `not-ready` with its `fix`, `owner-action`,
`remote` or `unsupported`) and an `installation` observation. Installation records do
not qualify numerical operations: `qualification` stays `built-unqualified` unless a
declared failure, exclusion or missing build narrows it further. `qualification_scope`
is empty in the installation report. Readiness still means the selected setup checks passed.

For a read-only comparison of a supplied operation receipt, use
`ravel.setup.qualification.compare_receipt(receipt, request)`. The request supplies
`scope` and `output_format` (`json` or `jsonl`); scope binds `tool`, a named `versions`
map, `platform`, `operation` and the exact tested `conditions`. The receipt supplies
`schema_version: 1`, the same scope and a nonempty `checks` list. Each check supplies
`name`, `status` (`passed`, `failed` or `not_run`) and `evidence` (`path`, `sha256`).
Missing inputs have reason `missing_qualification_input`; mismatched versions,
conditions or evidence bytes are refused. A `matched` result preserves this scope
and grants neither launch nor scientific acceptance authority. Scientific qualification
still requires executed reference comparisons and the ordinary review lifecycle.

Ordinary doctor checks are read-only. The installer preserves agent-host configuration and
leaves Wolfram AgentTools deployment to the operator. The installer records a digest of `~/.codex/config.toml` and
`~/.claude/settings.json` at the first install; the doctor warns when one changes, and
`ravel doctor --record-host-config` accepts the new state. It reads the Wolfram version without activating it, checks
that an API key variable is set without reading it, and does not start virtual machines.

## Things you do yourself

The installer never handles licences, passwords or administrator actions. The doctor tells you
when one of these is missing:

- **Wolfram**: FeynRules, SARAH, FeynCalc, FeynArts and FlexibleSUSY need a licensed Wolfram
  kernel (Mathematica or the free [Wolfram Engine](https://www.wolfram.com/engine/)). Activate it
  with `wolframscript -activate`, then rerun the installer to finish the symbolic tools. The doctor
  checks the activation and loads FeynRules, SARAH, FeynCalc and FeynArts, each in a fresh kernel. Without a
  kernel, Wolfram-backed operations are held with a message naming it, and each lists its fallback (a supplied
  model, a pregenerated spectrum or a Python evaluator).
- **TeX** for manuscripts: install TeX Live with the full scheme (it includes REVTeX), or use an
  existing full-scheme installation. In the prefix's `bin` directory, put `pdflatex` and `kpsewhich`
  wrappers that set `TEXMFHOME` to the prefix's `share/texmf` and run that installation's programs.
  Springer Nature's `sn-jnl` class is not on CTAN: take it from the publisher's
  [LaTeX template package](https://www.springernature.com/gp/authors/campaigns/latex-author-support)
  and place it in that `TEXMFHOME`. `ravel doctor --group tex` checks `pdflatex`, REVTeX and `sn-jnl`.
  Collaboration and other publisher templates come with each manuscript; record them with
  `python scripts/setup/publication_runtime.py --inventory DIR`.
- **Facility access**: grid proxy (`voms-proxy-init`) and Kerberos (`kinit`). ServiceX queries take their
  HTTPS endpoint, and the environment variable that holds the access token, from the `service` block of the
  operation's own configuration; RAVEL ships no endpoint and does not read `servicex.yaml`. A query
  that names no endpoint is refused ([the supplied contract](reference/dataset-query-quantities.md)).
- **Model access** for research and review roles (next section).

## Choose models and providers

Run setup from an operator terminal after installing a model CLI and logging in,
or configuring the environment variable named by an HTTP transport declaration:

```bash
source .venv/bin/activate
ravel operator init --mode physicist-in-the-loop
ravel setup-models
ravel models list
ravel models estimate --preset balanced
```

Use `ravel operator show` if an operator ledger already exists. Guided setup
checks installed CLIs and credential presence, shows candidate models, validates
role coverage and records preferences. It offers `premium`, `balanced` and
`economy`; `--yes` chooses balanced defaults. `--cost-cap-usd` sets the proposed
per-run spending ceiling. The estimate uses catalogue prices and a declared
workload; measured usage is reported separately.

Discovery and preference setup establish candidates. Probes inspect CLI versions
and flags. Qualification exercises the governed route and records the evidence
needed for seat selection. `ravel setup-models --verify` opts into paid
qualification, with `--verification-cost-cap-usd` bounding that verification.
Review the setup output and use its exact qualification command for each route
and model. The [transport reference](reference/transports.md) records current
executor and adoption boundaries.

Models can be maintained in `.ravel/models/catalogue.json`, or a file selected by
`RAVEL_MODEL_CATALOGUE`. Transport declarations name credential variables and
allowed model families. See [configuration](reference/configuration.md) and the
[provider appendix](architecture/providers.md).

### Host adapter configuration

The following host-adapter settings serve standalone model calls and legacy
Graph entry points. Controller workers use governed seats and their transport
qualification.

Research and review roles call a language model. Copy the template the installer writes and name
the environment variable that holds your key:

```bash
mkdir -p .ravel
cp native/build/config/host.example.json .ravel/host.json
export ANTHROPIC_API_KEY=...   # from your own secret manager; never put keys in files
```

`.ravel/host.json` (or the file named by `RAVEL_HOST_CONFIG`) selects one transport: `anthropic`
(Claude Messages), `responses` (OpenAI), `gemini`, or `chat_completions` for xAI, vLLM, Ollama or
llama.cpp. Claude, Gemini and compatible endpoints also need a `capabilities` object, for example:

```json
{
  "type": "anthropic",
  "endpoint": "https://api.anthropic.com/v1/messages",
  "api_key_env": "ANTHROPIC_API_KEY",
  "capabilities": {"output_mode": "tool_call", "token_limit_field": "max_tokens", "reasoning_efforts": [],
                   "max_context_bytes": 2000000, "max_output_tokens": 32000}
}
```

Use `max_tokens` for Claude and `maxOutputTokens` for Gemini. Set the limits for your model and
account. There is no fallback provider and no automatic model substitution.

A local model uses `"privacy": "local_only"`, a loopback endpoint such as
`http://127.0.0.1:8000/v1/chat/completions` and the exact model names in `local_models`. RAVEL then
refuses any other destination. The model server's own network access is yours to restrict.

**With an installed agent command line** (Claude Code, Codex, Antigravity or Gemini CLI) and its own
login, copy the shipped host configuration instead of the template:
`cp src/ravel/data/transports/hosts/agent-cli.json .ravel/host.json`. No key is stored or read; the
doctor reports this configuration ready when the command line it names is on your `PATH`.

**Without an API key**, review and research roles run in fresh Claude Code or Codex sessions:
`ravel agent-graph prepare-external --graph GRAPH --node NODE` writes the role's request, a fresh
session answers it, and `ravel agent-graph deliver-external --graph GRAPH --node NODE --response
RESPONSE.json` records the answer with that session's identity.

## Linux analysis facilities

`--profile site` installs pinned Miniforge, RAVEL's Python layer and two environments under
`<prefix>/.ravel-site/`: site-analysis for analysis and site-wms for hash-locked Snakemake
and cluster-generic. Choose `--lcg-view /absolute/view/path` or `--lcg-view none` explicitly.
Run `<prefix>/bin/ravel-snakemake` to isolate it from facility Python settings. Apptainer caches
and temporary files use the prefix. Keep the checkout, runs and transcripts in work space too.
One prefix holds one release per campaign; install an upgrade into a new prefix after the
campaign ends. The target retains PDF/graph tools, omits Combine and TeX, and uses pyhf.
Run `ravel site doctor --profile generic --prefix <prefix> --runs-dir <work-runs>
--transcripts-dir <work-transcripts>` for locks, plugins, quota, locations, caches, leases,
bubblewrap and stored worker qualification. See [site installation and qualification](reference/site-workflows.md#required-linux-installation).

From a Mac, print the commands for a facility checkout with
`python3.12 scripts/setup/site_installation.py --plan --linux-root /path/to/ravel/on/the/site`.

## Where things go

- Tools: the prefix (default `native/build` in the checkout), with `tools/`, `bin/`, `share/LHAPDF`,
  `downloads/` (a cache of verified files), `logs/`, `receipts/` (versions, commits and digests of
  what was installed) and `config/`.
- Python environments: `.venv`, `.venv-smodels` and `.venv-sfitter` in the checkout.
- A different `--prefix` is remembered in `.ravel/native-prefix`, so RAVEL finds it later.
- Analysis catalogue: the package ships a pinned snapshot of the public Rivet and SimpleAnalysis
  routine metadata (with its public probability-model index associations), so routine lookup works
  before anything is installed. The installer's catalogue group refreshes it into
  `share/ravel/analysis-catalog.json` in the prefix, built from the pinned Rivet and SimpleAnalysis
  source checkouts. Catalogue readers use `RAVEL_ANALYSIS_CATALOG` first, the user cache second, the
  installed prefix third, then the shipped snapshot. No shell setup is needed to find the installed
  catalogue. The doctor checks the installed catalogue's schema and pinned Rivet revision and prints
  the exact rebuild command when it fails. A catalogue row is discovery only: it confers neither
  execution admission nor physics validation.

The installer does not edit your shell start-up files, conda or container settings in your home
directory, Wolfram settings or agent configuration. `config/ravel-env.sh` in the prefix sets the
tool paths for a shell if you want them; source it yourself. To remove everything, delete the
prefix and the `.venv*` directories.

## Troubleshooting

The installer ends with one summary containing every failure, its step, error, log path
and fix, followed by every blocked group and the rerun command. An incomplete install
exits with status 1. Resolve each reported error, then run the printed command with
`--resume`. Finished steps are skipped and verified downloads are reused. A group marked
`waits for GROUP` runs after that prerequisite succeeds. Run `ravel doctor` after resuming;
each failed check names the command or manual action that fixes it.

pySecDec builds use `MAKEFLAGS=-j1` and `SCONSFLAGS=-j1` in both Python environments.
The remaining builds use the parallelism selected by `--jobs`.

## Use an existing toolchain

To keep a toolchain you already have, point the installer at it and keep what is there:

```bash
bash scripts/setup/install.sh --prefix /path/to/existing/build --adopt
```

Existing conda environments and Git checkouts are kept instead of created. The pip and build
steps still run, so they install missing packages into those environments and build missing tools.
The doctor then reports any versions that differ from the pins.

See the [component inventory](reference/component-inventory.md) for package and
native declarations and the [documentation inventory](reference/documentation-inventory.md)
for installer groups and readiness checks.
