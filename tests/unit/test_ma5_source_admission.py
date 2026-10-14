"""Fabricated source and SAF controls; no compiler, detector or event execution."""
import hashlib
import json
from pathlib import Path

import pytest

from ravel.physics import ma5_bookings as bookings, ma5_family, ma5_pad, ma5_saf
from ravel.physics import ma5_saf_reader as reader
from ravel.workflow import science


CONFIG = '''PHYSICS->mcConfig().Reset();
PHYSICS->mcConfig().AddHadronicId(-211);
PHYSICS->mcConfig().AddHadronicId(211);
PHYSICS->mcConfig().AddHadronicId(211);
PHYSICS->mcConfig().RemoveHadronicId(-211);
PHYSICS->mcConfig().AddInvisibleId(-51);
PHYSICS->mcConfig().AddInvisibleId(51);
PHYSICS->mcConfig().RemoveInvisibleId(99);
PHYSICS->recConfig().Reset();'''


def source(config=CONFIG):
    return 'bool A::Initialize(){'+config+'''Manager()->AddRegionSelection("SR");
Manager()->AddCut("#Phi(closest jet, MET) < 2.0");
Manager()->AddCut("pT balance # high"); return true;}
bool A::Execute(){return true;}'''


# These are declared synthetic API text fixtures, never imported/compiled C++.
API = {
 'mc': '''std::set<MAint32> invisible_ids_; std::set<MAint32> hadronic_ids_;
 void Reset(){invisible_ids_.clear();hadronic_ids_.clear();}
 void AddHadronicId(MAint32 id){hadronic_ids_.insert(id);}
 void RemoveHadronicId(MAint32 id){hadronic_ids_.erase(id);}
 void AddInvisibleId(MAint32 id){invisible_ids_.insert(id);}
 void RemoveInvisibleId(MAint32 id){invisible_ids_.erase(id);}''',
 'rec': 'void Reset(){deltaRalgo_=true;deltaR_=0.5;sumPT_=1.;ET_PT_=1.;}',
 'physics': 'MCconfig& mcConfig(){return Id->mcConfig();} RECconfig& recConfig(){return Id->recConfig();}',
 'identification': 'mcConfig_.hadronic_ids_.find(part.pdgid()); mcConfig_.invisible_ids_.find(part.pdgid());',
}
CORE = '''analyzers_[i]->Output()+"/"+analyzers_[i]->name()+".saf";
analyzers_[i]->Output()+"/Histograms/histos.saf";
myanalysis->Output()+"/Cutflows/"+CleanName(myRS->GetName())+".saf";
void ReplaceAll(std::string& name,const std::string& In,const std::string& Out){
size_t pos=name.find(In);while(pos!=std::string::npos){name.replace(pos,In.size(),Out);pos=name.find(In);}}
std::string CleanName(const std::string& name){std::string tmp=name;ReplaceAll(tmp," ","_");return tmp;}'''


def pin(path, raw=None):
    if raw is not None: path.write_text(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def js(path, doc): return pin(path, json.dumps(doc))


def frame(content): return '<SAFheader>\n</SAFheader>\n'+content+'\n<SAFfooter>\n</SAFfooter>\n'


def counters(names):
    content = '<InitialCounter>\n"Initial number of events"\n1 1\n2.5 1.5\n6.25 2.25\n</InitialCounter>\n'
    for name in names:
        content += '<Counter>\n"'+name+'" # 1st cut\n1 1 # nentries\n2.5 1.5 # sumw\n6.25 2.25 # sumw2\n</Counter>\n'
    return frame(content)


def documents(tmp_path, config=CONFIG):
    sp = pin(tmp_path/'analysis.cpp', source(config))
    expected = bookings.compile_source(source(config))
    declared = dict(expected, source=sp, scope='Fabricated literal source; no native claim')
    if config:
        declared['configuration_sources'] = {k: pin(tmp_path/(k+'.h'), v) for k,v in API.items()}
    bp = js(tmp_path/'bookings.json', declared)
    upstream = {'manager': pin(tmp_path/'manager.h', 'fabricated manager'),
                'saf_writer': pin(tmp_path/'writer.cpp', 'fabricated writer'),
                'core': pin(tmp_path/'core.cpp', CORE), 'revision':'fabricated source-control only'}
    root = tmp_path/'SAF'; (root/'Histograms').mkdir(parents=True); (root/'Cutflows').mkdir()
    pin(root/'A.saf', frame('<RegionSelection>\n"SR"\n</RegionSelection>'))
    pin(root/'Histograms/histos.saf', frame(''))
    pin(root/'Cutflows/SR.saf', counters(expected['cuts']['SR']))
    files = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    doc = {'schema_version':2, 'analysis':'A', 'source':sp, 'bookings':bp, 'upstream':upstream,
        'views':{'synthetic': {'root':str(root),'files':files,'expected_initial_entries':2,
                              'population_description':'two fabricated signed counters; not events'}},
        'population_scope':'Synthetic SAF only'}
    return doc, declared


def test_configuration_order_signed_idempotence_and_unknown_inherited_state():
    expected = bookings.compile_source(source())
    c = expected['physics_configuration']
    assert len(c['operations']) == 9
    assert c['mc_state_after_explicit_reset'] == {'hadronic_ids':[211], 'invisible_ids':[-51,51]}
    assert c['rec_state_after_explicit_reset']=={'delta_r_algorithm':True,'delta_r':.5,'sum_pt':1.,'et_pt':1.}
    assert c['native_effective_configuration_observed'] is False
    unknown = bookings.compile_source(source('PHYSICS->mcConfig().AddInvisibleId(51);'))['physics_configuration']
    assert unknown['mc_state_after_explicit_reset'] is None and unknown['rec_state_after_explicit_reset'] is None
    again = bookings.compile_source(source(CONFIG+'PHYSICS->mcConfig().Reset();'))['physics_configuration']
    assert again['mc_state_after_explicit_reset']=={'hadronic_ids':[], 'invisible_ids':[]}


@pytest.mark.parametrize('config', [
 'PHYSICS->mcConfig().AddHadronicId(code);', 'PHYSICS->mcConfig().AddHadronicId(0211);',
 'PHYSICS->mcConfig().AddHadronicId(0xD3);', 'PHYSICS->mcConfig().AddHadronicId(211.0);',
 'PHYSICS->mcConfig().AddHadronicId(2147483648);', 'PHYSICS->mcConfig().AddHadronicId(-2147483649);',
 'PHYSICS->recConfig().AddInvisibleId(51);', 'PHYSICS->mcConfig().Reset("hidden");',
 'PHYSICS->mcConfig().Unknown(51);', 'auto& cfg=PHYSICS->mcConfig();cfg.AddInvisibleId(51);',
 'if(enabled){PHYSICS->mcConfig().Reset();}', 'for(int i=0;i<3;i++){PHYSICS->mcConfig().AddInvisibleId(i);}',
 'PHYSICS->recConfig().UseDeltaRIsolation(.3);', 'Manager()->AddHadronicId(211);',
 'auto deferred=[](){PHYSICS->mcConfig().Reset();};',
 'auto ignored=PHYSICS->mcConfig().Reset();',
 'other.RemoveInvisibleId(51);', 'PHYSICS->mcConfig().AddInvisibleId(1١);',
])
def test_unsafe_dynamic_or_unknown_configuration_refused(config):
    with pytest.raises(ValueError): bookings.compile_source(source(config))


def test_outside_initialize_configuration_is_not_ignored():
    with pytest.raises(ValueError): bookings.compile_source(source().replace('bool A::Execute(){','bool A::Execute(){PHYSICS->mcConfig().Reset();'))


def test_deferred_bookings_are_not_a_literal_output_population():
    with pytest.raises(ValueError): bookings.compile_source('bool A::Initialize(){auto f=[](){Manager()->AddRegionSelection("SR");};return true;}')


def test_config_literals_in_comments_strings_do_not_create_operations():
    expected = bookings.compile_source(source('//PHYSICS->mcConfig().Reset();\nINFO << "AddUnknown(51) mcConfig()";'))
    assert 'physics_configuration' not in expected
    assert expected['cuts']['SR'][0].startswith('#Phi')


def test_native_quoted_hash_titles_and_trailing_comments_preserve_all_channels():
    value = reader.counters(counters(['#Phi < 2','pT # high']))
    assert [x['name'] for x in value['cuts']] == ['#Phi < 2','pT # high']
    assert value['cuts'][0]['negative']=={'nentries':1,'sumw':1.5,'sumw2':2.25}
    assert value['cuts'][1]['native_numeric_tokens']==[['1','1'],['2.5','1.5'],['6.25','2.25']]
    with pytest.raises(ValueError): reader.counters(counters(['#Phi < 2']).replace('"#Phi < 2"','"#Phi < 2'))


def test_family_full_input_graph_literal_delivery_and_legacy_shape(tmp_path):
    doc, declared = documents(tmp_path)
    task = {'input':js(tmp_path/'input.json',doc)['path']}
    graph = ma5_family.inputs(task,tmp_path)
    assert {Path(v['path']) for v in declared['configuration_sources'].values()} <= set(graph)
    result = ma5_family.run(task,tmp_path,tmp_path/'result')
    assert result['source_bookings']['physics_configuration']==declared['physics_configuration']
    assert result['views']['synthetic']['cutflows']['SR']['cuts'][0]['name'].startswith('#Phi')
    assert result['physics_validated'] is False and result['native_engine_executed'] is False
    assert result['views']['synthetic']['event_level_covariance_available'] is False
    legacy = bookings.compile_source(source(''))
    assert set(legacy)=={'regions','cuts','histograms'}


@pytest.mark.parametrize('change',['missing','wrong_state','unknown_pin','api_drift','quoted_api','bool_state'])
def test_family_configuration_declaration_and_api_refusals(tmp_path, change):
    doc, d = documents(tmp_path)
    if change=='missing': d.pop('configuration_sources')
    elif change=='wrong_state': d['physics_configuration']['mc_state_after_explicit_reset']['invisible_ids']=[51]
    elif change=='unknown_pin': d['configuration_sources']['extra']=d['configuration_sources']['mc']
    elif change=='api_drift': d['configuration_sources']['mc']=pin(tmp_path/'mc.h', API['mc'].replace('insert(id)','insert(abs(id))'))
    elif change=='bool_state': d['physics_configuration']['rec_state_after_explicit_reset']['delta_r_algorithm']=1
    else: d['configuration_sources']['rec']=pin(tmp_path/'rec.h', 'INFO << "'+API['rec']+'";')
    doc['bookings']=js(tmp_path/'bookings.json',d)
    js(tmp_path/'input.json',doc)
    with pytest.raises(ValueError): ma5_family.inputs({'input':'input.json'},tmp_path)


def pad_document(tmp_path):
    doc, declared = documents(tmp_path)
    main=pin(tmp_path/'main.cpp','Initialize(argc,argv,"pdg.ma5"); InitializeAnalyzer("A","analysis.saf");')
    exe=pin(tmp_path/'fake-executable','never execute this source-control'); Path(exe['path']).chmod(0o700)
    library=pin(tmp_path/'fake-library','opaque synthetic runtime marker')
    pdg=pin(tmp_path/'pdg.ma5','fabricated PDG asset')
    event=pin(tmp_path/'events.lhe','not physical events; never execute')
    runtime={'executable':exe,'main':main,'files':[library]}
    assets={'pdg.ma5':pdg}
    runtime['build_receipt']=js(tmp_path/'build.json',dict(executable=exe,main=main,source=doc['source'],
        assets=assets,runtime_files=[library],scope='Declared synthetic build only'))
    upstream=dict(doc['upstream'],configuration=pin(tmp_path/'configuration.h','fabricated runtime Configuration'))
    return dict(schema_version=1,analysis='A',source=doc['source'],bookings=doc['bookings'],upstream=upstream,
       runtime=runtime,events=[event],staged_assets=assets,population=dict(expected_initial_entries=2,
       description='two synthetic counters only',basis='signed_interference',weight_convention='declared only',response='unqualified'),
       max_seconds=1,max_ram_mib=512), declared


def test_pad_admission_graph_includes_config_and_unapproved_run_refuses(tmp_path):
    doc,d = pad_document(tmp_path); task={'input':js(tmp_path/'pad.json',doc)['path']}
    graph=ma5_pad.inputs(task,tmp_path)
    assert {Path(v['path']) for v in d['configuration_sources'].values()}<=set(graph)
    assert ma5_pad.execution_seconds(task,tmp_path)==31
    with pytest.raises(ValueError,match='ordinary approved'):ma5_pad.run(task,tmp_path,tmp_path/'unauthorized')
    assert not (tmp_path/'unauthorized').exists()
    assert science.adapter({'mode':'ma5-pad','task':task}) is ma5_pad


def test_pad_readback_rebases_configuration_pins_at_original_booking_base(tmp_path,monkeypatch):
    doc,d=pad_document(tmp_path)
    # Relative config pins belong to the original declaration, not pad-work.
    for pinvalue in d['configuration_sources'].values(): pinvalue['path']=Path(pinvalue['path']).name
    doc['bookings']=js(tmp_path/'bookings.json',d); task={'input':js(tmp_path/'pad.json',doc)['path']}
    rd=tmp_path/'ordinary'; rd.mkdir(); (rd/science.PLAN).parent.mkdir(); (rd/science.PLAN).write_text('{}')
    out=rd/'outputs'; spec={'mode':'ma5-pad','task':task}
    monkeypatch.setattr(science,'verify_worker',lambda _:dict(output_directory='outputs',max_seconds=31))
    monkeypatch.setattr(science,'execution_spec',lambda _:spec)
    # Only native dispatch is substituted. Real _load, copies, complete readback
    # and family.run execute on fabricated bytes under the ordinary API.
    from ravel.physics import reinterpret_db
    def inert(command,build,config):
        root=build.parent/'Output/SAF/supplied/A_0'
        (root/'Histograms').mkdir(parents=True); (root/'Cutflows').mkdir()
        (root/'A.saf').write_text(frame('<RegionSelection>\n"SR"\n</RegionSelection>'))
        (root/'Histograms/histos.saf').write_text(frame(''))
        (root/'Cutflows/SR.saf').write_text(counters(d['cuts']['SR']))
        return {'scope':'inert synthetic dispatch; not native execution'}
    monkeypatch.setattr(reinterpret_db,'execute_native',inert)
    result=ma5_pad.run(task,tmp_path,out)
    assert result['source_bookings']['physics_configuration']==d['physics_configuration']
    book=json.loads((out/'pad-bookings.json').read_text())
    assert all(Path(p['path']).is_absolute() for p in book['configuration_sources'].values())
    assert result['source_consumption_verified'] is False
