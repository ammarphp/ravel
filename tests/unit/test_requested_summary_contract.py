"""Fabricated sources/figures only: no P1 render, native/provider/model or governed worker."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,sys
import pytest
from ravel.physics import published_summary as op
from ravel.plotting import figure_target as ft,figure_manifest as fm,summary_overlay as overlay,science_figures, mplhep_style as house
from test_published_summary import fixture,write,pin


def basis(model,production):
    return {'model':model,'resonance':'Zprime','spin':1,'decay':'WW','production':production,
        'width':'Synthetic narrow-width convention','quantity':'95% CL UL [pb]','unit':'pb',
        'energy_tev':13,'branching_convention':'sigma times BR(Zprime->WW), synthetic'}


def make(tmp_path):
    tmp_path=tmp_path.resolve()
    panels={};summaries=[]
    definitions=[];candidates=[]
    for pid,experiment,model,production,cid in [('qq','ATLAS','HVT','qqA','A'),('vbf','CMS','SPM','VBF','C')]:
        folder=tmp_path/pid;folder.mkdir()
        survey,manifest,contract=fixture(folder)
        survey['candidates']=survey['candidates'][:1]
        survey['candidates'][0].update(id=cid,experiment=experiment)
        manifest['target_basis']['model']=model
        manifest['window_gev']=[0,500];manifest['coverage_gaps'][0]['lo_gev']=0
        manifest['curves'][0].update(survey_id=cid,source=cid+' l-nu-qq')
        contract.update(window={'lo_gev':0,'hi_gev':500,'upper_inclusive':False},
            survey=write(folder/'survey.json',survey),manifest=write(folder/'manifest.json',manifest),
            candidate_sources=[{'survey_id':cid,'mass_range_gev':[250,1000],'source_ids':['source'],'energy_tev':13}],
            resolved_series_sha256={cid:op.digest(manifest['curves'][0]['resolved'])})
        cp=write(folder/'contract.json',contract);summaries.append({'id':pid,'summary':cp})
        panels[pid]=op._load({'schema_version':1,'input':cp['path'],'input_sha256':cp['sha256']},tmp_path)
        definitions.append({'id':pid,'role':'requested_model' if pid=='qq' else 'alternative_model',
            'model_basis':basis(model,production),'axes':{'x':'linear','y':'log','x_label':'m(Zprime) [GeV]','y_label':'95% CL UL [pb]'},
            'caption':model+' '+production+' supplied synthetic basis','relation_to_request':'Separate model panel; no acceptance conversion.'})
        candidates.append({'id':cid,'experiment':experiment,'reference_ids':[pid+'-ref'],
            'mass_range_gev':[250,1000],'model_basis':basis(model,production),
            'disposition':'plotted' if pid=='qq' else 'alternative_panel','reason':'Fabricated in-window source quantity.',
            'panel_id':pid,'curve_id':cid})
    parent={'schema_version':1,'prompt':"Consider a model (say HVT) with a Z'->WW. Construct a summary plot of ATLAS+CMS searches sensitive for m(Zprime)<500 GeV.",
            'task_mode':'summary_plot','targets':{'model':'HVT','masses_gev':[500.]}}
    pp=write(tmp_path/'parent.json',parent)
    sources={}
    for identity in ['paper','catalog','review','mplhep','font']:
        p=tmp_path/(identity+'.txt');p.write_text('FABRICATED '+identity+' source resource.\n');sources[identity]=pin(p)
    target={'schema_version':2,'figure_class':'published-search-summary','parent_task_sha256':pp['sha256'],
        'request':{'model':'HVT','resonance':'Zprime','decay':'WW','experiments':['ATLAS','CMS'],
                   'window':{'lo_gev':0,'hi_gev':500,'upper_inclusive':False}},
        'panels':definitions,'candidates':candidates,'census_as_of':'2026-10-08',
        'references':[{'id':p['id']+'-ref','source_id':'paper','paper':p['model_basis']['model']+' fabricated source',
                       'version':'synthetic-v1','figure_or_table':'Table1','caption':'Synthetic observed/expected source limits.'} for p in definitions]}
    census={'schema_version':1,'kind':'official-search-census','as_of':'2026-10-08','experiments':['ATLAS','CMS'],
        'candidate_ids':['A','C'],'searches':[{'experiment':experiment,'source_id':'catalog','locator':'Synthetic catalogue line1',
            'query':'Neutral spin-one WW, all models/production and related incompatible sources.','candidate_ids':[cid]}
            for experiment,cid in [('ATLAS','A'),('CMS','C')]],'source_review_ids':['review']}
    contract={'schema_version':2,'kind':'requested-published-summary/v2','parent_task':pp,
        'figure_target':write(tmp_path/'target.json',target),'search_census':write(tmp_path/'census.json',census),
        'panels':summaries,'source_assets':sources,'runtime_resources':{'mplhep_source_id':'mplhep','font_source_ids':['font']}}
    return parent,target,census,panels,contract


def task(tmp_path,contract):
    p=write(tmp_path/'request.json',contract)
    return {'schema_version':2,'input':p['path'],'input_sha256':p['sha256']}


def validate(parent,target,census,panels,contract):
    return ft.validate_search_summary(target,parent,census,panels,set(contract['source_assets']),contract['parent_task']['sha256'])


def test_positive_original_request_two_incompatible_panels_and_literal_anchors(tmp_path):
    parent,target,census,panels,contract=make(tmp_path)
    r=validate(parent,target,census,panels,contract)
    assert r['task_contract_complete'] and r['scientific_task_accepted'] is False
    assert r['candidate_ids']==['A','C'] and r['panel_ids']==['qq','vbf']
    assert 'data_background_ratio_panel' in r['recipe']['not_applicable']
    loaded=op._load(task(tmp_path,contract),tmp_path)
    assert loaded['panels']['qq']['render_manifest']['curves'][0]['resolved']['mass_gev']==[250,300,450,500]
    assert loaded['panels']['vbf']['render_manifest']['excluded_boundary_anchors'][0]['in_requested_window'] is False
    assert len(op.inputs(task(tmp_path,contract),tmp_path))==17


@pytest.mark.parametrize('fault',['parent-model','missing-cms','prompt-quantity','window','lower-window','class','missing-discovery','omitted-found-candidate',
    'missing-review','unknown-ref','changed-width','changed-production','changed-br','changed-unit','changed-model','out-of-range','hide-eligible',
    'wrong-curve','dropped-curve','unknown-state','missing-main','source-unbound','panel-quantity','actual-model'])
def test_parent_source_and_model_panel_adversaries(tmp_path,fault):
    p,t,c,l,k=make(tmp_path)
    if fault=='parent-model':p['targets']['model']='other'
    elif fault=='missing-cms':t['request']['experiments']=['ATLAS']
    elif fault=='prompt-quantity':p['prompt']='Only show three retained ATLAS curves.'
    elif fault=='window':t['request']['window']['upper_inclusive']=True
    elif fault=='lower-window':t['request']['window']['lo_gev']=250
    elif fault=='class':t['figure_class']='diagnostic'
    elif fault=='missing-discovery':c['searches'].pop()
    elif fault=='omitted-found-candidate':t['candidates'].pop();c['candidate_ids']=['A']
    elif fault=='missing-review':c['source_review_ids']=[]
    elif fault=='unknown-ref':t['candidates'][0]['reference_ids']=['absent']
    elif fault=='changed-width':t['candidates'][0]['model_basis']['width']='broad'
    elif fault=='changed-production':t['candidates'][0]['model_basis']['production']='VBF'
    elif fault=='changed-br':t['candidates'][0]['model_basis']['branching_convention']='WW times W decay BR'
    elif fault=='changed-unit':t['panels'][0]['model_basis']['unit']='fb'
    elif fault=='changed-model':t['candidates'][1]['model_basis']['model']='HVT'
    elif fault=='out-of-range':t['candidates'][1]['disposition']='out_of_range'
    elif fault=='hide-eligible':t['candidates'][1].update(disposition='incompatible',panel_id=None,curve_id=None)
    elif fault=='wrong-curve':t['candidates'][1]['curve_id']='A'
    elif fault=='dropped-curve':l['vbf']['manifest']['curves'][0]['draw']='none'
    elif fault=='unknown-state':t['candidates'][0]['disposition']='harvest_pending'
    elif fault=='missing-main':t['panels'][0]['role']='alternative_model'
    elif fault=='source-unbound':t['references'][0]['source_id']='absent'
    elif fault=='panel-quantity':l['qq']['manifest']['target_basis']['quantity']='mu'
    elif fault=='actual-model':l['qq']['manifest']['target_basis']['model']='SPM'
    with pytest.raises(ValueError):validate(p,t,c,l,k)


def test_incompatible_scalar_nearmiss_and_outofrange_dispositions_are_source_bound(tmp_path):
    p,t,c,l,k=make(tmp_path)
    scalar=deepcopy(t['candidates'][1]);scalar.update(id='scalar',disposition='incompatible',panel_id=None,curve_id=None)
    scalar['model_basis'].update(spin=0,resonance='Higgs',model='scalar')
    high=deepcopy(t['candidates'][0]);high.update(id='high',mass_range_gev=[600,3000],disposition='out_of_range',panel_id=None,curve_id=None)
    t['candidates'] += [scalar,high];c['candidate_ids']+=['scalar','high']
    c['searches'][0]['candidate_ids']+=['high'];c['searches'][1]['candidate_ids']+=['scalar']
    assert validate(p,t,c,l,k)['candidate_ids']==['A','C','scalar','high']


def test_closed_resource_graph_parent_and_runtime_bytes(tmp_path):
    _,_,_,_,k=make(tmp_path);request=task(tmp_path,k)
    Path(k['parent_task']['path']).write_text('{}')
    with pytest.raises(ValueError,match='digest'):op.inputs(request,tmp_path)


def test_missing_named_font_resource_refuses_before_render(tmp_path):
    _,_,_,_,k=make(tmp_path);k['runtime_resources']['font_source_ids']=[]
    with pytest.raises(ValueError,match='runtime'):op.inputs(task(tmp_path,k),tmp_path)


def test_strict_style_missing_dependency_refuses_diagnostic_stays_explicit(monkeypatch):
    monkeypatch.setitem(sys.modules,'mplhep',None)
    with pytest.raises(ValueError,match='requires available'):house.apply_style('ATLAS',required=True)
    assert house.apply_style('ATLAS') is None


def test_standard_worker_route_dispatches_v2_child_adapter():
    from ravel.workflow import science
    assert science.adapter({'mode':'published-summary','task':{'schema_version':2}}) is op
    assert fm.summary_recipe('published-search-summary')['source_contract']=='published_summary.validate_requested_summary'


@pytest.mark.parametrize("relative_runtime",[False,True])
def test_synthetic_complete_worker_reporting_and_existing_primary_compose(tmp_path,monkeypatch,relative_runtime):
    p,t,c,l,k=make(tmp_path)
    runtime_actual={key:dict(k['source_assets'][key]) for key in ['mplhep','font']}
    if relative_runtime:
        for key in runtime_actual:k['source_assets'][key]['path']=Path(k['source_assets'][key]['path']).name
    request=task(tmp_path,k)
    def fabricated_renderer(panels,target,stem):
        # Renderer is mocked; this control tests genuine adapter/attachment/report IO only.
        from PIL import Image
        Image.new('RGB',(150,100),'white').save(stem+'.png')
        Path(stem+'.pdf').write_bytes(b'fabricated-pdf; no publication font qualification claimed')
        e={'status':'passed','mplhep_loaded':True,'geometric_lint':'passed','panel_count':2,
           'experiments':['ATLAS','CMS'],'figure_class':'published-search-summary',
           'mplhep_module':{**runtime_actual['mplhep'],'size':Path(runtime_actual['mplhep']['path']).stat().st_size},
           'fonts':[{**runtime_actual['font'],'size':Path(runtime_actual['font']['path']).stat().st_size,'family':'synthetic mock Helvetica'}]}
        return {'panels':[{'id':x} for x in panels],'publication_evidence':e,
            'output_pins':[{**pin(Path(stem+ext)), 'size':Path(stem+ext).stat().st_size} for ext in ['.png','.pdf']]}
    monkeypatch.setattr(overlay,'render_summary_panels',fabricated_renderer)
    worker=tmp_path.resolve()/'worker';worker.mkdir()
    out=worker/'published-summary'
    result=op.run(request,tmp_path,out)
    assert result['claim_scope']=='source_bound_requested_summary_delivery' and result['physics_validated'] is False
    target=result['figure_target_lifecycle']['targets'][0]
    assert target['primary'] and target['figure_id'] is None and target['source']=='description-only'
    assert target['composed_by']['tool']=='figure_target.py compose' and target['verified_by_physicist'] is None
    assert (out/'summary-reference-composite.png').is_file()
    assert science_figures.render({'mode':'published-summary','task':request},result,tmp_path,worker)['status']=='passed'
    (out/'summary.png').write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):science_figures.render({'mode':'published-summary','task':request},result,tmp_path,worker)


def test_diagnostic_style_cannot_satisfy_delivery_report(tmp_path):
    p,t,c,l,k=make(tmp_path)
    result={'kind':'published-limit-summary','new_limits_derived':False,'task_fulfillment':{'status':'diagnostic'},'figure_contract':t}
    with pytest.raises(ValueError,match='fulfillment'):science_figures.render({'mode':'published-summary','task':{'schema_version':2}},result,tmp_path,tmp_path)


def style_fixture(tmp_path):
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(4,3));ax.plot([250,300],[1,.5],label='Synthetic ATLAS 1 fb-1 obs.')
    ax.set_xlabel('m(Zprime) [GeV]');ax.set_ylabel('95% CL UL [pb]');ax.legend()
    house.tick_hygiene(ax);house.publication_axes(ax)
    h=[fig.text(.1,.98,'ATLAS and CMS published results',weight='bold',style='italic'),
       fig.text(.1,.90,'sqrt(s) = 13 TeV')]
    module=tmp_path/'synthetic-mplhep.py';module.write_text('# Fabricated source dependency\n')
    return fig,ax,h,SimpleNamespace(__file__=str(module))


def test_positive_artist_tick_header_resource_inspection_with_mock_font_registry(tmp_path,monkeypatch):
    # Genuine artists/ticks/header inspection. Font face classification alone is
    # mocked; this is not proof that this environment has an admitted house font.
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    with plt.rc_context({'pdf.fonttype':42,'ps.fonttype':42}):
        fig,ax,h,hep=style_fixture(tmp_path)
        monkeypatch.setattr(font_manager.FontProperties,'get_name',lambda self:'Helvetica')
        r=house.publication_evidence(fig,[ax],h,hep=hep,experiments=['ATLAS','CMS'],energies=[13])
        assert r['four_side_inward_minor_ticks'] and r['headers'][1]=='sqrt(s) = 13 TeV' and r['fonts']
        assert r['mplhep_module']['sha256']==pin(Path(hep.__file__))['sha256']
        plt.close(fig)


@pytest.mark.parametrize('fault',['fallback','experiment-header','energy-header','not-bold','ticks-out','missing-top','no-minor','wrong-font','fonttype'])
def test_style_contract_adversaries_with_actual_synthetic_artists(tmp_path,monkeypatch,fault):
    import matplotlib.pyplot as plt
    from matplotlib import font_manager,ticker
    with plt.rc_context({'pdf.fonttype':42,'ps.fonttype':42}):
        fig,ax,h,hep=style_fixture(tmp_path)
        if fault!='wrong-font':monkeypatch.setattr(font_manager.FontProperties,'get_name',lambda self:'Helvetica')
        if fault=='fallback':hep=None
        elif fault=='experiment-header':h[0].set_text('ATLAS only')
        elif fault=='energy-header':h[1].set_text('sqrt(s) = 8 TeV')
        elif fault=='not-bold':h[0].set_fontweight('normal')
        elif fault=='ticks-out':ax.tick_params(axis='both',which='both',direction='out')
        elif fault=='missing-top':ax.tick_params(axis='x',which='both',top=False)
        elif fault=='no-minor':ax.xaxis.set_minor_locator(ticker.NullLocator())
        elif fault=='fonttype':plt.rcParams['pdf.fonttype']=3
        with pytest.raises(ValueError):house.publication_evidence(fig,[ax],h,hep=hep,experiments=['ATLAS','CMS'],energies=[13])
        plt.close(fig)


def test_single_inwindow_source_sample_is_marker_without_invented_curve(tmp_path):
    import matplotlib.pyplot as plt
    _,_,_,panels,_=make(tmp_path)
    man=deepcopy(panels['vbf']['render_manifest'])
    man['curves'][0]['resolved']={'mass_gev':[250,500],'obs':[.51,.12],'exp':[.43,.10]}
    man['annotations']=[];man['coverage_gaps']=[]
    fig,ax=plt.subplots(figsize=(4,3))
    overlay._draw_manifest(ax,man)
    assert all(line.get_linestyle()=='None' and line.get_marker() in ['o','s'] for line in ax.lines)
    assert list(ax.lines[0].get_xdata())==[250,500]
    plt.close(fig)


@pytest.mark.parametrize('name',['summary.png','summary.pdf','source-font'])
def test_rendered_output_swap_during_attachment_refuses_success(tmp_path,monkeypatch,name):
    _,_,_,_,k=make(tmp_path);request=task(tmp_path,k)
    def renderer(panels,target,stem):
        from PIL import Image
        Image.new('RGB',(150,100),'white').save(stem+'.png');Path(stem+'.pdf').write_bytes(b'synthetic pdf')
        e={'status':'passed','mplhep_loaded':True,'geometric_lint':'passed','panel_count':2,
           'experiments':['ATLAS','CMS'],'figure_class':'published-search-summary',
           'mplhep_module':{**k['source_assets']['mplhep'],'size':Path(k['source_assets']['mplhep']['path']).stat().st_size},
           'fonts':[{**k['source_assets']['font'],'size':Path(k['source_assets']['font']['path']).stat().st_size,'family':'synthetic mock'}]}
        return {'panels':[{'id':x} for x in panels],'publication_evidence':e,
                'output_pins':[{**pin(Path(stem+ext)),'size':Path(stem+ext).stat().st_size} for ext in ['.png','.pdf']]}
    monkeypatch.setattr(overlay,'render_summary_panels',renderer)
    original=ft.attach_summary_delivery
    def swap(out,target):
        result=original(out,target)
        altered=Path(k['source_assets']['font']['path']) if name=='source-font' else out/name
        altered.write_bytes(altered.read_bytes()+b'changed bytes')
        return result
    monkeypatch.setattr(ft,'attach_summary_delivery',swap)
    out=tmp_path.resolve()/'output'
    with pytest.raises(ValueError,match='source/runtime changed' if name=='source-font' else 'image bytes changed'):op.run(request,tmp_path,out)
    assert (out/'summary.png').is_file() and not (out/'task-fulfillment.json').exists() and not (out/'published-summary.json').exists()
