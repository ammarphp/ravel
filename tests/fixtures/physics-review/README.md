# Scientific-review control fixtures

Deterministic inputs for the diagnostic-plan, decision-case and experiment-allocation checks.
They run no generator, detector simulation, fitter or language model, and they establish the
behavior of the evidence checks only.

```sh
python tests/fixtures/physics-review/run_controls.py --out /tmp/ravel-controls.json
ravel diagnose --plan tests/fixtures/physics-review/recipe-restoration-plan.json --out /tmp/ravel-diagnostic.json
ravel decision-case --case tests/fixtures/physics-review/recipe-restoration-case.json --out /tmp/ravel-case.json
```

Relative artifact paths resolve from the contract's directory, so the files keep their layout.
`run_controls.py` compares every outcome in `cases.json` with its frozen expectation.
