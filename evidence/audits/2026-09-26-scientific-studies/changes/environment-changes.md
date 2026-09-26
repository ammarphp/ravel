# Scientific adapter verification environment

A separate temporary CPython 3.12.13 environment was used for the new software
checks. It contains NumPy 1.26.4, SciPy 1.14.1, Spey 0.2.6, autograd 1.9.1,
matplotlib 3.9.4, mplhep 0.4.1, pyhf 0.7.6, iminuit 2.33.0, ONNX 1.23.0,
ONNX Runtime 1.30.0, uproot 5.7.6 and awkward 2.14.0. A second temporary
ONNX test environment was used during adapter development. Neither changed the
user's shared simulation environments or system configuration.

The existing native Rivet 4.1.3 / YODA 2.1.3 environment supplied its own Python,
compiler and libraries. Compilation ran with one worker and explicit SDK/library
paths. No Docker, VM, Geant4, shower generation or heavy Monte Carlo run was
started. All inference used small analytic fixtures and one BLAS/OMP worker.
The modern existing system Git was selected through task-local PATH because the
older default Git does not support the worktree configuration.

Pinned Rivet reference-binning files were materialized in an existing temporary
upstream checkout. The SimpleAnalysis framework was cloned for read-only source
inspection; the exact submodule revision was fetched and the relevant protocol
files matched it. No AnalysisBase installation or upstream SimpleAnalysis build
was attempted or claimed.

The package adds optional `science`, `measurement` and `classifier` extras and a
CI job that installs and exercises them. The existing replay lock is unchanged;
new extras have declared version bounds rather than a new complete hash lock.
See the [workflow guide](../../../../docs/workflow/reference/scientific-studies.md)
for installation and the [report](../README.md) for actual verification scope.
