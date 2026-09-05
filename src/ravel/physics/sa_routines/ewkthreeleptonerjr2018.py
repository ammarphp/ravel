"""EwkThreeLeptonERJR2018 -- native port of ATLAS-SUSY-2018-06's 3-lepton RJR-emulated search.

Line-faithful transcription of SimpleAnalysisCodes/src/ANA-SUSY-2018-06.cxx (242 lines; WZ + MET
with the recursive-jigsaw variables EMULATED via plain Lorentz boosts -- zero RestFrames).
Regions (addRegions order): Preselection, SRlow, SRISR, CRlow, CRISR, VRlow, VRISR,
VRISRsmallPTsoft, VRISRsmallRjetsinv. Validated bit-for-bit vs the container oracle.

AMBIGUITY LEDGER:
  A1  The cutflow HISTOGRAM fills are not transcribed (histograms are not in the txt the
      validation diffs; regions are).
  A2  Lepton/jet ID bits transcribed header-verbatim (ELooseBLLH, MuNotCosmic|MuQoPSignificance,
      JVT120Jet, EIsoFCTight, MuIsoFCTightFR, BTag77MV2c10); lepton-ID are no-ops on Delphes2SA
      input (0x7FFFFFFF), the JET bits are real.
  A3  TLorentzVector::Boost transcribed with ROOT's exact formula (gamma2=(gamma-1)/b2);
      vMETprime is NOT boosted in the C++ (H_boost uses its unboosted P()) -- kept.
  A4  The odd lepton-pT precut `(l0<25 && l1<25 && l2<20) -> reject` is AND in the C++ --
      transcribed as-is (rejects only when ALL three are soft).
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[3]))
    __package__ = "ravel.physics.sa_routines"

import sys, os, math

from ..sa_native_core import (ELooseBLLH, MuMedium, MuNotCosmic, MuQoPSignificance,
                            EMediumLH, ED0Sigma5, EZ05mm, EIsoFCTight,
                            MuD0Sigma3, MuZ05mm, MuIsoFCTightFR,
                            JVT120Jet, BTag77MV2c10, LessThan3Tracks,
                            filterObjects, overlapRemoval, overlapRemovalVR, calcMT,
                            concat_sorted, invmass, build_leptons_jets_met, BASE_BRANCHES)

NAME = "EwkThreeLeptonERJR2018"
BRANCHES = BASE_BRANCHES
FLAVOUR_FLAGS = ("ge2e", "ge2mu")

_SRS = ["Preselection", "SRlow", "SRISR", "CRlow", "CRISR",
        "VRlow", "VRISR", "VRISRsmallPTsoft", "VRISRsmallRjetsinv"]

MZ = 91.1876


def sr_order():
    return list(_SRS)


def _p4(pt, eta, phi, m):
    """(px,py,pz,E) from pt/eta/phi/m -- TLorentzVector::SetPtEtaPhiM."""
    px = pt * math.cos(phi); py = pt * math.sin(phi); pz = pt * math.sinh(eta)
    E = math.sqrt(px*px + py*py + pz*pz + m*m)
    return [px, py, pz, E]


def _add(a, b):
    return [a[i] + b[i] for i in range(4)]


def _boost(p, bx, by, bz):
    """ROOT TLorentzVector::Boost, verbatim semantics."""
    b2 = bx*bx + by*by + bz*bz
    gamma = 1.0 / math.sqrt(1.0 - b2)
    bp = bx*p[0] + by*p[1] + bz*p[2]
    gamma2 = (gamma - 1.0) / b2 if b2 > 0 else 0.0
    return [p[0] + gamma2*bp*bx + gamma*bx*p[3],
            p[1] + gamma2*bp*by + gamma*by*p[3],
            p[2] + gamma2*bp*bz + gamma*bz*p[3],
            gamma*(p[3] + bp)]


def _pmag(p):
    return math.sqrt(p[0]*p[0] + p[1]*p[1] + p[2]*p[2])


def select(arrays, i):
    baseEl, baseMu, preJets, met = build_leptons_jets_met(arrays, i, jet_preselect=(20.0, 4.5))
    # getElectrons(10., 2.47, ELooseBLLH) / getMuons(10, 2.4, MuMedium|MuNotCosmic|MuQoPSignificance)
    baselineElectrons = filterObjects(baseEl, 10, 2.47, ELooseBLLH)
    baselineMuons = filterObjects(baseMu, 10, 2.4, MuMedium | MuNotCosmic | MuQoPSignificance)
    baselineJets = preJets                                    # getJets(20., 4.5)
    metPt = met.pt

    # overlap removal (order + radii exactly as the .cxx)
    radiusCalcLepton = lambda lepton, other: min(0.4, 0.04 + 10.0/lepton.pt)
    baselineElectrons = overlapRemoval(baselineElectrons, baselineMuons, 0.01)
    baselineJets = overlapRemoval(baselineJets, baselineElectrons, 0.2)
    baselineJets = overlapRemoval(baselineJets, baselineMuons, 0.2, LessThan3Tracks)
    baselineElectrons = overlapRemovalVR(baselineElectrons, baselineJets, radiusCalcLepton)
    baselineMuons = overlapRemovalVR(baselineMuons, baselineJets, radiusCalcLepton)

    nbaselineleptons = len(baselineElectrons) + len(baselineMuons)

    # signal objects
    electrons = filterObjects(baselineElectrons, 20, 2.47,
                              EMediumLH | ED0Sigma5 | EZ05mm | EIsoFCTight)
    muons = filterObjects(baselineMuons, 20, 2.4, MuD0Sigma3 | MuZ05mm | MuIsoFCTightFR)
    jets = filterObjects(baselineJets, 20, 2.4, JVT120Jet)
    bjets = filterObjects(jets, 20., 2.4, BTag77MV2c10)
    leptons = concat_sorted(electrons, muons)                 # operator+ sorts; explicit sort follows in C++ anyway
    jets = sorted(jets, key=lambda o: -o.pt)                  # sortObjectsByPt(jets)

    nleptons = len(leptons); nelectrons = len(electrons); nmuons = len(muons)
    njets = len(jets); nbjets = len(bjets)

    # exactly 3 baseline and signal leptons
    if nbaselineleptons != 3: return None
    if nleptons != 3: return None
    # b-jet veto
    if nbjets > 0: return None
    # lepton pT precut (ledger A4: AND, reject only if ALL soft)
    if leptons[0].pt < 25 and leptons[1].pt < 25 and leptons[2].pt < 20: return None

    # SFOS assignment closest to mZ
    mll = -999.0; mdiff = 1e6; nSFOS = 0
    iZ1 = iZ2 = iW = -1
    for il in range(nleptons - 1):
        for jl in range(il + 1, nleptons):
            kl = nleptons - il - jl
            if leptons[il].typ == leptons[jl].typ and leptons[il].charge != leptons[jl].charge:
                nSFOS += 1
                imll = invmass(leptons[il], leptons[jl])
                imdiff = abs(MZ - imll)
                if imdiff < mdiff:
                    mdiff = imdiff; mll = imll
                    iZ1, iZ2, iW = il, jl, kl
    if nSFOS == 0: return None

    # mlll > 105
    vl = [_p4(l.pt, l.eta, l.phi, l.m) for l in leptons]
    tot = _add(_add(vl[0], vl[1]), vl[2])
    m2 = tot[3]*tot[3] - tot[0]*tot[0] - tot[1]*tot[1] - tot[2]*tot[2]
    mlll = math.sqrt(m2) if m2 > 0 else 0.0
    if mlll < 105.: return None
    # Z peak
    if mll < 75. or mll > 105.: return None

    mTW = calcMT(leptons[iW], met)

    accepted = {"Preselection"}

    # ISR / LEP / MET systems
    vISR = [0.0, 0.0, 0.0, 0.0]
    for jt in jets:
        vISR = _add(vISR, _p4(jt.pt, jt.eta, jt.phi, jt.m))
    vLEP = [0.0, 0.0, 0.0, 0.0]
    for l4 in vl:
        vLEP = _add(vLEP, l4)
    vMET = [met.px, met.py, 0.0, math.sqrt(met.px*met.px + met.py*met.py)]

    pTjets = dphijetsinv = Rjetsinv = pTsoft = -999.0
    if len(jets) > 0:
        pTjets = math.hypot(vISR[0], vISR[1])
        # TLorentzVector::DeltaPhi via transverse phi difference wrapped to (-pi, pi]
        d = math.atan2(vISR[1], vISR[0]) - math.atan2(vMET[1], vMET[0])
        while d >= math.pi: d -= 2*math.pi
        while d < -math.pi: d += 2*math.pi
        dphijetsinv = d
        Rjetsinv = abs(vMET[0]*vISR[0] + vMET[1]*vISR[1]) / abs(pTjets*pTjets)
        s = _add(_add(vLEP, vMET), vISR)
        pTsoft = math.hypot(s[0], s[1])

    sPP = _add(vLEP, vMET)
    pTsoftPP = math.hypot(sPP[0], sPP[1])
    meff3l = leptons[0].pt + leptons[1].pt + leptons[2].pt + metPt

    # Z-component of the invisible system (the RJR emulation)
    mLEP2 = vLEP[3]*vLEP[3] - vLEP[0]*vLEP[0] - vLEP[1]*vLEP[1] - vLEP[2]*vLEP[2]
    mLEP = math.sqrt(mLEP2) if mLEP2 > 0 else 0.0
    ptLEP = math.hypot(vLEP[0], vLEP[1])
    long_inv = vLEP[2] * math.sqrt(metPt*metPt) / math.sqrt(ptLEP*ptLEP + mLEP*mLEP)
    pI = math.sqrt(vMET[0]*vMET[0] + vMET[1]*vMET[1] + long_inv*long_inv)

    boostx = (vLEP[0] + vMET[0]) / (vLEP[3] + math.sqrt(pI*pI))
    boosty = (vLEP[1] + vMET[1]) / (vLEP[3] + math.sqrt(pI*pI))
    boostz = (vLEP[2] + long_inv) / (vLEP[3] + math.sqrt(pI*pI))

    # vMETprime = SetXYZM(px, py, long_inv, 0) -- NOT boosted (ledger A3)
    vMETprime_P = math.sqrt(vMET[0]*vMET[0] + vMET[1]*vMET[1] + long_inv*long_inv)

    H_boost = sum(_pmag(_boost(l4, -boostx, -boosty, -boostz)) for l4 in vl) + vMETprime_P
    HTratio = meff3l / H_boost
    pTratio = pTsoftPP / (pTsoftPP + meff3l)

    l0, l1, l2 = leptons[0].pt, leptons[1].pt, leptons[2].pt
    if (l0 > 60. and l1 > 40. and l2 > 30. and njets == 0 and mTW > 0. and mTW < 70.
            and H_boost > 250. and pTratio < 0.2 and HTratio > 0.75 and metPt > 40.):
        accepted.add("CRlow")
    if (l0 > 60. and l1 > 40. and l2 > 30. and njets == 0 and mTW > 70. and mTW < 100.
            and H_boost > 250. and pTratio < 0.2 and HTratio > 0.75):
        accepted.add("VRlow")
    if (l0 > 60. and l1 > 40. and l2 > 30. and njets == 0 and mTW > 100.
            and H_boost > 250. and pTratio < 0.05 and HTratio > 0.9):
        accepted.add("SRlow")

    if (l0 > 25. and l1 > 25. and l2 > 20. and njets > 0 and mTW < 100.
            and abs(dphijetsinv) > 2.0 and Rjetsinv > 0.55 and Rjetsinv < 1.0
            and pTjets > 80. and metPt > 60. and pTsoft < 25.):
        accepted.add("CRISR")
    if (l0 > 25. and l1 > 25. and l2 > 20. and njets > 0 and mTW > 60.
            and abs(dphijetsinv) > 2.0 and Rjetsinv > 0.55 and Rjetsinv < 1.0
            and pTjets > 80. and metPt > 60. and pTsoft > 25.):
        accepted.add("VRISR")
    if (l0 > 25. and l1 > 25. and l2 > 20. and njets > 0 and njets < 4 and mTW > 100.
            and abs(dphijetsinv) > 2.0 and Rjetsinv > 0.55 and Rjetsinv < 1.0
            and pTjets > 100. and metPt > 80. and pTsoft < 25.):
        accepted.add("SRISR")

    if (l0 > 25. and l1 > 25. and l2 > 20. and njets > 0 and mTW > 60.
            and abs(dphijetsinv) > 2.0 and Rjetsinv > 0.55 and Rjetsinv < 1.0
            and pTjets < 80. and metPt > 60. and pTsoft < 25.):
        accepted.add("VRISRsmallPTsoft")
    if (l0 > 25. and l1 > 25. and l2 > 20. and njets > 0 and mTW > 60.
            and abs(dphijetsinv) > 2.0 and Rjetsinv > 0.3 and Rjetsinv < 0.55
            and pTjets > 80. and metPt > 60. and pTsoft < 25.):
        accepted.add("VRISRsmallRjetsinv")

    return accepted, (nelectrons >= 2), (nmuons >= 2)
