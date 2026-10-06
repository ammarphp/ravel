# Public analysis catalogue survey

This is source-discovery and engineering evidence, not a scientific reproduction.
It preserves **633 routine/metadata entries**.
No analysis routine, event generator or likelihood fit was run in this survey.

- [Browse all entries](index.html) or download the [CSV](routines.csv).
- The [retrieval record](retrieval.json) and [installed CLI checks](installed-cli-checks.json) document
  how the snapshot was taken and checked.

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
python scripts/catalogue/build_analysis_catalog.py \
  --rivet /path/to/rivet \
  --simpleanalysis /path/to/simple-analysis \
  --rivet-ref rivet-4.1.4 --simpleanalysis-ref HEAD \
  --models evidence/audits/2026-09-26-analysis-landscape/probability-models.json \
  --retrieved-at 2026-09-26 --out /tmp/catalogue-rebuilt.json
```

Set the SimpleAnalysis checkout HEAD to
`5a33033d788619bb1039a5b8116fdf43c46fc72a` first. Rivet's selected release resolves
to `74816bd4cf29a9d71447f8c122887d498d3dea3a`. The independently rebuilt output
matched the packaged JSON byte-for-byte when it was built. Source facts come from
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
- Publication/evidence/agent-surface checks passed. Historical source identities
  were preserved.
- The HTML's embedded population, adaptation packets, local links and JavaScript
  syntax were checked. Browser visual/interaction QA was **not completed**.

An independent review of the classifier and planning interface found neutrino-final-state confusion, missed nuclear-beam cues,
qualified-status handling and omitted unresolved-asset warnings, plus missing
edge coverage. These were repaired and covered by tests. This is a software
review, not independent expert validation of all papers or physical adapters.
No historical audit was
rewritten to manufacture a pass.

## Limits

Family labels and dependency signals are conservative automated triage. Reference
YODA presence and probability-index membership do not establish likelihood
schema, covariance, detector fidelity or inference closure. Local source PASS
checks selected source/metadata/literal assets only, not transitive dependencies,
compilation, ABI or physics. A generic routine executor and a fixed-event
scientific admission workflow were not part of this survey.
