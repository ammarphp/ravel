"""Source-package refusals and contract variation, using fictional inputs."""
from pathlib import Path

import pytest

from ravel.physics import ma5_saf, width_inputs, mass_width_grid, mssm_observable_map


def test_saf_has_no_stored_source_identity_or_legacy_booking_parser():
    assert not hasattr(ma5_saf, 'SOURCE_SHA')
    assert not hasattr(ma5_saf, '_bookings')


def test_width_materializer_has_no_installed_release_mapping():
    assert not hasattr(width_inputs, 'RELEASE')
    assert not hasattr(width_inputs, 'REGION_FILES')
    assert not hasattr(width_inputs, 'SERIES')


def test_transfer_degree_and_efficiency_are_supplied():
    transfer = {'degree': 2, 'domain': ['0', '2'], 'evaluation': 'point',
                'coordinates': ['1'], 'coefficients': [], 'tag_efficiency': '1/5',
                'log_response': [], 'source': 'fictional'}
    assert mass_width_grid.transfer_basis(transfer, [['0', '2']]) == [[1/4], [1/2], [1/4]]
    assert not hasattr(mass_width_grid, 'REGIONS')


def test_map_has_only_the_general_population_reader():
    source = Path(mssm_observable_map.__file__).read_text()
    assert 'point_count' not in source
    assert 'm_lsp_GeV' not in source


def test_source_package_operational_instructions_are_packaged():
    from ravel.paths import WORKFLOW_INSTRUCTIONS
    assert 'docs/workflow/reference/width-input-materialization.md' in WORKFLOW_INSTRUCTIONS
    assert 'docs/reference/mass-width-grid-recipes.md' in WORKFLOW_INSTRUCTIONS


def test_output_contract_cannot_overwrite_derived_construction(tmp_path):
    from test_mass_width_grid import request_fixture, put
    path, document, _ = request_fixture(tmp_path)
    document['output']['result']['filename'] = 'point-0-construction.json'
    put(path, document)
    with pytest.raises(ValueError):
        mass_width_grid.run({'input':str(path)}, tmp_path, tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_width_grid_has_no_installed_upper_endpoint(tmp_path):
    from test_mass_width_grid import request_fixture, put
    path, document, _ = request_fixture(tmp_path, missing=True)
    document['axes'][1]['values'] = [.73, 1.27]
    for cell, value in zip(document['cells'], [.73, 1.27]):
        cell['coordinate']['width_over_mass'] = value
    put(path, document)
    result = mass_width_grid.run({'input':str(path)}, tmp_path, tmp_path/'out')
    assert [row['coordinate']['width_over_mass'] for row in result['cells']] == [.73, 1.27]
    assert all(row['state']=='blocked' for row in result['cells'])


def test_saf_two_contracts_and_typed_legacy_conversion(tmp_path):
    import hashlib
    import json
    from test_ma5_source_admission import documents, pin, js, frame
    from test_ma5_saf import histogram
    from ravel.physics import ma5_bookings
    from ravel.physics.supplied_contracts import MissingInputError
    for variant in (False, True):
        base = tmp_path/str(variant); base.mkdir()
        doc, _ = documents(base, config='')
        if variant:
            source_path=Path(doc['source']['path'])
            source_path.write_text(source_path.read_text().replace('return true;}\nbool', 'Manager()->AddHisto("momentum [GeV]",2,0,20); return true;}\nbool',1))
            doc['source']=pin(source_path)
            declared=dict(ma5_bookings.compile_source(source_path.read_text()),source=doc['source'],scope='Fictional ANA-0002')
            doc['bookings']=js(base/'bookings.json',declared)
            root=Path(doc['views']['synthetic']['root'])
            (root/'A.saf').rename(root/'B.saf');doc['analysis']='B'
            (root/'Histograms/histos.saf').write_text(histogram().replace('Resolved','SR'))
            for path in (root/'Cutflows').glob('*.saf'): path.write_text(path.read_text().replace('1 1','2 1'))
            view=doc['views'].pop('synthetic');view.update(expected_initial_entries=3,population_description='Three fictional signed entries')
            view['files']={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            doc['views']={'other_population':view};doc['population_scope']='Fictional ANA-0002 dataset'
        task={'input':js(base/'input.json',doc)['path'],'output':{'filename':'B.json' if variant else 'A.json','format':'json-compact' if variant else 'json'}}
        result=ma5_saf.run(task,base,base/'out')
        assert result['analysis']==doc['analysis'] and set(result['views'])==set(doc['views'])
        assert len(result['source_bookings']['histograms'])==int(variant)
        assert next(iter(result['views'].values()))['initial_entries']==(3 if variant else 2)
        assert json.loads((base/'out'/task['output']['filename']).read_bytes())==result
        assert sorted(p.name for p in (base/'out').iterdir())==[task['output']['filename']]
    path=tmp_path/'legacy.json';path.write_text('{"schema_version":1}')
    with pytest.raises(MissingInputError) as error: ma5_saf.inputs({'input':str(path)},tmp_path)
    assert error.value.reason=='missing-input' and error.value.field=='upstream'


def test_width_two_complete_contracts_preserve_single_use_normalization(tmp_path):
    import json
    from fractions import Fraction as F
    from test_mass_width_grid import request_fixture, response_fixture, par, put
    from ravel.physics.supplied_contracts import MissingInputError
    for variant in (False,True):
        base=tmp_path/str(variant);path,document,law=request_fixture(base)
        pair_count=3 if variant else 1;windows=[['1','2'],['2','3'],['3','5']] if variant else [['7','11']]
        n=len(windows);regions=['region'+str(i) for i in range(2*pair_count)];total=len(regions)*n
        law['windows']=windows;law['regions']=[{'id':rid,'role':'signal_region' if i==0 else 'control_region','observed':[7+i]*n,'source':'lawsrc'} for i,rid in enumerate(regions)]
        law['region_pairs']=[{'id':'pair'+str(i),'tagged':regions[i],'antitagged':regions[pair_count+i]} for i in range(pair_count)]
        degree=3 if variant else 1
        law['transfer'].update(degree=degree,domain=[windows[0][0],windows[-1][1]],coordinates=[str((F(a)+F(b))/2) for a,b in windows],
            coefficients=[par('coefficient'+str(i),'lawsrc') for i in range(degree+1)],tag_efficiency='1/7' if variant else '1/5',log_response=[['0'] for _ in range(total)])
        law['latent_rates']={pair['id']:[par(pair['id']+'_rate'+str(i),'lawsrc','21') for i in range(n)] for pair in law['region_pairs']}
        law['resonant_backgrounds']=[];document['regional_input']=put(base/'law.json',law)
        document['analysis'].update(id='ANA-0002' if variant else 'ANA-0001',region_ids=regions,energy_tev=9 if variant else 7,lumi_fb=31 if variant else 17,observable='other_observable' if variant else 'first_observable')
        document['analysis']['generation']['energy_gev']=[4500,4500] if variant else [3500,3500]
        masses=[17,83] if variant else [29];widths=[.03,.15,.61] if variant else [.04]
        document['axes']=[{'name':'mass_GeV','values':masses},{'name':'width_over_mass','values':widths}];document['cells']=[]
        for index,coordinate in enumerate({'mass_GeV':m,'width_over_mass':w} for m in masses for w in widths):
            response=response_fixture(base/('response'+str(index)),law,coordinate)
            response.update(region_ids=regions,observable=document['analysis']['observable'],energy_tev=document['analysis']['energy_tev'],lumi_fb=document['analysis']['lumi_fb'])
            response['normalization'].update(cross_section_pb='31/1000' if variant else '1/50',generated_sumw='900' if variant else '400',accepted_sumw=str(total),population='Complete fictional cohort '+str(900 if variant else 400))
            response['components'][0].update(selected_sumw=['1']*total,log_response=[['0'] for _ in range(total)])
            response['construction_metadata'].update(model_id='fictional'+str(index),question=document['analysis']['id']+' supplied construction',energy=str(response['energy_tev'])+' TeV',luminosity=str(response['lumi_fb'])+' fb^-1',scale='Supplied pb to fb conversion over complete generated exposure')
            document['cells'].append({'coordinate':coordinate,'generation_request':None,'response':put(base/('response'+str(index)+'.json'),response),'missing':[]})
        document['output']={'result':{'filename':'other.json' if variant else 'first.json','format':'json-compact' if variant else 'json'},
                            'report':{'filename':'other.csv' if variant else 'first.md','format':'csv' if variant else 'markdown'}}
        put(path,document);result=mass_width_grid.run({'input':str(path)},base,base/'out')
        assert len(result['cells'])==len(masses)*len(widths) and result['analysis']['id']==document['analysis']['id']
        for cell in result['cells']:
            model=json.loads(Path(cell['construction']['path']).read_bytes());signal=next(t for t in model['terms'] if t['id']=='signal_bsm')
            expected=F('31/1000')*1000*31/900 if variant else F('1/50')*1000*17/400
            assert len(model['bins'])==total and all(F(v)==expected for v in signal['coefficients'])
        table=mass_width_grid.write_report(result,base/'out')
        assert table[0]['files']==[document['output']['report']['filename']]
        assert json.loads((base/'out'/document['output']['result']['filename']).read_bytes())==result
    document.pop('analysis');put(path,document)
    with pytest.raises(MissingInputError) as error: mass_width_grid.inputs({'input':str(path)},base)
    assert error.value.field=='analysis'


def test_population_converter_and_map_two_contracts_and_typed_missing(tmp_path):
    import json
    from test_mssm_observable_map import fixture, emit, save
    from ravel.physics import population_inputs
    from ravel.physics.supplied_contracts import MissingInputError
    for variant in (False,True):
        base=tmp_path/str(variant);task,document=fixture(base,grid=variant)
        document['source']='ANA-0002 supplied population' if variant else 'ANA-0001 supplied population'
        source={'rows':[{'name':p['id'],'x':p['coordinate'][0],'y':p['coordinate'][1],'difference':str(int(p['coordinate'][0])-int(p['coordinate'][1]))} for p in document['points']]}
        mapping={'records':['rows'],'identity':['name'],'coordinates':[['x'],['y']],
                 'relations':[{'terms':[{'path':['x'],'factor':'1'},{'path':['y'],'factor':'-1'},{'path':['difference'],'factor':'-1'}],'equals':'0'}]}
        contract={'schema_version':1,'source':emit(base/'raw.json',source),'mapping':mapping,
                  'output':{'filename':'second.json' if variant else 'first.json','format':'json-compact' if variant else 'json'}}
        pin=population_inputs.run(contract,base,base/'population')
        normalized=json.loads(Path(pin['path']).read_bytes())
        assert normalized=={'schema_version':1,'points':[{k:p[k] for k in ('id','coordinate')} for p in document['points']]}
        document['population']={'kind':'source-listed','source':pin,'layout':'point-list-v1'};save(task,document)
        task['output']={'filename':'other-map.json' if variant else 'first-map.json','format':'json-compact' if variant else 'json'}
        result=mssm_observable_map.run(task,base,base/'out')
        assert result['source']==document['source'] and result['axes']==document['axes'] and result['population']['delivered_points']==(4 if variant else 1)
        assert json.loads((base/'out'/task['output']['filename']).read_bytes())==result
    document['population']['source']=None;save(task,document)
    with pytest.raises(MissingInputError) as error: mssm_observable_map.inputs(task,base)
    assert error.value.reason=='missing-input' and error.value.field=='source'


def test_population_mapping_refuses_missing_and_false_relations():
    from ravel.physics.population_inputs import normalize
    from ravel.physics.supplied_contracts import MissingInputError
    mapping={'records':['rows'],'identity':['id'],'coordinates':[['x']],'relations':[]}
    with pytest.raises(MissingInputError): normalize({'rows':[{'id':'p'}]},mapping)
    mapping['relations']=[{'terms':[{'path':['x'],'factor':'1'}],'equals':'2'}]
    with pytest.raises(ValueError,match='relation differs'): normalize({'rows':[{'id':'p','x':'3'}]},mapping)


def test_map_supplied_output_keeps_delivery_ceiling(tmp_path, monkeypatch):
    from test_mssm_observable_map import fixture
    task, _ = fixture(tmp_path)
    task['output'] = {'filename': 'compact-map.json', 'format': 'json-compact'}
    from ravel.physics import supplied_contracts
    monkeypatch.setattr(supplied_contracts, 'encode', lambda value, contract: b' '*(mssm_observable_map.MAX_INPUT_BYTES+1))
    with pytest.raises(ValueError, match='delivery ceiling'):
        mssm_observable_map.run(task, tmp_path, tmp_path/'out')
    assert not (tmp_path/'out').exists()
