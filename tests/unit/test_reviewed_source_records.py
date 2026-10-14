"""Synthetic supplied source records; no upstream execution or stored study inputs."""
import hashlib
import json
from pathlib import Path
import pytest
from ravel.physics import published_model, sfitter_card_derivation, sfitter_higgs_support, compressed_validation


def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def test_erratum_requires_explicit_byte_bound_review(tmp_path,monkeypatch):
    monkeypatch.delenv(published_model.REFERENCE_ACKS_ENV,raising=False)
    from test_published_model import fixture
    document,_,_=fixture(tmp_path)
    document['source_reference_acknowledgment']={'kind':'ANA-0001','field':'/metadata/references/hepdata',
        'observed':'unattributed','external_record':{'path':'missing.json','sha256':'0'*64}}
    with pytest.raises(ValueError) as error:published_model.validate_document(document)
    assert getattr(error.value,'reason',None)=='missing_reviewed_erratum'


def test_card_repair_has_no_builtin_selection(tmp_path):
    with pytest.raises(ValueError) as error:sfitter_card_derivation.derive(tmp_path,'ANA-0001.json')
    assert getattr(error.value,'reason',None)=='missing_repair_manifest'


def test_support_requires_reviewed_defect_registry(tmp_path):
    card={'observations':[],'predictions':[]}
    with pytest.raises(ValueError) as error:sfitter_higgs_support.require_supported(tmp_path,card)
    assert getattr(error.value,'reason',None)=='missing_defect_registry'


def test_cutflow_has_no_builtin_predicate_population():
    with pytest.raises(ValueError) as error:compressed_validation.new_event(1,1.)
    assert getattr(error.value,'reason',None)=='missing_cutflow_definition'


def context(variant):
    return {'identity':'ANA-0002' if variant else 'ANA-0001',
            'parameters':{'second':[2,4,6]} if variant else {'first':[0,1]},
            'datasets':['sample-b','sample-c'] if variant else ['sample-a'],
            'output_format':'jsonl' if variant else 'json',
            'card_output':'alternate.json' if variant else 'selected.json'}


def synthetic_card(rows=2):
    return {'observations':[{'ID':'row-'+str(i),'name':'fictional-'+str(i),'Meas':{'data':[i+1.]}} for i in range(rows)],
            'predictions':[{'ID':'row-'+str(i),'name':'fictional-'+str(i),'data':[i+1.],
                'modifiers':[{'name':'a','data':[2.]},{'name':'b','data':[3.]},{'name':'a','data':[0.]}]} for i in range(rows)]}


@pytest.mark.parametrize('variant',[False,True])
def test_supplied_repairs_preserve_lineage_and_runtime_contract(tmp_path,variant):
    from source_record_fixtures import reviewed,write,defect_registry
    card=synthetic_card(3 if variant else 2)
    card['observations'].append(json.loads(json.dumps(card['observations'][0])))
    card['predictions'].append(json.loads(json.dumps(card['predictions'][0])))
    cp=tmp_path/('ANA-0002.json' if variant else 'ANA-0001.json');cpin=write(cp,card)
    registry=defect_registry(tmp_path,card,context=context(variant))
    before=json.loads(json.dumps(card))
    manifest=reviewed(tmp_path,'repair-manifest',{'card':cpin},context=context(variant),card_source='card',
        defect_registry=registry,identity_template='{identity}__source_{row}',transforms=[
            {'operation':'coalesce','path':'/observations','keep':0,'remove':len(card['observations'])-1},
            {'operation':'replace','path':'/observations/1/Meas/data','expected':[2.],'value':[4.] if variant else [5.]},
            {'operation':'project-last','path':'/predictions/0/modifiers','expected':card['predictions'][0]['modifiers'],'key':'name'},
            {'operation':'retain','path':'/predictions/1/data','expected':[2.]}])
    mpin=write(tmp_path/'repairs.json',manifest)
    derived,proof=sfitter_card_derivation.derive(tmp_path,cp.name,mpin)
    assert derived['observations'][1]['Meas']['data']==([4.] if variant else [5.])
    assert derived['predictions'][0]['modifiers']==[{'name':'b','data':[3.]},{'name':'a','data':[0.]}]
    assert proof['rows'][0]['original_indices']==[0,len(card['observations'])-1]
    assert proof['changes'][2]['before']==card['predictions'][0]['modifiers']
    assert len(proof['rows'])==(3 if variant else 2) and proof['context']==context(variant)
    assert json.loads(cp.read_text())==before and proof['physics_validated'] is False
    result=sfitter_card_derivation.materialize(tmp_path,cp.name,tmp_path.parent/(tmp_path.name+'-derived'),mpin)
    assert Path(result['derived_card']['path']).name==context(variant)['card_output']
    assert json.loads(Path(result['derived_card']['path']).read_text())==derived


@pytest.mark.parametrize('variant',[False,True])
def test_support_contract_identity_grid_population_format_are_supplied(tmp_path,variant):
    from source_record_fixtures import defect_registry
    card=synthetic_card(3 if variant else 2)
    registry=defect_registry(tmp_path,card,context=context(variant),assumptions=[{'law':'supplied-law-'+str(variant)}])
    result=sfitter_higgs_support.require_supported(tmp_path,card,registry)
    assert result['scientific_input_support']['context']==context(variant)
    assert result['native_law_assumptions']==[{'law':'supplied-law-'+str(variant)}]
    assert result['scientific_input_holds']==[]
    with pytest.raises(ValueError) as error:sfitter_higgs_support.require_supported(tmp_path,synthetic_card(4),registry)
    assert error.value.reason=='missing_input_review'


@pytest.mark.parametrize('rename',[False,True])
def test_active_hold_survives_labels_numeric_spelling_and_needs_bound_resolution(tmp_path,rename):
    from source_record_fixtures import reviewed,write
    card=synthetic_card(2);held={'id':'response-defect','source':'card','observation_pointer':'/observations/1',
        'prediction_pointer':'/predictions/1','reason':'unknown physical response','resolution_required':'independent source review'}
    value=reviewed(tmp_path,'defect-registry',{'card':write(tmp_path/'card.json',card)},coverage=[],defects=[held],resolutions=[])
    registry=write(tmp_path/'registry.json',value)
    if rename:
        card['observations'][1]['ID']=card['predictions'][1]['ID']='renamed'
        card['observations'][1]['name']=card['predictions'][1]['name']='renamed'
        card['observations'][1]['Meas']['data']=[2]
    with pytest.raises(sfitter_higgs_support.HiggsInputSupportError) as error:
        sfitter_higgs_support.require_supported(tmp_path,card,registry)
    assert error.value.reason=='unresolved_source_defect'
    assert error.value.support['scientific_input_holds'][0]['input_observation_index']==1
    # Removing the held row gives no review of the remaining population.
    with pytest.raises(ValueError) as missing:
        sfitter_higgs_support.require_supported(tmp_path,{'observations':card['observations'][:1],'predictions':card['predictions'][:1]},registry)
    assert missing.value.reason=='missing_input_review'
    fingerprint=sfitter_higgs_support.fingerprint(card)
    value['coverage']=[{'input_fingerprint':fingerprint,'assumptions':[],'support':{}}]
    value['sources']['resolution']=write(tmp_path/'resolution.json',{'review':'fictional physical resolution'})
    value['resolutions']=[{'defect_id':held['id'],'input_fingerprint':fingerprint,'evidence':['resolution'],'disposition':'resolved'}]
    registry=write(tmp_path/'registry.json',value)
    assert sfitter_higgs_support.require_supported(tmp_path,card,registry)['scientific_input_holds']==[]
    Path(value['sources']['resolution']['path']).write_text('changed')
    with pytest.raises(ValueError,match='bytes changed'):sfitter_higgs_support.require_supported(tmp_path,card,registry)


@pytest.mark.parametrize('variant',[False,True])
def test_cutflows_accept_supplied_axes_population_mapping_and_format(tmp_path,variant):
    from source_record_fixtures import cutflow
    binding,definition=cutflow(tmp_path,variant=variant)
    bound=compressed_validation.bind(binding)
    data=[]
    for i,weight in enumerate([1.,2.,3.,4.] if variant else [1.,2.,3.]):
        row=bound.new_event(i,weight)
        row['predicates'].update({key:True for key in definition['predicates'] if key not in definition['unavailable']})
        row['predicates']['threshold']=i<2
        data.append(row)
    path=tmp_path/'trace.gz';bound.write_trace(path,data,{'input_events':len(data)})
    report=compressed_validation.summarize_trace(path)
    flow=next(iter(definition['flows']))
    assert report['context']==definition['context'] and report['all_events']['count']==len(data)
    assert set(report['cutflows'])=={flow}
    assert report['reference_cutflows'][flow]['reference_luminosity_pb_inverse']==(200 if variant else 100)
    assert report['reference_cutflows'][flow]['rows'][2]['native_cumulative_weighted_events_at_reference_lumi']==(600 if variant else 300)
    out=tmp_path/('result.jsonl' if variant else 'result.json')
    assert compressed_validation.main(['--trace',str(path),'--definition',binding['path'],
        '--definition-sha256',binding['sha256'],'--out',str(out),'--format',definition['context']['output_format']])==0
    assert json.loads(out.read_text())==report
    assert ('\n' in out.read_text().strip()) is (not variant)


@pytest.mark.parametrize('variant',[False,True])
def test_errata_contract_is_explicit_scoped_and_custody_bound(tmp_path,variant):
    from source_record_fixtures import reviewed,write
    from test_published_model import fixture
    d,_,_=fixture(tmp_path)
    d['coordinates']={'axis-b':4} if variant else {'axis-a':2}
    record={'identity':'ANA-0002' if variant else 'ANA-0001','datasets':['b','c'] if variant else ['a']}
    epin=write(tmp_path/'external.json',record)
    field='/metadata/references/supplied' if variant else '/metadata/references/hepdata'
    entry={'id':'supplied-erratum','source':d['source'],'archive_sha256':d['archive']['sha256'],
        'members':d['members'],'field':field,'observed':'placeholder','external_record_source':'external',
        'external_assertions':[{'pointer':'/identity','expected':record['identity']},{'pointer':'/datasets','expected':record['datasets']}]}
    registry=reviewed(tmp_path,'errata-registry',{'external':epin},errata=[entry],context=context(variant))
    rpin=write(tmp_path/'errata.json',registry)
    d['source_reference_acknowledgment']={'kind':entry['id'],'field':field,'observed':'placeholder',
        'external_record':epin,'reviewed_registry':rpin}
    assert published_model.validate_document(d)==d
    meta={'references':{'supplied' if variant else 'hepdata':'placeholder'}}
    result=published_model._verified_reference_acknowledgment(d,meta,tmp_path)
    assert result['field']==field and result['source_bytes_modified'] is False
    assert rpin in result['reviewed_inputs'] and epin in result['reviewed_inputs']
    for change in ('member','field','source'):
        mutated=json.loads(json.dumps(d))
        if change=='member':mutated['members']['patchset']['sha256']='0'*64
        elif change=='field':mutated['source_reference_acknowledgment']['field']='/metadata/other'
        else:mutated['source']['record_id']='ANA-0003'
        with pytest.raises(ValueError) as error:published_model.validate_document(mutated)
        assert error.value.reason=='source_scope_mismatch'
    Path(epin['path']).write_text('changed')
    with pytest.raises(ValueError,match='bytes changed'):published_model.validate_document(d)


def test_owned_modules_have_no_compiled_source_roster_or_reference_population():
    import ast,re
    for module in (sfitter_card_derivation,sfitter_higgs_support,compressed_validation):
        tree=ast.parse(Path(module.__file__).read_text())
        strings=[n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
        assert not any(re.fullmatch('[0-9a-f]{64}',value) for value in strings)
    assert not hasattr(sfitter_card_derivation,'SOURCES')
    assert not hasattr(sfitter_higgs_support,'CARDS')
    assert not hasattr(compressed_validation,'REFERENCE_ROWS')
    assert not hasattr(compressed_validation,'PREDICATES')
    assert not hasattr(published_model,'_ACK_FIELD')


def test_reader_refuses_duplicate_keys_and_nonfinite_values():
    from ravel.physics.reviewed_source import document
    with pytest.raises(ValueError):document('{"a":1,"a":2}')
    with pytest.raises(ValueError):document('{"a":NaN}')
    with pytest.raises(ValueError):document('{"a":1e999}')


def test_repair_copy_tracks_supplied_predecessor_and_preserves_original(tmp_path):
    from source_record_fixtures import reviewed,write,defect_registry
    card=synthetic_card(1);cp=tmp_path/'ANA-0001.json';cpin=write(cp,card)
    predecessor=write(tmp_path/'predecessor.json',{'measurement':[7.]})
    registry=defect_registry(tmp_path,card)
    manifest=reviewed(tmp_path,'repair-manifest',{'card':cpin,'predecessor':predecessor},card_source='card',
        defect_registry=registry,identity_template='{identity}_{row}',transforms=[{'operation':'copy',
        'path':'/observations/0/Meas/data','expected':[1.],'source':'predecessor','source_path':'/measurement'}])
    mpin=write(tmp_path/'manifest.json',manifest)
    output,proof=sfitter_card_derivation.derive(tmp_path,cp.name,mpin)
    assert output['observations'][0]['Meas']['data']==[7.]
    assert proof['changes'][0]['before']==[1.] and proof['changes'][0]['after']==[7.]
    assert predecessor in proof['inputs'] and json.loads(cp.read_text())==card


def test_unresolved_defect_precedes_any_repair_publication(tmp_path):
    from source_record_fixtures import reviewed,write
    card=synthetic_card(1);cp=tmp_path/'ANA-0001.json';cpin=write(cp,card)
    registry=reviewed(tmp_path,'defect-registry',{'card':cpin},coverage=[],resolutions=[],defects=[{
        'id':'unresolved','source':'card','observation_pointer':'/observations/0','prediction_pointer':'/predictions/0',
        'reason':'unknown response','resolution_required':'independent reviewed resolution'}])
    rpin=write(tmp_path/'registry.json',registry)
    manifest=reviewed(tmp_path,'repair-manifest',{'card':cpin},card_source='card',defect_registry=rpin,
        identity_template='{identity}_{row}',transforms=[])
    binding=write(tmp_path/'manifest.json',manifest);out=tmp_path.parent/(tmp_path.name+'-held')
    with pytest.raises(sfitter_higgs_support.HiggsInputSupportError):sfitter_card_derivation.materialize(tmp_path,cp.name,out,binding)
    assert not out.exists() and json.loads(cp.read_text())==card
