# Statistics core links

`ravel.physics.statistics_links` connects supplied HistFactory workspaces and
shared binned yields to Python inference. It launches no native tool and does
not acquire inputs. Existing search, measurement and differential-likelihood
operations retain their own statistical contracts and approval lifecycle.

## Released patch structure

`ravel.validation.patch_parity.patch_parity(background, patchset, produced_workspace,
patch_name=..., record_id=...)` selects exactly one named released patch. Its
declared record and canonical background SHA256 must match. Supported patches
add signal samples at exact channel/sample array positions. Other operations,
duplicate names and ambiguous selections are refused.

The result compares channel and sample sets and each sample's modifier name/type
pairs. A control channel with background but without its released signal sample
fails. Modifier type changes report both the missing and extra pair. The result
names every structural mismatch, pins the three JSON operands and records
`physics_validated: false`. Nominal coefficients and modifier response magnitudes
may differ for a new model and are outside this check's scope.

```bash
python -m ravel.validation.patch_parity \
  --background background.json --patchset patchset.json \
  --produced workspace.json --patch-name nominal --record-id 7 \
  --out patch-parity.json
```

The command writes the parity record and exits 1 for a mismatch. A parity pass
does not establish a complete uncertainty model, independent likelihood identity,
acceptance certification or calibrated inference.

## Profile and yield interfaces

`profile_likelihood(workspace, poi_values=[...], measurement=None, released=None)`
returns a JSON-safe `profile-likelihood` record with the workspace hash, pyhf
version, measurement, POI bounds, parameter order, observed and auxiliary data,
best fit, fixed-POI vectors and delta(-2 log L). Fit failures propagate; nonfinite
coordinates/results and profiles below the best objective by more than 1e-5 are
refused. Smaller negative differences retain their signed raw value alongside
the clipped scan value. Every fit runs through `pyhf_exclude.robust_optimizer`
(SLSQP with the guarded-MIGRAD fallback, escalation reset for this model), and
the record keeps its minimization, fallback and escalation counts. These are
local fits from pyhf's suggested initialization;
they do not certify a global optimum or statistical coverage. No confidence
threshold or exclusion interpretation is assigned. Backend state is restored;
calls must be serialized because pyhf's backend is process-global.

Supply `released={"background": ..., "patchset": ..., "patch_name": ...,
"record_id": ...}` when a released reference is available. Parity failure then
prevents fitting. Omitting this optional argument retains `patch_parity: null`;
it does not imply a parity pass.

```bash
python -m ravel.physics.statistics_links --workspace workspace.json \
  --poi-values 0 1 2 --out profile.json
```

The optional `--released` file holds the same four-field object. Downstream
figure consumers can use `profiles[].poi` and `profiles[].delta_twice_nll`, while
retaining the record's stated scope and numerical limitations.

`search_yields(binned_values)` returns the existing search core's `values` and
`sumw2` interface for absolute integrated event yields. The shared producer
schema is validated. Already-scaled `from_quantity` projections are accepted
when `normalization.original_kind` is `absolute`; no scale is applied again.
Shape normalization, absent moments, negative nominal yields and off-diagonal
covariance are refused by this independent-bin interface.

`measurement_prediction(binned_values)` returns aligned `prediction` and
`covariance` records with explicit producer bin IDs, units, complete covariance,
edges, representation, normalization and provenance. It checks positive
semidefiniteness and never substitutes a diagonal covariance. This covariance
describes producer sampling; the caller must separately supply experimental
covariance and any justified independence assumptions to the measurement core.

## Offline fetch fixtures

```bash
python -m ravel.workflow.hepdata_fetch --offline-fixture local-fixture \
  --tables --download-likelihood --out local-copy
```

The directory contains `record.json`, `tables/<table-id>.json`, and
`likelihoods.json`. The latter maps each likelihood resource URL to a list of
relative `models/` JSON paths. URLs are lookup keys and are never requested.
Record discovery, table loading and model copying use local regular files only;
missing, empty, corrupt or escaping members fail without network fallback.
The output must be outside the fixture directory. Its manifest records fixture
file hashes, `network_access: false`, and `tables_route: offline-fixture` when
tables are requested. Requested likelihood files are copied as JSON rather
than extracted from an archive. Synthetic fixtures test software behavior and
carry no claim of physical or published-data validity.
