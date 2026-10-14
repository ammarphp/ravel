---
name: rivet-routine
description: Use when building, loading or running a Rivet analysis routine on HepMC events - compiling a routine with rivet-build, checking that the loaded plugin is the one built, routines that need data files such as ONNX weights, and normalisation by the event-file cross section - in RAVEL's analyze and contur-yoda modes.
license: Apache-2.0
compatibility: Rivet 4.1.3 from RAVEL's rivet-shower toolchain group, with its HepMC3 and Pythia environment.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "analyze contur-yoda"
  upstream-version: "rivet-shower:rivet=4.1.3"
  last-reviewed: "2026-10-11"
---

# Rivet routines

## RAVEL's path

Routine builds are their own observed operation: RAVEL records the compiler
invocations and then loads the built library and checks which routine it
provides before any events run (`docs/reference/routine-build.md`). The
`analyze` mode runs preserved or constructed routines over supplied events.

## Data files a routine needs

Some routines load data at `init()`: reference YODA files, efficiency tables
or ONNX networks (`getONNX`). Check that every file the source asks for exists
before building:

```python ravel-block=routine-data-files
import re
from pathlib import Path

def missing_onnx(routine_source, name, search_dirs):
    """ONNX files a routine loads with getONNX that none of search_dirs holds."""
    if "getONNX" not in routine_source:
        return []
    wanted = set(re.findall(r'getONNX\(\s*"([^"]+)"', routine_source)) or {name}
    missing = []
    for stem in sorted(wanted):
        filename = stem if stem.endswith(".onnx") else stem + ".onnx"
        if not any((Path(d) / filename).is_file() for d in search_dirs):
            missing.append(filename)
    return missing
```

## Pitfalls

- The plugin library that loads is not the routine that was built. Caught by
  `ravel.physics.routine_build.verify_loader_observation`.
- A build that used other compiler flags or sources than planned. Caught by
  `ravel.physics.routine_build.verify_compiler_invocations`.
- Advisory: a routine that calls `getONNX` fails at `init()` when its
  `.onnx` file is absent; at least one upstream routine shipped without it.
  Use the `routine-data-files` block; see C8 in `docs/reference/failure-modes.md`.
- Advisory: routines that normalise with `crossSection()` take the value from
  the event file; check that the HepMC events carry the generator cross section
  you intend, and record it.
- Advisory: a routine validated on one generator setup is not validated for
  another; follow `docs/workflow/checklists/choosing-routine.md`.

More: `references/review.md`. Upstream: https://rivet.hepforge.org/ and
Bierlich et al., SciPost Phys. 8 (2020) 026, arXiv:1912.05451.
