#!/usr/bin/env python
"""Declarative reconstructed-object selection and signed counting yields.

Supply object selections, regions and normalization. Observable functions use
complete supplied collections; callers select objects before computing them.

Spec schema (JSON; every threshold is supplied by the study):
  {"name": "...", "lumi_fb": <L>,
   "objects": {"electron": {"pt":..,"eta":..,"id":..}, "muon": {...}, "jet": {"pt":..,"eta":..}},
   "overlap_removal": [{"remove":"jet","near":"electron","dR":..}, ...],
   "signal":  {"electron": {"pt":..}, "muon": {"pt":..}, "jet": {"pt":..}},
   "btag":    {"idbit":.., "pt":.., "eta":..},          # optional; all three keys required
   "dphi_min_jets": <N>,                                  # optional; default uses every signal jet
   "regions": [{"name":"SR1", "cuts":[{"var":"nJet","op":">=","val":..}, ...]}]}

Variables: nEl nMu nLep nJet nBjet MET HT meff mTlep mll mjj dphiMin
  jet1pt..jet4pt lep1pt lep2pt (see compute_vars).

Usage:
  native_sa_generic.py run --delphes <delphes.root> --spec <spec.json> --xs-pb <sigma> \
      [--lumi-fb <L>] [--out yields.json]
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


# Shared reconstructed-object and kinematic primitives.
from .sa_native_core import (Obj, filterObjects, overlapRemoval, invmass, calcMT,   # noqa: E402
                            minDphi, ELECTRON, MUON, ME, MMU, summarize_weights)
JET = 2   # jet type tag (native_simpleanalysis types only leptons; jets are a separate collection)


def die(msg):
    print(f"ERROR (native_sa_generic): {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------- the derived-variable library (cut-based observables) ----------------
def _lead(objs, n):
    return objs[n - 1].pt if len(objs) >= n else 0.0


def compute_vars(sig_el, sig_mu, sig_jet, sig_bjet, met, dphi_min_jets=None):
    leps = sorted(sig_el + sig_mu, key=lambda o: -o.pt)
    jets = sorted(sig_jet, key=lambda o: -o.pt)
    # dphiMin uses every signal jet unless the spec declares a leading-jet count.
    dphi_jets = jets if dphi_min_jets is None else jets[:dphi_min_jets]
    HT = sum(j.pt for j in jets)
    v = {
        "nEl": len(sig_el), "nMu": len(sig_mu), "nLep": len(leps),
        "nJet": len(jets), "nBjet": len(sig_bjet),
        "MET": met.pt, "HT": HT, "meff": HT + met.pt,
        "jet1pt": _lead(jets, 1), "jet2pt": _lead(jets, 2),
        "jet3pt": _lead(jets, 3), "jet4pt": _lead(jets, 4),
        "lep1pt": _lead(leps, 1), "lep2pt": _lead(leps, 2),
        "dphiMin": minDphi(met, dphi_jets) if dphi_jets else 9.99,
        "mTlep": calcMT(leps[0], met) if leps else 0.0,
    }
    # Invariant mass of the leading two leptons; no implicit flavour/charge pairing.
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
class MissingAnalysisInput(ValueError):
    """A declared selection or normalization input is missing."""


def select_event(spec, el, mu, jet, met):
    if 'btag' in spec and {'pt', 'eta', 'idbit'} - set(spec['btag']):
        raise MissingAnalysisInput('explicit btag pt, eta and idbit required')
    dphi_min_jets = spec.get('dphi_min_jets')
    if dphi_min_jets is not None and (type(dphi_min_jets) is not int or dphi_min_jets < 1):
        raise ValueError('dphi_min_jets must be a positive integer when declared')
    o = spec["objects"]
    base_el = filterObjects(el, o["electron"]["pt"], o["electron"]["eta"], o["electron"].get("id", 0))
    base_mu = filterObjects(mu, o["muon"]["pt"], o["muon"]["eta"], o["muon"].get("id", 0))
    base_jet = filterObjects(jet, o["jet"]["pt"], o["jet"]["eta"], o["jet"].get("id", 0))
    # overlap removal in the declared order
    coll = {"electron": base_el, "muon": base_mu, "jet": base_jet}
    for step in spec.get("overlap_removal", []):
        coll[step["remove"]] = overlapRemoval(coll[step["remove"]], coll[step["near"]], step["dR"])
    el2, mu2, jet2 = coll["electron"], coll["muon"], coll["jet"]
    # Apply every declared signal requirement to the baseline survivors.
    sig = spec.get("signal", {})
    def tighten(objects, name):
        cuts = sig.get(name, {})
        unsupported = set(cuts) - {"pt", "eta", "id"}
        if unsupported:
            raise ValueError(f"Unsupported signal {name} requirements: {sorted(unsupported)}")
        return filterObjects(objects, cuts.get("pt", 0), cuts.get("eta", math.inf), cuts.get("id", 0))
    el2, mu2, jet2 = tighten(el2, "electron"), tighten(mu2, "muon"), tighten(jet2, "jet")
    # b-jets (optional): from the signal jets, by id bit
    bjet = []
    if "btag" in spec:
        b = spec["btag"]
        bjet = [j for j in jet2 if j.pt >= b["pt"] and abs(j.eta) < b["eta"]
                and j.passId(b["idbit"])]
    return compute_vars(el2, mu2, jet2, bjet, met, dphi_min_jets)


def run_events(spec, events, weights, *, return_sumw2=False):
    """events = list of (el, mu, jet, met) Obj-lists; weights = per-event weight. Returns per-SR
    weighted yields."""
    if len(events) != len(weights):
        raise ValueError('Each event must have exactly one nominal weight')
    summarize_weights(weights)  # Reject missing, non-finite, or zero-normalization inputs.
    yields = {r["name"]: 0.0 for r in spec["regions"]}
    sumw2 = {name: 0.0 for name in yields}
    raw = {r["name"]: 0 for r in spec["regions"]}
    for (el, mu, jet, met), w in zip(events, weights):
        v = select_event(spec, el, mu, jet, met)
        for r in spec["regions"]:
            if passes(r, v):
                yields[r["name"]] += w
                sumw2[r["name"]] += w*w
                raw[r["name"]] += 1
    if return_sumw2:
        return yields, raw, sumw2
    return yields, raw


# ---------------- Delphes ROOT reader (uproot; the generic real-input path) ----------------
def read_delphes(path):
    import uproot
    import numpy as np
    f = uproot.open(path)
    t = f["Delphes"]
    if 'Event.Weight' not in t:
        raise ValueError('Delphes input lacks Event.Weight; nominal weights cannot be assumed to be unity')
    nominal = t['Event.Weight'].array(library='np')
    if any(len(row) != 1 for row in nominal):
        raise ValueError('Delphes Event.Weight must contain exactly one nominal weight per event')
    weights = [float(row[0]) for row in nominal]
    summarize_weights(weights)
    br = {b: t[b].array(library="np") for b in
          ("Electron.PT", "Electron.Eta", "Electron.Phi", "Electron.Charge",
           "Muon.PT", "Muon.Eta", "Muon.Phi", "Muon.Charge",
           "Jet.PT", "Jet.Eta", "Jet.Phi", "Jet.Mass", "Jet.BTag",
           "MissingET.MET", "MissingET.Phi") if b in t}
    n = len(br["MissingET.MET"])
    if len(weights) != n:
        raise ValueError('Event.Weight and MissingET have different event counts')
    events = []
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
    return events, weights


def validate_delphes_spec(spec):
    """Delphes cannot supply ATLAS lepton quality IDs or arbitrary jet working points.

    The direct reader represents only a boolean Delphes b tag with the established
    generic bit (1 << 4). Fully populated SA objects may use their actual IDs through
    select_event, but the Delphes adapter must not invent them.
    """
    for group in ['objects', 'signal']:
        for name, cuts in spec.get(group, {}).items():
            bits = cuts.get('id', 0)
            if not isinstance(bits, int) or isinstance(bits, bool) or bits < 0:
                raise ValueError(f'{group}.{name}.id must be a nonnegative integer mask')
            supported = (1 << 4) if name == 'jet' else 0
            if bits & ~supported:
                raise ValueError(f'{group}.{name}.id={bits} is unsupported by the Delphes adapter; '
                                 'supply reconstructed SA objects with real quality IDs')
    if 'btag' in spec and spec['btag'].get('idbit') != 1 << 4:
        raise ValueError('Delphes adapter supports only btag.idbit=16 (boolean Delphes BTag); '
                         'other ATLAS b-tag working points require a validated conversion')


# ---------------- selftest ----------------
def _mk(pt, eta, phi, typ, m=0.0, idbits=0x7FFFFFFF, charge=1):
    return Obj(pt, eta, phi, m, charge, idbits, typ)


def _selftest():
    fails = []
    # a 0-lepton jets+MET spec (archetype A), b-jet aware
    spec = {
        "name": "fictional-counting", "lumi_fb": 7,
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
    supplied_lumi = spec.get('lumi_fb', args.lumi_fb)
    if supplied_lumi is None:
        raise MissingAnalysisInput('explicit luminosity required in spec or --lumi-fb')
    lumi_fb = float(supplied_lumi)
    if not math.isfinite(lumi_fb) or lumi_fb <= 0:
        raise ValueError('luminosity must be finite and positive')
    validate_delphes_spec(spec)
    events, weights = read_delphes(args.delphes)
    n = len(events)
    yields, raw, sumw2 = run_events(spec, events, weights, return_sumw2=True)
    total = summarize_weights(weights)
    if not math.isfinite(args.xs_pb) or args.xs_pb <= 0 or not math.isfinite(lumi_fb) or lumi_fb <= 0:
        raise ValueError('Cross section and luminosity must be finite and positive')
    norm = args.xs_pb * 1000.0 * lumi_fb / total['sumW']
    out = {"analysis": spec["name"], "lumi_fb": lumi_fb, "xs_pb": args.xs_pb, "n_events": n,
           "sumw": total['sumW'], "sumw2": total['sumW2'],
           "regions": {name: {"raw": raw[name], "sumw": yields[name], "sumw2": sumw2[name],
                              "acceptance": yields[name] / total['sumW'],
                              "yield": yields[name] * norm,
                              "mc_stat_error": math.sqrt(sumw2[name]) * abs(norm)} for name in yields},
           "note": "cut-based native SimpleAnalysis via native_sa_generic; step-3.5 "
                   "detector-fidelity + certify_acceptance still apply"}
    dst = args.out or "sr_yields_generic.json"
    with open(dst, "w") as f:
        json.dump(out, f, indent=1, allow_nan=False)
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
    p.add_argument("--lumi-fb", type=float, default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_run)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
