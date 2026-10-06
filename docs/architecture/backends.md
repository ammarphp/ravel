# Where the work runs

[Architecture](README.md) · [Reading the figures](README.md#reading-the-figures)

A calculation runs on one of three backends, chosen by the route at step 2.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/backends.svg">
  <img alt="Where the work runs: the native toolchain on macOS runs the full event chain in about 30 to 50 minutes per point; the container fallback, an x86 container under podman, runs SimpleAnalysis routines without a native port in about 9 hours per point under emulation, one point at a time; Python-only routes on macOS or Linux run replay, likelihood-only runs and supplied-data studies in seconds to minutes." src="../figures/svg/light/backends.svg" width="100%">
</picture>

The native toolchain is the default. Before a native run, check the computer with the health check in [step 1](stage-1-environment.md). For portability notes, see [native portability](../reference/native-portability.md).
