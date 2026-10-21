# Constructed native count likelihoods

The `regional-poisson-construction/v1` route uses Combine counting-model Poisson factors, which form an uncategorized product rather than a `CMS_channel` simultaneous model. Its native witness binds the actual ModelConfig product/factors, source bin roles, observations, full-process count functions, complete nuisance/global populations and coordinate domains. Arbitrary supplied workspaces retain their original channel checks.

The supplied Gaussian observation law is full-real, even when the fitted parameter has finite bounds. The generated PhysicsModel `done()` hook removes only generated auxiliary-observation ranges after Combine creates its nuisances. Parameter ranges, measured values and constant unit widths remain explicit and verified. This avoids a parameter-dependent truncated-Gaussian normalizer; no NLL result is corrected after return. ROOT's own hasMin/hasMax conventions define native unbounded-range metadata.

Each source-bound regional probe adds two initial mean getters and one dummy-constant getter per bin, plus one constant-width getter per auxiliary. Returns are flushed as hexadecimal raw evidence before dependent checks. Subsequent resource admission must count these calls; none is a fit or an additional NLL call. Graph checks establish this representation's structural delivery only. Native accuracy, calibration, parameter-domain behavior and scientific applicability still require their own qualification.

The server iterator retains graph membership, not positional proxy roles. The
ROOT 6.22 Gaussian and Poisson public `getAnalyticalIntegral` query matches a
single requested proxy name into a temporary argument set: code 1 identifies
`x`, code 2 identifies `mean`. For the exact three-server Gaussian classes, the
remaining code-0 server identifies `sigma`. The probe retains every query and
matched name, and verifies complete distinct role coverage before reading the
width. It never calls `analyticalIntegral`, a generator, or a parameter setter
for this query. The host separately requires the declared nuisance, auxiliary
observation, unit constant width, count observation and expected-count roles;
the source law must establish those semantics independently of server-name order.

This adds three structural queries per Gaussian auxiliary and two per count
factor, while numerical getter and NLL budgets remain unchanged. Reordered
server populations are admitted only with correct observed semantic roles.
An older failed probe without these observations is preserved as failed
evidence; source/API controls do not retroactively qualify its native graph.

Primary implementation: [Combine counting and param construction](https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit/blob/v9.2.1/python/ModelTools.py), [ROOT Gaussian normalization](https://github.com/root-project/root/blob/v6-22-00/roofit/roofit/src/RooGaussian.cxx), [ROOT observation range API](https://github.com/root-project/root/blob/v6-22-00/roofit/roofitcore/src/RooRealVar.cxx).

Read-only semantic query source: [Gaussian role codes](https://github.com/root-project/root/blob/v6-22-00/roofit/roofit/src/RooGaussian.cxx), [Poisson role codes](https://github.com/root-project/root/blob/v6-22-00/roofit/roofit/src/RooPoisson.cxx), [proxy-name matching](https://github.com/root-project/root/blob/v6-22-00/roofit/roofitcore/src/RooAbsReal.cxx), [SimpleGaussianConstraint inheritance](https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit/blob/v9.2.1/interface/SimpleGaussianConstraint.h).
