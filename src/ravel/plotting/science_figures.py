"""Diagnostic figures from declared scientific quantities, with no hidden scaling."""
from pathlib import Path
import math
from ravel.workflow.state_io import read_json, atomic_json


def render(spec, result, base, output):
    """Always preserve numerical results; return an explicit optional figure status."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return {'status':'unavailable','reason':'Install ravel-hep[science] for PDF/PNG diagnostics','files':[]}
    from ravel.plotting import mplhep_style as house
    house.apply_style('ATLAS')
    out = Path(output)
    plots = []
    coordinates = {}
    mode, task = spec['mode'], spec['task']
    if mode == 'quantities':
        q = result['quantities']; c = q['contract'] if 'contract' in q else read_json(Path(base)/task['contract'])
        n = len(c['bins'])
        series=[]
        for k,w in enumerate(c['weight_names']):
            series.append((w,q['values'][w],[math.sqrt(max(0,q['covariance'][k*n+i][k*n+i])) for i in range(n)]))
        plots.append(('quantities', [b['id'] for b in c['bins']], series, q['unit'], 'Declared bin ID (see bin edges in quantities.json)'))
        if len(c['axes']) == 1:
            coordinates['quantities'] = (c['bins'], c['axes'][0])
    elif mode == 'analyze' and task['backend'] == 'rivet':
        q = read_json(out/'observables.json')
        for i,(path,obj) in enumerate(q['observables'].items()):
            bins=obj['bins']; c=obj['contract']
            labels=[str(j+1) for j in range(len(bins))]
            plots.append((f'observable-{i+1}',labels,[(path,[b['value'] for b in bins],[[b['error_low'] for b in bins],[b['error_high'] for b in bins]])],c['unit'],'Bin index (ordered edges in observables.json)'))
            if len(c['axes']) == 1:
                coordinates[f'observable-{i+1}'] = (bins, c['axes'][0])
    elif mode == 'analyze' and 'yields' in result:
        plots.append(('regions',result['region_names'],[(w,v,[math.sqrt(result['covariance'][w][i][i]) for i in range(len(v))]) for w,v in result['yields'].items()],
                      'Input weight / region','Region (overlap is retained, not combined)'))
    elif mode == 'measurement':
        model=read_json(Path(base)/task['input']); ids=result['bin_ids']
        def vector(key):
            r=model[key]; return [r['values'][r['bin_ids'].index(i)] for i in ids]
        cov=model['experimental_covariance']; idx=[cov['bin_ids'].index(i) for i in ids]
        dataerr=[math.sqrt(cov['matrix'][j][j]) for j in idx]
        sm,signal=vector('sm'),vector('signal')
        plots.append(('measurement',ids,[('Supplied measurement',vector('data'),dataerr),('Supplied SM',sm,None),
                      ('SM + tested signal',[s+task['signal_strength']*v for s,v in zip(sm,signal)],None)],result['unit'],'Declared measurement bin ID'))
        if len(model['quantity']['axes']) == 1:
            lookup={b['id']:b for b in model['quantity']['bins']}
            coordinates['measurement'] = ([lookup[i] for i in ids],model['quantity']['axes'][0])
    receipts=[]
    for name,labels,series,unit,xlabel in plots:
        ratio = None
        if mode == 'measurement':
            fig,(ax,ratio)=plt.subplots(2,1,figsize=(9,7.2),sharex=True,gridspec_kw={'height_ratios':[3,1]})
        else:
            fig,ax=plt.subplots(figsize=(9,5.8))
        xpos, xerr = list(range(len(labels))), None
        if name in coordinates:
            bins, axis = coordinates[name]
            xpos=[(b['low'][0]+b['high'][0])/2 for b in bins]
            xerr=[(b['high'][0]-b['low'][0])/2 for b in bins]
            xlabel=axis['name']+' ['+axis['unit']+']'
        for si,(label,values,errors) in enumerate(series):
            if len(values)!=len(labels) or any(not math.isfinite(x) for x in values):
                raise ValueError('nonfinite or misaligned figure quantities')
            color='black' if mode=='measurement' and si==0 else ('#0072B2','#D55E00','#009E73')[si%3]
            ax.errorbar(xpos,values,xerr=xerr,yerr=errors,fmt='o' if errors is not None else 's',ms=4,capsize=2,label=label,color=color)
            if ratio is not None and si != 1:
                denominators=series[1][1]
                rv=[v/s if s!=0 else float('nan') for v,s in zip(values,denominators)]
                re=[e/abs(s) if s!=0 else float('nan') for e,s in zip(errors,denominators)] if errors is not None else None
                ratio.errorbar(xpos,rv,xerr=xerr,yerr=re,fmt='o' if errors is not None else 's',ms=3,capsize=2,color=color)
        if ratio is not None:
            ratio.axhline(1,color='0.4',linewidth=1)
            ratio.set_ylabel('Ratio to SM',fontsize=15)
            house.tick_hygiene(ratio)
            from matplotlib.ticker import MaxNLocator
            ratio.yaxis.set_major_locator(MaxNLocator(3))
            ratio.tick_params(axis='y',labelsize=12)
            if any(s==0 for s in series[1][1]):
                ratio.set_ylabel('Ratio to SM\n(gaps at SM=0)',fontsize=12)
            if 'theory_covariance' in model:
                tc=model['theory_covariance'];ti=[tc['bin_ids'].index(i) for i in ids]
                terr=[math.sqrt(tc['matrix'][j][j]) for j in ti]
                for j,(x,y,e) in enumerate(zip(xpos,series[1][1],terr)):
                    half=xerr[j] if xerr is not None else .45
                    ax.fill_between([x-half,x+half],[y-e]*2,[y+e]*2,color='0.7',alpha=.35,hatch='///',label='Supplied prediction uncertainty' if j==0 else None)
                    if y!=0:ratio.fill_between([x-half,x+half],[1-e/abs(y)]*2,[1+e/abs(y)]*2,color='0.7',alpha=.35,hatch='///')
        stride=max(1,math.ceil(len(labels)/12))
        if name not in coordinates:
            (ratio if ratio is not None else ax).set_xticks(list(range(0,len(labels),stride)),labels[::stride],rotation=30 if any(len(x)>8 for x in labels) else 0,ha='right' if any(len(x)>8 for x in labels) else 'center')
        (ratio if ratio is not None else ax).set_xlabel(xlabel)
        ax.set_ylabel(unit); ax.axhline(0,color='0.6',linewidth=.7)
        # This is not an experiment's official result. Keep labels outside data.
        fig.suptitle('RAVEL supplied-input diagnostic',fontsize=14)
        if ratio is not None:
            fig.legend(*ax.get_legend_handles_labels(),loc='lower center',bbox_to_anchor=(.5,.01),fontsize=8,ncol=1)
        else:
            ax.legend(loc='upper center',bbox_to_anchor=(.5,-.24),fontsize=8,ncol=1)
        house.tick_hygiene(ax)
        fig.subplots_adjust(bottom=.30 if ratio is not None else .35,top=.9,hspace=.10)
        failures=house.lint_figure(fig)
        if failures:
            plt.close(fig)
            raise ValueError('scientific figure layout failed: '+'; '.join(failures))
        for ext in ('pdf','png'):
            fig.savefig(out/f'{name}.{ext}',dpi=220,bbox_inches='tight')
        plt.close(fig)
        receipts.append({'stem':name,'files':[name+'.pdf',name+'.png'],'plot_lint':'PASS','png_dpi':220,
                         'normalization':'No plot-time normalization or clipping; values and uncertainties read from artifacts'})
    return {'status':'passed' if receipts else 'not_applicable','figures':receipts,
            'scope':'Quantity diagnostics, not a published-reference closure figure; full covariance remains in machine artifacts'}
