# Local model provider qualification

`model-provider-bridge` qualifies an existing Wolfram 14.3 installation and exact
FeynRules 2.3.49 source before a separate Lagrangian or UFO study. It records
whether the kernel starts unattended, whether the pinned provider loads, and
whether the required entry points have evaluated definitions. It does not load a
model, calculate vertices or widths, or generate events.

```bash
ravel model-provider-bridge plan \
  --kernel /Applications/Wolfram.app/Contents/MacOS/WolframKernel \
  --application-metadata /Applications/Wolfram.app/Contents/Info.plist \
  --feynrules /absolute/path/to/pinned/feynrules-source \
  --source 'Exact provider attribution and requested operational qualification' \
  --trust-provider-source \
  --rundir /absolute/path/to/fresh-study \
  --review-policy /absolute/path/to/prospective-review-policy.json
```

The fresh plan binds the kernel executable, application metadata, complete
provider source census and RAVEL implementation. Existing-installation license
availability remains explicitly unverified. After actual CHECK-IN 1 approval,
the supervised worker loads a fresh private provider copy through a fixed script.
It uses `-noinit`, `-noprompt` and `-script`, removes optional Wolfram
initialization environment overrides, disables FeynRules parallel kernels, and
records the actual owned kernel PID. These flags follow the
[WolframKernel command reference](https://reference.wolfram.com/language/ref/program/WolframKernel.html).
No license credentials are read, no activation is requested, and startup errors
remain retained evidence.

The script observes a simple arithmetic control, native versions, parallel-kernel
state, and evaluated definitions for `LoadModel`, `FeynmanRules`, `WriteUFO` and
`CheckKineticTermNormalisation`. It distinguishes a real definition from an
unevaluated function name. In the qualified source version, the legacy spelling
`CheckKineticTerms` has no definition and cannot serve as a passing physics check.

A successful readiness receipt establishes that the declared local tool and
source worked for this attempt. It does not establish license rights or future
runtime availability. The installed proprietary libraries and operating-system
runtime remain outside the finite executable/source capsule. Lagrangian checks,
UFO export, independent amplitudes and widths, and generator or detector validity
need their own source-bound model studies. The supplied-UFO numerical route is
documented in [dynamic model tool checks](model-tool-bridge.md).
