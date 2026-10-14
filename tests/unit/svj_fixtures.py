"""Inert generated-event source controls, extracted from the C12 public tests.
No external runtime, model import, generator or event evaluation is permitted.
"""
from copy import deepcopy
import hashlib,json,sys
from pathlib import Path
from ravel.physics import model_events as m
def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2)+'\n' if isinstance(data,dict) else data)
    return pin(path)

def tree(root, files):
    for name,raw in files.items(): write(root/name,raw)
    manifest=root.parent/(root.name+'-manifest.json')
    return {'root':str(root),'manifest':write(manifest,m.bridge.source_tree(root))}

def policy():
    return {'schema_version':1,'policy':{'schema_version':1,
        'actors':{'proposer':'source-author','executor':'executor','physics_critic':'critic','skeptical_verifier':'verifier','physics_decider':'decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'generator-population','kind':'scientific'}],
        'claim_scopes':{'generated_event_delivery':{'checks':['integrity','generator-population'],'actions':['delivery','reuse']}}},
        'correction_contract':{'task_fields':[],'input_slots':[]}}

def config(base, scheme='unmerged_lo', *, variations=False, decay=False):
    base.mkdir(parents=True,exist_ok=True)
    mg=tree(base/'mg',{'VERSION':'version = 2.9.27\n','bin/mg5_aMC':'# Synthetic non-executable MG stand-in\n'})
    model=tree(base/'ufo',{x:'# Synthetic non-executable UFO stand-in\n' for x in ('__init__.py','parameters.py','particles.py','vertices.py','couplings.py','object_library.py','lorentz.py')})
    deps=tree(base/'deps',{'fc':'inert','cxx':'inert'})
    py=pin(Path(sys.executable).resolve()); support=write(base/'python-support.json',{'python_sha256':py['sha256'],'files':[pin(base/'deps/fc')]})
    order=m.SCHEMES[scheme];merged=scheme in ('mlm','ckkw_l','fxfx');mult=[0,1] if merged else [0]
    process='define p = g u u~ d d~\ndefine j = g u u~ d d~\ngenerate p p > t t~'+(' [QCD]' if order=='NLO' else '')+'\n'
    if merged:process+='add process p p > t t~ j'+(' [QCD]' if order=='NLO' else '')+'\n'
    run={'nevents':3,'iseed':19,'lpp1':1,'lpp2':1,'ebeam1':6500,'ebeam2':6500,'ickkw':{'unmerged_lo':0,'mlm':1,'ckkw_l':0,'mcatnlo':0,'fxfx':3}[scheme]}
    if order=='LO':run.update(use_syst=variations,systematics_program='systematics',systematics_arguments="['--mur=0.5,1,2','--muf=0.5,1,2','--pdf=errorset']",xqcut=20 if scheme=='mlm' else 0,ktdurham=20 if scheme=='ckkw_l' else -1,ptlund=-1)
    else:run.update(parton_shower='PYTHIA8',store_rwgt_info=True,reweight_scale=variations,reweight_pdf=variations,rw_rscale='[1,2,.5]',rw_fscale='[1,2,.5]')
    shower_on=scheme!='unmerged_lo'
    cards={name:None for name in m.CARD_NAMES}
    cards.update(process=write(base/'proc.dat',process),parameter=write(base/'param.dat','BLOCK MASS\n 6 172.5\nDECAY 6 1.4\n'),run=write(base/'run.dat','\n'.join(str(value)+' = '+key for key,value in run.items())+'\n'))
    if shower_on and order=='LO':
        pytext='Main:numberOfEvents = 3\nHEPMCoutput:file = auto\n'
        if scheme=='mlm':pytext+='JetMatching:qCut = 30\nJetMatching:nJetMax = 1\nJetMatching:merge = on\nJetMatching:scheme = 1\n'
        else:pytext+='Merging:TMS = 30\nMerging:Process = pp>ttbar\nMerging:nJetMax = 1\n'
        cards['pythia']=write(base/'pythia.dat',pytext)
    if order=='NLO':cards['shower']=write(base/'shower.dat','Qcut = '+('30' if merged else '-1')+'\nnjmax = 1\n')
    if decay:cards['madspin']=write(base/'madspin.dat','set spinmode madspin\nset seed 101\ndecay t > b w+\ndecay t~ > b~ w-\nlaunch\n')
    group=[{'name':'scale_variation','combine':'envelope','ids':['1001','1002']}] if variations else []
    vsource=write(base/'scale-source.json',{'synthetic':True,'literal_mur':[.5,2]})
    return {'schema_version':1,'source':'Synthetic source/API controls only; no physics sample',
        'runtime':{'madgraph_tree':mg,'python':py,'python_manifest':support,'dependencies':[{'role':'compiler','tree':deps}],
            'options':{'fortran_compiler':str(base/'deps/fc'),'cpp_compiler':str(base/'deps/cxx'),'pythia8_path':str(base/'deps') if shower_on else None,
                       'mg5amc_py8_interface_path':str(base/'deps') if shower_on and order=='LO' else None,'lhapdf':None}},
        'model_tree':model,'cards':cards,'generation':{'order':order,'scheme':scheme,'events':3,'seed':19,'beam_type':[1,1],'beam_pdg':[2212,2212],
            'energy_gev':[6500,6500],'jet_token':'j','jet_multiplicities':mult,'run_settings':{},'scale_pdf':('lo_systematics' if order=='LO' else 'nlo_on_the_fly') if variations else 'none'},
        'shower':{'backend':'PYTHIA8' if shower_on else 'OFF','settings':{},'merging_scale_gev':30 if merged else None,'max_jets':max(mult),
            'process':'pp>ttbar' if scheme=='ckkw_l' else None,'minimum_returned_events':1 if shower_on else 0},
        'decay':{'mode':'MADSPIN' if decay else 'OFF','spinmode':'madspin' if decay else None,'seed':101 if decay else None,
                 'commands':['decay t > b w+','decay t~ > b~ w-'] if decay else []},'reweight':{'mode':'OFF','weight_ids':[]},
        'weights':{'groups':group,'variation_points':[{'id':identity,'kind':'scale','source':vsource,'definition':{'mu_r_factor':factor,'mu_f_factor':1,'normalization':'absolute_lhe_weight'}} for identity,factor in zip(['1001','1002'],[.5,2])] if variations else [],'sampling_law':'unknown'},
        'outputs':{'lhe_relative':'Events/ravel/unweighted_events.lhe','hepmc_relative':'Events/ravel/tag_1_pythia8_events.hepmc' if shower_on else None,'max_decoded_lhe_bytes':1000000,
                   'shower_weight_map':[{'hepmc_name':'nominal','lhe_id':None},*([{'hepmc_name':'scale_'+identity,'lhe_id':identity} for identity in ['1001','1002']] if variations else [])] if shower_on else []},
        'max_seconds':60,'max_ram_mib':512,'assumptions':['Synthetic API control; matching stability, source amplitudes and physical validity unknown.']}

