"""Prospective CI3 consumer controls, authored but never run by the author.

Real build/qualification/execution-custody and final source-lineage APIs are used
with explicitly inert native, approval, writer-review and ROOT-projection seams.
They establish software behavior only, never actual qualification or blinding.
The 4097-leaf test isolates the real CI3 tree/capacity consumer behind an explicit
verified-build API fixture; the small complete control uses real verified_result.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
from ravel.physics import manuscript_build as mb
from ravel.workflow import execution, final_results_review as fr, manuscript_production as mp
from ravel.workflow import publication_runtime as pr, report_integrity as ri, science, scientific_autonomy
from test_publication_runtime_v2 import LIMITS, pin, put, qualification_fixture
from test_manuscript_six_findings import projection_fixture


def author_envelope(package_pin,package,safe):
    products=[package_pin,*[package[k] for k in ('latex','manuscript','integrity_request',
        'model_provenance','formatting_assessment_pin','author_binding')]]
    return {'outputs':{p['path']:p for p in products},'data':[safe],
        'support':[package['formatting_contract']],'machinery':[],'custody_only':[],
        'proof_pins':[safe,*products],'assessment':{'inert_review_fixture':True}}


def evidence_for(root,policy,projections,safe,package_pin,author,binding,pdf,input_paths):
    producer={'kind':'authored_manuscript','package':package_pin,'bindings':[{'inert_review':True}]}
    lineage=[{'artifact':p,'producer':producer,'inputs':[safe]} for p in author['outputs'].values()]
    data=[safe,*[p for path,p in author['outputs'].items() if path in input_paths]]
    lineage.append({'artifact':pdf,'producer':{'kind':'manuscript_build','binding':binding,
        'package':package_pin,'bindings':[{'inert_review':True}]},'inputs':data})
    artifacts=[{'path':p['path'],'sha256':p['sha256'],'role':'source_output'} for p in author['outputs'].values()]
    artifacts.append({'path':pdf['path'],'sha256':pdf['sha256'],'role':'figure'})
    return {'schema_version':2,'kind':'source_bound_final_blinding','policy':policy,
        'projections':projections,'lineage':lineage},artifacts


def complete_fixture(root,monkeypatch,*,current_extra=None):
    policy,projections,safe=projection_fixture(root,monkeypatch)
    task,c,rt,result,observations,calls,qualifier=qualification_fixture(root,monkeypatch)
    qualified=pr.qualify(rt['closure_manifest'],observations,root/'qualified-runtime.json')
    package=json.loads(Path(c['package']['path']).read_text())
    package['input_pins']=[safe]
    if current_extra=='prior-custody':package['input_pins'].append(pin(Path(c['package']['path'])))
    if current_extra=='unrelated':package['input_pins'].append(put(root/'unrelated-data.json',{'private':17}))
    package_pin=put(root/'current-public-package.json',package)
    normal=deepcopy(c);normal['package']=package_pin
    normal['runtime'].update({'purpose':'qualified','closure_manifest':qualified})
    normal_task={'config':put(root/'current-qualified-config.json',normal)['path']}
    rd=root/'current-ordinary';rd.mkdir();output=rd/'outputs';output.mkdir();build=output/'build'
    original_spec=science.execution_spec
    monkeypatch.setattr(science,'execution_spec',lambda p,**k:
        {'schema_version':2,'mode':'manuscript-build','task':deepcopy(normal_task)} if Path(p)==rd else original_spec(p,**k))
    paths=mb.inputs(normal_task,root)
    declaration=execution.plan_stage(rd,'render',[sys.executable,'-c','pass'],[str(p) for p in paths],[str(output)],[],str(rd))
    record=execution.begin_attempt(rd,'render',declaration,'logs/supervisor.log')
    current=mb.run(normal_task,root,build)
    (rd/'logs/supervisor.log').write_text('Synthetic inert native returns; no process or compiler ran.\n')
    execution.finish_attempt(rd,record,0);record=execution.load_execution(rd)['stages']['render']
    binding={'rundir':str(rd),'receipt':pin(execution.resolve_path(rd,record['attempt_record'])),
        'result':pin(build/'manuscript-build.json')}
    built=mb.verified_result(binding,base_dir=root)
    author=author_envelope(package_pin,package,safe)
    monkeypatch.setattr(mp,'verified_products',lambda *a,**k:deepcopy(author)) # Explicit review boundary only.
    evidence,artifacts=evidence_for(root,policy,projections,safe,package_pin,author,binding,current['pdf'],built['input_paths'])
    return {'policy':policy,'evidence':evidence,'artifacts':artifacts,'built':built,'binding':binding,
        'runtime':rt,'qualified':qualified,'observations':observations,'calls':calls,'qualifier':qualifier,
        'qualifier_task':task,'qualifier_config':c,'qualifier_result':result}


def test_public_ci3_preparation_accepts_actual_verified_runtime_proof_without_presenting_old_paper(tmp_path,monkeypatch):
    f=complete_fixture(tmp_path,monkeypatch)
    proof=fr._source_blinding(tmp_path,f['evidence'],{k:f['policy'][k] for k in ('path','sha256')},f['artifacts'])
    prior={p['path'] for p in f['built']['runtime_lineage']['qualification_custody']}
    assert f['qualifier_task']['config'] in prior
    # A prior file may also be a current independently authenticated author
    # product. Only genuinely prior-only custody must stay out of model proof.
    from ravel.physics import root_stream
    from ravel.workflow import scientific_report
    current_source=[pin(Path(module.__file__).resolve()) for module in (root_stream,scientific_report,execution)]
    expected_source={(row['path'],row['sha256']) for row in current_source}
    assert expected_source<={(row['path'],row['sha256']) for row in proof}
    # These three exact current consumer sources are independently admitted by
    # _source_blinding, even when the qualifier also consumed them. They are
    # current proof rather than private prior-only paper/data.
    prior_only=prior-{row['path'] for row in f['artifacts']}-{row['path'] for row in current_source}
    assert f['qualifier_task']['config'] in prior_only
    assert not prior_only&{p['path'] for p in proof}
    assert f['qualified']['path'] in {p['path'] for p in f['built']['runtime_lineage']['metadata']}
    prepared=fr.prepare_blinding_check(tmp_path,tmp_path/'ci3-source-evidence.json',policy=f['policy'],
        projections=f['evidence']['projections'],lineage=f['evidence']['lineage'],artifacts=f['artifacts'])
    assert json.loads(Path(prepared['path']).read_text())==f['evidence']
    assert len(f['calls'])==6 # All six were explicit inert Python returns, no tool launch.


@pytest.mark.parametrize('change',['changed','missing','foreign'])
def test_ci3_last_public_read_rechecks_original_qualification_proof(tmp_path,monkeypatch,change):
    f=complete_fixture(tmp_path,monkeypatch);real=scientific_autonomy._document;verified=mb.verified_result
    count=[0];fired=[False]
    def observe(*a,**k):
        result=verified(*a,**k);count[0]+=1;return result
    monkeypatch.setattr(mb,'verified_result',observe)
    pdf=f['built']['result']['pdf']['path']
    def last_read(p,*a,**k):
        result=real(p,*a,**k)
        if count[0] and p['path']==pdf and not fired[0]:
            fired[0]=True
            if change=='changed':Path(f['runtime']['closure_manifest']['path']).write_text('{"changed":true}\n')
            if change=='missing':Path(f['observations']['compiler']['receipt']['path']).unlink()
            if change=='foreign':
                doc=json.loads(Path(f['qualified']['path']).read_text())
                doc['qualification']['observations']['compiler']['receipt']=f['binding']['receipt']
                put(Path(f['qualified']['path']),doc)
        return result
    monkeypatch.setattr(scientific_autonomy,'_document',last_read)
    with pytest.raises((ValueError,OSError,KeyError)):
        fr._source_blinding(tmp_path,f['evidence'],{k:f['policy'][k] for k in ('path','sha256')},f['artifacts'])
    assert fired[0] and count[0]>=1 # The injection occurred after actual beginning verification.


@pytest.mark.parametrize('source',['prior-custody','unrelated'])
def test_prior_qualification_custody_cannot_launder_current_or_unrelated_data(tmp_path,monkeypatch,source):
    f=complete_fixture(tmp_path,monkeypatch,current_extra=source)
    assert f['built']['result']['runtime_qualified'] is True # Producer/runtime positive, not an early fixture failure.
    with pytest.raises(ValueError,match='authenticated data/support/runtime lineage'):
        fr._source_blinding(tmp_path,f['evidence'],{k:f['policy'][k] for k in ('path','sha256')},f['artifacts'])


def test_qualification_purpose_cannot_be_used_as_final_ci3_build(tmp_path,monkeypatch):
    f=complete_fixture(tmp_path,monkeypatch)
    row=f['evidence']['lineage'][-1]
    row['producer']['binding']={'rundir':str(f['qualifier']),
        'receipt':f['observations']['compiler']['receipt'],
        'result':pin(f['qualifier']/'outputs/build/manuscript-build.json')}
    with pytest.raises(ValueError,match='qualification-purpose'):
        fr._source_blinding(tmp_path,f['evidence'],{k:f['policy'][k] for k in ('path','sha256')},f['artifacts'])


@pytest.mark.parametrize('policy',['selected','legacy','small-union'])
def test_ci3_real_4097_tree_uses_original_selected_policy_and_complete_union(tmp_path,monkeypatch,policy):
    """Real tree and final consumer; explicit inert verified-build authority seam."""
    blind,projections,safe=projection_fixture(tmp_path,monkeypatch)
    assets=tmp_path/'runtime';assets.mkdir()
    leaves=[put(assets/(str(i)+'.sty'),b'x') for i in range(4097)]
    manifest=put(tmp_path/'runtime-tree.json',{'schema_version':1,'files':{Path(p['path']).name:p['sha256'] for p in leaves}})
    compiler=put(tmp_path/'pdflatex',b'INERT');pdfinfo=put(tmp_path/'pdfinfo',b'INERT')
    tree={'root':str(assets),'manifest':{k:manifest[k] for k in ('path','sha256')}}
    pkg={'source_base':str(tmp_path),'input_pins':[safe],'latex':put(tmp_path/'note.tex',b'INERT'),
        'manuscript':put(tmp_path/'paper.md',b'INERT'),'integrity_request':put(tmp_path/'integrity.json',{}),
        'model_provenance':put(tmp_path/'model.json',{}),'formatting_assessment_pin':put(tmp_path/'format-assessment.json',{}),
        'author_binding':put(tmp_path/'author.json',{}),'formatting_contract':put(tmp_path/'format.json',{})}
    package=put(tmp_path/'package.json',pkg);author=author_envelope(package,pkg,safe)
    pdf=put(tmp_path/'current.pdf',b'%PDF-SYNTHETIC-CONSUMER-ONLY\n')
    receipt=put(tmp_path/'receipt.json',{'output_snapshot':{pdf['path']:{'kind':'file','files':[{'name':'.','sha256':pdf['sha256'],'size':pdf['size']}]}}})
    limits=ri.custody_limits(None) if policy=='legacy' else {**LIMITS,**({'max_files':4097} if policy=='small-union' else {})}
    config=put(tmp_path/'config.json',{'explicit_capacity_fixture':True})
    binding={'rundir':str(tmp_path),'receipt':receipt,'result':receipt}
    all_runtime=[compiler,pdfinfo,manifest,*leaves]
    paths=[p['path'] for p in [config,*author['outputs'].values(),pkg['formatting_contract'],safe,*all_runtime]]
    built={'config':{'schema_version':1 if policy=='legacy' else 2,'runtime_base':str(tmp_path),
        'runtime':{'compiler':{k:compiler[k] for k in ('path','sha256')},'pdfinfo':{k:pdfinfo[k] for k in ('path','sha256')},'svg_converter':None,'asset_trees':[tree]}},
        'config_path':config['path'],'package':pkg,'result':{'package':package},'input_paths':paths,
        'custody_limits':limits,'custody_pins':[config,*author['outputs'].values(),pkg['formatting_contract'],safe,*all_runtime],
        'proof_pins':[receipt,pdf],'runtime_lineage':{'runtime':[compiler,pdfinfo,*leaves],'metadata':[manifest],'qualification_custody':[]}}
    monkeypatch.setattr(mb,'verified_result',lambda *a,**k:deepcopy(built)) # Isolate actual CI3 capacity; no ordinary success claimed.
    monkeypatch.setattr(mp,'verified_products',lambda *a,**k:deepcopy(author))
    evidence,artifacts=evidence_for(tmp_path,blind,projections,safe,package,author,binding,pdf,paths)
    if policy=='selected':
        assert fr._source_blinding(tmp_path,evidence,{k:blind[k] for k in ('path','sha256')},artifacts)
    else:
        with pytest.raises(ValueError):fr._source_blinding(tmp_path,evidence,{k:blind[k] for k in ('path','sha256')},artifacts)
