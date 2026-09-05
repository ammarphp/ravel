#!/usr/bin/env python3
"""cr005_validate -- per-routine ORACLE validation for the native SA backend (CR-005 S6).

Given a run dir whose native chain produced output/analysis/Delphes2SA.root, this: (1) runs the
CONTAINER SimpleAnalysis for the routine on that exact input (`mapyde run simpleanalysis` on a
derived TOML with [simpleanalysis].name switched), (2) diffs the container's per-SR integer
`events` column against the NATIVE <Routine>.txt (produced by native_simpleanalysis.py or
native_sa_generic.py --emit-container-txt), (3) prints a per-SR verdict table + BIT-FOR-BIT
verdict. The flagship's own acceptance bar, mechanized.

  cr005_validate.py --rundir <dir> --config <toml-rel> --routine <Name> --native-txt <path>

Requires the podman machine up + the SA image pulled (framework/CR005-NATIVE-SA-GENERALIZATION.md
§4; teardown after). Exit 0 = bit-for-bit; 1 = any SR differs; 2 = usage/infra.
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

from ravel.paths import native_build_root

import argparse
import os
import subprocess
import sys

BUILD = str(native_build_root())


def read_txt(path):
    """<Routine>.txt -> {SR: int events} (skips the All row; keeps its numbers for the report)."""
    rows, allrow = {}, None
    with open(path) as f:
        header = f.readline()
        for line in f:
            p = line.strip().split(",")
            if len(p) < 4:
                continue
            if p[0] == "All":
                allrow = p
                continue
            rows[p[0]] = int(p[1])
    return rows, allrow


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--config", required=True, help="mapyde TOML path relative to rundir")
    ap.add_argument("--routine", required=True)
    ap.add_argument("--native-txt", required=True)
    ap.add_argument("--keep-toml", action="store_true")
    args = ap.parse_args()

    rundir = os.path.abspath(args.rundir)
    cfg = os.path.join(rundir, args.config)
    if not os.path.exists(os.path.join(rundir, "output", "analysis", "Delphes2SA.root")):
        sys.exit("cr005_validate: no output/analysis/Delphes2SA.root in the rundir (run the "
                 "native chain through the analysis stage first)")
    if not os.path.exists(args.native_txt):
        sys.exit(f"cr005_validate: native txt not found: {args.native_txt}")

    # derive a validation TOML with the routine name switched (keyed line edit, never sed)
    lines = open(cfg).read().splitlines()
    out_lines, in_sa = [], False
    for l in lines:
        s = l.strip()
        if s.startswith("["):
            in_sa = (s == "[simpleanalysis]")
        if in_sa and s.startswith("name "):
            l = f'name = "{args.routine}"'
        if in_sa and s.startswith("skip "):
            l = "skip = false"
        if in_sa and s.startswith("outputtag"):
            l = 'outputtag = "_oracle"'   # container writes <Routine>_oracle.* — NEVER clobbers
        out_lines.append(l)              # the native <Routine>.txt at the same path (learned the
                                         # hard way on the flagship anchor run)
    vcfg = os.path.join(rundir, os.path.dirname(args.config),
                        f"cr005_validate_{args.routine}.toml")
    open(vcfg, "w").write("\n".join(out_lines) + "\n")

    # container SA via mapyde (pipeline env; podman machine must be up)
    conda = os.path.join(BUILD, "tools/miniforge3/bin/conda")
    env = dict(os.environ)
    tools = os.path.join(BUILD, "tools")
    env["CONTAINERS_HELPER_BINARY_DIR"] = os.path.join(tools, "miniforge3/envs/pipeline/bin")
    env["PATH"] = (os.path.join(tools, "podman-native/bin-wrap") + os.pathsep +
                   os.path.join(tools, "miniforge3/envs/pipeline/bin") + os.pathsep + env["PATH"])
    print(f"[oracle] mapyde run simpleanalysis {os.path.relpath(vcfg, rundir)} (in {rundir})")
    p = subprocess.run([conda, "run", "-n", "pipeline", "mapyde", "run", "simpleanalysis",
                        os.path.relpath(vcfg, rundir)],   # mapyde resolves configs vs its cwd
                       cwd=rundir, env=env, capture_output=True, text=True)
    logp = os.path.join(rundir, "logs", f"cr005_oracle_{args.routine}.log")
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    open(logp, "w").write(p.stdout + "\n--- stderr ---\n" + p.stderr)
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()[-4:]
        sys.exit("cr005_validate: container SA failed rc=%d (%s) — see %s"
                 % (p.returncode, " | ".join(tail), logp))

    # locate the container output txt
    cand = []
    for root, _dirs, files in os.walk(os.path.join(rundir, "output")):
        for f in files:
            if f == f"{args.routine}_oracle.txt":
                cand.append(os.path.join(root, f))
    if not cand:
        sys.exit(f"cr005_validate: container produced no {args.routine}_oracle.txt under "
                 f"output/ — see {logp}")
    ctxt = max(cand, key=os.path.getmtime)
    print(f"[oracle] container txt: {os.path.relpath(ctxt, rundir)}")

    nat, nat_all = read_txt(args.native_txt)
    con, con_all = read_txt(ctxt)
    srs = sorted(set(nat) | set(con))
    diffs = []
    for sr in srs:
        a, b = nat.get(sr), con.get(sr)
        if a != b:
            diffs.append((sr, a, b))
    n_nonzero = sum(1 for sr in srs if (con.get(sr) or 0) > 0)
    print(f"\nCR-005 ORACLE DIFF — routine {args.routine}: {len(srs)} SRs compared, "
          f"{n_nonzero} occupied in the container reference")
    if diffs:
        print(f"  BIT-FOR-BIT: FAIL — {len(diffs)} SR(s) differ (native vs container):")
        for sr, a, b in diffs[:20]:
            print(f"    {sr:24s} native={a} container={b}")
        sys.exit(1)
    print(f"  BIT-FOR-BIT: PASS — {len(srs)}/{len(srs)} SRs identical "
          f"(All row: native {nat_all} | container {con_all})")
    if not args.keep_toml:
        os.remove(vcfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
