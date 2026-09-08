# RRR 225/220 GeV shape control

The fresh 20,000-event control repeats the historical high-MET shape discrepancy:
88/186 events (47.3%) occupy the 101–102 GeV mT2 bin, compared with 93/200
(46.5%) historically and 29.4% in the released ATLAS signal template.

Read the [interpretation and next experiment](../../../docs/research/2026-09-08-rrr-shape-control.md).
This is supplementary diagnostic evidence, not a replacement for the active
fidelity audits or a physics certificate.

![Signal-bin comparison](signal-shape-comparison.png)

`measurements.json` contains counts, weight moments, shape covariance, flavor and
production-state decompositions, selection migrations, timings and source
commitments. The raw LHE, HepMC and ROOT files remain in the original research
run. Their hashes are commitments, not a claim that they are distributed here.

Verify the portable aggregate arithmetic with an environment containing NumPy:

```bash
python evidence/audits/2026-09-08-rrr-shape-control/verify.py
```

`verification.json` records the successful check and rejection of four corrupted
copies. It does not authenticate the retained raw events. PNG and PDF versions
of the three diagnostic figures are included. No likelihood inversion or new
full-plane contour was performed for this control.
