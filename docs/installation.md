# Install RAVEL

One command installs RAVEL and every tool it uses. A second command checks that everything works.

## Before you start

- **macOS** (Apple silicon or Intel, macOS 11 or newer): install the Xcode Command Line Tools with
  `xcode-select --install`. On Apple silicon, also install Rosetta 2 with
  `softwareupdate --install-rosetta`; the CMS Combine and ATLAS SimpleAnalysis images need it.
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
| `--adopt` | Keep existing conda environments and Git checkouts in the prefix instead of creating them |
| `--offline` | Take Miniforge and every archive from the download cache and refuse any that is missing; conda, pip and Git steps still use the network |
| `--jobs N` | Build with N parallel jobs (default: half the cores) |

| Target | Contents | Disk and time |
|---|---|---|
| `default` | Every released tool and its dependencies | Printed by `--dry-run` |
| `site` | Python layer, site environments and facility checks | Printed by `--profile site --dry-run` |

`site` is the only named profile. On a Linux analysis facility such as lxplus, install it in a
work area with enough space:

```bash
bash scripts/setup/install.sh --profile site --prefix /path/to/work/area/ravel-tools
```

## What gets installed

The installer prepares Python environments, native scientific programs, source-bound
agent tools, PDF, graph and SVG tools. AgentRivet and SFitterAgents are part of that
installation. RAVEL calls separately licensed GPL programs across process and file
boundaries; their sources and attribution remain separate from the Apache Python package.

Some tools run on Linux. On a Mac the installer uses a Podman virtual machine inside
the prefix for the CMS Combine and SimpleAnalysis images.
Facility environments run on the facility itself. Use `--prefix /path/to/volume/ravel`
for a larger volume or `--adopt --prefix /path/to/existing/toolchain` to retain installed tools.

## Check the installation

```bash
.venv/bin/ravel doctor
```

The doctor checks every tool in the default toolchain (use `--profile site` on a facility or `--group madgraph` for one group)
and prints one line per problem with the exact command that fixes it. `--json` gives a
machine-readable report and a failed requirement exits with status 1. `--strict` is accepted for existing scripts.

| Status | Meaning |
|---|---|
| `ready` | Installed and the right version |
| `missing` | Not installed; run the fix command |
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
Groups that cannot serve a request carry a `holds` entry with the
reason. The report also lists the refusal classes: loop decays of generated spectra, and the EasyScan cells
that need micrOMEGAs, SUSY-HIT, FeynHiggs, HiggsBounds or MultiNest, each with what would make it possible.

The doctor never changes anything, and the installer never runs Wolfram's AgentTools deploy command (it once
rewrote an agent host's configuration). The installer records a digest of `~/.codex/config.toml` and
`~/.claude/settings.json` at the first install; the doctor warns when one changes, and
`ravel doctor --record-host-config` accepts the new state. It reads the Wolfram version without activating it, checks
that an API key variable is set without reading it, and does not start virtual machines.

## Things you do yourself

The installer never handles licences, passwords or administrator actions. The doctor tells you
when one of these is missing:

- **Wolfram**: FeynRules, SARAH, FeynCalc, FeynArts and FlexibleSUSY need a licensed Wolfram
  kernel (Mathematica or the free [Wolfram Engine](https://www.wolfram.com/engine/)). Activate it
  with `wolframscript -activate`, then rerun the installer to finish the symbolic tools. The doctor
  proves the activation and loads FeynRules, SARAH, FeynCalc and FeynArts, each in a fresh kernel. Without a
  kernel, Wolfram-backed operations are held with a message naming it, and each lists its fallback (a supplied
  model, a pregenerated spectrum or a Python evaluator).
- **Facility access**: grid proxy (`voms-proxy-init`) and Kerberos (`kinit`).
- **Model access** for research and review roles (next section).

## Choose a provider and capability profile

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

`--profile site` installs Miniforge, RAVEL's Python layer and two site environments: one for
analysis with XRootD access and one for Snakemake. When CVMFS is mounted, it also records the
newest LCG view for this machine; `source .ravel-site/lcg-view.sh` loads it for ROOT, XRootD,
HTCondor and rucio tools. CMS Combine runs through apptainer. `ravel doctor --profile site` checks
CVMFS, the grid proxy, Kerberos, HTCondor, apptainer and the Claude Code or Codex command line.

From a Mac, print the commands for a facility checkout with
`python3.12 scripts/setup/site_installation.py --plan --linux-root /path/to/ravel/on/the/site`.

## Where things go

- Tools: the prefix (default `native/build` in the checkout), with `tools/`, `bin/`, `share/LHAPDF`,
  `downloads/` (a cache of verified files), `logs/`, `receipts/` (versions, commits and digests of
  what was installed) and `config/`.
- Python environments: `.venv`, `.venv-smodels` and `.venv-sfitter` in the checkout.
- A different `--prefix` is remembered in `.ravel/native-prefix`, so RAVEL finds it later.
- Analysis catalogue: `share/ravel/analysis-catalog.json` in the prefix. The installer builds
  it from the pinned Rivet and SimpleAnalysis source checkouts. Catalogue readers use
  `RAVEL_ANALYSIS_CATALOG` first, the user cache second, then the installed prefix. No shell
  setup is needed to find the installed catalogue. The doctor checks the catalogue's schema
  and pinned Rivet revision and prints the exact rebuild command when it fails.

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
