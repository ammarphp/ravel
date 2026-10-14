# Prepared runtime environment

Ordinary science and scoped plans retain `prepared_runtime` beside their stage
binding. It contains exactly the eight environment keys already hashed by
execution: `PATH`, `PYTHONPATH`, `LD_LIBRARY_PATH`, `DYLD_LIBRARY_PATH`,
`CONDA_PREFIX`, `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, and `MKL_NUM_THREADS`.
A JSON null means remove that variable; an empty string means set it to an empty
string. Other variables, credentials, shell initialization and working-directory
changes are outside this capsule.

The capsule binds the original runtime hashes, stage fingerprint, input-snapshot
digest and exact Python command spelling/resolved binary hash. It is part of the
plan bytes reviewed in CHECK-IN 1. It contains no assent or execution authority.
Ordinary approval and execution continue to recompute source, input, package,
platform, interpreter, command and runtime commitments.

Inspect a prepared capsule without approving or running a study:

```sh
ravel runtime-capsule --rundir <existing-run>
```

When the prepared source and interpreter remain identical but a caller inherits
a different selected environment, explicitly opt in for the required operation:

```sh
ravel approve --rundir <existing-run> --quote '<actual authorized assent>' --replay-runtime
ravel run --rundir <existing-run> --replay-runtime
ravel run --rundir <existing-run> --resume --replay-runtime
```

The selected variables are restored only for that ordinary operation, including
its supervised children, and reset when it returns or raises. The caller still
supplies the actual approval quote and any explicitly authorized scripted mode.
The API never signs, approves, retries, re-execs Python or selects a stored command.
A failed guard preserves the existing study. A source change requires its normal
new plan and approval; replay cannot make an upgraded package match an old plan.

Historical plans without retained values remain inspectable. If the original
values are independently available, create a separate capsule without rewriting
the historical plan:

```sh
ravel runtime-capsule --rundir <existing-run> --environment <exact-eight-key-values.json> --out <new-capsule.json>
ravel approve --rundir <existing-run> --quote '<actual authorized assent>' --replay-runtime --runtime-capsule <new-capsule.json>
```

Creation requires exact equality to the planned environment digest. A hash alone
cannot recover values. Missing/extra keys, non-string values except null,
interpreter aliases, tampered source association or an external replacement of
embedded values refuse. Passing `--runtime-capsule` without `--replay-runtime`
also refuses. Capsule files are bounded, must be regular paths without symlink
ancestors, and reject duplicate or nonfinite JSON tokens and nesting over 32 levels.

Replay is a dedicated, ordinary unoptimized main-thread CLI operation. Concurrent
mutation of process environment and nested replay are unsupported. Restoring
`PYTHONPATH` does not change Python's already initialized `sys.path`, already
imported modules or an installed dependency set. Use the original interpreter
spelling and source package before invocation. No native-weight, detector,
statistical or scientific qualification follows from capsule replay.

The Python API is `ravel.workflow.prepared_runtime.capture(binding,
environment=None)`, `for_plan(rundir, environment=None)` and the context manager
`replay(rundir, capsule_path=None)`. `validate(capsule, binding)` checks live
interpreter identity; frozen incidental-output proof readers use the explicit
metadata-only form `live_interpreter=False`, which grants no replay authority.
