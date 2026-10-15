# Challenge operations

This page covers running RAVEL inside another analysis project: an analysis challenge, a
collaboration repository or a paper's own repository. It describes six tools:

1. installing RAVEL's skills, hooks and rules into the project;
2. logging every agent prompt with its model, time, tokens and tool calls;
3. answering RAVEL's review requests with a fresh Claude Code or Codex session;
4. running a published analysis routine on the project's reconstructed ntuples;
5. writing a page-limited note from a supplied rule pack;
6. packaging the accepted analysis for submission and checking the package in a fresh clone.

Venue and challenge rules are always supplied as data files. RAVEL's lifecycle stays in charge:
plans are approved before compute, results are accepted through review, and an agent's answer is
recorded as a model answer, never as human or physicist review.

## 1. Install the agent surface

The effective registry, native-field evidence, redirects and adoption contract are
specified in [roles](roles.md). Regenerate with `ravel agent-surface render --project .`;
the coherence gate refuses drift and every orphan in an owned profile directory.
All shipped host profiles redirect to dispatch because their cards require
transport attestation. Governed nodes retain the full card. The manual `ravel-gate.sh`
adapters register no native events; Codex, Gemini and opencode are hookless.

Resolve the Tier B panel with `ravel agent-surface profiles --project ../my-analysis
--host codex`, or the matching host. Dispatch the effective physics-critic,
skeptical-verifier, physics-decider and physics-improver cards through the authorized
worker route. A profile or actor name supplies no independence or worker credit.

`finding_effect` resolves evidence IDs through a trusted resolver, ignoring the
reviewer's declared class. Without a resolver, evidence is opinion and advisory;
a pending typed request holds the decision. The review loop supplies the resolver
from its recorded decision evidence.
CHECK-IN 1 labels the exact role/model/transport/effort cell. Unqualified delegated
blocking or voting cells keep their mode and truthful qualification label.

Before approval, `ravel work pin-obligations --rundir RUN` writes the card/review-point
obligations once and pins the sidecar in CHECK-IN 1 and its approval fingerprint.
`ravel work adopt --rundir RUN --node-id N3.author --attempt 1` reads
`agent-work/N3.author/1/outputs/`, checks current derivation, approved bytes,
obligation coverage and required content, then copies only checked bytes. Adoption
never writes custody or registers receipts; only the dispatcher grants worker credit.

```bash
ravel agent-surface install --project ../my-analysis
ravel agent-surface check --project ../my-analysis
```

The installer adds RAVEL's workflow skills to `.claude/skills/` and `.agents/skills/`, its rules as
`.claude/rules/ravel-*.md`, software skills for the tools installed on this machine (with their
versions), and the prompt-logging hooks in `.claude/settings.json`. It adds a marked section to
`CLAUDE.md` and `AGENTS.md`. `CLAUDE.md` imports `@AGENTS.md` first, so the project's own rules load
first and stay in force.

Existing files are never overwritten. A file the installer wrote earlier is replaced only when it
is unchanged since. Running the installer again updates its own sections and leaves the project's
text alone. `ravel agent-surface skills --out DIR` writes only the software skills.

### Software skills

Each software skill (`.claude/skills/software-<name>/SKILL.md`, mirrored to `.agents/skills/`) states
what the tool is for in the project, its exact installed version, the import names and entry points
it exposes, the commands the workflow reaches it through, its licence and its upstream documentation
link. A field the distribution metadata does not carry says so. `software-ravel/dependencies.md`
lists RAVEL's required-dependency closure with version, licence and documentation link. The text
has no paths or times, so regenerating it in an unchanged environment is byte-identical and a
version change shows as exactly that line. A tool that is not installed has no skill. A project can
add tools through the `software` key of `workflow/policy.json`
(`{"software": {"python_packages": [...], "executables": [...]}}`).

### Strict execution guard (Claude Code)

```bash
ravel agent-surface install --project ../my-analysis --wms-guard
```

adds one `PreToolUse` hook for the Bash tool. It does nothing until the project's
`workflow/policy.json` selects it with `"execution_guard": "strict"`. The effective mode is the
stricter of the working-tree policy and the committed one, so an uncommitted edit cannot relax it.
In strict mode a command runs only if every statement of it is

- `snakemake` with listed options on a Snakefile (and its `include:` files and `rules/*.smk`) that is
  tracked in git and unmodified: dry runs and targets;
- `ravel` (or `python -m ravel`) with `status`, `validate`, `audit`, `initiate`, `plan`, `approve`,
  `gate`, `conformance`, `agent-audit`, `agent-surface check|profiles` or `wms init|add|launch|status`;
  `ravel run` is refused with the workflow-manager route;
- `git` reads, `add` and `commit`;
- a short list of read-only inspection programs;

and every program of the first three kinds has its software skill installed in the project.
Redirections, subshells, command substitution, background jobs, `cd`, environment prefixes and
wrappers (`bash -c`, `env`, `xargs`) are refused. Every decision is appended to
`.ravel/agent-audit/execution-guard.jsonl` (command hash, allowed or refused, rule matched, mode);
`python -m ravel.workflow.execution_guard summary --project .` summarises it for the conformance check.

What this enforces: the shell tool of an agent session that loads the project's
`.claude/settings.json`. What it cannot: a person at a terminal, a session started without the
project settings, an agent host that does not route its shell tool through this hook, or file
writes. An allowed program still runs its own configured helpers (git hooks, a configured external
diff). It is discipline with a record, not a security boundary. Under the same declaration a RAVEL
worker's toolbelt offers no general shell (read, write, knowledge, check and workflow-manager
actions only) and a launch that would give one is refused.

Codex has no per-project execution-policy file that RAVEL can install and verify from its bundled
help: its rules mechanism is user-scoped (`CODEX_HOME`). In a project with a strict policy, run Codex
with its shell tool disabled, or as a RAVEL worker whose toolbelt has no shell. RAVEL does not
generate Codex rules.

## 2. Log agent sessions

After installation, Claude Code appends one line per prompt and per finished turn to
`.ravel/agent-audit/prompts.jsonl`. For Codex, copy the `notify` line from
`.ravel/codex-notify.toml` into your Codex `config.toml`.

Build the audit log from the hook log and any transcripts you name:

```bash
ravel agent-audit build --log .ravel/agent-audit/prompts.jsonl --out audit
ravel agent-audit collect --transcript ~/.claude/projects/PROJECT/SESSION.jsonl --out audit-session
```

Each record holds the prompt text, the exact model build the CLI reported, the prompt timestamp,
input, cached and output token counts, and a summary of tool calls. Subagent and reviewer sessions
appear as their own streams. A value the transcript does not carry stays empty. A prompt the hooks
saw but no transcript recorded is listed as a gap. Only transcripts named by you or by a hook event
are read.

The output directory holds `agent-audit.jsonl` (one record per prompt), `agent-audit.md` (a table)
and `agent-audit.json` (totals, sources and gaps).

## 3. Answer review requests with a fresh session

RAVEL's external review requests (`ravel judgment prepare-role --external` and
`ravel agent-graph prepare-external`) can be answered by a new `claude -p`, `codex exec`, `agy -p`
(Google Antigravity) or `gemini -p` session:

```bash
ravel agent-cli detect
ravel agent-cli answer --request REQUEST.json --out RESPONSE.json
ravel agent-cli answer-graph --graph graph --prepare
```

Each answer runs in an empty temporary directory with only the request's instructions, output
schema and prepared context. No parent transcript is passed. The argv and the passed environment
names come from the CLI's `*-cli-oneshot` transport declaration (`ravel transport show <id>`), and
the CLI needs a current probe of the same executable (`ravel transport probe <id>`). The response
records `request_id`, `request_sha256`, `invocation_id`, `actor_id`, `observed_model`,
`parent_transcript_supplied: false`, `user_configuration_loaded`, `fresh_context` and the isolation
evidence, with the CLI's reported token usage. Beside it, `<response>.receipt.json` holds the
launcher's session receipt. `answer-graph` answers and delivers every external node of the graph
that is waiting for a response.

Claude runs with `--setting-sources project --safe-mode --strict-mcp-config` and no tools, and Codex
runs with a fresh `CODEX_HOME` holding a copy of your login. Both record
`user_configuration_loaded: false`. Codex keeps a shell that can read files, and Antigravity and
Gemini CLI keep read tools and have no flag that excludes your own settings and instructions, so a
critic or verifier is refused on them before any process starts. Every relay delivery is `self_attested`, including schema 3 with a matching declaration digest.
Its transport evidence is retained, but its authorship is not authenticated and it cannot count as
an independent critic, verifier or synthesizer vote. Use the verified host path below for voting roles.

To use the CLI as an agent graph's host, give the host configuration
`{"type": "agent-cli", "agent": "claude"}` (or `"codex"`, `"antigravity"`, `"gemini"`, or `"auto"`,
which picks an installed CLI when the host is configured). The host verifies the launcher's session
receipt and records `transport_attested` only when every condition in `docs/reference/transports.md`
holds. The session runs with your own agent login; it is not an operating-system sandbox.

## 4. Run a published routine on reconstructed ntuples

The `reco-ntuple-routine` science mode runs a registered native SimpleAnalysis routine port on flat
ntuples. A format descriptor maps the ntuple to the routine's objects:

```json
{
  "schema_version": 1, "kind": "reco-ntuple-format", "tree": "analysis", "energy_unit": "MeV",
  "event_number": "eventNumber", "weights": ["mcEventWeight", "pileupWeight"], "sort_by_pt": true,
  "collections": {
    "electron": {"pt": "el_pt", "eta": "el_eta", "phi": "el_phi", "charge": "el_charge", "mass": null,
                 "require": ["el_select_baseline"], "default_bits": [],
                 "id_bits": [{"flag": "el_select_tight", "bits": ["ETightLH", "EIsoFixedCutTight"]}]},
    "muon": {"pt": "mu_pt", "eta": "mu_eta", "phi": "mu_phi", "charge": "mu_charge", "mass": null,
             "require": [], "default_bits": ["MuMedium"], "id_bits": []},
    "jet": {"pt": "jet_pt", "eta": "jet_eta", "phi": "jet_phi", "charge": null, "mass": "jet_m",
            "require": [], "default_bits": [], "id_bits": [{"flag": "jet_select_btag", "bits": ["BTag77MV2c20"]}]}
  },
  "met": {"px": "met_px", "py": "met_py"}
}
```

`require` names flag branches an object must pass to be kept. `id_bits` sets SimpleAnalysis ID and
isolation bits on objects whose flag is set; `default_bits` applies to every kept object. Bit names
must exist in SimpleAnalysis. The event weight is the product of the named weight branches.

```bash
ravel reco-ntuple routines
ravel reco-ntuple check --descriptor format.json --ntuple sample.root
```

Then plan, approve and run the study with the task
`{"descriptor": "format.json", "ntuples": ["sample.root"], "routine": "<routine-name>", "max_events": null}`.
The result lists raw counts, `sumw` and `sumw2` for each region of the routine. Whether the
supplied flags match the routine's original object definitions is part of the study's review.
Normalising to a cross section and luminosity is a separate step with its own declared inputs.

## 5. Write a page-limited note

A note rule pack carries the page ceiling, which sections count toward it, figure and table
limits, and the sections the note must have:

```bash
ravel note-profile check --rule-pack pack.json
ravel note-profile contract --rule-pack pack.json --out formatting.json --source-basis rules-source.json
```

The formatting contract may tighten the pack's limits but never loosen them. The manuscript writer
must map every required section, keeps main-text sections out of the appendix, and the compiled
build refuses a page count above the pack's ceiling. A pack whose origin is a publisher or a
challenge needs `--source-basis`, the located text of the rules. RAVEL ships no rule pack: the
requester supplies the pack that states the actual requirements, and both commands refuse to run
without `--rule-pack`.

## 6. Package and verify a submission

Write a submission request next to your analysis:

```json
{
  "schema_version": 1, "kind": "ravel-submission-request", "title": "Search for ...",
  "rundir": "runs/search", "claim_scope": "reproduction",
  "results": ["runs/search/outputs/result.json"],
  "figures": ["figures/yields.pdf"], "note": ["note/note.pdf", "note/note.tex"],
  "recipe": ["recipe.json"], "code": ["analysis/selection.py"], "environment": ["container.def"],
  "inputs": [{"name": "signal sample", "uri": "root://eos.example//signal.root", "sha256": "<64 hex digits>", "size": 123}],
  "audit": {"logs": [".ravel/agent-audit/prompts.jsonl"], "transcripts": []},
  "partitions": [], "site_workflow": null,
  "code_repository": {"url": "https://example.org/analysis.git", "commit": "<commit>"}
}
```

```bash
ravel export-submission --request submission-request.json --into ../submission-repo
git -C ../submission-repo add submission && git -C ../submission-repo commit -m "Submission"
ravel export-submission verify --package ../submission-repo/submission --fresh-clone
```

Every result must be captured by an accepted review of the named claim scope; otherwise the export
stops. Paths in the request are relative to the request file. The package, in `submission/` by
default, holds:

| Path | Content |
|---|---|
| `submission.json` | every file with its sha256 and size, the acceptance record, the code version and the input references |
| `results/`, `figures/`, `note/`, `recipe/`, `code/` | copies of the named files |
| `inputs.json` | inputs by reference with sha256; local inputs are hashed, remote inputs carry the checksum you supply |
| `environment/` | `lock.json` and `requirements.txt` for the Python environment, plus any environment files you name |
| `run/` | the run's plan, approvals, execution records and review journal |
| `workflow/dag.json` | the workflow graph: planned and executed stages, partitioned stages and a site workflow export |
| `partitions/` | merge receipts and merged outputs of completed partitioned stages |
| `audit/` | the agent audit log and the raw hook log |
| `REPRODUCE.md`, `Snakefile` | how to check, rebuild the environment, fetch inputs and rerun |

Every path is relative, so the package works wherever it is cloned. An existing package directory
is never overwritten. A supplied rule pack (`--rules`) checks required parts, note formats and file
size ceilings:

```json
{"schema_version": 1, "kind": "submission-rules", "required": ["note", "figures", "results", "audit", "environment"],
 "note_suffixes": [".pdf"], "max_file_bytes": 50000000, "max_total_bytes": null}
```

`verify` checks every listed file against its sha256 and reports unlisted files and files that name
the package's own location. With `--fresh-clone` it clones the repository that holds the package
into a new directory (or copies the package when it is not in a git repository), checks it again
there, and runs `snakemake -n` so every packaged file resolves. Files the repository ignores, or
that were never committed, show up as missing.
