"""EwkThreeLeptonERJR2018 -- native port of ATLAS-SUSY-2018-06's 3-lepton RJR-emulated search.

Based on SimpleAnalysisCodes/src/ANA-SUSY-2018-06.cxx (WZ + MET with the recursive-jigsaw
variables emulated via Lorentz boosts). The published analysis itself uses eRJR.
Regions (addRegions order): Preselection, SRlow, SRISR, CRlow, CRISR, VRlow, VRISR,
VRISRsmallPTsoft, VRISRsmallRjetsinv. Historical container parity predates the H_boost
correction below; it is not a validation of the corrected low-mass regions.

AMBIGUITY LEDGER:
  A1  The cutflow HISTOGRAM fills are not transcribed (histograms are not in the txt the
      validation diffs; regions are).
  A2  Lepton/jet ID bits transcribed header-verbatim (ELooseBLLH, MuNotCosmic|MuQoPSignificance,
      JVT120Jet, EIsoFCTight, MuIsoFCTightFR, BTag77MV2c10); lepton-ID are no-ops on Delphes2SA
      input (0x7FFFFFFF), the JET bits are real.
  A3  H_boost follows ATLAS arXiv:1912.08479v2, section 5, page 9: apply the common
      boost to both the leptons and reconstructed invisible four-vector. The reference
      C++ at 5a33033d788619bb1039a5b8116fdf43c46fc72a omits the latter boost.
      Preserving that omission failed the paper definition and longitudinal invariance.
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


def _boosted_system(leptons, met_px, met_py):
    """Return all constituents in their common rest frame and the lab invisible vector."""
    visible = [sum(p[k] for p in leptons) for k in range(4)]
    transverse_energy2 = visible[3] ** 2 - visible[2] ** 2
    if transverse_energy2 <= 0:
        raise ValueError("H_boost requires a timelike visible lepton system")
    met_pt = math.hypot(met_px, met_py)
    invisible_pz = visible[2] * met_pt / math.sqrt(transverse_energy2)
    invisible = [met_px, met_py, invisible_pz,
                 math.hypot(met_pt, invisible_pz)]
    total = _add(visible, invisible)
    boost = tuple(-component / total[3] for component in total[:3])
    return [_boost(p, *boost) for p in [*leptons, invisible]], invisible


def h_boost(leptons, met_px, met_py):
    """ATLAS eRJR H_boost in GeV, from lepton (px, py, pz, E) vectors.

    The massless invisible system has the visible system's rapidity. Boost every
    constituent into their common rest frame before summing momentum magnitudes.
    Reference: https://arxiv.org/pdf/1912.08479v2#page=9 (section 5).
    """
    boosted, _ = _boosted_system(leptons, met_px, met_py)
    return sum(_pmag(p) for p in boosted)


def _low_regions(l0, l1, l2, njets, mtw, h, ptratio, meff, met):
    """Shared low-mass region definitions; the differential audit changes only h."""
    regions = set()
    if not (l0 > 60 and l1 > 40 and l2 > 30 and njets == 0 and h > 250):
        return regions
    ratio = meff / h
    if 0 < mtw < 70 and ptratio < .2 and ratio > .75 and met > 40:
        regions.add('CRlow')
    if 70 < mtw < 100 and ptratio < .2 and ratio > .75:
        regions.add('VRlow')
    if mtw > 100 and ptratio < .05 and ratio > .9:
        regions.add('SRlow')
    return regions


def select(arrays, i, *, diagnostics=None):
    """Select paper-defined regions; optionally expose preselected-event observables."""
    if diagnostics is not None:
        diagnostics.clear()
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

    H_boost = h_boost(vl, met.px, met.py)
    HTratio = meff3l / H_boost
    pTratio = pTsoftPP / (pTsoftPP + meff3l)

    l0, l1, l2 = leptons[0].pt, leptons[1].pt, leptons[2].pt
    accepted.update(_low_regions(l0, l1, l2, njets, mTW, H_boost, pTratio, meff3l, metPt))

    if diagnostics is not None:
        diagnostics.update(leptons=vl, met_px=met.px, met_py=met.py, met=metPt,
                           lepton_pt=[l0, l1, l2], njets=njets, mTW=mTW,
                           Hboost=H_boost, HTratio=HTratio, pTratio=pTratio, meff3l=meff3l)

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


def audit_reconstruction(input_path):
    """Replay retained detector events, isolating the historical mixed-frame error.

    The historical expression is an audit control only. Production selection always
    uses the paper definition. No event generation, detector changes, or fit occurs.
    """
    import hashlib
    from pathlib import Path
    from .. import sa_native_core
    from ..sa_native_core import load_ntuple

    path = Path(input_path)
    input_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    arrays, events, n, weights = load_ntuple(path)
    denominator = float(weights['sumW'])
    if denominator <= 0 or not math.isfinite(denominator):
        raise ValueError('Audit requires a finite, positive total nominal event weight')
    names = sr_order()
    stages = ['preselection', 'lepton_pt_and_jet_veto', 'Hboost', 'pTratio', 'HTratio', 'mTW']
    counts = {policy: {sr: 0 for sr in names} for policy in ['historical', 'paper']}
    sums = {policy: {sr: 0. for sr in names} for policy in counts}
    cutflow = {policy: {stage: 0 for stage in stages} for policy in counts}
    changed = []
    diagnostics = {}
    for i in range(n):
        result = select(arrays, i, diagnostics=diagnostics)
        if result is None:
            continue
        d = diagnostics
        boosted, invisible = _boosted_system(d['leptons'], d['met_px'], d['met_py'])
        historical_h = sum(_pmag(p) for p in boosted[:-1]) + _pmag(invisible)
        paper_regions = result[0]
        historical_regions = paper_regions - {'SRlow', 'CRlow', 'VRlow'}
        historical_regions |= _low_regions(*d['lepton_pt'], d['njets'], d['mTW'],
                                           historical_h, d['pTratio'], d['meff3l'], d['met'])
        weight = float(weights['w_all'][i])
        if not math.isfinite(weight):
            raise ValueError(f'Non-finite nominal event weight at entry {i}')
        for policy, regions, h in [('historical', historical_regions, historical_h),
                                   ('paper', paper_regions, d['Hboost'])]:
            for sr in regions:
                counts[policy][sr] += 1
                sums[policy][sr] += weight
            l0, l1, l2 = d['lepton_pt']
            decisions = [True, l0 > 60 and l1 > 40 and l2 > 30 and d['njets'] == 0,
                         h > 250, d['pTratio'] < .05, d['meff3l']/h > .9, d['mTW'] > 100]
            for stage, passed in zip(stages, decisions):
                if not passed:
                    break
                cutflow[policy][stage] += 1
        if historical_regions != paper_regions:
            changed.append({'entry': i, 'event': int(events[i]),
                            'historical': sorted(historical_regions), 'paper': sorted(paper_regions),
                            'Hboost_historical': historical_h, 'Hboost_paper': d['Hboost'],
                            'HTratio_historical': d['meff3l']/historical_h,
                            'HTratio_paper': d['HTratio'], 'mTW': d['mTW'], 'pTratio': d['pTratio']})
    if hashlib.sha256(path.read_bytes()).hexdigest() != input_hash:
        raise ValueError('Input changed during reconstruction audit')
    return {'schema_version': 1, 'analysis': NAME, 'input_name': path.name,
            'input_sha256': input_hash, 'selection_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'core_sha256': hashlib.sha256(Path(sa_native_core.__file__).read_bytes()).hexdigest(),
            'reference': 'https://arxiv.org/pdf/1912.08479v2#page=9',
            'historical_reference_commit': '5a33033d788619bb1039a5b8116fdf43c46fc72a',
            'entries': n, 'sum_weights': denominator,
            'weights_min': float(min(weights['w_all'])), 'weights_max': float(max(weights['w_all'])),
            'counts': counts, 'acceptance': {p: {sr: value/denominator for sr, value in s.items()} for p, s in sums.items()},
            'cutflow_order': stages, 'cutflow': cutflow, 'changed_events': changed,
            'scope': 'Cached detector-event reanalysis. Only the invisible Hboost contribution changes frame. No fresh generation, detector simulation, fit, or acceptance certification.'}


def main():
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Audit the eRJR invisible-boost correction on saved detector events.')
    parser.add_argument('--input', required=True, type=Path, help='Retained Delphes2SA.root ntuple (requires numpy and uproot)')
    parser.add_argument('--out', required=True, type=Path, help='New differential JSON; historical run files should be preserved')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('--out must be a new path; retain previous audit evidence')
    try:
        report = audit_reconstruction(args.input)
    except (OSError, ValueError, ImportError) as exc:
        parser.exit(2, f'Cannot audit retained events: {exc}\n')
    with args.out.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(f"Replayed {report['entries']} retained events; SRlow "
          f"{report['counts']['historical']['SRlow']} -> {report['counts']['paper']['SRlow']}; "
          f"SRISR {report['counts']['historical']['SRISR']} -> {report['counts']['paper']['SRISR']}. "
          'This is not a new acceptance certification.')


if __name__ == '__main__':
    main()
