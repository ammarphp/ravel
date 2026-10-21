# Released Contur companion operations

`ravel contur-companion --input request.json --review-policy policy.json --out science.json`
prepares an ordinary version-2 scientific study. Continue with ordinary `science plan`,
Check-In 1 approval, supervised execution and fresh separated scientific reviews.
The adapter permits one
attempt and a review policy with zero automatic redos.

The new mode is `contur-companion`. It calls the separately installed released Contur
3.1.5 source (commit `3d3ccb52188acc86940f3881c98251ea904bb9e0`) through its actual argument
parser and operation entry. Contur's GPL source supplies its likelihood, renderer and extractor algorithms. The implementation requires the independently
reviewed complete-mode `contur_yoda`/`contur_import` custody interfaces.

| Request operation | Released function | Population and quantity |
|---|---|---|
| `sm-test` | `run_smtest.main` | Every selected/unselected analysis, prediction/file/histogram, native getter, skip and exception; original default or Spey p-values and probability populations |
| `herwig-xs-br` | `run_extract_xs_bf.run_extract_xs_bf` | Original particle properties/BRs, matrix-element map, total and every unrounded process percentage before the printed cutoff |
| `map-plots` | `run_plot.main` | Every DB point's literal parameters/full-mode/pool results, native metric availability and original figures; optional opaque `contur.plot` |
| `rivet-plots` | `run_mkplots.main` | Native beam/runpoint resolution, script-associated histogram/pool populations, complete requested modes, exact selection and every dispatched renderer/product |

SM tests are not BSM Contur-YODA inference. The released SM loop overwrites subset
exclusions and uses `stat_types=[SMBG]` with source-defined diagonal theory covariance
and native config fallback. Default and Spey methods are retained as native quantities,
not converted into new CLs. Native `None`, nonfinite results and missing metrics are
explicit; they never become zero. An empty getter population or native exception fails
delivery. The original last-getter prediction text is retained alongside the complete
getter observation, rather than presented as the full prediction population.

For extraction the source profile requires the actual `params.dat` and matching
`herwig-S<seed>-<tag>_<runpoint>.log/.out` inside the literal runpoint directory. Native
default selectors are seed 101 and tag `runpoint`. The `.out` must explicitly declare
`Cross-section (nb)` (the original header spans two lines). The native printed fb value
is `percentage * total_nb * 0.01 * 1e6`. Its parser discards the parenthesized total error;
RAVEL reports that uncertainty as missing. All raw percentages remain available,
including those below `100*tolerance` that the original printer omits. No BRs or
uncertainties are reconstructed from another input.

Map and Rivet plotting require genuine source-associated native SQLite results and,
for Rivet plotting, the complete associated script tree. Existing grid preparation can
supply these artifacts after its own admitted native execution. A request description
is an attribution, not proof that an artifact was produced by an accepted scientific
study. No DB, SM references, plot scripts or values are invented during preparation.
`contur.plot` is retained as opaque native pickle bytes; RAVEL never unpickles it.
Map interpolation remains native interpolation of supplied results, not a new evaluation.

## Input contract

The closed request contains exactly:

```json
{
  "schema_version": 1,
  "source": "Original study and applicability declaration",
  "operation": "sm-test",
  "runtime": {"python": {"path": "...", "sha256": "..."}, "manifest": {"path": "...", "sha256": "..."}},
  "assets": {"source": {"path": "...", "sha256": "..."}, "data": {"path": "...", "sha256": "..."}, "user": {"path": "...", "sha256": "..."}},
  "entry": {"path": ".../bin/contur-smtest", "sha256": "..."},
  "inputs": {"config": null},
  "options": {"offline": false, "use_spey": false, "only_analyses": [], "veto_analyses": [], "prediction": "A", "graphics": false},
  "max_seconds": 120,
  "max_ram_mib": 1024,
  "renderer_cores": 1
}
```

All pins bind actual ordinary files. Source/data/user manifests and the declared runtime
use the existing complete Contur custody schema. Runtime lists the exact Python hash,
complete declared dependency files and startup environment; a distribution label is not
an ABI claim. The native worker reauthenticates these bindings before runtime imports,
checks the actual Contur version and observes loaded module origins. A genuine
multiprocessing worker alias must have the exact admitted worker source origin.

Other operation inputs are `{"payload": pin}` for extraction and
`{"payload": pin, "database": "literal.db"}` for plotting. The payload manifest has
`schema_version=1`, `kind="contur-companion-input"`, absolute ordinary `root`, complete
`files` map of canonical relative paths to SHA256, and explicit `source` attribution.
It binds all members, not only a selected DB/log/script. Source roots and copied writable
user/payload/config roots are disjoint before any writes. Originals are not modified.
Native user-area changes are retained explicitly at ending checkpoints.

Options are explicit and closed. Herwig accepts seed/tag/tolerance and the nine released
folding/splitting/merging flags. Map plotting accepts two parameter names, one to three
levels, a complete explicit remaining-variable slice, save-plots/databg/no-exp/pools,
pdf/png/svg format and native interpolation/style settings. Rivet plotting accepts
analysis match/veto selectors, databg/no-exp, exact beam/runpoint or native single-point
`null`, include-none and the native selection threshold. Missing or foreign grid subjects
refuse; RAVEL never chooses an arbitrary point. `offline` is always declared, never forced.
The mode uses the declared noninteractive overlay and native companion contract.

Native time is bounded to 1–900 seconds, declared RAM to 512–8192 MiB, and renderer cores
to 1–4. The ordinary stage includes 60 seconds of readback in addition to native time.
Payload limits are 20,000 files, 128 MiB/member, 512 MiB aggregate and 16 MiB for its
manifest; the request is 2 MiB. These are prospective admission ceilings, not measured
cost or scientific accuracy guarantees.

## Native rendering and delivery

The original dispatcher, parser options, script argv/cwd/environment and native core
return are preserved. The actual dispatch must fit the prospective core ceiling.
A top-level observer callback can be resolved in a fresh spawned Pool worker, unlike a
closure-only parent patch. It calls the original `executeScript`, observes real savefig
calls, retains errors and records the actual selected start method. This has software
source-compatible controls; actual SDK startup/spawn behavior still needs qualification.

The original serial branch launches its script via its unchanged shell argv. Its grandchild
must not inherit a parent savefig callback. For that branch RAVEL retains the actual native
error output and verifies the complete finite source-declared target population. Literal
paths and the released profile generator's `__file__`/`plotDir`/`os.path.join`/string-suffix
conventions are supported without executing or evaluating an AST. The profile generator's
serial `__file__` output directory is preserved even when the shell argument names another
directory. Other dynamic output expressions/control flow refuse explicitly; they are not
silently guessed or claimed covered. Native Pool execution can observe dynamic savefig
paths directly. No global or persistent interpreter customization is installed.

Every dispatched script requires one successful complete receipt and nonempty actual
products. Native swallowed errors, missing receipts, failed saves, missing/changed products
or an absent required HTML/figure population fail delivery even if the native wrapper
returned `None` or its process exited zero. All original scripts, native DB, stdout/stderr,
operation observations, output inventory and opaque artifacts survive failure. Intended
JSON bytes are committed at emission and checked at ending; changed bytes are not blessed
by recomputing their expected digest. Checkpoints are time-local observations, not a lock
or proof of every OS/native read.

`contur-companion-results.json` preserves the raw operation observation and ordinary
product registration lists original native output files. RAVEL adds no replacement plots.
Supplied script copies retain their ordinary file permissions, including the execute
bits needed by the released serial shell dispatcher. Set-user-ID, set-group-ID and
sticky bits refuse before copying. Original copied input bytes, membership, regular
file type and permissions remain checked through ending readback.
The initial admitted scientific file modes are captured before copying and committed
in `preparation.json`. Current originals and copies must continue to match that
initial map; changing both does not establish a new baseline. Public delivery retains
the intended preparation commitment, and the native worker retains its authenticated
startup preparation snapshot through its ending checks. No permissions are normalized
to a guessed execute mode.

The released serial profile generator can write its figures beside its copied script.
Those files are admitted and registered only as the exact authenticated native product
population from a successful source-bound renderer receipt. They remain separate from
the original scientific input inventory; no directory-wide empty or extra-file waiver
is applied. Unknown source target expressions still refuse.

The operation record carries its intended emitted commitment and field census through
semantic reconciliation. Final native-observation and ordinary result files must also
match their returned values exactly. Altering a record after its initial verification,
or changing a returned dictionary while leaving its emitted JSON intact, refuses.
Successful delivery has `physics_validated=false`, `calibration_qualified=false` and
`original_task_complete=false`. Fresh applicability, physics criticism, skeptical
verification and task synthesis remain required. Software checks are not native or
scientific qualification.

## Original command scope and later qualification

All twelve active released `tests/sources/grid_cl_args.yaml` variants remain accounted.
This mode covers preparation interfaces for the seven companion variants: `sm_test`,
`sm_test_spey`, `grid_xsbf`, `contur_plot`, `rivetplots`, `rivetplots_databg`,
`rivetplots_noExp`. Existing complete inference/grid/no-exp modules own `grid_spey`,
`grid_default`, `single_default`, `single_default_noExp`. `contur_oracle` training remains
recorded as a user decision. These records describe implementation dispositions.

Later root-admitted qualification must use the genuine complete original SM libraries,
actual Spey/dependency versions and config fallback; the genuine seed101 runpoint0003
Herwig pair; generated full native DB/script associations; all map metrics with native
missing-value behavior; and both native serial and actual selected multiprocessing
renderer start methods. Check complete raw/printed/getter/cut/script/output populations,
including failed paths. Renderer ABI/import availability, scientific calibration and
reproduction/comparative claims remain unserved until that evidence exists.
