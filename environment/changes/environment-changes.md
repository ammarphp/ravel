# Environment changes

## 2026-09-09 scoped workflows

Built and installed the candidate wheel into an existing isolated CPython 3.12.13 scientific
environment using uv. Numerical dependencies were retained: pyhf 0.7.6, NumPy 1.26.4,
SciPy 1.14.1, iminuit 2.32.0 and Matplotlib 3.9.4. Wheel builds used an isolated Hatch build
environment. No global Python, native installation, container or system package changed.

Native controls copied MadGraph 2.9.27 into immutable run inputs and regenerated caches only
in working copies. The native compiler, compatible Python and existing macOS SDK were explicit
in each specification. One thread and a 120-second per-attempt ceiling applied. No native
toolchain was downloaded, upgraded or reconfigured in place.

The first installed-wheel attempt exposed duplicate package discovery in the bootstrap.
It failed before physics execution and remains in the records. The fixed bootstrap is
covered by a regression and installed CLI controls.

Workflow: [scoped execution](../../docs/workflow/reference/scoped-workflows.md).
Interpretation: [benchmark controls](../../benchmarks/scoped/README.md).
