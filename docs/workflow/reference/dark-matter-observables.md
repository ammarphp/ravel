# Dark matter calculation conventions

Specify the supplied model, particle identity, mass, couplings and spectrum for
relic-density and scattering calculations. Preserve the source, version, licence
and input-file digests with the calculation record.

A relic-density result requires its freeze-out prescription. An annihilation
rate requires the velocity and an explicit fixed-velocity or velocity-average
definition. Use the same definition in the prediction and its reference.

Direct-detection comparisons require the local density, velocity distribution,
density fraction, scattering convention and target response. An experimental
limit is valid for the signal and astrophysical assumptions used to derive it.
Record the units and scalar or spin-dependent convention for every cross section.

Preserve signed amplitudes and complete decay and channel populations. Derive
branching fractions from the supplied widths and record the source of each
nuisance response and uncertainty correlation.

Keep native execution inputs, outputs, logs and failed attempts with their source
identities. Scientific review checks physical applicability, numerical precision,
reference conventions and uncertainty propagation against the requested quantity.
Use the [scientific-study procedure](scientific-studies.md) and the
[check-in requirements](../checklists/check-ins.md) for admitted computations.
