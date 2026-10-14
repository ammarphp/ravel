"""Diagnostic figures from declared scientific quantities, with no hidden scaling."""
from pathlib import Path
import math
from ravel.workflow.state_io import read_json, atomic_json
from .display_labels import display_label, axis_label, unit_label


def _iris_figures(result, output):
    """Source-unqualified histogram delivery through the ordinary house route."""
    from ravel.physics.dataset_query_quantities import write_report
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    delivery=result.get('delivery')
    tables=write_report(result,out)
    if result.get('status')!='passed' or delivery is None:
        return {'status':'unavailable','figures':[],'tables':tables,'reason':'No complete passed native quantity delivery to plot'}
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise ValueError('Required IRIS histogram delivery needs Matplotlib and mplhep house runtime') from error
    from ravel.plotting import mplhep_style as house
    house.apply_style('ATLAS',required=True)
    receipts=[];plot_data=[]
    from ravel.physics.dataset_query_quantities_core import presentation
    selected=presentation({'plot_kind':delivery.get('plot_kind'),'formats':delivery.get('plot_formats')},
                          components=delivery.get('dataset_components') is not None)
    kind=selected['plot_kind']
    if kind=='none':return {'status':'passed','figures':[],'tables':tables,'scope':'Supplied table-only columnar delivery'}
    stack=kind=='dataset_stack'
    components=delivery.get('dataset_components')
    if stack and (components is None or not components['did_order']):
        raise ValueError('Dataset stack requires every declared component contribution')
    for oi,(name,q) in enumerate(delivery['observables'].items()):
        c=q['contract'];bins=c['bins'];weights=c['weight_names'];n=len(bins)
        if len(c['axes'])!=1:raise ValueError('Columnar histogram delivery requires an explicit one-dimensional axis')
        xpos=[(b['low'][0]+b['high'][0])/2 for b in bins]
        widths=[b['high'][0]-b['low'][0] for b in bins]
        if any(not math.isfinite(v) or v<=0 for v in widths):raise ValueError('Finite positive histogram bin widths required')
        panels=[[w] for w in weights] if stack else [weights]
        for pi,panel in enumerate(panels):
            fig,ax=plt.subplots(figsize=(9,5.8));series=[]
            try:
                for weight in panel:
                    k=weights.index(weight);values=q['values'][weight]
                    errors=[math.sqrt(q['covariance'][k*n+i][k*n+i]) for i in range(n)]
                    if len(values)!=n or any(not math.isfinite(v) for v in (*values,*errors)):
                        raise ValueError('Finite complete values and declared marginal errors required')
                    if stack:
                        row=components['observables'][name]
                        if row['unit']!=q['unit'] or row['normalization']!=c['normalization']:
                            raise ValueError('DID stack and full histogram normalization differ')
                        positive=[0.]*n;negative=[0.]*n;content=[]
                        for di,did in enumerate(components['did_order']):
                            values_part=row['values'][did][weight]
                            if len(values_part)!=n or any(not math.isfinite(v) for v in values_part):
                                raise ValueError('Finite complete DID component values required')
                            bottom=[positive[i] if v>=0 else negative[i] for i,v in enumerate(values_part)]
                            ax.bar(xpos,values_part,width=widths,bottom=bottom,align='center',color=house.STACK_CYCLE[di%len(house.STACK_CYCLE)],edgecolor='black',linewidth=.4,label=display_label(did, (delivery.get('display_labels') or {}).get(did, 'Dataset '+str(di+1))))
                            for i,v in enumerate(values_part):
                                if v>=0:positive[i]+=v
                                else:negative[i]+=v
                            content.append({'did':did,'values':values_part})
                        ax.errorbar(xpos,values,xerr=[v/2 for v in widths],yerr=errors,fmt='o',color='black',ms=3,label=display_label(weight)+' total (grouped MC)')
                        series.append({'weight':weight,'total':values,'errors':errors,'components':content,'component_error_policy':row['component_error_policy'],'roundoff_residual':row['aggregation_roundoff_residual'][weight]})
                    else:
                        color=house.STACK_CYCLE[k%len(house.STACK_CYCLE)]
                        # Separate finite rectangles preserve actual bin geometry,
                        # including gaps; no invented common rebinning or scaling.
                        ax.bar(xpos,values,width=widths,align='center',fill=False,edgecolor=color,linewidth=1.4,label=display_label(weight))
                        ax.errorbar(xpos,values,xerr=[v/2 for v in widths],yerr=errors,fmt='o',ms=3,color=color,capsize=2)
                        series.append({'weight':weight,'values':values,'errors':errors})
                axis=c['axes'][0]
                ax.set_xlabel(axis_label(axis));ax.set_ylabel(unit_label(q['unit']))
                ax.axhline(0,color='0.6',linewidth=.7)
                title='RAVEL synthetic software fixture' if result.get('software_fixture_scope') else 'RAVEL supplied-input diagnostic'
                fig.suptitle(title+' — '+display_label(name, c.get('display_label', 'Observable '+str(oi+1))),fontsize=12)
                ax.legend(loc='upper center',bbox_to_anchor=(.5,-.23),fontsize=8,ncol=1)
                house.tick_hygiene(ax);fig.subplots_adjust(bottom=.36,top=.9)
                failures=house.lint_figure(fig,readable_labels=True)
                if failures:raise ValueError('IRIS histogram layout refused: '+'; '.join(failures))
                stem='iris-observable-'+str(oi+1)+('-weight-'+str(pi+1) if stack else '')
                for extension in selected['formats']:fig.savefig(out/(stem+'.'+extension),dpi=220,bbox_inches='tight')
                receipts.append({'stem':stem,'files':[stem+'.'+extension for extension in selected['formats']],'plot_lint':'PASS','png_dpi':220,'kind':'signed_did_stack' if stack else 'histogram_diagnostic','normalization':'Exact declared artifact values/units; no plot-time rescale, clipping or component-independent error sum','physics_validated':False})
                plot_data.append({'stem':stem,'observable':name,'bins':bins,'axes':c['axes'],'unit':q['unit'],'normalization':c['normalization'],'series':series,'full_covariance_retained_in_quantity_artifact':True,'display_labels':{'observable':display_label(name,c.get('display_label','Observable '+str(oi+1))),'weights':{w:display_label(w) for w in weights},'datasets':{did:display_label(did,(delivery.get('display_labels') or {}).get(did,'Dataset '+str(di+1))) for di,did in enumerate(components['did_order'])} if stack else {}},'style':'mplhep ATLAS house style, no official experiment/result label'})
            finally:plt.close(fig)
    atomic_json(out/'iris-plot-contract.json',{'schema_version':1,'kind':'histogram_diagnostic','plots':plot_data,'synthetic_software_fixture':bool(result.get('software_fixture_scope')),'physics_validated':False,'error_scope':delivery['uncertainty_scope']})
    tables=write_report(result,out,figures=receipts)
    return {'status':'passed','figures':receipts,'tables':tables,'scope':'Requested source-unqualified histograms and complete signed DID stack; no service, SF or physics qualification'}


def _scalar_tables(observables, output):
    """Retain scalar marginal output and RAW moments without inventing an axis."""
    counters = []
    rows = []
    for path, obj in observables.items():
        contract = obj['contract']
        if obj.get('quantity_kind') != 'scalar_counter' and contract.get('quantity_kind') != 'scalar_counter':
            continue
        bins = obj['bins']
        if (obj.get('quantity_kind') != 'scalar_counter' or contract.get('quantity_kind') != 'scalar_counter'
                or contract['axes'] != [] or contract['representation'] != 'integrated'
                or contract['normalization'] != 'absolute' or len(bins) != 1
                or bins[0]['low'] != [] or bins[0]['high'] != []):
            raise ValueError('scalar_counter figure report requires one scalar with no bin geometry')
        value = bins[0]
        numbers = [value[key] for key in ('value', 'error_low', 'error_high')]
        if (any(type(number) not in (int, float) or not math.isfinite(number) for number in numbers)
                or value['error_low'] < 0 or value['error_high'] < 0):
            raise ValueError('scalar_counter figure report requires finite values and nonnegative marginal errors')
        # Keep final Counter/Estimate0D and RAW Counter semantics distinct. The
        # table does not derive covariance or replace native errors with RAW ones.
        counters.append({'path': path, 'observable': obj})
        cells = [path, *numbers, contract['unit'], obj['storage_semantics']]
        rows.append('| ' + ' | '.join(str(cell).replace('|', '\\|').replace('\n', ' ') for cell in cells) + ' |')
    if not counters:
        return []
    out = Path(output)
    atomic_json(out / 'scalar-counters.json', {'schema_version': 1, 'kind': 'scalar_counter_report',
        'counters': counters, 'physics_validated': False,
        'scope': 'Native scalar values and marginal errors; RAW moments retained separately; no cross-counter covariance inferred'})
    (out / 'scalar-counters.md').write_text(
        '# Supplied scalar counter outputs\n\n'
        '| Observable | Value | Error low | Error high | Unit | Storage semantics |\n'
        '|---|---:|---:|---:|---|---|\n' + '\n'.join(rows) + '\n\n'
        'These are scalar outputs with no bin axis or bin-width conversion. '
        'The exact final output, RAW moments and their separate conventions are in '
        '[scalar-counters.json](scalar-counters.json). Cross-counter and event-group '
        'covariance are not inferred. No physics certification is established.\n', encoding='utf-8')
    return [{'stem': 'scalar-counters', 'files': ['scalar-counters.json', 'scalar-counters.md'],
             'normalization': 'Native scalar values/errors retained without conversion; RAW moments remain separate'}]


def _native_derived_tables(observables, output):
    estimates, rows = [], []
    for path, obj in observables.items():
        if obj.get('quantity_kind') != 'native_derived_estimate':
            continue
        contract = obj['contract']
        from ravel.physics.native_estimate import validate_request
        validate_request(contract)
        if obj['all_native_bins'] != obj['native_finalized']['bins']:
            raise ValueError('native derived report requires the complete finalized bin census')
        estimates.append({'path': path, 'observable': obj})
        for b in obj['all_native_bins']:
            errors = '; '.join(str(e['label']) + ': ' + e['down_token'] + ', ' + e['up_token'] for e in b['native_errors'])
            cells = [path, b['bin'], b['low'], b['high'], b['value_token'], errors, b['status']]
            rows.append('| ' + ' | '.join(str(c).replace('|', '\\|').replace('\n', ' ') for c in cells) + ' |')
    if not estimates:
        return []
    out = Path(output)
    atomic_json(out / 'native-derived-estimates.json', {'schema_version': 1,
        'kind': 'native_derived_estimate_report', 'estimates': estimates,
        'physics_validated': False, 'covariance': None})
    (out / 'native-derived-estimates.md').write_text(
        '# Native derived estimates\n\n'
        '| Observable | Bin | Low | High | Native value token | Signed native errors | Status |\n'
        '|---|---|---|---|---|---|---|\n' + '\n'.join(rows) + '\n\n'
        'All finite and flow rows, undefined tokens, RAW estimates and histogram operands '
        'are retained in native-derived-estimates.json. Native errors remain marginal '
        'source errors; no histogram variance, group covariance, density conversion or '
        'physics certification is inferred.\n', encoding='utf-8')
    return [{'stem': 'native-derived-estimates',
             'files': ['native-derived-estimates.json', 'native-derived-estimates.md'],
             'normalization': 'Untransformed native derived values and errors, including undefined flow rows'}]


def render(spec, result, base, output):
    if spec['mode'] == 'ml-training':
        return {'status': 'passed', 'figures': [
            {**f, 'stem': 'ml/' + f['stem'], 'files': ['ml/' + p for p in f['files']]}
            for f in result['figures']], 'tables': [
                {'stem': 'ml/receipt', 'files': ['ml/receipt.json', 'ml/RESULT.md']}],
            'scope': 'All declared arm and seed diagnostics on the withheld test split'}
    if spec['mode']=='manuscript-build':
        from ravel.workflow.execution import file_hash
        pdf=Path(result['pdf']['path'])
        if result.get('status')!='passed' or not pdf.is_file() or file_hash(pdf)!=result['pdf']['sha256']:
            raise ValueError('exact delivered manuscript PDF required')
        return {'status':'passed','figures':[],'tables':[{'stem':'manuscript-build/source/note','files':[pdf.relative_to(output).as_posix()]}],
            'scope':'Actual compiled PDF only; claim/citation/visual/venue/CI3 review remains separate.'}
    if spec['mode'] in ('amplitude-integration', 'amplitude-predictions', 'weighted-events', 'amplitude-crosscheck'):
        return {'status': 'not_applicable', 'figures': [], 'tables': [],
                'scope': 'Binned predictions and stores feed figure and likelihood modes; this mode draws none'}
    if spec['mode'] == 'literal-calculation':
        return {'status': 'not_applicable', 'figures': [], 'tables': [],
                'scope': 'Exact scalar with its unit; no plot or invented comparison basis required'}
    if spec['mode'] in ('feyn-graph','diagram-analysis'):
        from ravel.workflow.science import adapter
        impl=adapter(spec); destination=Path(output)/spec['mode']
        tables=impl.write_report(destination,result)
        for table in tables:
            table['stem']=spec['mode']+'/'+table['stem']
            table['files']=[spec['mode']+'/'+name for name in table['files']]
        return {'status':'passed','figures':[],'tables':tables,'scope':'Complete structured diagram census and source-native SVG/TikZ exports; no numerical comparison or amplitude qualification.'}
    if spec['mode'] in ('symbolic-evaluation','feynarts-amplitude'):
        from ravel.physics.symbolic_evaluation import write_report
        return {'status': 'passed', 'figures': [], 'tables': write_report(result, output),
                'scope': 'Complete symbolic strings and evaluated complex pairs; no physics validation.'}
    if spec['mode'] == 'full-auxiliary-calibration':
        out=Path(output); out.mkdir(parents=True,exist_ok=True)
        inference=result.get('inference',{}); summary=inference.get('delivery',{}).get('summary')
        failed_audit=False
        if summary is None:
            summary=result.get('calibration_failure_audit',{}).get('summary');failed_audit=summary is not None
        if summary is None:
            (out/'calibration-report.md').write_text('Full auxiliary calibration delivery failed. Inspect the complete retained native logs and scheduled-slot journal; no coverage claim.\n')
        else:
            atomic_json(out/'calibration-summary.json',summary)
            rows=['| Truth | Scheduled | Included | Excluded | Unresolved | Identification interval | Binomial envelope |','|---|---:|---:|---:|---:|---|---|']
            rows += ['| '+ ' | '.join(map(str,[c['truth_id'],c['scheduled'],c['included'],c['excluded'],c['unresolved'],c['identification_interval'],c['conservative_binomial_interval']]))+' |' for c in summary['cohorts']]
            graph_scope=('Native-model repeated experiment with complete native TOTAL means. Retained native-mean NLL factorization is an algebra check; independent source/integral equivalence and numerical convergence remain unqualified.\n\n' if inference.get('delivery',{}).get('kind')=='source-graph-full-auxiliary-calibration/v1' else '')
            (out/'calibration-report.md').write_text(graph_scope+('Native delivery failed; the following is a conservative full-scheduled-population failure audit, not qualified native fit evidence.\n\n' if failed_audit else '')+'Pointwise fixed-truth profile-LR inclusion at the predeclared cutoff. Every failed/unissued slot remains in the original denominator. No CLs, uniform coverage or optimizer globality qualification.\n\n'+'\n'.join(rows)+'\n')
        return {'status':'passed','figures':[],'tables':[{'stem':'calibration-report','files':['calibration-report.md']+(['calibration-summary.json'] if summary is not None else []),'normalization':'Full fixed scheduled toy denominator; unresolved-fit envelope retained'}],'scope':'Pointwise full-law diagnostics, no uniform coverage or globality qualification'}
    """Always preserve numerical results; return an explicit optional figure status."""
    out = Path(output)
    mode, task = spec['mode'], spec['task']
    if mode in ('formula-grid', 'coupling-morphing', 'prescribed-statistic', 'search-statistics', 'differential-likelihood'):
        from ravel.physics.inference.figures import render as inference_figures
        return inference_figures(out)
    tables, rivet_observables = [], None
    if mode == 'analyze' and task.get('backend') == 'routine-build' and result.get('kind') == 'ma5-sfs-materialization-receipt':
        from ravel.physics.ma5_sfs_materialization import write_report
        return {'status':'passed','figures':[],'tables':write_report(result,out),'scope':'Source materialization only; no build/load/events or tuned-response qualification'}
    if mode == 'cosmic-evolution':
        from ravel.physics.cosmic_evolution import write_report
        return {'status': 'not_applicable', 'figures': [], 'tables': write_report(result, out),
                'scope': 'Complete declared IC/Nyx custody; scientific/native qualification remains separate'}
    if mode=='cosmology-solver':
        return {'status':'not_applicable','figures':[],'scope':'Complete cosmological native cells retained in result/raw artifacts; no invented histogram or uncertainty.'}
    if mode == 'tree-array-export':
        from ravel.physics.tree_array_export import write_report
        return {'status':'passed', 'figures':[], 'tables':write_report(result,out), 'scope':'Complete raw source arrays only; no preprocessing or ML'}
    if mode == 'parameter-space-sampling':
        from ravel.physics.parameter_space_sampling import write_report
        return write_report(result,out)
    if mode == 'asimov-sensitivity':
        from ravel.physics.asimov_sensitivity import write_report
        return {'status':'not_applicable','figures':[],'tables':write_report(result,out),'scope':'Literal expected-local discovery diagnostic and complete profile denominator; no observed/global discovery plot.'}
    if mode in ('ntuple-inventory', 'mc-expected-construction', 'mc-closure'):
        from ravel.physics import ntuple_inventory, mc_expected_construction, mc_closure
        module = {'ntuple-inventory':ntuple_inventory,'mc-expected-construction':mc_expected_construction,'mc-closure':mc_closure}[mode]
        return {'status':'not_applicable', 'figures':[], 'tables':module.write_report(result,out), 'scope':'Ntuple source preparation only; no computed physics figure'}
    if mode == 'root-stream':
        from ravel.physics.root_stream import write_report
        return {'status':'not_applicable','figures':[],'tables':write_report(result,out),'scope':'Complete public MC and allowed CR/VR data aggregates only; restricted DATA completeness witness, no SR or raw data'}
    if mode == 'dataset-query-quantities':
        return _iris_figures(result,out)
    if mode == 'columnar-analysis':
        from ravel.physics.columnar_analysis import write_figures
        return write_figures(result, out)
    if mode == 'figure-comparison':
        from ravel.physics.figure_comparison import write_figures
        return write_figures(result, out)
    if mode == 'event-production':
        from ravel.physics.event_production import write_figures
        return write_figures(result, out)
    if mode == 'scientific-delivery':
        from ravel.physics.scientific_delivery import write_report
        destination=out/'scientific-delivery'
        tables=write_report(result,destination)
        return {'status':'not_applicable','figures':[],
                'tables':[{**t,'files':['scientific-delivery/'+f for f in t['files']]} for t in tables],
                'reason':'Complete source reports and prospective ordinary/publication routes; no plot was rendered.'}
    if mode == 'background-discrete-profile':
        from ravel.physics.background_discrete_profile import write_report
        return {'status':'passed','figures':[], 'tables':write_report(result,out),
                'scope':'Complete candidate scans and explicit finite envelope; no interval/calibration claim'}
    if mode == 'contur-companion':
        from ravel.physics.contur_companion import SCOPE,verify_emitted
        if result.get('status_scope') != SCOPE or result.get('physics_validated') is not False:
            raise ValueError('native companion product registration requires exact limited scope')
        work = out / 'contur-companion-work'
        products = result['observation']['outputs']
        names = ['contur-companion-work/native-output/' + n for n in products]
        for pin in result.get('staged_after_readback',{}).get('generated_input_products',[]):
            path=Path(pin['path'])
            if not path.is_relative_to(work/'input'):
                raise ValueError('native companion generated product outside exact input copy')
            verify_emitted([pin]);names.append(path.relative_to(out).as_posix())
        for name in names:
            if not (out/name).is_file():
                raise ValueError('native companion product missing')
        return {'status': 'passed', 'figures': [], 'tables': [
            {'stem': 'contur-companion', 'files': ['contur-companion-results.json', *names],
             'normalization': 'Original native quantities and source-defined plots; no replacement rendering'}],
            'scope': SCOPE}
    if mode == 'contur-yoda':
        if result.get('kind') != 'native-contur-single-point' or result.get('fresh_inference') is not True:
            raise ValueError('fresh Contur table must retain its native inference scope')
        for name in ('contur-results.json', 'native-columns.csv'):
            if not (out/name).is_file() or not (out/name).stat().st_size:
                raise ValueError('complete Contur delivery missing')
        return {'status': 'passed', 'figures': [], 'tables': [{'stem': 'native-columns',
            'files': ['native-columns.csv', 'contur-results.json'],
            'normalization': 'Supplied YODA normalization; native confidence plus separately named complement'}],
            'scope': 'Complete native single-point and pool results; no reproduction/calibration claim'}
    if mode=='eft-convention-transport':
        report=out/'eft-convention-report.md'
        report.write_text('Exact EFT coefficient-coordinate transport: '+result['status']+'\n\n'
            'The full polynomial, supplied map, coordinate domains and exact binary64 rounding residuals are retained. '
            'Physical basis equivalence and EFT applicability remain unknown. No normalization, RGE, uncertainty or likelihood transformation was applied.\n')
        return {'status':'passed','figures':[],'tables':[{'stem':'eft-convention-report','files':[report.name]}],
                'scope':'Exact supplied coefficient-coordinate algebra; no physical basis/RGE qualification'}
    if mode == 'sfitter-native-fit':
        from ravel.physics.sfitter_native import write_report
        return {'status':'passed','figures':[],'tables':write_report(result,out),'scope':'Raw native SFitter delivery; no interval or convergence qualification'}
    if mode == 'published-summary':
        if result.get('kind') != 'published-limit-summary' or result.get('new_limits_derived') is not False:
            raise ValueError('published summary must preserve its supplied literature-only scope')
        if task['schema_version']==2:
            from ravel.plotting.figure_target import verify_summary_delivery
            verify_summary_delivery(result,out/'published-summary')
            required=['summary.png','summary.pdf','published-summary.json','task-fulfillment.json',
                      'figure_target.json','summary-reference-composite.png','search-census.json',
                      'source-references.json','SOURCE-GALLERY.md','original-request.json','SUMMARY.md']
            destination=out/'published-summary'
            if any(not (destination/name).is_file() or (destination/name).stat().st_size==0 for name in required):
                raise ValueError('complete original-task figure lifecycle delivery missing')
            return {'status':'passed','figures':[{'stem':'published-summary/summary',
                'files':['published-summary/summary.png','published-summary/summary.pdf'],
                'normalization':'Source limits; independent compatible model/production panels'}],
                'tables':[{'stem':'published-summary/fulfillment',
                'files':['published-summary/'+n for n in required[2:]],
                'normalization':'Original quantity, census, source references and pending-review primary target'}],
                'scope':'Original-task publication contract delivered pending independent scientific review'}
        required = ['summary.png','summary.pdf','published-summary.json','survey.json','basis-manifest.json',
                    'render-manifest.json','summary-audit.json','SUMMARY.md']
        destination = out / 'published-summary'
        if any(not (destination / name).is_file() or (destination / name).stat().st_size == 0 for name in required):
            raise ValueError('complete required summary figure/census/basis delivery missing')
        prefix = 'published-summary/'
        return {'status':'passed','figures':[{'stem':prefix+'summary','files':[prefix+'summary.png',prefix+'summary.pdf'],
                'normalization':'Supplied published limits on the declared common basis; no new limit'}],
                'tables':[{'stem':prefix+'published-summary','files':[prefix+name for name in required[2:]],
                'normalization':'Full literal curves/census and exact supplied source identities'}],
                'scope':'Published source summary; independent physics/census acceptance remains separate'}
    if mode=='analyze' and task.get('backend')=='agentrivet-source':
        from ravel.physics.agentrivet_source import write_report
        return {'status':'passed','figures':[],'tables':write_report(result,out),
            'scope':'Unverified supplier domain declarations; no numeric or native plots'}
    if mode == 'analysis-response-features':
        from ravel.physics.analysis_response_features import write_report
        return {'status':'passed','figures':[],'tables':write_report(result,out),'scope':'Source preparation or complete retained native response; no new inference/calibration'}
    if mode == 'published-classifier':
        from ravel.physics.published_classifier import write_report
        return {'status':'passed','figures':[],'tables':write_report(result,out),'scope':'Complete declared classifier event/quantity delivery; no calibration or native equivalence'}
    if mode == 'classifier-inputs':
        from ravel.physics.classifier_inputs import write_report
        return {'status':'passed','figures':[],'tables':write_report(result,out),'scope':'Source-bound static classifier census and declared scalar preparation; no inference'}
    if mode == 'native-group-acquisition':
        from ravel.physics.native_group_fills import write_report
        return {'status':'passed','figures': [], 'tables': write_report(result, out),'scope':'Source-bound event group/RAW reconciliation; no native execution authentication or inference'}
    if mode == 'llp-plane-recipe':
        from ravel.physics.llp_plane_recipe import write_report
        return {'status':'passed','figures':[],'tables':write_report(result,out),
                'scope':'Complete supplied LLP model-plane recipe and moments; no events, fit or exclusion.'}
    if mode == 'mass-width-grid':
        from ravel.physics.mass_width_grid import write_report
        return {'status':'passed','figures':[],'tables':write_report(result,out),'scope':'Whole supplied width inputs; no native fit or original physics completion'}
    if mode == 'svj-recipe':
        from ravel.physics.svj_recipe import write_report
        return {'status':'passed','figures':[],'tables':write_report(result,out),
                'scope':'Complete supplied SVJ scan recipe, no event generation, fits or physics qualification'}
    if mode == 'numerical-reference-check':
        from ravel.validation.numerical_reference import write_report
        return {'status':'passed', 'figures':[], 'tables':write_report(result, out),
                'scope':'Complete supplied held-out numerical comparison; no model or physics qualification'}
    if mode == 'source-tables':
        from ravel.physics.source_tables import write_report
        tables=write_report(result,out)
        return {'status':'passed','figures':[],'tables':tables,'scope':'Literal source tables and supplied matrices; no histogram plotting or inference'}
    if mode == 'analyze' and task['backend'] in ('rivet', 'rivet-built'):
        rivet_observables = read_json(out / 'observables.json')['observables']
        tables = _scalar_tables(rivet_observables, out) + _native_derived_tables(rivet_observables, out)
        from ravel.physics.native_density import write_report
        tables += write_report(rivet_observables, out)
        from ravel.physics.native_categorical import write_report as categorical_report
        tables += categorical_report(rivet_observables, out)
        from ravel.physics.native_cumulant import render_tables as cumulant_report
        tables += cumulant_report(rivet_observables, out)
        rivet_observables = {path: obj for path, obj in rivet_observables.items()
                             if obj.get('quantity_kind') not in ('scalar_counter', 'native_derived_estimate','native_density_estimate','native_categorical','native_cumulant')}
        if not rivet_observables:
            return {'status': 'passed' if tables else 'not_applicable', 'figures': [], 'tables': tables,
                    'scope': 'Native scalar/derived tables retain full machine output; no unavailable values or errors are plotted as zero'}
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        unavailable = {'status':'unavailable','reason':'Install ravel-hep[science] for PDF/PNG diagnostics','files':[]}
        if tables:
            unavailable['tables'] = tables
        return unavailable
    from ravel.plotting import mplhep_style as house
    house.apply_style('ATLAS')
    plots = []
    coordinates = {}
    series_identities = {}
    if mode == 'quantities':
        q = result['quantities']; c = q['contract'] if 'contract' in q else read_json(Path(base)/task['contract'])
        n = len(c['bins'])
        series=[]
        for k,w in enumerate(c['weight_names']):
            series.append((w,q['values'][w],[math.sqrt(max(0,q['covariance'][k*n+i][k*n+i])) for i in range(n)]))
        plots.append(('quantities', [b['id'] for b in c['bins']], series, q['unit'], 'Declared bin ID (see bin edges in quantities.json)'))
        if len(c['axes']) == 1:
            coordinates['quantities'] = (c['bins'], c['axes'][0])
    elif mode == 'analyze' and task['backend'] in ('rivet', 'rivet-built'):
        observables = rivet_observables if rivet_observables is not None else read_json(out/'observables.json')['observables']
        for i,(path,obj) in enumerate(observables.items()):
            bins=obj['bins']; c=obj['contract']
            if obj.get('quantity_kind') == 'scalar_counter' or c.get('quantity_kind') == 'scalar_counter':
                raise ValueError('scalar_counter must be routed through the complete native scalar table')
            labels=[str(j+1) for j in range(len(bins))]
            series_identities[f'observable-{i+1}'] = [path]
            plots.append((f'observable-{i+1}',labels,[(display_label(path,c.get('display_label','Observable '+str(i+1))),[b['value'] for b in bins],[[b['error_low'] for b in bins],[b['error_high'] for b in bins]])],c['unit'],'Bin index (ordered edges in observables.json)'))
            if len(c['axes']) == 1:
                coordinates[f'observable-{i+1}'] = (bins, c['axes'][0])
    elif mode == 'analyze' and 'yields' in result:
        plots.append(('regions',result['region_names'],[(w,v,[math.sqrt(result['covariance'][w][i][i]) for i in range(len(v))]) for w,v in result['yields'].items()],
                      'Input weight / region','Region (overlap is retained, not combined)'))
    elif mode == 'contrast':
        labels = result['bin_ids']
        quantity = result['quantity']
        for contrast in result['contrasts']:
            stem = 'contrast-' + contrast['id']
            series = []
            for key, label, covariance in (
                    ('baseline', contrast['baseline_stream'], 'baseline_covariance'),
                    ('candidate', contrast['candidate_stream'], 'candidate_covariance'),
                    ('difference', 'Candidate minus baseline (paired MC)', 'covariance')):
                matrix = contrast[covariance]
                if (len(matrix) != len(labels) or any(len(row) != len(labels) for row in matrix)
                        or any(not math.isfinite(matrix[i][i]) or matrix[i][i] < 0 for i in range(len(labels)))):
                    raise ValueError('invalid declared contrast covariance for figure')
                series.append((label, contrast[key], [math.sqrt(matrix[i][i]) for i in range(len(labels))]))
            plots.append((stem, labels, series, result['unit'], 'Declared contrast bin ID'))
            if len(quantity['axes']) == 1:
                coordinates[stem] = (quantity['bins'], quantity['axes'][0])
    elif mode == 'measurement':
        model=read_json(Path(base)/task['input']); ids=result['bin_ids']
        def vector(key):
            r=model[key]; return [r['values'][r['bin_ids'].index(i)] for i in ids]
        cov=model['experimental_covariance']; idx=[cov['bin_ids'].index(i) for i in ids]
        dataerr=[math.sqrt(cov['matrix'][j][j]) for j in idx]
        sm=vector('sm')
        if task.get('inference')=='linear_fit':
            terms=model['linear_terms'];best=result['linear_fit']['best_fit']
            rows=[terms['matrix'][terms['bin_ids'].index(i)] for i in ids]
            tested=('SM + best-fit linear terms',[s+sum(b*t for b,t in zip(best,row)) for s,row in zip(sm,rows)],None)
        else:
            signal=vector('signal')
            tested=('SM + tested signal',[s+task['signal_strength']*v for s,v in zip(sm,signal)],None)
        plots.append(('measurement',ids,[('Supplied measurement',vector('data'),dataerr),('Supplied SM',sm,None),
                      tested],result['unit'],'Declared measurement bin ID'))
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
            xlabel=axis_label(axis)
        for si,(label,values,errors) in enumerate(series):
            if len(values)!=len(labels) or any(not math.isfinite(x) for x in values):
                raise ValueError('nonfinite or misaligned figure quantities')
            color='black' if mode=='measurement' and si==0 else ('#0072B2','#D55E00','#009E73')[si%3]
            ax.errorbar(xpos,values,xerr=xerr,yerr=errors,fmt='o' if errors is not None else 's',ms=4,capsize=2,label=display_label(label),color=color)
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
        display_ticks=[display_label(label) for label in labels]
        stride=max(1,math.ceil(len(labels)/12))
        if name not in coordinates:
            (ratio if ratio is not None else ax).set_xticks(list(range(0,len(labels),stride)),display_ticks[::stride],rotation=30 if any(len(x)>8 for x in display_ticks) else 0,ha='right' if any(len(x)>8 for x in display_ticks) else 'center')
        (ratio if ratio is not None else ax).set_xlabel(xlabel)
        ax.set_ylabel(unit_label(unit)); ax.axhline(0,color='0.6',linewidth=.7)
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
                         'source_series_ids':series_identities.get(name,[label for label,_,_ in series]),
                         'display_labels':{'ticks':dict(zip(labels,display_ticks)),'series':{label:display_label(label) for label,_,_ in series},'x':xlabel,'y':unit_label(unit)},
                         'normalization':'No plot-time normalization or clipping; values and uncertainties read from artifacts'})
    rendered = {'status':'passed' if receipts or tables else 'not_applicable','figures':receipts,
                'scope':'Quantity diagnostics, not a published-reference closure figure; full covariance remains in machine artifacts'}
    if tables:
        rendered['tables'] = tables
    return rendered
