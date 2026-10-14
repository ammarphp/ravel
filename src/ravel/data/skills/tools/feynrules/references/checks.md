# FeynRules checks RAVEL requests

The request schema is validated by `ravel.physics.model_physical_checks.validate`:

- `hermiticity`: true or false. When true, the script calls
  `CheckHermiticity[lagrangian, FlavorExpand -> True]` and records success.
- `feynman_gauge`: the gauge the model source uses; the script records
  `FeynmanGauge` before and after.
- `partial_widths.channels`: up to eight two-body channels, each a parent and
  two daughters, optionally with a reference of kind `scalar-dirac-yukawa`
  (one scalar decaying to a fermion and its antiparticle) and tolerances.

The FeynRules functions are documented in the FeynRules 2.0 manual
(Alloul et al., Comput. Phys. Commun. 185 (2014) 2250, arXiv:1310.1921) and at
https://feynrules.irmp.ucl.ac.be/.

An illustrative session in the Wolfram language:

```wolfram ravel-block=fr-session-shape
LoadModel["model.fr"];
CheckHermiticity[LSM, FlavorExpand -> True];
WriteUFO[LSM];
```
