"""Portable file bridge controls and supplied executions of real source bodies."""
from pathlib import Path
import hashlib,json
import pytest
from ravel.physics import agentrivet_candidate as bridge
from ravel import analysis_sources
from ravel.physics import routine_build

CODE=b'#include "Rivet/Analysis.hh"\nnamespace Rivet { class TEST : public Analysis {}; RIVET_DECLARE_PLUGIN(TEST); }\n'
MODEL={'beam_energy':'13 TeV','process':'test process','object_construction':'supplied particles','cuts':['pT > 1 GeV'],
 'histograms':[{'name':'pt','observable_definition':'selected particle pT','binning_source':'TEXT','hepdata_id':None,'bin_edges':[0,1,2],'description':None}],
 'hepdata_url':None,'fiducial_definition':'supplied example, no physics claim'}
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def fixture(root,*,accepted=False,code=CODE):
    root.mkdir();paper=root/'paper.txt';paper.write_bytes(b'literal supplied paper text\n')
    cc=root/'TEST.cc';cc.write_bytes(code)
    m={'paper_text':paper.read_text(),'code_draft':[code.decode()],
      'analysis_model':{'__kind__':'pydantic','__class__':'AnalysisModel','data':MODEL},
      'code_review':[{'__kind__':'pydantic','__class__':'CodeReviewModel','data':{'approved':True,'summary':'supplied','blockers':[],'revision_focus':None}}],
      'physics_review':[{'__kind__':'pydantic','__class__':'PhysicsReviewModel','data':{'summary':'still wrong','advisories':['wrong selection'],'revision_focus':'fix selection'}}]}
    if accepted:m['accepted_code']=code.decode()
    memory=root/'memory.json';memory.write_text(json.dumps(m))
    return {'schema_version':1,'routine':'TEST','paper':pin(paper),'memory':pin(memory),'translation_unit':pin(cc),'assets':[]}
def read(ref):return json.loads(Path(ref['path']).read_bytes())

@pytest.mark.parametrize('accepted',[False,True])
def test_import_preserves_bytes_whole_declaration_and_no_authority(tmp_path,accepted):
    request=fixture(tmp_path/'input',accepted=accepted)
    result=bridge.import_candidate(request,base_dir=tmp_path,output_dir=tmp_path/'out')
    capsule=read(result['capsule']);proposal=read(result['proposal'])
    assert (Path(capsule['root'])/'TEST.cc').read_bytes()==CODE
    assert (Path(capsule['root'])/'provenance/memory.json').read_bytes()==Path(request['memory']['path']).read_bytes()
    assert analysis_sources.inventory(capsule,tmp_path)['declared_files_verified']==4
    assert len(proposal['obligations'])==7 and all(not o['paper_fidelity_verified'] for o in proposal['obligations'])
    assert proposal['upstream_code_acceptance_asserted']==accepted
    assert proposal['upstream_reviews']['physics_review'][0]['data']['revision_focus']=='fix selection'
    assert not any(proposal[k] for k in ('execution_authorized','physics_validated','scientific_acceptance','provider_model_calls_authenticated'))
    assert proposal['AgentGraph_model_receipt'] is None and not capsule['dependency_review']['complete']

def test_real_routine_build_rejects_unreviewed_import(tmp_path):
    req=fixture(tmp_path/'input');result=bridge.import_candidate(req,base_dir=tmp_path,output_dir=tmp_path/'out')
    proposal=read(result['proposal']);config={'schema_version':1,'source_capsule':result['capsule']['path'],'recipe':proposal['next_build_recipe'],'runtime':{},'probe':{}}
    p=tmp_path/'build-unreviewed.json';p.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='unresolved declared transitive dependency'):
        routine_build.seal_configuration({'backend':'routine-build','input':str(p)},tmp_path)

def test_explicit_reference_asset_preserved_without_mapping_inference(tmp_path):
    req=fixture(tmp_path/'input');asset=tmp_path/'ref.yoda';asset.write_bytes(b'literal supplied reference bytes\n')
    req['assets']=[{'path':'TEST.yoda','role':'reference','input':pin(asset)}]
    result=bridge.import_candidate(req,base_dir=tmp_path,output_dir=tmp_path/'out')
    c=read(result['capsule']);assert (Path(c['root'])/'TEST.yoda').read_bytes()==asset.read_bytes()
    assert c['layout']['asset_dirs']==['.'] and not c['dependency_review']['complete']

@pytest.mark.parametrize('mutation',['hash','substitute','duplicate_json','nonfinite','symlink','overwrite','escape','asset_collision'])
def test_adverse_inputs_refuse(tmp_path,mutation):
    req=fixture(tmp_path/'input');out=tmp_path/'out'
    if mutation=='hash':Path(req['translation_unit']['path']).write_bytes(b'changed')
    elif mutation=='substitute':
        p=Path(req['translation_unit']['path']);p.write_bytes(b'other source');req['translation_unit']=pin(p)
    elif mutation in ('duplicate_json','nonfinite'):
        p=Path(req['memory']['path']);p.write_bytes(b'{"x":1,"x":2}' if mutation=='duplicate_json' else b'{"x":1e999}');req['memory']=pin(p)
    elif mutation=='symlink':
        p=tmp_path/'link.cc';p.symlink_to(req['translation_unit']['path']);req['translation_unit']['path']=str(p)
    elif mutation=='overwrite':out.mkdir()
    else:req['assets']=[{'path':'../outside' if mutation=='escape' else 'TEST.cc','role':'data','input':req['paper']}]
    with pytest.raises(ValueError):bridge.import_candidate(req,base_dir=tmp_path,output_dir=out)

def test_fenced_failed_draft_retained_as_failure_not_claimed_compilable(tmp_path):
    source=b'```cpp\ninvalid C++\n```\n';req=fixture(tmp_path/'input',code=source)
    result=bridge.import_candidate(req,base_dir=tmp_path,output_dir=tmp_path/'out')
    c=read(result['capsule']);assert (Path(c['root'])/'TEST.cc').read_bytes()==source
    assert read(result['proposal'])['literal_registration_observation']['TEST']['registration']=='declared-capsule-primary'
    assert not c['dependency_review']['complete']

def test_consumption_uses_authenticated_bytes_not_later_read_text(tmp_path,monkeypatch):
    req=fixture(tmp_path/'input');original=Path.read_text
    def no_reread(path,*a,**k):
        if path==Path(req['memory']['path']):pytest.fail('unverified parse reread')
        return original(path,*a,**k)
    monkeypatch.setattr(Path,'read_text',no_reread)
    assert bridge.import_candidate(req,base_dir=tmp_path,output_dir=tmp_path/'out')

def test_different_truthful_paper_pin_cannot_replace_cached_Analyst_input(tmp_path):
    req=fixture(tmp_path/'input');p=Path(req['paper']['path']);p.write_bytes(b'other truthful paper pin\n');req['paper']=pin(p)
    with pytest.raises(ValueError,match='paper text differs'):bridge.import_candidate(req,base_dir=tmp_path,output_dir=tmp_path/'out')

def test_declared_file_ceiling_refuses_before_materialization(tmp_path,monkeypatch):
    req=fixture(tmp_path/'input');monkeypatch.setattr(bridge,'MAX_FILE_BYTES',1)
    with pytest.raises(ValueError,match='bounded regular file'):bridge.import_candidate(req,base_dir=tmp_path,output_dir=tmp_path/'out')
    assert not (tmp_path/'out').exists()




@pytest.mark.parametrize('url',[None,'https://www.hepdata.net/record/ins1012'])
def test_hepdata_url_is_explicit_unverified_declaration_including_null(tmp_path,url):
    req=fixture(tmp_path/'input');p=Path(req['memory']['path']);m=json.loads(p.read_bytes())
    m['analysis_model']['data']['hepdata_url']=url;p.write_text(json.dumps(m));req['memory']=pin(p)
    result=bridge.import_candidate(req,base_dir=tmp_path,output_dir=tmp_path/'out')
    declarations=[o for o in read(result['proposal'])['obligations'] if o['selector']=='/analysis_model/data/hepdata_url']
    assert len(declarations)==1 and declarations[0]['declaration']==url
    assert declarations[0]['status']=='unverified_supplier_claim' and declarations[0]['paper_fidelity_verified'] is False
