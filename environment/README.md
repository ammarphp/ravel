# Environment setup

Install everything with `bash scripts/setup/install.sh` and check it with `ravel doctor`;
the [installation guide](../docs/installation.md) explains both. The installer reads
its pinned sources from `native/setup/toolchain-manifest.json`.

| Path | Purpose |
|---|---|
| `python/` | Python requirement files and the installation record for `.venv`, `.venv-smodels` and `.venv-sfitter` |
| `site-profiles.json` | The Linux site analysis and Snakemake environments |
| `scripts/00-install-miniforge.sh`, `01-create-env.sh`, `02-get-madgraph.sh` | Earlier macOS bootstrap helpers, kept for existing toolchains |
| `scripts/03-run-madgraph.sh` | Historical generation example; new runs use the approved native executor |
| `scripts/normalize_param_card.py` | Normalize parameter-card formatting |
| `changes/` | Record of deliberate environment changes |

Installed environments and build products stay out of version control. An existing
toolchain is kept as it is with `bash scripts/setup/install.sh --adopt --prefix <path>`.

Event generation is compute work: enter through the
[physics workflow](../docs/workflow/start.md) and obtain the plan approval before
running it.
