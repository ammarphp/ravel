# Finite-integral compiler compatibility

The default finite-integral build has no extra compiler flags. A configuration
may explicitly request one prospective compatibility mode for the pySecDec
1.6.6 `Series` template syntax diagnosed by Clang:

```json
"build_compatibility": {
  "mode": "clang-template-keyword-without-argument-list/v1",
  "compiler": {"path": "/absolute/path/to/clang++", "sha256": "<64 lowercase hex>"},
  "reason": "Located upstream Series member-template syntax diagnostic.",
  "evidence": [{"path": "/absolute/path/to/diagnostic.json", "sha256": "<64 lowercase hex>"}]
}
```

The compiler pin must equal `runtime.cxx`; the worker also requires that exact
compiler in its admitted process-input census. The mode emits one direct Make
argument, `CXXFLAGS=-Wno-missing-template-arg-list-after-template-kw`. Arbitrary
flags and extra schema fields are refused. The mode has a nonempty bounded
reason and one to eight exact evidence pins, which enter both normal scientific
inputs and finite-integral context dependencies. The selected mode is retained
in the native record. Inherited compiler/build flags are cleared as before.

The [Clang diagnostic reference](https://clang.llvm.org/docs/DiagnosticsReference.html#wmissing-template-arg-list-after-template-kw)
documents this diagnostic and its specific disabling option. It permits this
upstream grammar compatibility without changing the captured pySecDec header.
Other errors and warnings retain their normal behavior. `-std=c++17`, `-j1`,
the generator specification, QMC arguments, resource ceilings, import census,
driver binding and ending input/output checks are unchanged.

A prospective declaration is not compiler compatibility evidence. It requires
a fresh admitted source epoch, root-owned ordinary plan/approval/execution and
retained compiler output. The build or integral may still fail. The runtime
compiler pin is an input supplied by each study; no machine-specific compiler
path or digest is embedded in the product implementation.
