"""Supplied instrumentation, source arithmetic and complete delivery controls."""
import copy,json
from pathlib import Path
import pytest
from ravel.physics import analysis_response_features as ar,hhh_native_trace as native,hhh_response as response
from instrumentation_fixture import assets,contracts,descriptor,census,log,pin,sha,path,op

@pytest.mark.parametrize('identity,models,count',[('ANA_0001',1,3),('ANA_0002',2,6)])
def test_supplied_source_models_destinations_and_population(tmp_path,identity,models,count):
    base=assets(tmp_path/'supplied',identity,models);d=descriptor(base);d['study']['output']['formats']=['json'] if models==1 else ['markdown'];dp=base/'instrumentation.json';dp.write_text(json.dumps(d));doc=json.loads((base/'prepare-input.json').read_text());doc['instrumentation']=pin(dp);(base/'prepare-input.json').write_text(json.dumps(doc));cs=contracts(base)
    task={'schema_version':1,'operation':'prepare-source','input':str(base/'prepare-input.json'),'input_sha256':sha(base/'prepare-input.json')}
    prepared=ar.run(task,base,tmp_path/'prepared')
    report_dir=tmp_path/'report';report_dir.mkdir();tables=ar.write_report(prepared,report_dir)
    assert tables[0]['files']==['analysis-response-report.'+('json' if models==1 else 'md')]
    assert prepared['new_native_calls']==0 and len(prepared['models'])==models
    assert prepared['required_final_histograms']==d['final_histograms']
    events=census(count);result=response.consume(log(events,d['trace']),events,cs,d['trace'])
    assert result['events']==count and result['destinations']==d['trace']['destinations']
    assert all(e['allocation']==[.5]*models+[1.] for e in result['rows'])
    generated=(tmp_path/'prepared/source/observer.cc').read_bytes();original=Path(next(iter(cs.values()))['source']['path']).read_bytes()
    inverse=generated.decode()
    for edit in reversed(prepared['edits']):inverse=inverse.replace(edit['new'],edit['old'])
    assert inverse.encode()==original

@pytest.mark.parametrize('fault',['source','model','missing_descriptor','anchor_count','inverse_collision'])
def test_source_and_instrumentation_refuse_before_outputs(tmp_path,fault):
    base=assets(tmp_path/'inputs');task={'schema_version':1,'operation':'prepare-source','input':str(base/'prepare-input.json'),'input_sha256':sha(base/'prepare-input.json')};d=descriptor(base)
    if fault=='source':Path(next(iter(contracts(base).values()))['source']['path']).write_text('changed')
    elif fault=='model':Path(next(iter(contracts(base).values()))['model']['path']).unlink()
    elif fault=='missing_descriptor':
        doc=json.loads((base/'prepare-input.json').read_text());doc.pop('instrumentation');(base/'prepare-input.json').write_text(json.dumps(doc));task['input_sha256']=sha(base/'prepare-input.json')
    else:
        if fault=='anchor_count':d['instrumentation']['edits'][0]['count']=2
        else:d['instrumentation']['edits']=[{'old':'result','new':'input','count':1}]
        with pytest.raises(ValueError):native.instrument(Path(next(iter(contracts(base).values()))['source']['path']).read_bytes(),d['instrumentation'])
        return
    with pytest.raises((ValueError,OSError)):ar.run(task,base,tmp_path/'out')
    assert not (tmp_path/'out').exists()

@pytest.mark.parametrize('fault',['identity','missing_event','extra_event','reordered','missing_feature','input_arithmetic','output_width','nonfinite','missing_footer','extra_footer','disposition','weight_names'])
def test_complete_trace_adverse_controls(tmp_path,fault):
    base=assets(tmp_path/'inputs');d=descriptor(base);cs=contracts(base);events=census();raw=log(events,d['trace']);records=[json.loads(line[len(d['trace']['prefix']):]) for line in raw.decode().splitlines()]
    if fault=='identity':records[1]['data']['event_number']=900
    elif fault=='missing_event':records=[r for r in records if r['event']!=2 or r['phase']=='normalization']
    elif fault=='extra_event':records.insert(-1,dict(event=4,phase='identity',data=events[0]['native_identity']))
    elif fault=='reordered':records[2],records[3]=records[3],records[2]
    elif fault=='missing_feature':records[2]['data'].pop('x')
    elif fault=='input_arithmetic':records[3]['data'][0]=2.
    elif fault=='output_width':records[4]['data'].pop()
    elif fault=='nonfinite':records[4]['data'][0]='NaN'
    elif fault=='missing_footer':records.pop()
    elif fault=='extra_footer':records.append(copy.deepcopy(records[-1]))
    elif fault=='disposition':records[2]['phase']='unknown'
    else:events[0]['native_identity']['selected_weight_names']=['changed']
    changed=''.join(d['trace']['prefix']+json.dumps(dict(r,seq=i+1))+'\n' for i,r in enumerate(records)).encode()
    with pytest.raises(ValueError):response.consume(changed,events,cs,d['trace'])

def test_migration_identity_shared_group_gram_and_source_float_arithmetic(tmp_path):
    from ravel.physics.detector_response import summarize
    base=assets(tmp_path/'inputs');d=descriptor(base);events=census();out=response.consume(log(events,d['trace']),events,contracts(base),d['trace'])
    config={'axes':[{'name':'coordinate','knots':[1]}],'anchors':[{'point':[1]}],'reference_point':{'coordinate':1},'weight_name':'nominal','normalization':{'scale':1.,'denominator':'fixed','fixed_denominator':1.}}
    rows=[{k:e[k] for k in ('event_id','group_id','weights','allocation')} for e in out['rows']]
    moments=summarize(config,d['trace']['destinations'],[rows])
    # Independent oracle: the first group sums signed subevents before its outer product.
    assert moments['group_marks']['nominal']['0']==[.5,1.,1.]
    assert moments['joint_weight_anchor_covariance']==[[.25,.5],[.5,1.]]
    c=copy.deepcopy(next(iter(contracts(base).values())));c['features'][0].update(operation='normalize',offset=16777216.,scale=1.)
    assert response.ci.prepare_features(c,{'x':16777217.,'y':2.75})['values'][0]==0
    c['features'][0]['arithmetic']='binary64_then_cast'
    assert response.ci.prepare_features(c,{'x':16777217.,'y':2.75})['values'][0]==1

def test_compact_source_serialization_preserves_values_and_prewrite_commit(tmp_path,monkeypatch):
    value={'signed':-0.,'tiny':5e-324,'large':1e300,'all_zero_coordinates':[0.]*7,'failed':None}
    encoded=ar._json_bytes(value);assert json.loads(encoded)==value
    emitted=ar._Emitted(tmp_path);original=Path.write_bytes
    def altered(path,raw):return original(path,raw.replace(b'"failed":null',b'"failed":true'))
    monkeypatch.setattr(Path,'write_bytes',altered)
    with pytest.raises(ValueError,match='differs from committed'):emitted.json(tmp_path/'changed.json',value)

def test_separate_emitted_bound_does_not_raise_original_input_or_log_bounds(tmp_path,monkeypatch):
    p=tmp_path/'small';p.write_bytes(b'abc')
    with pytest.raises(ValueError):ar._pin(pin(p),tmp_path,limit=2)
    monkeypatch.setattr(ar,'MAX_EMITTED_BYTES',5)
    with pytest.raises(ValueError,match='bounded exact emitted'):ar._Emitted(tmp_path/'out').json(tmp_path/'out/member.json',{'too':'large'})
    assert not (tmp_path/'out').exists()

def test_supplied_expressions_score_bins_and_category_weight():
    ctx={'score':.625,'flag':True}
    assert response.evaluate(op('bin_label',path('score'),{'literal':[.1,.5,.75]},{'literal':['low','middle','high']},1.,'flow'),ctx)=='middle'
    assert response.evaluate(op('float32',op('div',3.,7.)),ctx)==response.ci.cast(3./7.,'float32')
    with pytest.raises(ValueError):response.evaluate(op('unknown',1),ctx)
    with pytest.raises(response.ResponseInputError) as caught:response.evaluate(path('missing'),ctx)
    assert caught.value.reason=='missing_input'

def test_full_retained_consumer_and_report_use_supplied_anchor_grid(tmp_path,monkeypatch):
    outputs=[]
    for identity,model_count,point_values,event_count,formats in [('ANA_0001',1,[1],3,['json']),('ANA_0002',2,[2,3,5],6,['markdown'])]:
        base=assets(tmp_path/identity,identity,model_count);desc=descriptor(base);desc['study']['output']['formats']=formats
        dp=base/'instrumentation.json';dp.write_text(json.dumps(desc));prep=json.loads((base/'prepare-input.json').read_text());prep['instrumentation']=pin(dp);(base/'prepare-input.json').write_text(json.dumps(prep))
        task={'schema_version':1,'operation':'prepare-source','input':str(base/'prepare-input.json'),'input_sha256':sha(base/'prepare-input.json')};prepared_dir=tmp_path/(identity+'-prepared');prepared=ar.run(task,base,prepared_dir)
        events=base/'events.hepmc'
        with events.open('w') as stream:
            stream.write('HepMC::Version 3.0.0\nHepMC::Asciiv3-START_EVENT_LISTING\nW nominal\n')
            for i,e in enumerate(census(event_count),1):stream.write(f'E {i} 0 3\nU GEV MM\nW {e["weights"]["nominal"]}\nP 1 0 2212 0 0 6500 6500 0 4\nP 2 0 2212 0 0 -6500 6500 0 4\nP 3 0 22 1 0 0 1 0 1\n')
            stream.write('HepMC::Asciiv3-END_EVENT_LISTING\n')
        meta=base/'metadata.json';metadata={'schema_version':1,'event_level':'hadron','beam_pdg':desc['beam_pdg'],'beam_energy_gev':desc['beam_energy_gev'],'weight_names':['nominal'],'events':event_count,'groups':'independent','cross_section_pb':1.,'source':'Fictional complete input population'};meta.write_text(json.dumps(metadata))
        population,_=ar.original_census(events,metadata);raw=log(population,desc['trace']);anchors=[]
        for value in point_values:
            p=base/('producer'+str(value)+'.json');p.write_text(json.dumps({'seed':value}));trace_file=base/('trace'+str(value));trace_file.write_bytes(raw)
            anchors.append({'point':[value],'trace':pin(trace_file),'producer_task':pin(p),'build_reuse':pin(p),'loader':pin(p)})
        # Native custody is deliberately mocked; original source/event parsing,
        # arithmetic, joint moments, byte commitments and reporting are real.
        monkeypatch.setattr(ar,'_producer',lambda a,*args:Path(a['trace']['path']).read_bytes())
        d={'schema_version':1,'instrumentation':pin(dp),'prepared':pin(prepared_dir/'prepared.json'),'events':pin(events),'metadata':pin(meta),'contracts':pin(base/'contracts.json'),'anchors':anchors,'axes':[{'name':'coordinate','knots':point_values}],'reference_point':{'coordinate':point_values[0]},'nominal_weight':'nominal','normalization_tolerance':{'atol':0.,'rtol':1e-12}}
        out=tmp_path/(identity+'-consume');out.mkdir();result=ar.consume(d,base,out,contracts(base));assert result['events']==event_count
        assert len(result['anchors'])==len(point_values) and result['study']==desc['study']
        assert result['response']['destination_ids']==desc['trace']['destinations']
        report=tmp_path/(identity+'-report');report.mkdir();tables=ar.write_report(result,report)
        assert tables[0]['files']==['analysis-response-report.'+('json' if formats==['json'] else 'md')]
        outputs.append(result)
        generated=Path(result['generated_outputs'][0]['path']);generated.write_bytes(generated.read_bytes()+b'changed')
        with pytest.raises(ValueError,match='changed completed'):ar.write_report(result,tmp_path/(identity+'-changed'))
    assert outputs[0]!=outputs[1]

def test_supplied_repeated_object_predicates_and_exact_signed_remainder():
    ctx={'objects':[{'draw':.2,'eff':.3},{'draw':.4,'eff':.5}]}
    expression=op('all_items',path('objects'),op('le',path('item','draw'),path('item','eff')))
    assert response.evaluate(expression,ctx) is True
    ctx['objects'][1]['draw']=.7
    assert response.evaluate(expression,ctx) is False
    for integer in (2**63-1,-(2**63-1),2**63,-(2**63)):
        expected=abs(integer)%3*(-1 if integer<0 else 1)
        assert response.evaluate(op('mod',integer,3),{})==expected
