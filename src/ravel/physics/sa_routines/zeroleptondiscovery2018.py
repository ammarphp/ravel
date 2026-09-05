"""ZeroLeptonDiscovery2018 -- native port of ATLAS-SUSY-2018-22's discovery SRs (CR-005).

Line-faithful transcription of SimpleAnalysisCodes/src/ANA-SUSY-2018-22_Discovery.cxx (185
lines; 10 inclusive meff-based signal regions, 0-lepton jets+MET). Validated bit-for-bit vs the
container oracle (cr005_validate.py) before use.

AMBIGUITY LEDGER (transcription decisions; the oracle diff adjudicates each):
  A1  OverlapVeto = event->getMCVeto(): the Delphes2SA ntuple carries no mcVetoCode, so the
      container SA sees veto=0 for these samples; transcribed as the constant 0.
  A2  Lepton-ID bits (ELooseLH/ETightLH/iso/MuMedium...) are transcribed faithfully but are
      no-ops on Delphes2SA input (el_id/mu_id = 0x7FFFFFFF, all bits set) -- identical on both
      sides of the diff (the flagship's MAINTAINER WARNING applies).
  A3  `auto leptons = electrons + muons` etc.: SA's operator+ SORTS by pT after concatenation
      (AnalysisObject.cxx) -- transcribed via core.concat_sorted. Load-bearing for
      corrected_jets = goodJets + signalleptons1 (a hard lepton can outrank jets in [0]/[1]).
  A4  bjets (BTag77MV2c20 bit) feed only an ntupVar in the C++, never an SR cut -- counted but
      unused here.
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[3]))
    __package__ = "ravel.physics.sa_routines"

import sys, os

from ..sa_native_core import (Obj, ELECTRON, MUON, NOT, LooseBadJet, ELooseLH, ETightLH,
                            MuMedium, ED0Sigma5, EZ05mm, EIsoFixedCutTight,
                            MuD0Sigma3, MuZ05mm,
                            MuIsoFixedCutTightTrackOnly, BTag77MV2c20,
                            filterObjects, countObjects, overlapRemoval, calcMT,
                            concat_sorted, sum_objects_pt, min_dphi_n, aplanarity,
                            build_leptons_jets_met, BASE_BRANCHES)

NAME = "ZeroLeptonDiscovery2018"
BRANCHES = BASE_BRANCHES
FLAVOUR_FLAGS = ("is0L", "is1SigL")     # bookkeeping flags (this analysis is flavour-blind)

_SRS = ["SR2j_1600_SR", "SR2j_2200_SR", "SR2j_2800_SR",
        "SR4j_1000_SR", "SR4j_2200_SR", "SR4j_3400_SR",
        "SR5j_1600_SR",
        "SR6j_1000_SR", "SR6j_2200_SR", "SR6j_3400_SR"]


def sr_order():
    return list(_SRS)


def select(arrays, i):
    """ProcessEvent transcription. Returns (accepted_set, is0L, is1SigL) or None."""
    import math
    baseEl, baseMu, preJets, met = build_leptons_jets_met(arrays, i, jet_preselect=(20.0, 2.8))
    # getElectrons(7, 2.47, ELooseLH) / getMuons(6, 2.7, MuMedium) / getJets(20., 2.8)
    electrons = filterObjects(baseEl, 7, 2.47, ELooseLH)
    muons = filterObjects(baseMu, 6, 2.7, MuMedium)
    jets = preJets
    metPt = met.pt

    # Reject events with bad jets
    if countObjects(jets, 20, 2.8, NOT(LooseBadJet)) != 0:
        return None

    # Standard SUSY overlap removal
    jets = overlapRemoval(jets, electrons, 0.2)
    electrons = overlapRemoval(electrons, jets, 0.4)
    muons = overlapRemoval(muons, jets, 0.4)

    # signal leptons (ID/iso bits transcribed; no-ops on Delphes2SA input -- ledger A2)
    signalMuons = filterObjects(muons, 6, 2.7, MuD0Sigma3 | MuZ05mm | MuIsoFixedCutTightTrackOnly)
    signalElectrons = filterObjects(electrons, 7, 2.47, ETightLH | ED0Sigma5 | EZ05mm | EIsoFixedCutTight)
    signalMuons1 = filterObjects(muons, 50, 2.7, MuD0Sigma3 | MuZ05mm | MuIsoFixedCutTightTrackOnly)
    signalElectrons1 = filterObjects(electrons, 50, 2.47, ETightLH | ED0Sigma5 | EZ05mm | EIsoFixedCutTight)

    goodJets = filterObjects(jets, 50, 100.0)                  # filterObjects(jets, 50)
    bjets = filterObjects(goodJets, 50, 2.5, BTag77MV2c20)     # ntupVar only (ledger A4)

    leptons = concat_sorted(electrons, muons)
    signalleptons = concat_sorted(signalElectrons, signalMuons)
    signalleptons1 = concat_sorted(signalElectrons1, signalMuons1)

    # preselection: SR and CRT
    if not (len(leptons) == 0 or len(signalleptons) == 1):
        return None

    corrected_jets = goodJets if len(leptons) == 0 else concat_sorted(goodJets, signalleptons1)

    meffIncl = sum_objects_pt(corrected_jets) + metPt
    Njets = len(corrected_jets)

    # preselection
    if metPt < 300:
        return None
    if len(corrected_jets) < 2:
        return None
    if corrected_jets[0].pt < 200.:
        return None
    if corrected_jets[1].pt < 50.:
        return None
    if meffIncl < 800:
        return None

    dphiMin3 = min_dphi_n(met, corrected_jets, 3)
    dphiMinRest = min_dphi_n(met, corrected_jets)
    Ap = aplanarity(corrected_jets)
    OverlapVeto = 0                                            # ledger A1

    accepted = set()
    j = corrected_jets                                          # brevity for the SR block

    if OverlapVeto == 0 and len(leptons) == 0 and metPt >= 300.0:
        sig = metPt / math.sqrt(meffIncl - metPt)

        if (Njets >= 2 and meffIncl >= 1600.0 and sig >= 16.0 and dphiMin3 >= 0.8
                and (dphiMinRest >= 0.4 or Njets <= 3) and j[0].pt >= 250 and j[1].pt >= 250
                and abs(j[0].eta) <= 2.0 and abs(j[1].eta) <= 2.0):
            accepted.add("SR2j_1600_SR")

        if (Njets >= 2 and meffIncl >= 2200.0 and sig >= 16.0 and dphiMin3 >= 0.4
                and (dphiMinRest >= 0.2 or Njets <= 3) and j[0].pt >= 600 and j[1].pt >= 50
                and abs(j[0].eta) <= 2.8 and abs(j[1].eta) <= 2.8):
            accepted.add("SR2j_2200_SR")

        if (Njets >= 2 and meffIncl >= 2800.0 and sig >= 16.0 and dphiMin3 >= 0.8
                and (dphiMinRest >= 0.4 or Njets <= 3) and j[0].pt >= 250 and j[1].pt >= 250
                and abs(j[0].eta) <= 1.2 and abs(j[1].eta) <= 1.2):
            accepted.add("SR2j_2800_SR")

        if (Njets >= 4 and meffIncl >= 1000.0 and sig >= 16.0 and dphiMin3 >= 0.4
                and (dphiMinRest >= 0.2 or Njets <= 3)
                and j[0].pt >= 200 and j[1].pt >= 100 and j[2].pt >= 100 and j[3].pt >= 100
                and abs(j[0].eta) <= 2.0 and abs(j[1].eta) <= 2.0 and abs(j[2].eta) <= 2.0
                and abs(j[3].eta) <= 2.0 and Ap >= 0.04):
            accepted.add("SR4j_1000_SR")

        if (Njets >= 4 and meffIncl >= 2200.0 and sig >= 16.0 and dphiMin3 >= 0.4
                and (dphiMinRest >= 0.2 or Njets <= 3)
                and j[0].pt >= 200 and j[1].pt >= 100 and j[2].pt >= 100 and j[3].pt >= 100
                and abs(j[0].eta) <= 2.0 and abs(j[1].eta) <= 2.0 and abs(j[2].eta) <= 2.0
                and abs(j[3].eta) <= 2.0 and Ap >= 0.04):
            accepted.add("SR4j_2200_SR")

        if (Njets >= 4 and meffIncl >= 3400.0 and sig >= 10.0 and dphiMin3 >= 0.4
                and (dphiMinRest >= 0.2 or Njets <= 3)
                and j[0].pt >= 200 and j[1].pt >= 100 and j[2].pt >= 100 and j[3].pt >= 100
                and abs(j[0].eta) <= 2.0 and abs(j[1].eta) <= 2.0 and abs(j[2].eta) <= 2.0
                and abs(j[3].eta) <= 2.0 and Ap >= 0.04):
            accepted.add("SR4j_3400_SR")

        if (Njets >= 5 and meffIncl >= 1600.0 and sig >= 16.0 and dphiMin3 >= 0.4
                and (dphiMinRest >= 0.2 or Njets <= 3)
                and j[0].pt >= 600 and j[1].pt >= 50 and j[2].pt >= 50 and j[3].pt >= 50
                and j[4].pt >= 50
                and abs(j[0].eta) <= 2.8 and abs(j[1].eta) <= 2.8 and abs(j[2].eta) <= 2.8
                and abs(j[3].eta) <= 2.8 and abs(j[4].eta) <= 2.8):
            accepted.add("SR5j_1600_SR")

        if (Njets >= 6 and meffIncl >= 1000.0 and sig >= 16.0 and dphiMin3 >= 0.4
                and (dphiMinRest >= 0.2 or Njets <= 3)
                and j[0].pt >= 200 and j[1].pt >= 75 and j[2].pt >= 75 and j[3].pt >= 75
                and j[4].pt >= 75 and j[5].pt >= 75
                and abs(j[0].eta) <= 2.0 and abs(j[1].eta) <= 2.0 and abs(j[2].eta) <= 2.0
                and abs(j[3].eta) <= 2.0 and abs(j[4].eta) <= 2.0 and abs(j[5].eta) <= 2.0
                and Ap >= 0.08):
            accepted.add("SR6j_1000_SR")

        if (Njets >= 6 and meffIncl >= 2200.0 and sig >= 16.0 and dphiMin3 >= 0.4
                and (dphiMinRest >= 0.2 or Njets <= 3)
                and j[0].pt >= 200 and j[1].pt >= 75 and j[2].pt >= 75 and j[3].pt >= 75
                and j[4].pt >= 75 and j[5].pt >= 75
                and abs(j[0].eta) <= 2.0 and abs(j[1].eta) <= 2.0 and abs(j[2].eta) <= 2.0
                and abs(j[3].eta) <= 2.0 and abs(j[4].eta) <= 2.0 and abs(j[5].eta) <= 2.0
                and Ap >= 0.08):
            accepted.add("SR6j_2200_SR")

        if (Njets >= 6 and meffIncl >= 3400.0 and sig >= 10.0 and dphiMin3 >= 0.4
                and (dphiMinRest >= 0.2 or Njets <= 3)
                and j[0].pt >= 200 and j[1].pt >= 75 and j[2].pt >= 75 and j[3].pt >= 75
                and j[4].pt >= 75 and j[5].pt >= 75
                and abs(j[0].eta) <= 2.0 and abs(j[1].eta) <= 2.0 and abs(j[2].eta) <= 2.0
                and abs(j[3].eta) <= 2.0 and abs(j[4].eta) <= 2.0 and abs(j[5].eta) <= 2.0
                and Ap >= 0.08):
            accepted.add("SR6j_3400_SR")

    return accepted, (len(leptons) == 0), (len(signalleptons) == 1)
