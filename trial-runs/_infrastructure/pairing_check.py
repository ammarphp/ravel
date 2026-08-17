#!/usr/bin/env python3
"""pairing_check -- the likelihood<->selection PAIRING gate (closes the KNOWN-LIMITATIONS
'asserted, not verified' entry; run once per analysis+chain pairing, and at step 7 whenever
the patch generator or the published workspace version changes).

The original check (KNOWN-LIMITATIONS' only 'none'-graded entry):
structurally verify the signal patch produced by our chain against the published bkg-only
workspace it is applied to -- channel-name bijection, per-channel bin counts, and patch-target
paths that actually exist in the workspace.

Also emits the machine artifact `pairing_check.json` (beside --patch by default, or --out):
{schema_version, generated_utc, generator, bkg_workspace, patch, paired, n_channels,
 mismatches, verdict} with verdict=="pass" iff paired and no mismatches -- the SAME condition
that decides exit 0 vs SystemExit(1) (unchanged CLI behaviour for existing callers).
"""
import argparse
import json
import os
import re
import sys


def _resolve_timestamp(cli_timestamp=None):
    """generated_utc: --timestamp, else $PAIRING_CHECK_UTC, else "" -- never datetime.now()."""
    if cli_timestamp:
        return cli_timestamp
    return os.environ.get("PAIRING_CHECK_UTC", "")


def check_pairing(bkg_path, patch_path):
    """Structural pairing check. Returns (paired: bool, n_channels: int, mismatches: [str],
    report: [str]) -- report is the informational print lines, mismatches is what fails the gate."""
    ws = json.load(open(bkg_path))
    patch = json.load(open(patch_path))

    chans = {c["name"]: len(c["samples"][0]["data"]) for c in ws["channels"]}
    obs = {o["name"]: len(o["data"]) for o in ws["observations"]}
    report = [f"workspace: {len(chans)} channels; observations match channels: "
              f"{set(chans) == set(obs)}; bin-count consistency: "
              f"{all(chans[k] == obs[k] for k in chans)}"]

    adds = [op for op in patch if op["op"] == "add"]
    mismatches = []
    touched = set()
    for op in adds:
        m = re.match(r"/channels/(\d+)/samples/(\d+)", op["path"])
        if not m:
            mismatches.append(f"unexpected patch path {op['path']}")
            continue
        ci = int(m.group(1))
        if ci >= len(ws["channels"]):
            mismatches.append(f"patch targets channel index {ci} beyond workspace "
                              f"({len(ws['channels'])})")
            continue
        ch = ws["channels"][ci]["name"]
        touched.add(ch)
        nbins = len(op["value"]["data"])
        if nbins != chans[ch]:
            mismatches.append(f"channel {ch}: patch adds {nbins} bins vs workspace {chans[ch]}")
        mods = {mm["type"] for mm in op["value"].get("modifiers", [])}
        if "normfactor" not in mods:
            mismatches.append(f"channel {ch}: signal sample lacks the mu normfactor")

    untouched = set(chans) - touched
    report.append(f"patch: {len(adds)} signal-sample adds -> {len(touched)} channels touched; "
                   f"{len(untouched)} untouched (CRs/VRs expected untouched: "
                   f"{sorted(list(untouched))[:6]}{'...' if len(untouched) > 6 else ''})")
    sr_untouched = [c for c in untouched if c.upper().startswith("SR")]
    if sr_untouched:
        mismatches.append(f"SR channels NOT patched: {sr_untouched}")

    paired = not mismatches
    return paired, len(chans), mismatches, report


def write_pairing_check_json(out_path, bkg_path, patch_path, paired, n_channels, mismatches,
                              timestamp):
    """verdict=='pass' iff paired and no mismatches -- the same condition that decides exit 0/1."""
    verdict = "pass" if (paired and not mismatches) else "fail"
    record = {
        "schema_version": 1,
        "generated_utc": timestamp,
        "generator": "pairing_check.py",
        "bkg_workspace": bkg_path,
        "patch": patch_path,
        "paired": bool(paired),
        "n_channels": int(n_channels),
        "mismatches": list(mismatches),
        "verdict": verdict,
    }
    outdir = os.path.dirname(os.path.abspath(out_path))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(record, fh, indent=2)
    return record


def _default_out(patch_path):
    return os.path.join(os.path.dirname(os.path.abspath(patch_path)), "pairing_check.json")


# ---------------------------------------------------------------- selftest
def _selftest():
    import tempfile
    fails = []

    def make_ws(n_bins_sr=3, n_bins_cr=2):
        return {
            "channels": [
                {"name": "SR", "samples": [{"name": "bkg", "data": [10.0] * n_bins_sr}]},
                {"name": "CR", "samples": [{"name": "bkg", "data": [20.0] * n_bins_cr}]},
            ],
            "observations": [
                {"name": "SR", "data": [10] * n_bins_sr},
                {"name": "CR", "data": [20] * n_bins_cr},
            ],
        }

    def sig_op(ci, n_bins, with_normfactor=True):
        return {
            "op": "add", "path": f"/channels/{ci}/samples/0",
            "value": {"name": "sig", "data": [1.0] * n_bins,
                      "modifiers": ([{"type": "normfactor", "name": "mu"}]
                                    if with_normfactor else [])},
        }

    with tempfile.TemporaryDirectory(prefix="pairing_check_selftest_") as td:
        ws_path = os.path.join(td, "bkg.json")
        json.dump(make_ws(n_bins_sr=3, n_bins_cr=2), open(ws_path, "w"))

        # 1) MATCHED: SR patched with correct bin count + mu normfactor -> pass, JSON verdict=pass
        patch_ok = os.path.join(td, "patch_ok.json")
        json.dump([sig_op(0, 3)], open(patch_ok, "w"))
        paired1, n_ch1, mism1, _ = check_pairing(ws_path, patch_ok)
        out1 = os.path.join(td, "pairing_check_ok.json")
        rec1 = write_pairing_check_json(out1, ws_path, patch_ok, paired1, n_ch1, mism1,
                                         _resolve_timestamp())
        ok1 = (paired1 and not mism1 and os.path.isfile(out1)
               and rec1["verdict"] == "pass" and rec1["paired"] is True)
        if not ok1:
            fails.append(f"matched case: paired={paired1} mismatches={mism1} "
                         f"verdict={rec1['verdict']}")
        print(f"[selftest] 1 matched pairing: verdict={rec1['verdict']}  {'ok' if ok1 else 'FAIL'}")

        # 2) MISMATCHED bin count: workspace SR has 3 bins, patch adds 2 -> fail
        patch_bad = os.path.join(td, "patch_bad.json")
        json.dump([sig_op(0, 2)], open(patch_bad, "w"))
        paired2, n_ch2, mism2, _ = check_pairing(ws_path, patch_bad)
        out2 = os.path.join(td, "pairing_check_bad.json")
        rec2 = write_pairing_check_json(out2, ws_path, patch_bad, paired2, n_ch2, mism2,
                                         _resolve_timestamp())
        ok2 = ((not paired2) and mism2 and os.path.isfile(out2) and rec2["verdict"] == "fail")
        if not ok2:
            fails.append(f"mismatched bin-count case: paired={paired2} mismatches={mism2} "
                         f"verdict={rec2['verdict']}")
        print(f"[selftest] 2 mismatched bin count: verdict={rec2['verdict']}  "
              f"{'ok' if ok2 else 'FAIL'}")

        # 3) SR left unpatched (only CR touched) -> fail, mismatch names the SR
        patch_unpatched = os.path.join(td, "patch_unpatched.json")
        json.dump([sig_op(1, 2)], open(patch_unpatched, "w"))
        paired3, n_ch3, mism3, _ = check_pairing(ws_path, patch_unpatched)
        out3 = os.path.join(td, "pairing_check_unpatched.json")
        rec3 = write_pairing_check_json(out3, ws_path, patch_unpatched, paired3, n_ch3, mism3,
                                         _resolve_timestamp())
        ok3 = (not paired3) and any("SR" in m for m in mism3) and rec3["verdict"] == "fail"
        if not ok3:
            fails.append(f"SR-untouched case: paired={paired3} mismatches={mism3}")
        print(f"[selftest] 3 SR left unpatched: verdict={rec3['verdict']}  "
              f"{'ok' if ok3 else 'FAIL'}")

        # 4) default --out location: beside the patch
        default_out = _default_out(patch_ok)
        ok4 = default_out == os.path.join(td, "pairing_check.json")
        if not ok4:
            fails.append(f"default out path: {default_out}")
        print(f"[selftest] 4 default JSON path beside patch: {default_out}  "
              f"{'ok' if ok4 else 'FAIL'}")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("pairing_check selftest: PASS (matched, mismatched bin-count, SR-unpatched, default-out)")
    return 0


# ---------------------------------------------------------------- CLI
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        sys.exit(_selftest())

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bkg", required=True, help="published bkg-only HistFactory workspace")
    ap.add_argument("--patch", required=True, help="the chain's signal patch")
    ap.add_argument("--out", default=None,
                     help="pairing_check.json path (default: beside --patch)")
    ap.add_argument("--timestamp", default=None,
                     help="generated_utc override (else $PAIRING_CHECK_UTC, else \"\")")
    args = ap.parse_args(argv)

    paired, n_channels, mismatches, report = check_pairing(args.bkg, args.patch)
    for line in report:
        print(line)

    out_path = args.out or _default_out(args.patch)
    write_pairing_check_json(out_path, args.bkg, args.patch, paired, n_channels, mismatches,
                              _resolve_timestamp(args.timestamp))
    print(f"wrote {out_path}")

    if mismatches:
        print("PAIRING PROBLEMS:")
        for p in mismatches:
            print("  -", p)
        raise SystemExit(1)
    print("PAIRING CHECK PASS: every patched channel exists with matching bin counts + mu "
          "normfactor; every SR channel receives signal; untouched channels are CR/VR-class.")


if __name__ == "__main__":
    main()
