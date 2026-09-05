# Environment setup

The helpers here bootstrap the native event-generation toolchain. They are
separate from the Python-only replay environment installed by the
[installation guide](../docs/installation.md).

| Script | Purpose |
|---|---|
| `scripts/00-install-miniforge.sh` | Install a user-local Miniforge distribution for the recorded macOS ARM64 setup |
| `scripts/01-create-env.sh` | Create the MadGraph Python/compiler environment |
| `scripts/02-get-madgraph.sh` | Obtain the MadGraph tool installation |
| `scripts/03-run-madgraph.sh` | Execute the configured event-generation example |
| `scripts/normalize_param_card.py` | Normalize parameter-card formatting |

Follow [environment provisioning](../docs/workflow/steps/01-environment.md) for
the command order and the additional shower, detector, and analysis requirements.
The [environment reference](../docs/reference/environment.md) records the tool
versions and build context. These bootstrap scripts are not a complete lock for
all native dependencies.

Keep local build products and installed environments out of version control.
When reusing an existing development toolchain, retain its recorded location and
configuration rather than silently replacing it. The repository's Python replay
lock does not alter those native environments.

Event generation is compute work: enter through the
[physics workflow](../docs/workflow/start.md), review the process and model cards,
and obtain the required plan approval before running it. For learning material,
see the [event-generation guide](../docs/guides/event-generation.pdf).
