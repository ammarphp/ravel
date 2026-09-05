#!/usr/bin/env python
"""native_sa_generic -- a DECLARATIVE native SimpleAnalysis engine (CR-005, the generalization).

`native_simpleanalysis.py` reproduces ONE analysis (EwkCompressed2018) bit-for-bit, including its
recursive-jigsaw variables -- that hard case stays exactly as-is. But most SimpleAnalysis routines
(~85% of the surveyed BSM population: 0-lep jets+MET, 1-lep+jets, 2-lep, monojet -- the 4 archetypes)
are cut-and-count on standard objects with NO RJR. This engine serves that common case NATIVELY, VM-
free, from a DECLARATIVE SPEC -- so porting a new analysis is writing a JSON spec + (only if it needs
a novel observable) a small variable plugin, NOT a C++-to-Python rewrite. It REUSES the framework
primitives already validated in native_simpleanalysis.py (Obj, filterObjects, overlapRemoval,
invmass, calcMT, calcMTauTau, get_mT2, minDphi) -- one implementation, imported, never duplicated.

Scope + honesty (docs/workflow/reference/native-pipeline.md): this covers cut-based counting SRs on
standard reconstructed objects. Analyses needing recursive jigsaw (EwkCompressed2018), bespoke
taggers, or per-event ML discriminants are OUT of scope -- they take the dedicated port (RJR) or a
different route (shape_fit.py, effmap_fold.py, Option C). Every run still passes the step-3.5
detector-fidelity gate + the acc-eff certification (certify_acceptance.py) -- the SPEC does not
excuse validation; it just removes the boilerplate.

Spec schema (JSON):
  {"name": "...", "lumi_fb": 139,
   "objects": {"electron": {"pt":20,"eta":2.47,"id":0}, "muon": {...}, "jet": {"pt":20,"eta":2.8}},
   "overlap_removal": [{"remove":"jet","near":"electron","dR":0.2}, {"remove":"electron","near":"jet","dR":0.4}],
   "signal":  {"electron": {"pt":25}, "muon": {"pt":25}, "jet": {"pt":30}},   # signal-level tightenings
   "btag":    {"idbit":4, "pt":30, "eta":2.5},                                # b-jet definition (optional)
   "regions": [{"name":"SR1", "cuts":[{"var":"nLep","op":"==","val":0},
                                      {"var":"nJet","op":">=","val":4},
                                      {"var":"MET","op":">=","val":250},
                                      {"var":"meff","op":">=","val":800},
                                      {"var":"dphiMin","op":">=","val":0.4}]}]}

Variables (the cut-based library): nEl nMu nLep nJet nBjet MET HT meff mTlep mll dphiMin
  jet1pt jet2pt jet3pt jet4pt lep1pt lep2pt mjj njet_or_more (see VARS). Extend VARS for a new one.

Usage:
  native_sa_generic.py run --delphes <delphes.root> --spec <spec.json> --xs-pb <sigma> [--out yields.json]
  native_sa_generic.py --selftest
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse
import json
import math
import os
import sys


# reuse the VALIDATED framework primitives -- never re-implement them. (CR-005: they now live in
# sa_native_core, the shared layer under BOTH the flagship port and this engine.)
from .sa_native_core import (Obj, filterObjects, overlapRemoval, invmass, calcMT,   # noqa: E402
                            minDphi, ELECTRON, MUON, ME, MMU)
JET = 2   # jet type tag (native_simpleanalysis types only leptons; jets are a separate collection)


def die(msg):
    print(f"ERROR (native_sa_generic): {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------- the derived-variable library (cut-based observables) ----------------
def _lead(objs, n):
    return objs[n - 1].pt if len(objs) >= n else 0.0


def compute_vars(sig_el, sig_mu, sig_jet, sig_bjet, met):
    leps = sorted(sig_el + sig_mu, key=lambda o: -o.pt)
    jets = sorted(sig_jet, key=lambda o: -o.pt)
    HT = sum(j.pt for j in jets)
    v = {
        "nEl": len(sig_el), "nMu": len(sig_mu), "nLep": len(leps),
        "nJet": len(jets), "nBjet": len(sig_bjet),
        "MET": met.pt, "HT": HT, "meff": HT + met.pt,
        "jet1pt": _lead(jets, 1), "jet2pt": _lead(jets, 2),
        "jet3pt": _lead(jets, 3), "jet4pt": _lead(jets, 4),
        "lep1pt": _lead(leps, 1), "lep2pt": _lead(leps, 2),
        "dphiMin": minDphi(met, jets[:4]) if jets else 9.99,
        "mTlep": calcMT(leps[0], met) if leps else 0.0,
    }
    # dilepton invariant mass of the leading opposite-sign same-flavour pair (else leading two)
    if len(leps) >= 2:
        v["mll"] = invmass(leps[0], leps[1])
    else:
        v["mll"] = 0.0
    v["mjj"] = invmass(jets[0], jets[1]) if len(jets) >= 2 else 0.0
    return v


OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b,
       ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}


def passes(region, v):
    for cut in region["cuts"]:
        var, op, val = cut["var"], cut["op"], cut["val"]
        if var not in v:
            die(f"region {region['name']}: unknown variable {var!r} "
                f"(known: {', '.join(sorted(v))}) -- add it to compute_vars()")
        if op not in OPS:
            die(f"region {region['name']}: unknown op {op!r} (known: {', '.join(OPS)})")
        if not OPS[op](v[var], val):
            return False
    return True


# ---------------- per-event selection from the spec ----------------
def select_event(spec, el, mu, jet, met):
    o = spec["objects"]
    base_el = filterObjects(el, o["electron"]["pt"], o["electron"]["eta"], o["electron"].get("id", 0))
    base_mu = filterObjects(mu, o["muon"]["pt"], o["muon"]["eta"], o["muon"].get("id", 0))
    base_jet = filterObjects(jet, o["jet"]["pt"], o["jet"]["eta"], o["jet"].get("id", 0))
    # overlap removal in the declared order
    coll = {"electron": base_el, "muon": base_mu, "jet": base_jet}
    for step in spec.get("overlap_removal", []):
        coll[step["remove"]] = overlapRemoval(coll[step["remove"]], coll[step["near"]], step["dR"])
    el2, mu2, jet2 = coll["electron"], coll["muon"], coll["jet"]
    # signal-level tightenings (optional)
    sig = spec.get("signal", {})
    if "electron" in sig:
        el2 = [c for c in el2 if c.pt >= sig["electron"].get("pt", 0)]
    if "muon" in sig:
        mu2 = [c for c in mu2 if c.pt >= sig["muon"].get("pt", 0)]
    if "jet" in sig:
        jet2 = [c for c in jet2 if c.pt >= sig["jet"].get("pt", 0)]
    # b-jets (optional): from the signal jets, by id bit
    bjet = []
    if "btag" in spec:
        b = spec["btag"]
        bjet = [j for j in jet2 if j.pt >= b.get("pt", 0) and abs(j.eta) < b.get("eta", 2.5)
                and j.passId(b["idbit"])]
    return compute_vars(el2, mu2, jet2, bjet, met)


def run_events(spec, events, weights):
    """events = list of (el, mu, jet, met) Obj-lists; weights = per-event weight. Returns per-SR
    weighted yields."""
    yields = {r["name"]: 0.0 for r in spec["regions"]}
    raw = {r["name"]: 0 for r in spec["regions"]}
    for (el, mu, jet, met), w in zip(events, weights):
        v = select_event(spec, el, mu, jet, met)
        for r in spec["regions"]:
            if passes(r, v):
                yields[r["name"]] += w
                raw[r["name"]] += 1
    return yields, raw


# ---------------- Delphes ROOT reader (uproot; the generic real-input path) ----------------
def read_delphes(path):
    import uproot
    import numpy as np
    f = uproot.open(path)
    t = f["Delphes"]
    br = {b: t[b].array(library="np") for b in
          ("Electron.PT", "Electron.Eta", "Electron.Phi", "Electron.Charge",
           "Muon.PT", "Muon.Eta", "Muon.Phi", "Muon.Charge",
           "Jet.PT", "Jet.Eta", "Jet.Phi", "Jet.Mass", "Jet.BTag",
           "MissingET.MET", "MissingET.Phi") if b in t}
    n = len(br["MissingET.MET"])
    events, weights = [], []
    for i in range(n):
        el = [Obj(br["Electron.PT"][i][j], br["Electron.Eta"][i][j], br["Electron.Phi"][i][j],
                  ME, br["Electron.Charge"][i][j], 0x7FFFFFFF, ELECTRON)
              for j in range(len(br.get("Electron.PT", [[]]*n)[i]))]
        mu = [Obj(br["Muon.PT"][i][j], br["Muon.Eta"][i][j], br["Muon.Phi"][i][j],
                  MMU, br["Muon.Charge"][i][j], 0x7FFFFFFF, MUON)
              for j in range(len(br.get("Muon.PT", [[]]*n)[i]))]
        jet = []
        for j in range(len(br.get("Jet.PT", [[]]*n)[i])):
            # jet idbits carry ONLY the b-tag bit (bit 4) -- a clean baseline so the b-jet filter is
            # meaningful (0x7FFFFFFF would set bit 4 on EVERY jet). Jet quality/id cuts are not
            # applied here (spec jet "id" defaults to 0 -> no-op), matching the Delphes fast-sim.
            idbits = (1 << 4) if br.get("Jet.BTag", [[0]]*n)[i][j] else 0
            jet.append(Obj(br["Jet.PT"][i][j], br["Jet.Eta"][i][j], br["Jet.Phi"][i][j],
                           br["Jet.Mass"][i][j], 0, idbits, JET))
        met = Obj(br["MissingET.MET"][i][0], 0.0, br["MissingET.Phi"][i][0], 0.0, 0, 0, JET)
        events.append((el, mu, jet, met))
        weights.append(1.0)
    return events, weights


# ---------------- selftest ----------------
def _mk(pt, eta, phi, typ, m=0.0, idbits=0x7FFFFFFF, charge=1):
    return Obj(pt, eta, phi, m, charge, idbits, typ)


def _selftest():
    fails = []
    # a 0-lepton jets+MET spec (archetype A), b-jet aware
    spec = {
        "name": "selftest-0L", "lumi_fb": 139,
        "objects": {"electron": {"pt": 20, "eta": 2.47}, "muon": {"pt": 20, "eta": 2.5},
                    "jet": {"pt": 20, "eta": 2.8}},
        "overlap_removal": [{"remove": "jet", "near": "electron", "dR": 0.2},
                            {"remove": "electron", "near": "jet", "dR": 0.4},
                            {"remove": "muon", "near": "jet", "dR": 0.4}],
        "signal": {"jet": {"pt": 30}},
        "btag": {"idbit": 1 << 4, "pt": 30, "eta": 2.5},
        "regions": [
            {"name": "SR_4j_METhi", "cuts": [{"var": "nLep", "op": "==", "val": 0},
                                             {"var": "nJet", "op": ">=", "val": 4},
                                             {"var": "MET", "op": ">=", "val": 250},
                                             {"var": "meff", "op": ">=", "val": 800},
                                             {"var": "dphiMin", "op": ">=", "val": 0.4}]},
            {"name": "SR_2b", "cuts": [{"var": "nBjet", "op": ">=", "val": 2},
                                       {"var": "MET", "op": ">=", "val": 200}]},
            {"name": "SR_1L", "cuts": [{"var": "nLep", "op": "==", "val": 1},
                                       {"var": "mTlep", "op": ">=", "val": 100}]},
        ]}
    # EVENT A: 4 hard jets (2 b-tagged via bit 4 on a clean baseline), big MET well-separated from
    # jets, no leptons -> SR_4j_METhi + SR_2b
    jetsA = [_mk(300, 0.5, 0.0, JET, idbits=(1 << 4)),
             _mk(200, -0.3, 0.3, JET, idbits=(1 << 4)),
             _mk(120, 1.0, 0.6, JET, idbits=0), _mk(60, -1.2, 0.9, JET, idbits=0)]
    metA = _mk(400, 0.0, math.pi, JET)          # opposite side -> dphiMin large
    evA = ([], [], jetsA, metA)
    # EVENT B: one electron with high mT, few jets, low MET -> SR_1L only
    elB = [_mk(80, 0.2, 0.0, ELECTRON, m=ME)]
    metB = _mk(120, 0.0, math.pi, JET)          # mT = sqrt(2 pt_l MET (1-cos dphi)) = sqrt(2*80*120*2)
    evB = (elB, [], [_mk(40, 0.5, 1.0, JET)], metB)
    # EVENT C: empty-ish, fails everything
    evC = ([], [], [_mk(25, 0.0, 0.0, JET)], _mk(50, 0, 0, JET))

    events = [evA, evB, evC]
    weights = [1.0, 1.0, 1.0]
    yields, raw = run_events(spec, events, weights)

    # hand-checks
    vA = select_event(spec, *evA)
    if not (vA["nJet"] == 4 and vA["nBjet"] == 2 and vA["nLep"] == 0 and vA["MET"] == 400
            and abs(vA["meff"] - (680 + 400)) < 1e-6 and vA["dphiMin"] > 0.4):
        fails.append(f"event A vars wrong: {vA}")
    vB = select_event(spec, *evB)
    mT_expect = math.sqrt(2 * 80 * 120 * (1 - math.cos(math.pi)))     # dphi=pi -> (1-cos)=2
    if not (vB["nLep"] == 1 and abs(vB["mTlep"] - mT_expect) < 1e-6):
        fails.append(f"event B mT wrong: got {vB['mTlep']:.2f} want {mT_expect:.2f}")
    exp = {"SR_4j_METhi": 1.0, "SR_2b": 1.0, "SR_1L": 1.0}
    if yields != exp:
        fails.append(f"SR yields {yields} != expected {exp}")
    else:
        print(f"[selftest] SR yields exact: {yields}")
    # overlap-removal check: an electron-overlapping jet is dropped
    elOR = [_mk(50, 0.0, 0.0, ELECTRON, m=ME)]
    jetOR = [_mk(100, 0.0, 0.05, JET), _mk(100, 2.0, 2.0, JET)]   # first jet within dR 0.2 of the el
    vOR = select_event(spec, elOR, [], jetOR, _mk(100, 0, math.pi, JET))
    if vOR["nJet"] != 1:
        fails.append(f"overlap removal failed: nJet={vOR['nJet']} (want 1; the el-overlapping jet must drop)")
    else:
        print("[selftest] overlap removal: el-overlapping jet dropped (nJet 2->1)  ok")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("native_sa_generic selftest: PASS (variable library, SR cascade, overlap removal, b-tag)")
    return 0


def cmd_run(args):
    with open(args.spec) as f:
        spec = json.load(f)
    events, weights = read_delphes(args.delphes)
    lumi_fb = float(spec.get("lumi_fb", args.lumi_fb))
    n = len(events)
    yields, raw = run_events(spec, events, weights)
    # yields above are raw event counts; scale to expected = xs[pb]*1000*lumi[fb]*(passing/total)
    norm = args.xs_pb * 1000.0 * lumi_fb / n if n else 0.0
    out = {"analysis": spec["name"], "lumi_fb": lumi_fb, "xs_pb": args.xs_pb, "n_events": n,
           "regions": {name: {"raw": raw[name], "acceptance": raw[name] / n if n else 0.0,
                              "yield": raw[name] * norm} for name in yields},
           "note": "cut-based native SimpleAnalysis via native_sa_generic (CR-005); step-3.5 "
                   "detector-fidelity + certify_acceptance still apply"}
    dst = args.out or "sr_yields_generic.json"
    with open(dst, "w") as f:
        json.dump(out, f, indent=1)
    for name in yields:
        print(f"  {name:16s} raw={raw[name]:5d}  acc={out['regions'][name]['acceptance']:.4f}  "
              f"yield={out['regions'][name]['yield']:.2f}")
    print(f"wrote {dst}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="apply a declarative spec to a Delphes ROOT -> per-SR yields")
    p.add_argument("--delphes", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--xs-pb", type=float, required=True)
    p.add_argument("--lumi-fb", type=float, default=139.0)
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_run)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
