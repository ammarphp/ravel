# September 26 survey tooling

No installed scientific runtime, simulator, detector configuration, compiler or
HEP data environment changed. Public upstream sources were cloned into temporary
research directories for read-only Git-object inspection; no upstream routine
was executed. Existing Python 3.12.13/PyYAML 6.0.3 provided extraction/tests.
The system's older PATH Git cannot read a modern sparse checkout; the commands
used existing `/usr/bin/git` through a task-local PATH prefix, without changing
system configuration. A separate dependency-free Python 3.12 wheel environment
was created for installed CLI checks. Hatchling build isolation uses the pinned
project build requirement. No Docker/VM, event generation or new fit was launched.
