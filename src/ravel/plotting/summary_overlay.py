#!/usr/bin/env python
"""Render supplied limit curves on a declared common comparison basis.

The manifest supplies curves, provenance, gaps and display disposition.
Supply experiment, beam energy, luminosity and output destination."""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.plotting"

import argparse
import json
import math
import os
import sys

import numpy as np




def _draw_manifest(ax, man, *, logy=True):
    """One source of plotting primitives for legacy and multisource summary figures."""
    from types import SimpleNamespace
    from . import mplhep_style as house
    args=SimpleNamespace(logy=logy)
    tgt = man["target_basis"]
    curves = [c for c in man["curves"]
              if c.get("resolved", {}).get("mass_gev") and c.get("draw", "primary") != "none"]
    dropped = [c for c in man["curves"]
               if not c.get("resolved") or c.get("draw", "primary") == "none"]
    if not curves and not man.get("coverage_gaps"):
        raise ValueError("summary overlay needs resolved curves or an explicit coverage-only window")
    rendered_series = []
    def display_kwargs(masses, values, kind):
        window=man.get('window_gev')
        def in_window(mass):
            if not window:
                return True
            return window[0] <= mass and (mass <= window[1] if
                man.get('window_upper_inclusive', True) else mass < window[1])
        available=[mass for mass,value in zip(masses,values) if value is not None and in_window(mass)]
        # One source point within the requested window is a point, not an invented curve.
        return {'linestyle':'None','marker':'o' if kind=='obs' else 's'} if len(available)==1 else {}
    colors = list(house.OKABE_ITO.values())
    color_i = 0
    for c in curves:
        r = c["resolved"]
        m = np.asarray(r["mass_gev"], float)
        draw = c.get("draw", "primary")
        prov_suffix = " (digitized)" if c.get("provenance") == "digitized" else ""
        if draw == "crosscheck":
            # faint dashed grey -- present for comparison, never co-equal with a primary curve
            col, alpha = "0.55", 0.75
            obs_ls, exp_ls, lw_obs, lw_exp = "--", ":", 1.4, 1.1
        else:
            col, alpha = colors[color_i % len(colors)], 1.0
            obs_ls, exp_ls, lw_obs, lw_exp = "-", "--", 2.2, 1.6
            color_i += 1
        if r.get("obs") and any(v is not None for v in r["obs"]):
            rendered_series.append({"survey_id":c.get("survey_id"),"kind":"obs","available_points":sum(v is not None for v in r["obs"])})
            obs = np.asarray([v if v is not None else np.nan for v in r["obs"]], float)
            options=display_kwargs(m,r["obs"],"obs")
            ax.plot(m, obs, **({"linestyle":obs_ls,**options}), color=col, lw=lw_obs, alpha=alpha,
                    label=f"{c['source']}{prov_suffix} obs. ({c.get('lumi_fb', '?')} fb$^{{-1}}$)")
        if r.get("exp") and any(v is not None for v in r["exp"]):
            rendered_series.append({"survey_id":c.get("survey_id"),"kind":"exp","available_points":sum(v is not None for v in r["exp"])})
            exp = np.asarray([v if v is not None else np.nan for v in r["exp"]], float)
            options=display_kwargs(m,r["exp"],"exp")
            ax.plot(m, exp, **({"linestyle":exp_ls,**options}), color=col, lw=lw_exp, alpha=alpha,
                    label=f"{c['source']}{prov_suffix} exp.")
        if r.get("theory") and any(v is not None for v in r["theory"]):
            rendered_series.append({"survey_id":c.get("survey_id"),"kind":"theory","available_points":sum(v is not None for v in r["theory"])})
            th = np.asarray([v if v is not None else np.nan for v in r["theory"]], float)
            ax.plot(m, th, ":", color="0.25", lw=2.0, label=r.get("theory_label", "theory"))

    win = man.get("window_gev")
    if win:
        ax.set_xlim(win)
    for g in man.get("coverage_gaps", []):
        lo = g.get("lo_gev", ax.get_xlim()[0])
        hi = g.get("hi_gev", ax.get_xlim()[1])
        ax.axvspan(lo, hi, color="0.85", alpha=0.6, zorder=0)
        ax.text(0.5 * (lo + hi), 0.965, g.get("note", "no published limit"),
                transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=9.5,
                color="0.25", rotation=90 if (hi - lo) < 0.12 * (ax.get_xlim()[1] -
                                                                 ax.get_xlim()[0]) else 0)
    if args.logy:
        ax.set_yscale("log")
    ax.set_xlabel(tgt.get("x_label", r"$m$ [GeV]"))
    ax.set_ylabel(tgt.get("quantity", "95% CL UL"))
    # Full source/provenance labels can span every inside corner. Keep them
    # outside the data axes; tight saving includes the complete legend.
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(1.03, 1.0),
                  bbox_transform=ax.transAxes, fontsize=10.5)
    lines = [f"target basis: {tgt.get('quantity', '?')}",
             f"{tgt.get('model', '')}",
             f"{len(curves)} published limit set(s), re-expressed on one basis",
             "published limits only — no new limit derived here"]
    if dropped:
        lines.append(f"{len(dropped)} candidate(s) dropped: see manifest reasons")
    lines.extend(man.get('annotations', []))
    house.smart_annotate(ax, [l for l in lines if l], fontsize=9.5)
    house.tick_hygiene(ax, axr=None, logy=args.logy, logx=False)
    return {"series":rendered_series,"drawn_curves":len(curves),"coverage_gaps":man.get("coverage_gaps",[])}


def render_manifest(man, out, *, experiment, com, lumi, logy=True, allow_lint=False):
    """Diagnostic legacy rendering; publication qualification requires the typed figure route."""
    if not isinstance(experiment,str) or not experiment.strip():raise ValueError('explicit experiment required')
    if not isinstance(com,(int,float)) or isinstance(com,bool) or not math.isfinite(com) or com<=0:raise ValueError('positive explicit energy required')
    if type(lumi) not in (int,float) or not math.isfinite(lumi) or lumi<=0:raise ValueError('positive explicit luminosity required')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from . import mplhep_style as house
    hep=house.apply_style(experiment)
    fig,ax=plt.subplots(figsize=(9,6.5))
    try:
        report=_draw_manifest(ax,man,logy=logy)
        header_error=None
        try:
            if hep is None or experiment not in ('ATLAS','CMS'):
                raise ValueError('single-experiment header unavailable')
            getattr(hep,experiment.lower()).label(ax=ax,data=True,text='',com=com,lumi=lumi,loc=0)
        except Exception as exc:
            header_error=str(exc)
        house.enforce_lint(fig,where=os.path.basename(out),allow=allow_lint)
        for ext in ('.png','.pdf'):fig.savefig(out+ext,dpi=200,bbox_inches='tight')
        return {**report,'files':[os.path.basename(out)+'.png',os.path.basename(out)+'.pdf'],
                'plot_lint':'bypassed' if allow_lint else 'passed',
                'publication_contract_satisfied':False,'mplhep_loaded':hep is not None,
                'header_error':header_error,'figure_class':'diagnostic-unqualified-summary'}
    finally:plt.close(fig)


def render_summary_panels(panels, target, out):
    """Existing summary primitives plus required figure-class/house publication contract."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from . import mplhep_style as house
    from .figure_manifest import summary_recipe
    summary_recipe(target['figure_class'])
    definitions=target['panels']
    experiments=target['request']['experiments']
    # Collaboration house typography, with an explicitly mixed-source header.
    # This is a summary of published results, not a collaboration-branded new limit.
    hep=house.apply_style(house.house_style_for(experiments),required=True)
    fig,axs=plt.subplots(len(definitions),1,figsize=(9,6.5*len(definitions)),squeeze=False)
    axes=list(axs[:,0]);reports=[]
    try:
        for ax,definition in zip(axes,definitions):
            loaded=panels[definition['id']]
            report=_draw_manifest(ax,loaded['render_manifest'],logy=definition['axes']['y']=='log')
            ax.set_xlabel(definition['axes']['x_label']);ax.set_ylabel(definition['axes']['y_label'])
            ax.set_title(definition['caption'],loc='left',fontsize=11)
            house.publication_axes(ax)
            reports.append({'id':definition['id'],**report})
        fig.subplots_adjust(top=.91,hspace=.45)
        headers=[fig.text(.12,.985,' and '.join(experiments)+' published results',ha='left',va='top',weight='bold',style='italic'),
                 fig.text(.12,.955,'; '.join(f"sqrt(s) = {e:g} TeV" for e in sorted({p['model_basis']['energy_tev'] for p in definitions})),ha='left',va='top')]
        evidence=house.publication_evidence(fig,axes,headers,hep=hep,experiments=experiments,
                    energies=[p['model_basis']['energy_tev'] for p in definitions])
        # Lint remains a distinct geometric gate; it cannot substitute for style/task evidence.
        house.enforce_lint(fig,where=os.path.basename(out),allow=False)
        evidence['geometric_lint']='passed'
        for ext in ('.png','.pdf'):fig.savefig(out+ext,dpi=200,bbox_inches='tight')
        import hashlib
        from pathlib import Path
        from ravel.physics.source_tables import bounded_read
        output_pins=[]
        for ext in ('.png','.pdf'):
            path=Path(out+ext);raw=bounded_read(path,limit=16*1024*1024)
            output_pins.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)})
        return {'panels':reports,'publication_evidence':evidence,'output_pins':output_pins,
                'files':[os.path.basename(out)+'.png',os.path.basename(out)+'.pdf']}
    finally:plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--logy", action="store_true", default=True)
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--com", type=float, required=True)
    ap.add_argument("--lumi", type=float, required=True)
    ap.add_argument("--no-lint", action="store_true")
    args = ap.parse_args(argv)
    with open(args.manifest) as stream:
        man = json.load(stream)
    return render_manifest(man,args.out,experiment=args.experiment,com=args.com,lumi=args.lumi,logy=args.logy,allow_lint=args.no_lint)


if __name__ == "__main__":
    main()
