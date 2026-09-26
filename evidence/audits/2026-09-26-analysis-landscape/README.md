# Expanded public analysis landscape

This is source-discovery and engineering evidence, not a scientific reproduction.
It preserves **633 routine/metadata entries**, **40 proposed validation targets**,
and a **12-system competitor assessment** with eleven live repository pins.
No competitor framework, analysis routine, event generator or likelihood fit
was run in this survey.

- [Read the landscape and adaptation sequence](../../../docs/research/2026-09-26-analysis-landscape.md).
- [Browse all entries](index.html) or download the [CSV](routines.csv).
- [Read the validation portfolio](../../../docs/research/2026-09-26-validation-targets.md).
- [Read the competitor map](../../../docs/research/2026-09-26-competitor-capability-map.md).
- [Inspect the exact target definitions](validation-targets.json), [competitor sources](competitors.json),
  [retrieval record](retrieval.json), and [installed CLI checks](installed-cli-checks.json).

## Integrity and reproduction

`catalog.json.gz` preserves the exact uncompressed package catalogue at this date.
`manifest.json` binds the frozen survey artifacts. The stdlib verifier checks byte
identity, complete populations, source bindings and the absence of implied
execution/physics validation:

```sh
python evidence/audits/2026-09-26-analysis-landscape/verify.py
```

To independently rebuild the catalogue, acquire official Git checkouts at the
commits recorded in the snapshot. Use Python 3.12, PyYAML 6 and Git supporting the
chosen checkout format. No upstream code is imported or executed. With a new
output path, run:

```sh
python scripts/research/build_analysis_catalog.py \
  --rivet /path/to/rivet \
  --simpleanalysis /path/to/simple-analysis \
  --rivet-ref rivet-4.1.4 --simpleanalysis-ref HEAD \
  --models evidence/audits/2026-09-26-analysis-landscape/probability-models.json \
  --retrieved-at 2026-09-26 --out /tmp/catalogue-rebuilt.json
```

Set the SimpleAnalysis checkout HEAD to
`5a33033d788619bb1039a5b8116fdf43c46fc72a` first. Rivet's selected release resolves
to `74816bd4cf29a9d71447f8c122887d498d3dea3a`. The independently rebuilt output
matched the packaged JSON byte-for-byte in this task. Source facts come from
Git blobs rather than potentially modified checkout files. The separate
`ravel analyses check-source` intentionally verifies actual selected checkout
bytes and their revision.

## Validation performed

- **41 catalogue/evidence tests** passed, covering population accounting,
  exact/ambiguous identity, false-friend domain classification, malformed
  metadata, source mutation, wrong revision, symlinks, unresolved assets,
  qualified upstream statuses and corrupt/omitted evidence.
- **38 existing CLI/intake tests** passed. Their two wheel-only checks were
  initially skipped, then **both passed separately** against the newly built
  wheel. This is **81 distinct focused and wheel tests**, not a full local suite.
- **10 installed CLI checks** passed in a fresh, dependency-free Python environment
  outside the source checkout. They include both real upstream source checks and
  intentional ambiguity, wrong-checkout and unresolved-asset failures.
- Publication/evidence/agent-surface checks passed. Historical source and pristine
  parent-card identities were preserved. The final staged export and remote CI
  are separate release checks.
- The HTML's embedded population, adaptation packets, local links and JavaScript
  syntax were checked. Browser visual/interaction QA was **not completed**:
  the browser URL policy blocked the local file. No alternate browser or server
  workaround was used.

One bounded independent agent reviewed the classifier and planning interface.
The review found neutrino-final-state confusion, missed nuclear-beam cues,
qualified-status handling and omitted unresolved-asset warnings, plus missing
edge coverage. These were repaired and covered by tests. This is a software
review, not independent expert validation of all papers or physical adapters.
Initial integration tests also caught a portfolio field-name mismatch and a
JSON tuple/list comparison mismatch; both were corrected. A publication check
rejected a docstring edit to pinned physics source; that edit was reverted and
the interpretation correction retained in the survey. No historical audit was
rewritten to manufacture a pass.

## Limits

Family labels and dependency signals are conservative automated triage. The forty
targets are engineering selections, not forty individual paper reviews. Reference
YODA presence and probability-index membership do not establish likelihood
schema, covariance, detector fidelity or inference closure. Local source PASS
checks selected source/metadata/literal assets only, not transitive dependencies,
compilation, ABI or physics. The generic routine executor and fixed-event
scientific admission workflow remain to be built.
