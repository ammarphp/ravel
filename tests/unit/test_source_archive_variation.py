"""Full archive ingestion varies supplied identity, grid, population and result encoding."""
from copy import deepcopy
import json
from source_record_fixtures import reviewed,write
from test_published_model import fixture,oracle


def test_two_supplied_archive_contracts_use_identical_ingestion_code(tmp_path):
    contracts=[{'identity':'ANA-0001','axis':'first','grid':[2,4],'datasets':['sample-a','sample-b'],'format':'json'},
               {'identity':'ANA-0002','axis':'second','grid':[5,7,9],'datasets':['sample-c','sample-d','sample-e'],'format':'jsonl'}]
    for i,contract in enumerate(contracts):
        root=tmp_path/str(i);root.mkdir()
        def change(background,patchset):
            template=background['channels'][0]
            background['channels']=[{**deepcopy(template),'name':name} for name in contract['datasets']]
            background['observations']=[{'name':name,'data':[12.]} for name in contract['datasets']]
            patchset['metadata']['labels']=[contract['axis']]
            patchset['metadata']['analysis_id']=contract['identity']
            patchset['metadata']['references']['hepdata']='placeholder'
            patch=deepcopy(patchset['patches'][0]['patch'])
            patchset['patches']=[{'metadata':{'name':'point-'+str(n),'values':[point]},'patch':deepcopy(patch)}
                                 for n,point in enumerate(contract['grid'])]
        d,_,_=fixture(root,change=change)
        d['source']['record_id']=contract['identity']
        external=write(root/'external.json',{'identity':contract['identity'],'datasets':contract['datasets']})
        row={'id':'attribution','source':d['source'],'archive_sha256':d['archive']['sha256'],'members':d['members'],
            'field':'/metadata/references/hepdata','observed':'placeholder','external_record_source':'record',
            'external_assertions':[{'pointer':'/identity','expected':contract['identity']},
                                   {'pointer':'/datasets','expected':contract['datasets']}]}
        registry=write(root/'registry.json',reviewed(root,'errata-registry',{'record':external},context=contract,errata=[row]))
        d['source_reference_acknowledgment']={'kind':row['id'],'field':row['field'],'observed':row['observed'],
            'external_record':external,'reviewed_registry':registry}
        result=[]
        for point in contract['grid']:
            d['coordinates']={contract['axis']:point}
            admitted=oracle.load_published_model(d)
            assert [c['name'] for c in admitted.workspace()['channels']]==contract['datasets']
            assert admitted.manifest()['source']['record_id']==contract['identity']
            result.append({'coordinates':admitted.manifest()['coordinates'],'workspace':admitted.workspace()})
        assert len(result)==len(contract['grid'])
        output=root/('output.jsonl' if contract['format']=='jsonl' else 'output.json')
        output.write_text(''.join(json.dumps(row)+'\n' for row in result) if contract['format']=='jsonl'
                          else json.dumps(result,indent=2)+'\n')
        decoded=[json.loads(line) for line in output.read_text().splitlines()] if contract['format']=='jsonl' else json.loads(output.read_text())
        assert decoded==result
