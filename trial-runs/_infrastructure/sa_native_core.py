#!/usr/bin/env python
"""sa_native_core -- the routine-AGNOSTIC core of the native (VM-free) SimpleAnalysis backend.

CR-005: everything here was extracted VERBATIM from the validated EwkCompressed2018 port
(native_simpleanalysis.py, bit-for-bit 141/141 vs the container) -- object model, SA framework
ID-bit vocabulary, filter/overlap-removal primitives, kinematic calculators (incl. the Lester
asymmetric mT2 ported from arXiv:1411.4312), ntuple IO + the SA weight conventions, and the
container-format writers. Per-routine SELECTION code lives in sa_routines/<name>.py; this module
must stay free of any analysis-specific cut.

Semantics rule: any change here invalidates every ported routine's bit-for-bit validation --
re-run the container diffs (framework/CR005-NATIVE-SA-GENERALIZATION.md §4) after touching it.
"""
import math
import os
import subprocess
import sys

# numpy/uproot are imported LAZILY (inside the IO functions): the kinematic/selection
# primitives and every selftest that uses them must stay runnable on a bare python3.

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INFRA = os.path.join(REPO, "trial-runs", "_infrastructure")
CONDA = os.path.join(REPO, "stages", "01-event-generation", "build", "tools",
                     "miniforge3", "bin", "conda")

# ---------------- Lester asymmetric mT2 (arXiv:1411.4312), ported verbatim ----------------
class Lester:
    @staticmethod
    def ellipsesAreDisjoint(e1, e2):
        if e1 == e2:
            return False
        c3 = e1['det']
        c2 = Lester.lesterFactor(e1, e2)
        c1 = Lester.lesterFactor(e2, e1)
        c0 = e2['det']
        if abs(c3) >= abs(c0):
            return Lester._priv(c3, c2, c1, c0)
        else:
            return Lester._priv(c0, c1, c2, c3)

    @staticmethod
    def lesterFactor(e1, e2):
        return (e1['c_xx']*e1['c_yy']*e2['c'] + 2.0*e1['c_xy']*e1['c_y']*e2['c_x']
                - 2.0*e1['c_x']*e1['c_yy']*e2['c_x'] + e1['c']*e1['c_yy']*e2['c_xx']
                - 2.0*e1['c']*e1['c_xy']*e2['c_xy'] + 2.0*e1['c_x']*e1['c_y']*e2['c_xy']
                + 2.0*e1['c_x']*e1['c_xy']*e2['c_y'] - 2.0*e1['c_xx']*e1['c_y']*e2['c_y']
                + e1['c']*e1['c_xx']*e2['c_yy'] - e2['c_yy']*(e1['c_x']**2)
                - e2['c']*(e1['c_xy']**2) - e2['c_xx']*(e1['c_y']**2))

    @staticmethod
    def _priv(c3, c2, c1, c0):
        if c3 == 0:
            raise ValueError("singular")
        a = c2/c3; b = c1/c3; c = c0/c3
        thing1 = -3.0*b + a*a
        if thing1 <= 0:
            return False
        thing2 = -27.0*c*c + 18.0*c*a*b + a*a*b*b - 4.0*a*a*a*c - 4.0*b*b*b
        if thing2 <= 0:
            return False
        return ((a >= 0 and 3.0*a*c + b*a*a - 4.0*b*b < 0) or (a < 0))


def _ellipse(c_xx, c_yy, c_xy, c_x, c_y, c):
    det = (2.0*c_x*c_xy*c_y + c*c_xx*c_yy - c_yy*c_x*c_x - c*c_xy*c_xy - c_xx*c_y*c_y)
    return dict(c_xx=c_xx, c_yy=c_yy, c_xy=c_xy, c_x=c_x, c_y=c_y, c=c, det=det)


def _helper(mSq, mtSq, tx, ty, mqSq, pxmiss, pymiss):
    txSq=tx*tx; tySq=ty*ty; pxmissSq=pxmiss*pxmiss; pymissSq=pymiss*pymiss
    c_xx = 4.0*mtSq + 4.0*tySq
    c_yy = 4.0*mtSq + 4.0*txSq
    c_xy = -4.0*tx*ty
    c_x = (-4.0*mtSq*pxmiss - 2.0*mqSq*tx + 2.0*mSq*tx - 2.0*mtSq*tx
           + 4.0*pymiss*tx*ty - 4.0*pxmiss*tySq)
    c_y = (-4.0*mtSq*pymiss - 4.0*pymiss*txSq - 2.0*mqSq*ty + 2.0*mSq*ty
           - 2.0*mtSq*ty + 4.0*pxmiss*tx*ty)
    c = (-mqSq*mqSq + 2*mqSq*mSq - mSq*mSq + 2*mqSq*mtSq + 2*mSq*mtSq - mtSq*mtSq
         + 4.0*mtSq*pxmissSq + 4.0*mtSq*pymissSq + 4.0*mqSq*pxmiss*tx
         - 4.0*mSq*pxmiss*tx + 4.0*mtSq*pxmiss*tx + 4.0*mqSq*txSq
         + 4.0*pymissSq*txSq + 4.0*mqSq*pymiss*ty - 4.0*mSq*pymiss*ty
         + 4.0*mtSq*pymiss*ty - 8.0*pxmiss*pymiss*tx*ty + 4.0*mqSq*tySq
         + 4.0*pxmissSq*tySq)
    return _ellipse(c_xx, c_yy, c_xy, c_x, c_y, c)


def get_mT2(mVis1, px1, py1, mVis2, px2, py2, pxMiss, pyMiss, mInvis1, mInvis2, prec=0.0):
    m1Min = mVis1 + mInvis1
    m2Min = mVis2 + mInvis2
    if m1Min > m2Min:
        return get_mT2(mVis2, px2, py2, mVis1, px1, py1, pxMiss, pyMiss, mInvis2, mInvis1, prec)
    mMin = m2Min
    msSq=mVis1*mVis1; sx=px1; sy=py1; mpSq=mInvis1*mInvis1
    mtSq=mVis2*mVis2; tx=px2; ty=py2; mqSq=mInvis2*mInvis2
    sSq=sx*sx+sy*sy; tSq=tx*tx+ty*ty; pMissSq=pxMiss*pxMiss+pyMiss*pyMiss
    massSqSum=msSq+mtSq+mpSq+mqSq
    scaleSq=(massSqSum+sSq+tSq+pMissSq)/8.0
    if scaleSq == 0:
        return 0.0
    scale=math.sqrt(scaleSq)
    mLower=mMin; mUpper=mMin+scale
    attempts=0
    while True:
        attempts += 1
        mUpperSq=mUpper*mUpper
        s1=_helper(mUpperSq, msSq, -sx, -sy, mpSq, 0, 0)
        s2=_helper(mUpperSq, mtSq, +tx, +ty, mqSq, pxMiss, pyMiss)
        try:
            disjoint=Lester.ellipsesAreDisjoint(s1, s2)
        except Exception:
            return -1.0
        if not disjoint:
            break
        if attempts >= 10000:
            return -1.0
        mUpper *= 2
    goLow=True
    while prec <= 0 or (mUpper-mLower) > prec:
        trialM = (mLower*15+mUpper)/16 if goLow else (mUpper+mLower)/2.0
        if trialM <= mLower or trialM >= mUpper:
            return trialM
        trialMSq=trialM*trialM
        s1=_helper(trialMSq, msSq, -sx, -sy, mpSq, 0, 0)
        s2=_helper(trialMSq, mtSq, +tx, +ty, mqSq, pxMiss, pyMiss)
        try:
            disjoint=Lester.ellipsesAreDisjoint(s1, s2)
            if disjoint:
                mLower=trialM; goLow=False
            else:
                mUpper=trialM
        except Exception:
            return mLower
    return (mLower+mUpper)/2.0

# ---------------- object model ----------------
ELECTRON, MUON = 0, 1
ME = 0.510998910/1000.0
MMU = 105.6583715/1000.0

class Obj:
    __slots__=('pt','eta','phi','m','charge','idbits','typ','px','py','pz','E')
    def __init__(self, pt, eta, phi, m, charge, idbits, typ):
        pt=float(pt); eta=float(eta); phi=float(phi); m=float(m)
        self.pt=pt; self.eta=eta; self.phi=phi; self.m=m
        self.charge=int(charge); self.idbits=int(idbits)&0xFFFFFFFF; self.typ=typ
        self.px=pt*math.cos(phi); self.py=pt*math.sin(phi); self.pz=pt*math.sinh(eta)
        p2=self.px**2+self.py**2+self.pz**2
        self.E=math.sqrt(p2+m*m)
    def deltaPhi(self, o):
        d=self.phi-o.phi
        while d>=math.pi: d-=2*math.pi
        while d<-math.pi: d+=2*math.pi
        return d
    def deltaR(self, o):
        return math.hypot(self.eta-o.eta, self.deltaPhi(o))
    def passId(self, idbits):
        NotBit=1<<31
        if idbits & NotBit:
            return (idbits & self.idbits)==0
        return (idbits & self.idbits)==idbits

# ---- SA framework ID-bit vocabulary — VERBATIM from AnalysisObject.h enums (verified
# 2026-08-16 against the SA source; never guess these, wrong bits diff silently) ----
NotBit=1<<31
def NOT(x): return NotBit|x
# AnalysisJetID
LooseBadJet=1<<8; TightBadJet=1<<9; JVT50Jet=1<<10; LessThan3Tracks=1<<11
JVT59Jet=1<<12; JVT120Jet=1<<14; JVTLoose=1<<16
BTag85MV2c20=1<<0; BTag80MV2c20=1<<1; BTag77MV2c20=1<<2; BTag70MV2c20=1<<3
BTag85MV2c10=1<<4; BTag77MV2c10=1<<5; BTag70MV2c10=1<<6; BTag60MV2c10=1<<7
BTag85DL1r=1<<20; BTag77DL1r=1<<21; BTag70DL1r=1<<22; BTag60DL1r=1<<23
# AnalysisElectronID
EVeryLooseLH=1<<0; ELooseLH=1<<1; EMediumLH=1<<2; ETightLH=1<<3; ELooseBLLH=1<<4
EIsoGradientLoose=1<<8; EIsoBoosted=1<<9; EIsoFixedCutTight=1<<10; EIsoLooseTrack=1<<11
EIsoLoose=1<<12; EIsoGradient=1<<13; EIsoFixedCutLoose=1<<14; ED0Sigma5=1<<16; EZ05mm=1<<17
EIsoFCTight=1<<18; EIsoFCTightTrackOnly=1<<19
EGood=EVeryLooseLH|ELooseLH|EMediumLH|ETightLH|ELooseBLLH|ED0Sigma5|EZ05mm
# AnalysisMuonID
MuLoose=1<<0; MuMedium=1<<1; MuTight=1<<2; MuVeryLoose=1<<3; MuHighPt=1<<4
MuIsoGradientLoose=1<<8; MuIsoBoosted=1<<9; MuIsoFixedCutTightTrackOnly=1<<10
MuIsoLooseTrack=1<<11; MuIsoLoose=1<<12; MuIsoGradient=1<<13; MuIsoFixedCutLoose=1<<14
MuD0Sigma3=1<<16; MuZ05mm=1<<17; MuNotCosmic=1<<18; MuQoPSignificance=1<<19
MuIsoFCTightTrackOnly=1<<21; MuIsoFCTightFR=1<<22


def filterObjects(cands, ptCut, etaCut, idbits=0):
    return [c for c in cands if c.pt>=ptCut and abs(c.eta)<etaCut and c.passId(idbits)]

def countObjects(cands, ptCut, etaCut, idbits=0):
    return sum(1 for c in cands if c.pt>=ptCut and abs(c.eta)<etaCut and c.passId(idbits))

def overlapRemovalVR(cands, others, radius_fn, passId=0):
    """SA's variable-radius overlapRemoval overload (AnalysisClass.cxx): remove cand when any
    other lies within radius_fn(cand, other) and cand passes passId. Semantics identical to the
    scalar version except the per-pair radius."""
    out=[]
    for cand in cands:
        overlap=False
        for other in others:
            if cand.deltaR(other) < radius_fn(cand, other) and cand is not other \
                    and cand.passId(passId):
                overlap=True; break
        if not overlap:
            out.append(cand)
    return out


def overlapRemoval(cands, others, deltaR, passId=0):
    out=[]
    for cand in cands:
        overlap=False
        for other in others:
            if cand.deltaR(other) < deltaR and cand is not other and cand.passId(passId):
                overlap=True; break
        if not overlap:
            out.append(cand)
    return out

def invmass(a,b):
    px=a.px+b.px; py=a.py+b.py; pz=a.pz+b.pz; E=a.E+b.E
    m2=E*E-px*px-py*py-pz*pz
    return math.sqrt(m2) if m2>0 else 0.0

def sumobj(objs):
    """4-vector sum -> Obj (massless-safe); handy for meff/HT-style composites."""
    px=sum(o.px for o in objs); py=sum(o.py for o in objs)
    pz=sum(o.pz for o in objs); E=sum(o.E for o in objs)
    pt=math.hypot(px,py); phi=math.atan2(py,px)
    p=math.sqrt(px*px+py*py+pz*pz)
    eta=0.5*math.log((p+pz)/(p-pz)) if p>abs(pz) else 0.0
    m2=E*E-p*p
    return Obj(pt, eta, phi, math.sqrt(m2) if m2>0 else 0.0, 0, 0, 5)

def pairDeltaPhi_to_met(a,b,met):
    px=a.px+b.px; py=a.py+b.py
    phi=math.atan2(py,px)
    d=phi-met.phi
    while d>=math.pi: d-=2*math.pi
    while d<-math.pi: d+=2*math.pi
    return abs(d)

def calcMT(lep, met):
    mT=2*lep.pt*met.pt*(1-math.cos(lep.phi-met.phi))
    return math.sqrt(mT) if mT>=0 else -math.sqrt(-mT)

def calcMTauTau(o1,o2,met):
    det=o1.px*o2.py - o1.py*o2.px
    if det==0: return 0.0
    xi1=(met.px*o2.py - o2.px*met.py)/det
    xi2=(met.py*o1.px - o1.py*met.px)/det
    dot = o1.E*o2.E - o1.px*o2.px - o1.py*o2.py - o1.pz*o2.pz
    M2=(1.+xi1)*(1.+xi2)*2*dot
    return math.sqrt(M2) if M2>=0 else -math.sqrt(abs(M2))

def calcAMT2(o1,o2,met,m1,m2):
    return get_mT2(o1.m,o1.px,o1.py,o2.m,o2.px,o2.py,met.px,met.py,m1,m2)

def minDphi(met, cands):
    dphi_min=999.0
    for c in cands:
        d=abs(met.deltaPhi(c))
        if d<dphi_min: dphi_min=d
    return dphi_min

def meff(met, jets, leptons=()):
    return met.pt + sum(j.pt for j in jets) + sum(l.pt for l in leptons)


# ---------------- ntuple IO + SA weight conventions ----------------
BASE_BRANCHES = ['Event',
                 'el_pt','el_eta','el_phi','el_charge','el_id',
                 'mu_pt','mu_eta','mu_phi','mu_charge','mu_id',
                 'jet_pt','jet_eta','jet_phi','jet_id','jet_m',
                 'met_pt','met_phi','mcWeights']


def load_ntuple(path, ngen=None, branches=BASE_BRANCHES):
    """Read the Delphes2SA 'ntuple' -> (arrays, events, Nread, weights dict).
    Weight conventions match the container SA exactly (see write_txt)."""
    import numpy as np
    import uproot
    tin = uproot.open(path)["ntuple"]
    nentries = tin.num_entries
    N = ngen if ngen is not None else nentries
    Nread = min(N, nentries)
    arrays = tin.arrays(branches, entry_stop=Nread, library='np')
    events = arrays['Event']
    w_all = np.array([x[0] if len(x) > 0 else 1.0 for x in arrays['mcWeights']],
                     dtype=np.float64)
    w = dict(w_all=w_all,
             sumW=float(w_all.sum()),
             sumW2=float((w_all * w_all).sum()),
             absw0=float(abs(w_all[0])) if len(w_all) else 1.0,
             Ngen=N)
    return arrays, events, Nread, w


def build_leptons_jets_met(arrays, i, jet_preselect=(20.0, 4.5)):
    """The universal Delphes2SA unpacking every SA routine starts from: base electron/muon
    candidate lists, pre-jets above (pt, |eta|) preselection, and the MET Obj."""
    baseElectrons=[]
    for j in range(len(arrays['el_pt'][i])):
        baseElectrons.append(Obj(arrays['el_pt'][i][j], arrays['el_eta'][i][j],
                                 arrays['el_phi'][i][j], ME, arrays['el_charge'][i][j],
                                 arrays['el_id'][i][j], ELECTRON))
    baseMuons=[]
    for j in range(len(arrays['mu_pt'][i])):
        baseMuons.append(Obj(arrays['mu_pt'][i][j], arrays['mu_eta'][i][j],
                             arrays['mu_phi'][i][j], MMU, arrays['mu_charge'][i][j],
                             arrays['mu_id'][i][j], MUON))
    ptc, etac = jet_preselect
    preJets=[]
    for j in range(len(arrays['jet_pt'][i])):
        if arrays['jet_pt'][i][j]>=ptc and abs(arrays['jet_eta'][i][j])<etac:
            preJets.append(Obj(arrays['jet_pt'][i][j], arrays['jet_eta'][i][j],
                               arrays['jet_phi'][i][j], arrays['jet_m'][i][j], 0,
                               arrays['jet_id'][i][j], 4))
    met=Obj(arrays['met_pt'][i], 0.0, arrays['met_phi'][i], 0.0, 0, 0, 6)
    return baseElectrons, baseMuons, preJets, met


# ---------------- container-format writers (parameterized by routine) ----------------
def _g(x):
    """ROOT %g-style formatting (6 significant digits), matching the container."""
    if x == 0:
        return "0"
    return f"{x:.6g}"


def write_txt(path, counts, sr_order, w):
    """Emit <Routine>.txt in the container's exact format and order.
    All row : events = N_gen ; acceptance = sum(w) ; err = sum(w^2).
    Per-SR  : events = raw unweighted count ; acceptance = events*|w|/sum(w) ;
              err = sqrt(events)*|w|/sum(w). The integer `events` column is the
              bit-for-bit quantity the validation diff compares."""
    norm = (w['absw0'] / w['sumW']) if w['sumW'] != 0 else 0.0
    lines = ["SR,events,acceptance,err"]
    lines.append(f"All,{w['Ngen']},{_g(w['sumW'])},{_g(w['sumW2'])}")
    for sr in sr_order:
        ev = counts.get(sr, 0)
        acc = ev * norm
        err = math.sqrt(ev) * norm
        lines.append(f"{sr},{ev},{_g(acc)},{_g(err)}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_root(path, ntuple_rows, sr_order, flavour_flags=("isee", "ismm")):
    """Emit <Routine>.root with tree 'ntuple' in the SimpleAnalysis layout sa2json consumes:
    per-SR branch = eventWeight if the event entered that SR else 0, plus flavour flags +
    Event. ntuple_rows: (Event, weight, flag1, flag2, accepted_set)."""
    import numpy as np
    import uproot
    data = {
        "Event":       np.array([r[0] for r in ntuple_rows], dtype=np.int32),
        "eventWeight": np.array([r[1] for r in ntuple_rows], dtype=np.float64),
    }
    for k, flag in enumerate(flavour_flags):
        data[flag] = np.array([1 if r[2+k] else 0 for r in ntuple_rows], dtype=np.int32)
    for sr in sr_order:
        data[sr] = np.array([row[1] if sr in row[4] else 0.0 for row in ntuple_rows],
                            dtype=np.float64)
    with uproot.recreate(path) as fo:
        fo["ntuple"] = data


# ---------------- the single-pass counting driver (routines WITHOUT external resolvers) ----------------
def run_counting_routine(routine, input_path, output_dir, ngen=None):
    """Generic driver for plain counting routines: per event, routine.select(arrays, i) ->
    (accepted_set, flag1, flag2) or None. Writes <name>.txt + <name>.root. Routines needing a
    mid-pass external resolver (the flagship's RJR) implement their own run() instead."""
    os.makedirs(output_dir, exist_ok=True)
    branches = getattr(routine, "BRANCHES", BASE_BRANCHES)
    arrays, events, Nread, w = load_ntuple(input_path, ngen, branches)
    order = routine.sr_order()
    counts = {sr: 0 for sr in order}
    rows = []
    for i in range(Nread):
        res = routine.select(arrays, i)
        if res is None:
            continue
        accepted, f1, f2 = res
        for sr in accepted:
            counts[sr] += 1
        rows.append((int(events[i]), float(w['w_all'][i]), f1, f2, accepted))
    outtxt = os.path.join(output_dir, f"{routine.NAME}.txt")
    write_txt(outtxt, counts, order, w)
    write_root(os.path.join(output_dir, f"{routine.NAME}.root"), rows, order,
               getattr(routine, "FLAVOUR_FLAGS", ("isee", "ismm")))
    print(f"[native:{routine.NAME}] {Nread} events read, "
          f"{sum(counts.values())} SR-accepts, wrote {outtxt} (+.root)")
    return counts

# ---------------- SA-framework helper semantics pinned from source (CR-005 ports) ----------------
def concat_sorted(*colls):
    """SA's AnalysisObjects operator+ (AnalysisObject.cxx): concatenate THEN sortObjectsByPt.
    The sort is LOAD-BEARING wherever a combined collection feeds [i].pt cuts (e.g. jets+leptons
    'corrected jets'); python list + does NOT sort — never use it for SA `a + b` transcription."""
    out = []
    for c in colls:
        out.extend(c)
    out.sort(key=lambda o: -o.pt)
    return out


def sum_objects_pt(cands, maxNum=10000, ptCut=0.0):
    """SA sumObjectsPt: sum pT over the FIRST min(maxNum, len) objects with pt > ptCut
    (list order, which is pT order for SA collections)."""
    return sum(c.pt for c in cands[:maxNum] if c.pt > ptCut)


def min_dphi_n(met, cands, maxNum=10000, ptCut=0.0):
    """SA minDphi(met, cands, maxNum, ptCut): min |dphi| over the first maxNum candidates
    with pt > ptCut; 999 if none qualify."""
    dphi_min = 999.0
    for c in cands[:maxNum]:
        d = abs(met.deltaPhi(c))
        if d < dphi_min and c.pt > ptCut:
            dphi_min = d
    return dphi_min


def aplanarity(jets, r=2):
    """SA aplanarity: 1.5 x smallest eigenvalue of the |p|^(r-2)-weighted momentum tensor
    normalized by sum(|p|^r) (AnalysisClass.cxx calcEigenValues); 0 for <2 jets."""
    if len(jets) < 2:
        return 0.0
    import numpy as np
    T = np.zeros((3, 3))
    norm = 0.0
    for j in jets:
        p = (j.px, j.py, j.pz)
        mod_p = math.sqrt(p[0]*p[0] + p[1]*p[1] + p[2]*p[2])
        wgt = mod_p ** (r - 2)
        for a in range(3):
            for b in range(3):
                T[a, b] += p[a] * p[b] * wgt
        norm += mod_p ** r
    if norm == 0:
        return 0.0
    T /= norm
    eig = np.linalg.eigvalsh(T)          # ascending; SA uses descending with index 2 = smallest
    return 1.5 * float(eig[0])
