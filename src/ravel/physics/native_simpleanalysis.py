#!/usr/bin/env python3
"""Native EwkCompressed2018 signal-region and slepton control-region selection.

Read Delphes2SA objects and nominal weights, reconstruct RestFrames variables
from the selected jets and leptons, then write per-event region weights and
weighted cutflows. Object/SR cuts follow public ANA-SUSY-2018-16.cxx. Six nominal
slepton controls are separately transcribed from arXiv:1911.12606v2 Tables 2,
5 and 8; there is no public SimpleAnalysis CR implementation in the pinned
source, and these controls are not an ATLAS acceptance validation.

Object quality masks are applied. The mapyde Delphes converter supplies all
lepton quality bits, so those particular inputs cannot test real ATLAS lepton
ID/trigger performance or its uncertainty. No efficiency variations are invented.

The default writes SRs and six slepton CRs. --compressed-signal-model
sr-only-diagnostic retains an explicit SR-only diagnostic. ROOT branches retain
signed weights, including the information needed to calculate sumw2 downstream.
Use --input <Delphes2SA.root> --output <directory>; --ngen defaults to all entries.
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import sys, os, math, argparse, subprocess

# CR-005: the routine-AGNOSTIC machinery now lives in sa_native_core (extracted VERBATIM from
# this file's validated implementation). This module keeps ONLY the EwkCompressed2018-specific
# selection + the RJR two-pass orchestration, and RE-EXPORTS the primitives so existing importers
# (native_sa_generic.py and any run-local script) keep working unchanged.

from .sa_native_core import (   # noqa: F401  (re-exports are the compat surface)
    Lester, _ellipse, _helper, get_mT2,
    Obj, ELECTRON, MUON, ME, MMU,
    NotBit, NOT, LooseBadJet, JVT50Jet, LessThan3Tracks, BTag85MV2c10,
    filterObjects, countObjects, overlapRemoval, concat_sorted,
    invmass, pairDeltaPhi_to_met, calcMT, calcMTauTau, calcAMT2, minDphi,
    load_ntuple, write_txt, write_root, _g,
    CONDA)

from ..paths import native_binary
RJR_BIN = str(native_binary("rjr_resolve"))


# ---------------- per-event object selection (returns the gated objects, or None) ----------------
def select_objects(arrays, i, *, trace=None):
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
    bad_jet_veto = countObjects(preJets, 20, 4.5, NOT(LooseBadJet)) == 0
    if trace is not None:
        trace['predicates']['bad_jet_veto'] = bool(bad_jet_veto)
        trace['objects'].update(pre_jets=len(preJets), base_electrons_before_or=len(baseElectrons),
                                base_muons_before_or=len(baseMuons))
    if not bad_jet_veto:
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

    # AnalysisObjects::operator+ sorts the combined collection by pT. This is
    # essential for the leading/subleading cuts in opposite-flavour controls.
    baseLeptons=concat_sorted(baseElectrons, baseMuons)
    signalLeptons=concat_sorted(signalElectrons, signalMuons)

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
    baseTracks=concat_sorted(baseElTracks, baseMuTracks)
    baseElTracks=overlapRemoval(baseElTracks, baseJets, 0.5)
    baseMuTracks=overlapRemoval(baseMuTracks, baseJets, 0.5)
    signalElTracks=overlapRemoval(baseElTracks, baseTracks, 0.3)
    signalMuTracks=overlapRemoval(baseMuTracks, baseTracks, 0.3)
    signalElTracks=filterObjects(signalElTracks, 1, 2.5, (1<<16)|(1<<17))  # ED0Sigma5|EZ05mm
    signalMuTracks=filterObjects(signalMuTracks, 1, 2.5, (1<<16)|(1<<17))  # MuD0Sigma3|MuZ05mm
    signalTracks=concat_sorted(signalElTracks, signalMuTracks)

    # ProcessEvent guards BEFORE the RJR helper is invoked
    if trace is not None:
        trace['predicates'].update(baseline_lepton=bool(len(baseLeptons)>=1),
                                   signal_jet=bool(len(signalJets)>=1),
                                   two_signal_leptons=bool(len(signalLeptons)==2),
                                   jet_count=bool(len(signalJets)>=1))
        trace['objects'].update(base_leptons=len(baseLeptons), signal_leptons=len(signalLeptons),
                                signal_jets=len(signalJets), signal_bjets=len(signalBJets),
                                signal_tracks=len(signalTracks))
        trace['leptons'] = [{'pt':float(l.pt), 'eta':float(l.eta), 'phi':float(l.phi),
                             'flavour':int(l.typ), 'charge':int(l.charge)} for l in signalLeptons]
    if not (len(baseLeptons)>=1): return None
    if not (len(signalJets)>=1): return None

    return dict(met=met, signalJets=signalJets, signalBJets=signalBJets,
                signalLeptons=signalLeptons, signalTracks=signalTracks)


# The public SimpleAnalysis implementation contains no control regions. These
# six selections implement arXiv:1911.12606v2, Tables 2, 5 and 8; they have not
# been validated against ATLAS event-level CR acceptance. Unchanged cuts use
# the strict interval boundaries of the existing native SR implementation.
# Table 2 gives lower mll bounds for ee/mm only: no extra e-mu floor is invented.
def cr_order():
    return [f"CR_S_{process}_{met}" for process in ("VV", "tau", "top")
            for met in ("high", "low")]


def select_slepton_controls(*, is2L, isOS, isee, ismm, pt1, pt2, mll, drll,
                            mtautau, met, njets, nbjets, jet1pt, min_dphi,
                            lead_dphi, mt, mt2, risr):
    """Paper-defined nominal slepton controls, with all four lepton flavours.

    Opposite-flavour pairs inherit the global mll upper bound and resonance
    veto, but no unspecified flavour-dependent lower bound. CR boundaries are
    open to preserve SR orthogonality with the existing strict SR cuts.
    """
    if not all(math.isfinite(value) for value in
               (pt1, pt2, mll, drll, mtautau, met, jet1pt, min_dphi, lead_dphi,
                mt, mt2, risr)):
        raise ValueError("compressed control-region kinematics must be finite")
    different_flavour = not (isee or ismm)
    common = (is2L and isOS and pt1 > 5 and 0 <= mll < 60
              and ((isee and mll > 3 and drll > .3)
                   or (ismm and mll > 1 and drll > .05)
                   or (different_flavour and drll > .2))
              and (mll < 3 or mll > 3.2) and met > 120 and njets >= 1
              and jet1pt > 100 and min_dphi > .4 and lead_dphi > 2
              and 100 < mt2 < 140)
    if not common:
        return set()
    high = met > 200 and pt2 > min(20, 2.5 + 2.5*(mt2-100))
    low = 150 < met < 200 and pt2 > min(15, 7.5 + .75*(mt2-100))
    tau_veto = mtautau < 0 or mtautau > 160
    tau_window = 60 < mtautau < 120
    accepted = set()
    for band, passes in (("high", high), ("low", low)):
        if not passes:
            continue
        if nbjets >= 1 and tau_veto and (.7 if band == "high" else .8) < risr < 1:
            accepted.add(f"CR_S_top_{band}")
        if nbjets == 0 and tau_window and (.7 if band == "high" else .6) < risr < 1:
            accepted.add(f"CR_S_tau_{band}")
        if (nbjets == 0 and tau_veto
                and (.7 if band == "high" else .6) < risr < (.85 if band == "high" else .8)
                and (band == "high" or (mt > 30 and 1 <= njets <= 2))):
            accepted.add(f"CR_S_VV_{band}")
    return accepted


# ---------------- per-event SR cascade (given R_ISR/M_S) ----------------
def select_regions(sel, R_ISR, M_S, *, include_controls=True, trace=None):
    """Apply the kinematic + RJR SR selection (ProcessEvent lines 277-559) and
    return the set of accepted SR names. `sel` is the dict from select_objects;
    R_ISR/M_S come from the native resolver."""
    met=sel['met']; metPt=met.pt
    signalJets=sel['signalJets']; signalBJets=sel['signalBJets']
    signalLeptons=sel['signalLeptons']; signalTracks=sel['signalTracks']

    is2L=(len(signalLeptons)==2)
    is1LT=(len(signalLeptons)==1 and len(signalTracks)>=1)
    if trace is not None:
        trace['predicates']['two_signal_leptons'] = bool(is2L)
        trace['rjr_status'] = 'solved'
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

    accepted = (select_slepton_controls(
        is2L=is2L, isOS=isOS, isee=isee, ismm=ismm, pt1=lep1Pt, pt2=lep2Pt,
        mll=mll, drll=drll, mtautau=MTauTau, met=metPt, njets=len(signalJets),
        nbjets=len(signalBJets), jet1pt=jet1Pt, min_dphi=minDPhiAllJetsMet,
        lead_dphi=dPhiJ1Met, mt=mt, mt2=mt2, risr=R_ISR) if include_controls else set())

    pass_pre1LT = (is1LT and lep1Pt<10. and drll>0.05 and drll<1.5 and isOS and isSF
                   and mll>0.5 and mll<5 and (mll<3. or mll>3.2) and metPt>120.
                   and len(signalJets)>=1 and jet1Pt>100. and minDPhiAllJetsMet>0.4 and dPhiJ1Met>2.0)
    keep_SR_E_1LT = (pass_pre1LT and metPt>200. and metOverHtLep>30. and dPhiLepMet<1. and lep2Pt<5.)

    common_predicates = dict(
        two_signal_leptons=is2L, leading_lepton_pt=lep1Pt>5.,
        lepton_separation=((drll>0.05 and ismm) or (drll>0.3 and isee)),
        opposite_charge=isOS, same_flavour=isSF,
        mll_window=((mll>1. and mll<60. and ismm) or (mll>3. and mll<60. and isee)),
        jpsi_veto=(mll<3. or mll>3.2), mtautau_veto=(MTauTau<0. or MTauTau>160.),
        met_preselection=metPt>120., jet_count=len(signalJets)>=1, b_veto=len(signalBJets)==0,
        leading_jet_pt=jet1Pt>100., min_jet_met_dphi=minDPhiAllJetsMet>0.4,
        leading_jet_met_dphi=dPhiJ1Met>2.0)
    pass_common = all(common_predicates.values())

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

    slepton_predicates = dict(met_high=metPt>200., met_low=150.<metPt<200.,
        mt2_lt_140=mt2<140., mt2_gt_100=mt2>100.,
        subleading_pt_high=lep2Pt>min(20., 2.5+2.5*(mt2-100.)),
        subleading_pt_low=lep2Pt>min(15., 7.5+0.75*(mt2-100.)),
        risr_high=(R_ISR<1. and R_ISR>max(0.85, 0.98-0.02*(mt2-100))),
        risr_low=(0.8<R_ISR<1.))
    keep_SR_S_high = pass_common and all(slepton_predicates[key] for key in
        ('met_high','mt2_lt_140','mt2_gt_100','subleading_pt_high','risr_high'))
    keep_SR_S_low = pass_common and all(slepton_predicates[key] for key in
        ('met_low','mt2_lt_140','mt2_gt_100','subleading_pt_low','risr_low'))
    keep_SR_S = keep_SR_S_high or keep_SR_S_low

    keep_iMT2a = mt2<100.5; keep_iMT2b = mt2<101.; keep_iMT2c = mt2<102.; keep_iMT2d = mt2<105.
    keep_iMT2e = mt2<110.; keep_iMT2f = mt2<120.; keep_iMT2g = mt2<130.; keep_iMT2h = mt2<140.
    if trace is not None:
        trace['predicates'].update({key:bool(value) for key,value in
                                   (common_predicates | slepton_predicates).items()})
        trace['predicates'].update({key:bool(value) for key,value in zip(
            ('mt2_lt_100p5','mt2_lt_101','mt2_lt_102','mt2_lt_105','mt2_lt_110','mt2_lt_120','mt2_lt_130'),
            (keep_iMT2a,keep_iMT2b,keep_iMT2c,keep_iMT2d,keep_iMT2e,keep_iMT2f,keep_iMT2g))})
        trace['kinematics'].update({key:float(value) for key,value in dict(
            pt1=lep1Pt, pt2=lep2Pt, mll=mll, drll=drll, met=metPt, mtautau=MTauTau,
            mt=mt, mt2=mt2, mt2_test_mass=mn, risr=R_ISR, ms=M_S,
            jet1_pt=jet1Pt, min_jet_met_dphi=minDPhiAllJetsMet, leading_jet_met_dphi=dPhiJ1Met).items()})

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

    if trace is not None:
        trace['accepted_regions'] = sorted(accepted)
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
    ap.add_argument("--rjr-binary", default=RJR_BIN, help="explicit RestFrames helper for EwkCompressed2018")
    ap.add_argument("--recast-env", default=None, help="explicit conda prefix for the RestFrames helper")
    ap.add_argument("--rjr-conda", default=CONDA, help="explicit conda executable for the RestFrames helper")
    ap.add_argument("--compressed-signal-model", choices=("full", "sr-only-diagnostic"), default="full",
                    help="full writes six slepton controls; diagnostic retains archival SR-only output")
    ap.add_argument("--validation-reference-directory", help="optional HEPData v5 m150/140 cutflow directory")
    ap.add_argument("--validation-masses", nargs=2, type=float, metavar=("PARENT", "LSP"),
                    help="declared plan masses recorded with the trace; reference cutflows require150/140")
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
    if args.ngen is not None and (args.ngen <= 0 or args.ngen != Nread):
        raise ValueError("requested event count does not match the loaded ntuple")
    if len(set(map(int, events))) != len(events):
        raise ValueError("duplicate Event identifiers cannot be joined to RestFrames safely")
    include_controls = args.compressed_signal_model == "full"
    order = sr_order() + (cr_order() if include_controls else [])
    if include_controls:
        print("[native] six nominal slepton controls from paper Tables 2/5/8; CR acceptance unvalidated")
    else:
        print("[native] DIAGNOSTIC ONLY: slepton control-region signal omitted")

    # MC weights: load_ntuple applies the container conventions (w["sumW"/"sumW2"/"absw0"/"Ngen"]).
    # ---- pass 1: object selection + write the RJR-resolver input ----
    from . import compressed_validation as validation
    traces = {int(events[i]): validation.new_event(int(events[i]), float(w['w_all'][i])) for i in range(Nread)}
    selected = {}   # Event -> sel dict (only events reaching the RJR helper)
    with open(objfile, "w") as f:
        f.write("# Event met_pt met_phi nJet (jet_pt jet_phi jet_m)* nLep (lep_pt lep_phi lep_m)*\n")
        for i in range(Nread):
            ev = int(events[i])
            sel = select_objects(arrays, i, trace=traces[ev])
            if sel is None:
                continue
            sel['_w'] = float(w['w_all'][i])   # original nominal SA weight, normalized to cross section in pb
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
    environment = ["-p",args.recast_env] if args.recast_env else ["-n","recast"]
    cmd = [args.rjr_conda, "run", *environment, args.rjr_binary, "--objects", objfile, rjrcsv]
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
            if ev in rjr or ev not in selected or solved not in (0, 1) or not all(map(math.isfinite, (RISR, MS))):
                raise ValueError("invalid or duplicate RestFrames event result")
            rjr[ev] = (RISR, MS, solved)

    n_unsolved = sum(1 for ev in selected if rjr.get(ev, (0,0,0))[2] == 0)
    if n_unsolved:
        raise ValueError(f"{n_unsolved} gated events lack a solved RestFrames result")

    # ---- pass 2: apply the SR cascade with native RJR ----
    counts = {sr: 0 for sr in order}
    sumw = {sr: 0.0 for sr in order}
    sumw2 = {sr: 0.0 for sr in order}
    ntuple_rows = []   # (Event, weight, isee, ismm, accepted-set) per selected event -> the SA .root
    for ev, sel in selected.items():
        r = rjr.get(ev)
        if r is None:
            # event reached RJR helper but resolver has no row -> treat as unsolved
            RISR, MS = 0.0, 0.0
        else:
            RISR, MS = r[0], r[1]
        accepted, isee, ismm = select_regions(sel, RISR, MS, include_controls=include_controls, trace=traces[ev])
        for sr in accepted:
            counts[sr] += 1
            sumw[sr] += sel['_w']
            sumw2[sr] += sel['_w']*sel['_w']
        ntuple_rows.append((ev, sel['_w'], isee, ismm, accepted))

    # ---- emit the txt (exact container format + order) ----
    write_txt(outtxt, counts, order, w, sumw=sumw, sumw2=sumw2)

    # diagnostic summary to stdout
    tot = sum(counts.values())
    print(f"[native] total region-accept count (sum over SRs and requested CRs): {tot}")
    print(f"[native] wrote {outtxt}")
    rootpath = os.path.join(args.output, "EwkCompressed2018.root")
    write_root(rootpath, ntuple_rows, order)
    print(f"[native] wrote {rootpath} (ntuple: {len(ntuple_rows)} rows, "
          f"per-SR eventWeight + isee/ismm for sa2json)")
    from pathlib import Path
    import json
    tracepath = Path(args.output)/"compressed_trace.jsonl.gz"
    validation.write_trace(tracepath, traces.values(), {
        "input_sha256":validation.file_hash(args.input), "input_events":Nread,
        "selection_source_sha256":validation.file_hash(__file__),
        "diagnostic_source_sha256":validation.file_hash(validation.__file__),
        "rjr_binary_sha256":validation.file_hash(args.rjr_binary),
        "compressed_signal_model":args.compressed_signal_model,
        "masses_gev":args.validation_masses,
        "mass_metadata_source":"declared_command_arguments",
        "origin_state_status":"unavailable_in_converted_ntuple"})
    report = validation.summarize_trace(tracepath, args.validation_reference_directory)
    (Path(args.output)/"compressed_validation.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
