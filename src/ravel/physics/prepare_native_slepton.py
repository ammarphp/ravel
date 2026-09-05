#!/usr/bin/env python
"""Materialize the NATIVE-pipeline inputs for ONE slepton-bino model point.

The driver-gap closer: run-pipeline-native.sh expects a run dir with output/run.mg5 +
output/shower.cfg + the cards already present. This writes them from just the point's
masses, so scan_orchestrator can drive a grid of native points end-to-end.

The ONLY per-point difference for a slepton-bino scan is the param-card masses: the base
SleptonBino.slha has literal {{MSLEP}}/{{MN1}} placeholders (6 + 1) and explicit BR=1 decay
rows (slepton -> chi10 + lepton), so no width-only decay trap. The MadGraph process block
(p p > chsleptons chsleptons j / susystrong @1) is mass-independent -> a fixed template.

Writes into <rundir>/output/:
  param_card.dat   (SleptonBino.slha rendered with MSLEP=m_parent, MN1=m_lsp)
  run_card.dat     (mapyde default_LO.dat, keyed-edited: the TOML's [madgraph.run.options]
                    block FIRST (ptj1min=50 etc., fail-loud on unmatched keys -- CR-002: dropping
                    it silently generated at ptj1min=0, a x2.14 sigma_tag drift), then nevents,
                    iseed, pdlabel=cteq6l1, use_syst=False -- cteq6l1 is MadGraph-internal so no
                    LHAPDF needed; acc x eff is cross-section-independent so the PDF set does not
                    bias the cert)
  pythia_card.dat  (copied; unused by pythia_shower but kept for provenance)
  run.mg5          (the slepton process template + native `output output/PROC_madgraph`,
                    shower=OFF -- native pythia_shower runs separately -- and the rendered cards)
  shower.cfg       (Beams:frameType=4 + Beams:LHEF=<abs LHE> + Monash default, per
                    docs/workflow/reference/shower-config-template.cfg)

Usage:
  prepare_native_slepton.py --rundir <abs> --m-parent 150 --m-lsp 140 [--nevents 50000] [--seed 0]
See docs/workflow/steps/08-scan.md.
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse
import os
import re
import shutil
import sys

from ..paths import native_build_root, package_data_path
MSHARE = str(native_build_root() / "tools/miniforge3/envs/pipeline/share/mapyde")
BASE_PARAM = f"{MSHARE}/cards/param/SleptonBino.slha"
BASE_RUNCARD = f"{MSHARE}/cards/run/default_LO.dat"
BASE_PYTHIA = f"{MSHARE}/cards/pythia/pythia8_card.dat"
GEN_TEMPLATE = str(package_data_path("templates", "slepton_isrslep_generate.mg5"))


def die(m):
    sys.exit(f"prepare_native_slepton: {m}")


def render_param(m_parent, m_lsp, out):
    if not os.path.exists(BASE_PARAM):
        die(f"base param card not found: {BASE_PARAM}")
    txt = open(BASE_PARAM).read()
    if "{{MSLEP}}" not in txt or "{{MN1}}" not in txt:
        die("base SleptonBino.slha lost its {{MSLEP}}/{{MN1}} placeholders")
    txt = txt.replace("{{MSLEP}}", f"{m_parent:g}").replace("{{MN1}}", f"{m_lsp:g}")
    open(out, "w").write(txt)


def read_run_options(toml_path):
    """The mapyde TOML's [madgraph.run.options] block (CR-002: it MUST be applied).

    The container path (mapyde) applies this block when it renders the run card; the native
    prep originally did not, so native samples generated at ptj1min=0 instead of 50 — a ×2.14
    tag-definition σ drift vs the reference sample (FAILURE-CATALOGUE B2). Fail-loud on a
    missing file or a missing block: silently generating without the options is the bug.
    """
    if not os.path.exists(toml_path):
        die(f"run-options TOML not found: {toml_path} (CR-002: refusing to guess)")
    import tomllib
    with open(toml_path, "rb") as fh:
        cfg = tomllib.load(fh)
    try:
        return cfg["madgraph"]["run"]["options"]
    except KeyError:
        die(f"no [madgraph.run.options] block in {toml_path} (CR-002: refusing to guess)")


def render_runcard(nevents, seed, out, run_options, pdf="cteq6l1"):
    if not os.path.exists(BASE_RUNCARD):
        die(f"base run card not found: {BASE_RUNCARD}")
    lines = open(BASE_RUNCARD).read().splitlines()
    # keyed line edits (never a greedy sed -- .claude/rules/madgraph-pythia.md)
    def setkey(key, val):
        for i, l in enumerate(lines):
            if re.search(rf"=\s*{re.escape(key)}\b", l):
                indent = l[: len(l) - len(l.lstrip())]
                lines[i] = f"{indent}  {val}  = {key}"
                return True
        return False
    # CR-002: apply the [madgraph.run.options] block FIRST, fail-loud on any unmatched key —
    # dropping it silently generated at ptj1min=0 (×2.14 σ_tag drift vs the container reference).
    for k, v in run_options.items():
        val = ("True" if v else "False") if isinstance(v, bool) else str(v)
        if not setkey(k, val):
            die(f"[madgraph.run.options] key '{k}' has no matching run-card line -- "
                f"the template changed; add an explicit rule for it (CR-002 fail-loud)")
    setkey("nevents", f"{int(nevents)}")
    setkey("iseed", f"{int(seed)}")
    setkey("ebeam1", "6500.0")   # {{ecms}} -> per-beam energy (sqrt(s)=13 TeV)
    setkey("ebeam2", "6500.0")
    if pdf == "cteq6l1":                       # MadGraph-internal PDF (the pre-CR-004 baseline)
        setkey("pdlabel", "cteq6l1")
    elif pdf == "nn23nlo":                     # CR-004 basis: MG-INTERNAL NNPDF2.3 NLO — no
        setkey("pdlabel", "nn23nlo")           # LHAPDF linking (the arm64 gensym link vs conda
                                               # libLHAPDF is a recorded blocker; see CR-004 note)
    elif pdf == "nnpdf30":                     # LHAPDF NNPDF30_nlo (lhaid 260000): BLOCKED on this
        if not setkey("pdlabel", "lhapdf") or not setkey("lhaid", "260000"):
            die("run-card template lacks a pdlabel/lhaid line -- cannot set the LHAPDF basis "
                "(same silent-drop class as CR-002; refusing)")
    else:
        die(f"unknown --pdf '{pdf}' (cteq6l1|nnpdf30)")
    setkey("use_syst", "False")
    rendered = "\n".join(lines) + "\n"
    # fail-loud: no un-rendered jinja placeholder may reach MadGraph (it crashes with
    # "{{X}} can not be mapped to a float" -- the bug a live scan run surfaced).
    if "{{" in rendered:
        leftover = sorted(set(re.findall(r"\{\{[^}]+\}\}", rendered)))
        die(f"run card still has unrendered placeholder(s) {leftover} -- add a setkey() for each")
    open(out, "w").write(rendered)


def write_run_mg5(rundir, param_path, runcard_path, seed, out):
    if not os.path.exists(GEN_TEMPLATE):
        die(f"process template not found: {GEN_TEMPLATE} (head -42 of a slepton run.mg5)")
    gen = open(GEN_TEMPLATE).read().rstrip()
    body = f"""{gen}
output output/PROC_madgraph

set run_mode 2
set nb_core 4
launch output/PROC_madgraph
madspin=OFF
shower=OFF
reweight=OFF

{param_path}
{runcard_path}
set iseed {int(seed)}
done
"""
    open(out, "w").write(body)


def write_shower_cfg(rundir, out):
    lhe = f"{rundir}/output/PROC_madgraph/Events/run_01/unweighted_events.lhe"
    open(out, "w").write(
        "! native pythia_shower config (Monash 2013 default = the mapyde container shower)\n"
        "! per docs/workflow/reference/shower-config-template.cfg\n"
        "Beams:frameType = 4\n"
        f"Beams:LHEF = {lhe}\n"
        "Print:quiet = on\n"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rundir", required=True, help="absolute run dir")
    ap.add_argument("--m-parent", type=float, required=True, help="slepton mass (GeV)")
    ap.add_argument("--m-lsp", type=float, required=True, help="bino LSP mass (GeV)")
    ap.add_argument("--nevents", type=int, default=50000)
    ap.add_argument("--pdf", choices=["cteq6l1", "nn23nlo", "nnpdf30"], default="cteq6l1",
                    help="proton PDF: cteq6l1 (MG-internal, the record-scan baseline) or "
                         "nnpdf30 (LHAPDF lhaid=260000 — the CR-004 rescan basis; requires "
                         "lhapdf in the mg5 env + the set installed)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--toml", default=f"{MSHARE}/templates/sleptons.toml",
                    help="mapyde TOML whose [madgraph.run.options] block is applied to the run "
                         "card (CR-002); the orchestrator passes the point's own config TOML")
    args = ap.parse_args()

    rundir = os.path.abspath(args.rundir)
    if args.m_lsp >= args.m_parent:
        die(f"m_lsp ({args.m_lsp}) must be < m_parent ({args.m_parent}) -- kinematically forbidden")
    outdir = os.path.join(rundir, "output")
    os.makedirs(outdir, exist_ok=True)

    run_options = read_run_options(args.toml)
    print(f"applying [madgraph.run.options] from {args.toml}: "
          f"{', '.join(f'{k}={v}' for k, v in run_options.items())}")
    render_param(args.m_parent, args.m_lsp, os.path.join(outdir, "param_card.dat"))
    render_runcard(args.nevents, args.seed, os.path.join(outdir, "run_card.dat"), run_options,
                   pdf=args.pdf)
    if os.path.exists(BASE_PYTHIA):
        shutil.copy(BASE_PYTHIA, os.path.join(outdir, "pythia_card.dat"))
    write_run_mg5(rundir, os.path.join(outdir, "param_card.dat"),
                  os.path.join(outdir, "run_card.dat"), args.seed,
                  os.path.join(outdir, "run.mg5"))
    write_shower_cfg(rundir, os.path.join(outdir, "shower.cfg"))
    print(f"prepared native inputs for slepton ({args.m_parent:g},{args.m_lsp:g}) "
          f"Δm={args.m_parent-args.m_lsp:g}, nevents={args.nevents} -> {outdir}/")
    for f in ("param_card.dat", "run_card.dat", "run.mg5", "shower.cfg"):
        print(f"  output/{f}")


if __name__ == "__main__":
    main()
