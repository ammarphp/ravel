# Photon luminosity check

This check convolves photon densities with the massive Born cross section for a
single charged-lepton pair and compares it to a completed generator result. It
accepts supplied process identities, beam energy, PDF set and member, scale rule,
lepton mass, electromagnetic coupling, cuts and relative tolerance. It provides
an independent numerical reference for the photon channel. A passing synthetic
control does not qualify an installed generator. A qualification receipt needs
the admitted native job, the recorded effective setup and a passing comparison
under those exact conditions.

## Formula and validity

For two equal-energy proton or antiproton beams, write \(s=E_{\rm cm}^2\),
\(\hat s=M^2\), \(\tau=M^2/s\), \(x_{1,2}=\sqrt\tau e^{\pm y}\), and
\(\beta=\sqrt{1-4m^2/\hat s}\). For unpolarized on-shell photons producing one
opposite-charge, same-flavour charged-lepton pair of unit electric charge,

\[
\frac{d\hat\sigma}{dz}=\frac{2\pi\alpha^2\beta}{\hat s}
\frac{1+2\beta^2(1-\beta^2)(1-z^2)-\beta^4z^4}
{(1-\beta^2z^2)^2},\qquad z=\cos\theta.
\]

With full angular acceptance this integrates to

\[
\hat\sigma=\frac{4\pi\alpha^2}{\hat s}
\left[(3-\beta^4)\operatorname{atanh}\beta-\beta(2-\beta^2)\right].
\]

A cut requiring each lepton to have \(p_T\ge p_{T,\min}\) restricts
\(|z|\le c=\sqrt{1-4p_{T,\min}^2/(M^2-4m^2)}\). Below that threshold the
cross section is zero. Define \(d=1-\beta^2\). The integral over this interval is

\[
\hat\sigma_c=\frac{4\pi\alpha^2\beta}{\hat s}
\left[-c-\frac{d^2c}{1-\beta^2c^2}
+\frac{3-\beta^4}{\beta}\operatorname{atanh}(\beta c)\right].
\]

The convolution is

\[
\sigma=\int d\tau\int_{-Y}^{Y}dy\,
 f_\gamma(x_1,Q)f_\gamma(x_2,Q)\hat\sigma_c(M^2),
\qquad Y=\min\{\log(E_{\rm cm}/M),y_{\max}\}.
\]

The mass window limits the outer integral. When no pair rapidity bound is
supplied, the kinematic bound alone applies. The implementation integrates in
\(\log M\): the integrand becomes \(2[x_1f_\gamma][x_2f_\gamma]\hat\sigma_c\).
It uses the supplied fixed coupling and retains the positive mass regulator.
The unit conversion is \(1\,{\rm GeV}^{-2}=389379372.1\,{\rm pb}\).

The validity range is collinear, unpolarized leading-order production by two photon
partons, with stable leptons and positive finite mass. The supported scale is
fixed or a supplied multiple of pair mass. The beams have equal energies;
`energy_gev` is their total centre-of-mass energy. Proton and antiproton use the
same supplied charge-conjugate photon density. The supported cuts are the pair
mass window, absolute pair rapidity and each lepton's minimum transverse
momentum. Individual pseudorapidity, angular asymmetry, radiation, detector
selection, elastic-only restrictions, survival factors, running coupling and
additional amplitudes are outside this formula and must be refused. The check uses the stated photon-initiated fixed-order formula.

## Supplied interfaces

`photon_luminosity.cross_section(spec, density)` returns a JSON-ready record.
All energies, masses, scales and pT values are GeV. Cross sections and absolute
errors are pb. The specification is a mapping with these fields:

| Field | Supplied value |
|---|---|
| `energy_gev` | Positive centre-of-mass energy |
| `beams` | Two proton/antiproton PDG identifiers |
| `process` | `initial: [22, 22]`, `final: [pdg, -pdg]` for the supplied charged lepton |
| `pdf` | `name`, nonnegative integer `member`, installed/supplied `flavours` containing 22 |
| `scale` | `kind: fixed, q_gev: Q` or `kind: pair_mass, factor: k` |
| `lepton_mass_gev` | Positive executed lepton mass |
| `alpha` | Positive fixed electromagnetic coupling used in the executed matrix element |
| `cuts` | `mass_window_gev: [lower, upper]`; when supplied, `pair_abs_rapidity_max` and `lepton_pt_min_gev` |
| `integration` | When supplied, both `epsrel` and `epsabs_pb`; defaults are 1e-7 and 1e-9 pb |

Unknown fields are refused. A window must be ordered and lie at or below beam
energy; its physical integration interval is intersected with the pair threshold.
Cuts with zero admitted phase space return zero. No efficiency or multiplicative
physics correction is assumed.

The density provider is callable as `density(x, Q)` and returns **x times the
photon density**, not the photon density alone, as a finite nonnegative real
number. Synthetic checks can supply an analytic callable. Production uses `DensityTable(table)`, built from the
separate worker's output. The result preserves the complete spec, effective
quadrature settings, formula identifier, units, numerical value and
`integration_error_pb`; a table-backed result also preserves the table and its
metadata. QUADPACK's outer estimate plus the largest observed inner estimate
times the integration interval is an error estimate, not a rigorous upper
bound. Failure to converge is refused. A table-backed density changes slope at
its nodes, so the rapidity integral is split where either momentum fraction
crosses an x node and, under the pair-mass scale rule, the mass integral is
split where the scale crosses a Q node. The default precision therefore applies
to tables as well as to smooth callables.

`photon_luminosity.compare(check, generator_result, tolerance)` consumes a
completed check and a generator record with **exactly** `spec`,
`cross_section_pb`, and `statistical_error_pb`. The caller builds that spec from
the run's executed beam/card/PDF records, not from intended settings. The
comparator validates set, member, energy, beams, process, mass, coupling, cuts
and scale rule. Numerical integration settings and flavour-census ordering are
not physical setup differences. Missing metadata or changed conditions require
repairing the record or calculating a matching check; they must not pass the
comparison. The generator's integration statistical error belongs in
`statistical_error_pb`.

The supplied tolerance lies strictly between zero and one. Pass requires
`abs(generator - check) <= tolerance * check`, and the numerical quadrature
error must also be below that relative tolerance. Generator statistical and PDF
uncertainties are recorded without increasing the allowed central difference.
The comparison record preserves both inputs, both numbers, statistical error,
quadrature error, tolerance and the verdict. For a zero reference, only an exact
zero comparison with zero quadrature error can pass; `relative_difference` is
null. This record grants no launch or scientific-acceptance authority.

For a requested PDF uncertainty, call
`with_pdf_uncertainty(check, member_checks, prescription)` before `compare`.
Supply the complete ordered error-member list, `kind` (`replicas` or
`symmetric_hessian`), `confidence_level` in (0,1), and positive `rescale` from
the set's metadata. Replica uncertainty uses the sample standard deviation
about the replica mean. Symmetric Hessian members are adjacent plus/minus
pairs and use half the quadrature sum of pair differences. `rescale` is the
explicit caller-supplied confidence conversion. Other prescriptions require a
separately justified implementation. Missing/duplicate members or changed setups
are refused. All member results, their quadrature errors and the prescription
are retained; quadrature error is not subtracted from PDF uncertainty.

## Separate density worker

`photon_density_worker.py` runs as a standalone script in the selected generator
environment and imports its LHAPDF binding there. The RAVEL process never
imports that binding. Locate the interpreter through
`generator_versions.installed_madgraph`: the selected manifest `madgraph`
source is paired with an options file, whose `lhapdf_py3` path determines
`parent.parent / bin/python`. Use the interpreter of the run's selected version.
The provider helper executes the argument list
`[runtime['python'], '-B', worker_path]` with a JSON request on stdin; a timeout
or nonzero exit is refused, and the refusal quotes the worker's last error line
(for example a set with no photon density, or a node outside the set's range).
It never starts MadGraph.

The request contains exactly:

```text
{"set": supplied_name, "member": supplied_member,
 "x": supplied_increasing_x_nodes, "q_gev": supplied_increasing_Q_nodes}
```

Each axis has at least two finite positive nodes; x is at most one. A request
contains at most 100000 points. The reply contains exactly:

```text
{"schema_version": 1, "set": requested_name, "member": requested_member,
 "x": requested_x_nodes, "q_gev": requested_Q_nodes,
 "values": rows_of_xfxQ22_in_x_major_Q_minor_order,
 "flavours": installed_flavours, "lhapdf_version": observed_version}
```

`density_from_worker([runtime['python'], '-B'], request)` returns a
`DensityTable`. Wrong set/member/grid identity, malformed JSON, missing photon
flavour, invalid shape and negative/nonfinite values are refused. The worker
refuses nodes beyond the PDF's x/Q validity interval. The host interpolates
**x*f** bilinearly in log(x) and log(Q), with no extrapolation. A single grid
does not determine interpolation error. Compare independently refined grids
and preserve their results; that difference is separate from quadrature error.
The grid must cover the full admitted x and Q region, including the kinematic
rapidity endpoints. Under an unrestricted rapidity integral, the smallest x
needed is the lower physical pair-mass squared divided by beam energy squared.

## Check a finished run

Prepare `spec.json` and `generator-result.json` from the finished run's effective
setup, then supply its photon-density grid as `density-table.json`. Preserve the
source run receipt and recorded card/PDF bytes alongside those local files.
The reader command takes only local supplied files:

```sh
python -B -m ravel.physics.photon_luminosity \
  --spec spec.json --density-table density-table.json \
  --generator-result generator-result.json \
  --tolerance "$RELATIVE_TOLERANCE" --output comparison.json
```

The command launches no process. It writes a comparison on pass or numerical
failure, exits zero on pass and one on failure; malformed inputs produce an
argument error. For a requested PDF uncertainty, construct member checks with
the Python API and serialize the final `compare` record.

A mismatch first requires checking executed beam identity, photon-only initial
state, PDF member, coupling convention, masses, scale and cuts. Resolve grid
interpolation and quadrature precision separately from generator integration
statistics. A significant same-setup difference can indicate a generator/PDF
configuration defect or a formula applicability mismatch. It is not evidence that
other channels or generator versions are validated. The tool census can record
the scoped receipt only after the ordinary admitted native generation job and
this comparator both have current evidence. The generation front end already
refuses a photon parton with a photonless PDF set in `beam_content.content` when
its required flavour census is present; this check leaves that front end unchanged.
