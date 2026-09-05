"""sa_routines -- per-routine native SimpleAnalysis ports on sa_native_core (CR-005).

Each module transcribes ONE routine's ProcessEvent from the ATLAS SimpleAnalysis source
(SimpleAnalysisCodes/src/ANA-*.cxx) line-faithfully, exposes NAME / BRANCHES / FLAVOUR_FLAGS /
sr_order() / select(arrays, i), and is validated bit-for-bit against the container oracle
(cr005_validate.py) before it may serve results. Registry: REGISTRY below; the flagship
EwkCompressed2018 stays in native_simpleanalysis.py (its RJR two-pass flow predates this layout
and is equally oracle-validated).
"""
REGISTRY = {
    "ZeroLeptonDiscovery2018": "ravel.physics.sa_routines.zeroleptondiscovery2018",
    "EwkThreeLeptonERJR2018": "ravel.physics.sa_routines.ewkthreeleptonerjr2018",
}
