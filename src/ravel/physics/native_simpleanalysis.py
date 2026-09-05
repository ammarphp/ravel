#!/usr/bin/env python3
"""
native_simpleanalysis.py -- fully-native, VM-free reimplementation of ATLAS's
EwkCompressed2018 (ANA-SUSY-2018-16) SimpleAnalysis selection.

It reads a Delphes2SA 'ntuple' directly with uproot (rivet conda env), does the
COMPLETE object selection (getElectrons/getMuons/getJets, the 5-step overlap
removal, filterObjects, signalJets/signalBJets/signalLeptons, the soft-track
machinery, calcMT2/calcMTauTau/calcMT/mll/MET), and reproduces the container's
per-SR yields.

Single source of truth: object selection lives HERE. The two RestFrames RJR
variables (R_ISR, M_S) are computed by the native C++ resolver
(trial-runs/_infrastructure/rjr_resolve, recast env) on the EXACT signalJets +
summed signal-lepton system this script produces -- NOT on a looser jet
selection, and NEVER by reading the container's RJR_* branches.

Flow:
  1. object selection (per event) -> for events passing the ProcessEvent RJR
     gate (baseLeptons>=1 && signalJets>=1), write signalJets (pt,phi,m) + each
     signalLepton (pt,phi,m) + MET (pt,phi) to an objects file keyed by Event.
  2. subprocess: <conda> run -n recast rjr_resolve --objects <objfile> <csv>
  3. read R_ISR/M_S back keyed by Event, run the full SR accept cascade, emit
     EwkCompressed2018.txt (and optionally .root).

Usage:
  <conda> run -n rivet python native_simpleanalysis.py \
      --input  <Delphes2SA.root> \
      --output <dir> \
      [--ngen N]   (default: number of entries in the ntuple)

The object-selection code below is the validated prototype (object selection,
overlap removal, mT2, MTauTau, mT, mll, MET) -- proven boolean-exact against the
container GIVEN the correct RJR. The ONLY change vs the prototype is that R_ISR
and M_S now come from the native resolver instead of the container branches.

MAINTAINER WARNING -- lepton-ID cuts are DELIBERATE no-ops (do not "fix" them).
Delphes2SA writes el_id/mu_id = 0x7FFFFFFF (all quality bits set) for every
lepton (mapyde share Delphes2SA.py: `def Add(self, obj, objID=0x7FFFFFFF, ...)`),
because Delphes has no real ID-quality emulation. This script therefore reads
the id fields but NEVER cuts on them -- exactly like the container chain, which
is why the per-SR yields are bit-for-bit (141/141 SRs). Implementing "real"
ID/quality cuts here (e.g. porting them from the ATLAS EwkCompressed2018 source)
would silently change every yield and break the validated container parity.
Durable record: docs/workflow/reference/native-pipeline.md (charter 4d-b).
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import sys, os, math, argparse, subprocess
import numpy as np

# CR-005: the routine-AGNOSTIC machinery now lives in sa_native_core (extracted VERBATIM from
# this file's validated implementation). This module keeps ONLY the EwkCompressed2018-specific
# selection + the RJR two-pass orchestration, and RE-EXPORTS the primitives so existing importers
# (native_sa_generic.py and any run-local script) keep working unchanged.

from .sa_native_core import (   # noqa: F401  (re-exports are the compat surface)
    Lester, _ellipse, _helper, get_mT2,
    Obj, ELECTRON, MUON, ME, MMU,
    NotBit, NOT, LooseBadJet, JVT50Jet, LessThan3Tracks, BTag85MV2c10,
    filterObjects, countObjects, overlapRemoval,
    invmass, pairDeltaPhi_to_met, calcMT, calcMTauTau, calcAMT2, minDphi,
    load_ntuple, write_txt, write_root, _g,
    CONDA)

from ..paths import native_binary
RJR_BIN = str(native_binary("rjr_resolve"))


# ---------------- per-event object selection (returns the gated objects, or None) ----------------
def select_objects(arrays, i):
    """Full object selection ported from ANA-SUSY-2018-16.cxx::ProcessEvent
    (prepare-objects block, lines 135-209). Returns a dict with the gated
    quantities needed for (a) the RJR resolver input and (b) the kinematic SR
    cascade -- or None if the event is rejected before the RJR helper is reached
    (bad-jet veto, baseLeptons<1, or signalJets<1)."""
    baseElectrons=[]
    for j in range(len(arrays['el_pt'][i])):
        baseElectrons.append(Obj(arrays['el_pt'][i][j], arrays['el_eta'][i][j], arrays['el_phi'][i][j],
                                 ME, arrays['el_charge'][i][j], arrays['el_id'][i][j], ELECTRON))
    baseMuons=[]
    for j in range(len(arrays['mu_pt'][i])):
        baseMuons.append(Obj(arrays['mu_pt'][i][j], arrays['mu_eta'][i][j], arrays['mu_phi'][i][j],
                             MMU, arrays['mu_charge'][i][j], arrays['mu_id'][i][j], MUON))
    preJets=[]
    for j in range(len(arrays['jet_pt'][i])):
        if arrays['jet_pt'][i][j]>=20.0 and abs(arrays['jet_eta'][i][j])<4.5:
            preJets.append(Obj(arrays['jet_pt'][i][j], arrays['jet_eta'][i][j], arrays['jet_phi'][i][j],
                               arrays['jet_m'][i][j], 0, arrays['jet_id'][i][j], 4))
    met=Obj(arrays['met_pt'][i], 0.0, arrays['met_phi'][i], 0.0, 0, 0, 6)
    metPt=met.pt

    baseElectrons=filterObjects(baseElectrons, 4.5, 2.47, 1<<0)  # EVeryLooseLH
    baseMuons=filterObjects(baseMuons, 3, 2.5, 1<<1)             # MuMedium
    if countObjects(preJets, 20, 4.5, NOT(LooseBadJet))!=0:
        return None

    baseJets=overlapRemoval(preJets, baseElectrons, 0.2, NOT(BTag85MV2c10))
    baseElectrons=overlapRemoval(baseElectrons, baseJets, 0.4)
    baseElectrons=overlapRemoval(baseElectrons, baseMuons, 0.01)
    baseJets=overlapRemoval(baseJets, baseMuons, 0.4, LessThan3Tracks)
    baseMuons=overlapRemoval(baseMuons, baseJets, 0.4)

    signalJets=filterObjects(baseJets, 30, 2.8, JVT50Jet)
    signalBJets=filterObjects(baseJets, 20, 2.5, BTag85MV2c10)
    signalElectrons=filterObjects(baseElectrons, 4.5, 2.47, (1<<2)|(1<<16)|(1<<17)|(1<<13))  # EMediumLH|ED0Sigma5|EZ05mm|EIsoGradient
    signalMuons=filterObjects(baseMuons, 3, 2.5, (1<<16)|(1<<17)|(1<<10))  # MuD0Sigma3|MuZ05mm|MuIsoFixedCutTightTrackOnly

    baseLeptons=baseElectrons+baseMuons
    signalLeptons=signalElectrons+signalMuons

    # tracks
    preElTracks=[]
    for j in range(len(arrays['el_pt'][i])):
        if arrays['el_pt'][i][j]>=0.5 and abs(arrays['el_eta'][i][j])<2.5:
            preElTracks.append(Obj(arrays['el_pt'][i][j], arrays['el_eta'][i][j], arrays['el_phi'][i][j],
                                   ME, arrays['el_charge'][i][j], arrays['el_id'][i][j], ELECTRON))
    preMuTracks=[]
    for j in range(len(arrays['mu_pt'][i])):
        if arrays['mu_pt'][i][j]>=0.5 and abs(arrays['mu_eta'][i][j])<2.5:
            preMuTracks.append(Obj(arrays['mu_pt'][i][j], arrays['mu_eta'][i][j], arrays['mu_phi'][i][j],
                                   MMU, arrays['mu_charge'][i][j], arrays['mu_id'][i][j], MUON))

    def matches_signal(track, signals):
        for s in signals:
            if abs(track.px-s.px)<1e-9 and abs(track.py-s.py)<1e-9 and abs(track.pz-s.pz)<1e-9 and abs(track.E-s.E)<1e-9:
                return True
        return False

    baseElTracks=[t for t in preElTracks if not matches_signal(t, signalElectrons)]
    baseMuTracks=[t for t in preMuTracks if not matches_signal(t, signalMuons)]
    baseTracks=baseElTracks+baseMuTracks
    baseElTracks=overlapRemoval(baseElTracks, baseJets, 0.5)
    baseMuTracks=overlapRemoval(baseMuTracks, baseJets, 0.5)
    signalElTracks=overlapRemoval(baseElTracks, baseTracks, 0.3)
    signalMuTracks=overlapRemoval(baseMuTracks, baseTracks, 0.3)
    signalElTracks=filterObjects(signalElTracks, 1, 2.5, (1<<16)|(1<<17))  # ED0Sigma5|EZ05mm
    signalMuTracks=filterObjects(signalMuTracks, 1, 2.5, (1<<16)|(1<<17))  # MuD0Sigma3|MuZ05mm
    signalTracks=signalElTracks+signalMuTracks

    # ProcessEvent guards BEFORE the RJR helper is invoked
    if not (len(baseLeptons)>=1): return None
    if not (len(signalJets)>=1): return None

    return dict(met=met, signalJets=signalJets, signalBJets=signalBJets,
                signalLeptons=signalLeptons, signalTracks=signalTracks)


# ---------------- per-event SR cascade (given R_ISR/M_S) ----------------
def select_regions(sel, R_ISR, M_S):
    """Apply the kinematic + RJR SR selection (ProcessEvent lines 277-559) and
    return the set of accepted SR names. `sel` is the dict from select_objects;
    R_ISR/M_S come from the native resolver."""
    met=sel['met']; metPt=met.pt
    signalJets=sel['signalJets']; signalBJets=sel['signalBJets']
    signalLeptons=sel['signalLeptons']; signalTracks=sel['signalTracks']

    is2L=(len(signalLeptons)==2)
    is1LT=(len(signalLeptons)==1 and len(signalTracks)>=1)
    if not (is2L or is1LT):
        return set(), False, False

    lep1=signalLeptons[0]
    lep2=signalLeptons[1] if is2L else signalTracks[0]

    jet1Pt=signalJets[0].pt
    dPhiJ1Met=abs(signalJets[0].deltaPhi(met))
    minDPhiAllJetsMet=minDphi(met, signalJets)
    lep1Pt=lep1.pt; lep2Pt=lep2.pt
    dPhiLepMet=pairDeltaPhi_to_met(lep1,lep2,met)
    isOS=(lep1.charge!=lep2.charge)
    isSF=(lep1.typ==lep2.typ)
    isee=(lep1.typ==ELECTRON and lep2.typ==ELECTRON)
    ismm=(lep1.typ==MUON and lep2.typ==MUON)
    mll=invmass(lep1,lep2)
    drll=lep1.deltaR(lep2)
    metOverHtLep=metPt/(lep1Pt+lep2Pt)
    MTauTau=calcMTauTau(lep1,lep2,met)
    mt=calcMT(lep1,met)
    mn=100.0
    mt2=calcAMT2(lep1,lep2,met,mn,mn)

    accepted=set()

    pass_pre1LT = (is1LT and lep1Pt<10. and drll>0.05 and drll<1.5 and isOS and isSF
                   and mll>0.5 and mll<5 and (mll<3. or mll>3.2) and metPt>120.
                   and len(signalJets)>=1 and jet1Pt>100. and minDPhiAllJetsMet>0.4 and dPhiJ1Met>2.0)
    keep_SR_E_1LT = (pass_pre1LT and metPt>200. and metOverHtLep>30. and dPhiLepMet<1. and lep2Pt<5.)

    pass_common = (is2L and lep1Pt>5.
                   and ((drll>0.05 and ismm) or (drll>0.3 and isee))
                   and isOS and isSF
                   and ((mll>1. and mll<60. and ismm) or (mll>3. and mll<60. and isee))
                   and (mll<3. or mll>3.2)
                   and (MTauTau<0. or MTauTau>160.)
                   and metPt>120. and len(signalJets)>=1 and len(signalBJets)==0
                   and jet1Pt>100. and minDPhiAllJetsMet>0.4 and dPhiJ1Met>2.0)

    keep_SR_E_high = (pass_common and metPt>200. and mt<60.
                      and lep2Pt>min(10., 2+mll/3.) and R_ISR<1.
                      and R_ISR>max(0.85, 0.98-0.02*mll))
    keep_SR_E_med = (pass_common and mll<30. and metPt>120. and metPt<200.
                     and metOverHtLep>10. and M_S<50.)
    keep_SR_E_low = (pass_common and metPt>120. and metPt<200. and metOverHtLep<10.
                     and lep2Pt>(5.+mll/4.) and mt>10. and mt<60. and R_ISR<1. and R_ISR>0.8)
    keep_SR_E = keep_SR_E_high or keep_SR_E_med or keep_SR_E_low or keep_SR_E_1LT

    keep_iMLLa = mll<1.; keep_iMLLb = mll<2.; keep_iMLLc = mll<3.; keep_iMLLd = mll<5.
    keep_iMLLe = mll<10.; keep_iMLLf = mll<20.; keep_iMLLg = mll<30.; keep_iMLLh = mll<40.
    keep_iMLLi = mll<60.

    keep_SR_S_high = (pass_common and metPt>200. and mt2<140. and mt2>100.
                      and lep2Pt>min(20., 2.5+2.5*(mt2-100.)) and R_ISR<1.
                      and R_ISR>max(0.85, 0.98-0.02*(mt2-100)))
    keep_SR_S_low = (pass_common and metPt>150. and metPt<200. and mt2<140. and mt2>100.
                     and lep2Pt>min(15., 7.5+0.75*(mt2-100.)) and R_ISR<1. and R_ISR>0.8)
    keep_SR_S = keep_SR_S_high or keep_SR_S_low

    keep_iMT2a = mt2<100.5; keep_iMT2b = mt2<101.; keep_iMT2c = mt2<102.; keep_iMT2d = mt2<105.
    keep_iMT2e = mt2<110.; keep_iMT2f = mt2<120.; keep_iMT2g = mt2<130.; keep_iMT2h = mt2<140.

    def acc(name): accepted.add(name)

    # ---- Electroweakino inclusive SRs ----
    if keep_SR_E_high and keep_iMLLa: acc("SR_E_high_iMLLa")
    if keep_SR_E_high and keep_iMLLb: acc("SR_E_high_iMLLb")
    if keep_SR_E_high and keep_iMLLc: acc("SR_E_high_iMLLc")
    if keep_SR_E_high and keep_iMLLd: acc("SR_E_high_iMLLd")
    if keep_SR_E_high and keep_iMLLe: acc("SR_E_high_iMLLe")
    if keep_SR_E_high and keep_iMLLf: acc("SR_E_high_iMLLf")
    if keep_SR_E_high and keep_iMLLg: acc("SR_E_high_iMLLg")
    if keep_SR_E_high and keep_iMLLh: acc("SR_E_high_iMLLh")
    if keep_SR_E_high and keep_iMLLi: acc("SR_E_high_iMLLi")
    if keep_SR_E_med and keep_iMLLa: acc("SR_E_med_iMLLa")
    if keep_SR_E_med and keep_iMLLb: acc("SR_E_med_iMLLb")
    if keep_SR_E_med and keep_iMLLc: acc("SR_E_med_iMLLc")
    if keep_SR_E_med and keep_iMLLd: acc("SR_E_med_iMLLd")
    if keep_SR_E_med and keep_iMLLe: acc("SR_E_med_iMLLe")
    if keep_SR_E_med and keep_iMLLf: acc("SR_E_med_iMLLf")
    if keep_SR_E_med and keep_iMLLg: acc("SR_E_med_iMLLg")
    if keep_SR_E_med and keep_iMLLh: acc("SR_E_med_iMLLh")
    if keep_SR_E_med and keep_iMLLi: acc("SR_E_med_iMLLi")
    if keep_SR_E_low and keep_iMLLa: acc("SR_E_low_iMLLa")
    if keep_SR_E_low and keep_iMLLb: acc("SR_E_low_iMLLb")
    if keep_SR_E_low and keep_iMLLc: acc("SR_E_low_iMLLc")
    if keep_SR_E_low and keep_iMLLd: acc("SR_E_low_iMLLd")
    if keep_SR_E_low and keep_iMLLe: acc("SR_E_low_iMLLe")
    if keep_SR_E_low and keep_iMLLf: acc("SR_E_low_iMLLf")
    if keep_SR_E_low and keep_iMLLg: acc("SR_E_low_iMLLg")
    if keep_SR_E_low and keep_iMLLh: acc("SR_E_low_iMLLh")
    if keep_SR_E_low and keep_iMLLi: acc("SR_E_low_iMLLi")
    if keep_SR_E_1LT and keep_iMLLa: acc("SR_E_lT_iMLLa")
    if keep_SR_E_1LT and keep_iMLLb: acc("SR_E_lT_iMLLb")
    if keep_SR_E_1LT and keep_iMLLc: acc("SR_E_lT_iMLLc")
    if keep_SR_E_1LT and keep_iMLLd: acc("SR_E_lT_iMLLd")
    if keep_SR_E_1LT and keep_iMLLe: acc("SR_E_lT_iMLLe")
    if keep_SR_E_1LT and keep_iMLLf: acc("SR_E_lT_iMLLf")
    if keep_SR_E_1LT and keep_iMLLg: acc("SR_E_lT_iMLLg")
    if keep_SR_E_1LT and keep_iMLLh: acc("SR_E_lT_iMLLh")
    if keep_SR_E_1LT and keep_iMLLi: acc("SR_E_lT_iMLLi")
    if keep_SR_E and keep_iMLLa: acc("SR_E_iMLLa")
    if keep_SR_E and keep_iMLLb: acc("SR_E_iMLLb")
    if keep_SR_E and keep_iMLLc: acc("SR_E_iMLLc")
    if keep_SR_E and keep_iMLLd: acc("SR_E_iMLLd")
    if keep_SR_E and keep_iMLLe: acc("SR_E_iMLLe")
    if keep_SR_E and keep_iMLLf: acc("SR_E_iMLLf")
    if keep_SR_E and keep_iMLLg: acc("SR_E_iMLLg")
    if keep_SR_E and keep_iMLLh: acc("SR_E_iMLLh")
    if keep_SR_E and keep_iMLLi: acc("SR_E_iMLLi")

    # ---- Electroweakino exclusive SRs (else-if cascades) ----
    if   keep_SR_E_high and mll<2.:  acc("SR_E_high_eMLLa")
    elif keep_SR_E_high and mll<3.:  acc("SR_E_high_eMLLb")
    elif keep_SR_E_high and mll<5.:  acc("SR_E_high_eMLLc")
    elif keep_SR_E_high and mll<10.: acc("SR_E_high_eMLLd")
    elif keep_SR_E_high and mll<20.: acc("SR_E_high_eMLLe")
    elif keep_SR_E_high and mll<30.: acc("SR_E_high_eMLLf")
    elif keep_SR_E_high and mll<40.: acc("SR_E_high_eMLLg")
    elif keep_SR_E_high and mll<60.: acc("SR_E_high_eMLLh")

    if   keep_SR_E_med and mll<2.:  acc("SR_E_med_eMLLa")
    elif keep_SR_E_med and mll<3.:  acc("SR_E_med_eMLLb")
    elif keep_SR_E_med and mll<5.:  acc("SR_E_med_eMLLc")
    elif keep_SR_E_med and mll<10.: acc("SR_E_med_eMLLd")
    elif keep_SR_E_med and mll<20.: acc("SR_E_med_eMLLe")
    elif keep_SR_E_med and mll<30.: acc("SR_E_med_eMLLf")

    if   keep_SR_E_low and mll<2.:  acc("SR_E_low_eMLLa")
    elif keep_SR_E_low and mll<3.:  acc("SR_E_low_eMLLb")
    elif keep_SR_E_low and mll<5.:  acc("SR_E_low_eMLLc")
    elif keep_SR_E_low and mll<10.: acc("SR_E_low_eMLLd")
    elif keep_SR_E_low and mll<20.: acc("SR_E_low_eMLLe")
    elif keep_SR_E_low and mll<30.: acc("SR_E_low_eMLLf")
    elif keep_SR_E_low and mll<40.: acc("SR_E_low_eMLLg")
    elif keep_SR_E_low and mll<60.: acc("SR_E_low_eMLLh")

    if   keep_SR_E_1LT and mll<1.:  acc("SR_E_lT_eMLLa")
    elif keep_SR_E_1LT and mll<1.5: acc("SR_E_lT_eMLLb")
    elif keep_SR_E_1LT and mll<2.:  acc("SR_E_lT_eMLLc")
    elif keep_SR_E_1LT and mll<3.:  acc("SR_E_lT_eMLLd")
    elif keep_SR_E_1LT and mll<4.:  acc("SR_E_lT_eMLLe")
    elif keep_SR_E_1LT and mll<5.:  acc("SR_E_lT_eMLLf")

    # ---- Slepton inclusive SRs ----
    if keep_SR_S_high and keep_iMT2a: acc("SR_S_high_iMT2a")
    if keep_SR_S_high and keep_iMT2b: acc("SR_S_high_iMT2b")
    if keep_SR_S_high and keep_iMT2c: acc("SR_S_high_iMT2c")
    if keep_SR_S_high and keep_iMT2d: acc("SR_S_high_iMT2d")
    if keep_SR_S_high and keep_iMT2e: acc("SR_S_high_iMT2e")
    if keep_SR_S_high and keep_iMT2f: acc("SR_S_high_iMT2f")
    if keep_SR_S_high and keep_iMT2g: acc("SR_S_high_iMT2g")
    if keep_SR_S_high and keep_iMT2h: acc("SR_S_high_iMT2h")
    if keep_SR_S_low and keep_iMT2a: acc("SR_S_low_iMT2a")
    if keep_SR_S_low and keep_iMT2b: acc("SR_S_low_iMT2b")
    if keep_SR_S_low and keep_iMT2c: acc("SR_S_low_iMT2c")
    if keep_SR_S_low and keep_iMT2d: acc("SR_S_low_iMT2d")
    if keep_SR_S_low and keep_iMT2e: acc("SR_S_low_iMT2e")
    if keep_SR_S_low and keep_iMT2f: acc("SR_S_low_iMT2f")
    if keep_SR_S_low and keep_iMT2g: acc("SR_S_low_iMT2g")
    if keep_SR_S_low and keep_iMT2h: acc("SR_S_low_iMT2h")
    if keep_SR_S and keep_iMT2a: acc("SR_S_iMT2a")
    if keep_SR_S and keep_iMT2b: acc("SR_S_iMT2b")
    if keep_SR_S and keep_iMT2c: acc("SR_S_iMT2c")
    if keep_SR_S and keep_iMT2d: acc("SR_S_iMT2d")
    if keep_SR_S and keep_iMT2e: acc("SR_S_iMT2e")
    if keep_SR_S and keep_iMT2f: acc("SR_S_iMT2f")
    if keep_SR_S and keep_iMT2g: acc("SR_S_iMT2g")
    if keep_SR_S and keep_iMT2h: acc("SR_S_iMT2h")

    # ---- Slepton exclusive SRs (else-if cascades) ----
    if   keep_SR_S_high and mt2<100.5: acc("SR_S_high_eMT2a")
    elif keep_SR_S_high and mt2<101.:  acc("SR_S_high_eMT2b")
    elif keep_SR_S_high and mt2<102.:  acc("SR_S_high_eMT2c")
    elif keep_SR_S_high and mt2<105.:  acc("SR_S_high_eMT2d")
    elif keep_SR_S_high and mt2<110.:  acc("SR_S_high_eMT2e")
    elif keep_SR_S_high and mt2<120.:  acc("SR_S_high_eMT2f")
    elif keep_SR_S_high and mt2<130.:  acc("SR_S_high_eMT2g")
    elif keep_SR_S_high and mt2<140.:  acc("SR_S_high_eMT2h")

    if   keep_SR_S_low and mt2<100.5: acc("SR_S_low_eMT2a")
    elif keep_SR_S_low and mt2<101.:  acc("SR_S_low_eMT2b")
    elif keep_SR_S_low and mt2<102.:  acc("SR_S_low_eMT2c")
    elif keep_SR_S_low and mt2<105.:  acc("SR_S_low_eMT2d")
    elif keep_SR_S_low and mt2<110.:  acc("SR_S_low_eMT2e")
    elif keep_SR_S_low and mt2<120.:  acc("SR_S_low_eMT2f")
    elif keep_SR_S_low and mt2<130.:  acc("SR_S_low_eMT2g")
    elif keep_SR_S_low and mt2<140.:  acc("SR_S_low_eMT2h")

    return accepted, isee, ismm


# ---------------- canonical SR ordering (matches the container txt exactly) ----------------
def sr_order():
    order=[]
    order += ["SR_E_lT_eMLL"+c for c in "abcdef"]
    order += ["SR_E_high_eMLL"+c for c in "abcdefgh"]
    order += ["SR_E_med_eMLL"+c for c in "abcdef"]
    order += ["SR_E_low_eMLL"+c for c in "abcdefgh"]
    order += ["SR_E_lT_iMLL"+c for c in "abcdefghi"]
    order += ["SR_E_high_iMLL"+c for c in "abcdefghi"]
    order += ["SR_E_med_iMLL"+c for c in "abcdefghi"]
    order += ["SR_E_low_iMLL"+c for c in "abcdefghi"]
    order += ["SR_E_iMLL"+c for c in "abcdefghi"]
    order += ["SR_S_high_eMT2"+c for c in "abcdefgh"]
    order += ["SR_S_low_eMT2"+c for c in "abcdefgh"]
    order += ["SR_S_high_iMT2"+c for c in "abcdefgh"]
    order += ["SR_S_low_iMT2"+c for c in "abcdefgh"]
    order += ["SR_S_iMT2"+c for c in "abcdefgh"]
    # SR_VBF -- dead code in ProcessEvent (never accepted); emit as 0
    order += ["SR_VBF_high_eMLL"+c for c in "abcdefg"]
    order += ["SR_VBF_low_eMLL"+c for c in "abcdefg"]
    order += ["SR_VBF_high_iMLL"+c for c in "abcdefg"]
    order += ["SR_VBF_iMLL"+c for c in "abcdefg"]
    return order


def main():
    ap = argparse.ArgumentParser(description="Native VM-free SimpleAnalysis (CR-005: "
                                             "flagship + ported routines)")
    ap.add_argument("--input", required=True, help="Delphes2SA.root (tree 'ntuple')")
    ap.add_argument("--output", required=True, help="output directory")
    ap.add_argument("--ngen", type=int, default=None, help="N_gen (default: ntuple entries)")
    ap.add_argument("--routine", default="EwkCompressed2018",
                    help="EwkCompressed2018 (this module's RJR two-pass flow) or a ported "
                         "routine from sa_routines.REGISTRY (single-pass counting driver)")
    args = ap.parse_args()

    if args.routine != "EwkCompressed2018":
        # CR-005 ported routines: thin per-routine modules on sa_native_core's counting driver
        import importlib
        from .sa_routines import REGISTRY
        if args.routine not in REGISTRY:
            raise SystemExit(f"unknown routine {args.routine!r}; known: "
                             f"EwkCompressed2018, {', '.join(sorted(REGISTRY))}")
        from .sa_native_core import run_counting_routine
        mod = importlib.import_module(REGISTRY[args.routine])
        run_counting_routine(mod, args.input, args.output, args.ngen)
        return

    os.makedirs(args.output, exist_ok=True)
    objfile = os.path.join(args.output, "native_objects.txt")
    rjrcsv  = os.path.join(args.output, "native_rjr.csv")
    outtxt  = os.path.join(args.output, "EwkCompressed2018.txt")

    arrays, events, Nread, w = load_ntuple(args.input, args.ngen)

    # MC weights: load_ntuple applies the container conventions (w["sumW"/"sumW2"/"absw0"/"Ngen"]).
    # ---- pass 1: object selection + write the RJR-resolver input ----
    selected = {}   # Event -> sel dict (only events reaching the RJR helper)
    with open(objfile, "w") as f:
        f.write("# Event met_pt met_phi nJet (jet_pt jet_phi jet_m)* nLep (lep_pt lep_phi lep_m)*\n")
        for i in range(Nread):
            sel = select_objects(arrays, i)
            if sel is None:
                continue
            ev = int(events[i])
            sel['_w'] = float(w['w_all'][i])   # per-event SA eventWeight (mcWeights[0], XS*lumi-normalized)
            selected[ev] = sel
            met = sel['met']; sj = sel['signalJets']; sl = sel['signalLeptons']
            parts = [str(ev), repr(met.pt), repr(met.phi), str(len(sj))]
            for j in sj:
                parts += [repr(j.pt), repr(j.phi), repr(j.m)]
            parts.append(str(len(sl)))
            for l in sl:
                parts += [repr(l.pt), repr(l.phi), repr(l.m)]
            f.write(" ".join(parts) + "\n")

    print(f"[native] object selection done: {Nread} events read, "
          f"{len(selected)} reach the RJR helper")

    # ---- run the native RJR resolver (recast env) on the pre-selected objects ----
    cmd = [CONDA, "run", "-n", "recast", RJR_BIN, "--objects", objfile, rjrcsv]
    print(f"[native] invoking native RJR resolver:\n  {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stdout + "\n" + res.stderr + "\n")
        raise SystemExit(f"rjr_resolve failed (rc={res.returncode})")
    sys.stderr.write(res.stderr)

    # ---- read R_ISR / M_S back, keyed by Event ----
    rjr = {}   # Event -> (RISR, MS, solved)
    with open(rjrcsv) as f:
        header = f.readline()
        for line in f:
            line = line.strip()
            if not line:
                continue
            p = line.split(",")
            ev = int(p[0]); RISR = float(p[3]); MS = float(p[4]); solved = int(p[10])
            rjr[ev] = (RISR, MS, solved)

    n_unsolved = sum(1 for ev in selected if rjr.get(ev, (0,0,0))[2] == 0)
    if n_unsolved:
        print(f"[native] WARNING: {n_unsolved} gated events did not solve in RestFrames")

    # ---- pass 2: apply the SR cascade with native RJR ----
    counts = {sr: 0 for sr in sr_order()}
    sumw = {sr: 0.0 for sr in sr_order()}
    sumw2 = {sr: 0.0 for sr in sr_order()}
    ntuple_rows = []   # (Event, weight, isee, ismm, accepted-set) per selected event -> the SA .root
    for ev, sel in selected.items():
        r = rjr.get(ev)
        if r is None:
            # event reached RJR helper but resolver has no row -> treat as unsolved
            RISR, MS = 0.0, 0.0
        else:
            RISR, MS = r[0], r[1]
        accepted, isee, ismm = select_regions(sel, RISR, MS)
        for sr in accepted:
            counts[sr] += 1
            sumw[sr] += sel['_w']
            sumw2[sr] += sel['_w']*sel['_w']
        ntuple_rows.append((ev, sel['_w'], isee, ismm, accepted))

    # ---- emit the txt (exact container format + order) ----
    write_txt(outtxt, counts, sr_order(), w, sumw=sumw, sumw2=sumw2)

    # diagnostic summary to stdout
    tot = sum(counts.values())
    print(f"[native] total SR-accept count (sum over SRs): {tot}")
    print(f"[native] wrote {outtxt}")
    rootpath = os.path.join(args.output, "EwkCompressed2018.root")
    write_root(rootpath, ntuple_rows, sr_order())
    print(f"[native] wrote {rootpath} (ntuple: {len(ntuple_rows)} rows, "
          f"per-SR eventWeight + isee/ismm for sa2json)")


if __name__ == "__main__":
    main()
