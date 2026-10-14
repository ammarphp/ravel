"""Source-bound native density Estimate1D + RAW Histo1D transport.

No width/unit conversion, variance from error bars, unit-area normalization,
cross-output covariance or inference. This is a private production proposal.
"""
from pathlib import Path
from copy import deepcopy
import json,re
from ravel.physics import native_estimate as native
from ravel.workflow.state_io import atomic_json

Error=native.NativeEstimateError
require=native._require


def _unit(value):
    require(type(value) is str and bool(value.strip()) and len(value)<=128,'explicit bounded native unit required')
    return value


def validate_request(request):
    native._keys(request,('path','axes','representation','normalization','unit','quantity_kind','native_density'))
    require(request['quantity_kind']=='native_density_estimate' and request['representation']=='native'
            and request['normalization']=='absolute','native density requires native representation and explicit absolute normalization')
    name=request['path'];require(type(name) is str and name.startswith('/') and not name.startswith('/RAW/'),'literal final native density path required')
    require(type(request['axes']) is list and len(request['axes'])==1,'one continuous native density axis required')
    axis=request['axes'][0];native._keys(axis,('name','unit'));native._text(axis['name']);_unit(axis['unit']);_unit(request['unit'])
    contract=request['native_density'];native._keys(contract,('operation','source','source_dependencies','native_error_semantics','raw_histogram_path','integrated_unit','raw_weight_unit','normalization_expression','group_width','flow_policy','group_covariance'))
    require(contract['operation']=='histogram_density','explicit native histogram-density operation required')
    require(contract['raw_histogram_path']=='/RAW'+name,'exact matching RAW Histo1D path required')
    require(contract['flow_policy']=='retain_all' and contract['group_covariance']=='not_supplied','all native flows required; group covariance must remain separate')
    for key in ('native_error_semantics','normalization_expression'):native._text(contract[key])
    integral=_unit(contract['integrated_unit']);_unit(contract['raw_weight_unit'])
    expected=integral if axis['unit']=='1' else integral+'/'+axis['unit']
    group=contract['group_width']
    if group is not None:
        native._keys(group,('axis','low','high','unit','operation'));native._text(group['axis']);_unit(group['unit'])
        require(group['operation']=='divide_by_group_width','explicit grouped density width convention required')
        from fractions import Fraction
        for value in (group['low'],group['high']):
            require(type(value) is str and len(value)<=128 and re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',value),'literal finite decimal group geometry required')
        from decimal import Decimal
        numbers=[Decimal(group[key]) for key in ('low','high')]
        require(all(x.is_zero() or -324<=x.adjusted()<=308 for x in numbers),'representable bounded decimal group geometry required')
        require(Fraction(numbers[0])<Fraction(numbers[1]),'positive exact source-group width required')
        if group['unit']!='1':expected+='/'+group['unit']
    require(request['unit']==expected,'declared native density unit must explicitly match integral/axis/group dimensions; no conversion')
    dependencies=contract['source_dependencies'];require(type(dependencies) is list and 1<=len(dependencies)<=32,'bounded reviewed source/API dependency excerpts required')
    paths=set()
    for source in [contract['source'],*dependencies]:
        native._keys(source,('path','sha256','first_line','last_line','text'))
        require(type(source['path']) is str and Path(source['path']).is_absolute(),'absolute ordinary source definition required')
        require(type(source['sha256']) is str and re.fullmatch('[0-9a-f]{64}',source['sha256']),'exact source SHA256 required')
        require(type(source['first_line']) is int and type(source['last_line']) is int and 1<=source['first_line']<=source['last_line'],'positive exact source excerpt required');native._text(source['text'])
        identity=(source['path'],source['first_line'],source['last_line']);require(identity not in paths,'duplicate source dependency excerpt');paths.add(identity)
    return request


def inputs(request,base_dir='.'):
    """All formula/API bytes and parser/transport implementations are normal pins."""
    validate_request(request);contract=request['native_density']
    paths=[native._source({'source':source},base_dir) for source in [contract['source'],*contract['source_dependencies']]]
    return list(dict.fromkeys([*paths,Path(__file__).resolve(),Path(native.__file__).resolve()]))


def _identity(block,path):
    rows=re.findall(r'^Path: (.+)$',block['body'],re.M)
    require(rows==[path],'BEGIN/native Path identity must match exactly once')


def _literal_geometry(block):
    from decimal import Decimal
    rows=re.findall(r'^Edges\(A1\): (.+)$',block['body'],re.M)
    require(len(rows)==1,'one literal continuous axis required')
    try:values=json.loads(rows[0],parse_float=Decimal,parse_int=Decimal)
    except ValueError as exc:raise Error('literal decimal edge geometry required') from exc
    require(type(values) is list and all(isinstance(x,Decimal) and x.is_finite() for x in values),'finite literal decimal edge geometry required')
    return values


def transport(path,request,*,base_dir='.'):
    """Preserve every final native value/error/flow and RAW primitive row."""
    inputs(request,base_dir);contract=request['native_density'];objects,digest=native._read(path);name=request['path'];raw_name=contract['raw_histogram_path']
    require(name in objects and raw_name in objects,'complete final density and matching RAW histogram required')
    _identity(objects[name],name);_identity(objects[raw_name],raw_name)
    require(_literal_geometry(objects[name])==_literal_geometry(objects[raw_name]),'final native density and RAW literal decimal geometry differ')
    final=native._estimate(objects[name]);raw=native._histogram(objects[raw_name]);require(final['edges']==raw['edges'],'final native density and RAW geometry differ')
    raw['weight_unit']=contract['raw_weight_unit'];raw['coordinate_unit']=request['axes'][0]['unit']
    return {'contract':deepcopy(request),'quantity_kind':'native_density_estimate','bins':[b for b in final['bins'] if not b['flow']],
        'all_native_bins':final['bins'],'native_finalized':final,'raw_histogram':raw,
        'raw_operands':[{'id':'raw_histogram','role':'unfinalized_source_histogram','path':raw_name,'object':raw}],
        'yoda_text_sha256':digest,'all_object_paths':sorted(objects),'native_final_path':name,'native_raw_path':raw_name,
        'storage_semantics':'Untransformed source-native density Estimate1D with matching unfinalized RAW Histo1D; native labeled marginal errors/undefined tokens and all flows retained.',
        'source_definition':contract['source'],'source_dependencies':deepcopy(contract['source_dependencies']),
        'native_error_semantics':contract['native_error_semantics'],'normalization_expression':contract['normalization_expression'],
        'group_width':deepcopy(contract['group_width']),'flow_sumw':None,'flow_sumw2':None,'raw_flow_sumw':None,
        'covariance':None,'covariance_scope':'Native marginal errors only; RAW per-fill moments remain separate from bin/event-group covariance.',
        'unit_scope':'Explicit source-declared native density unit '+request['unit']+'; RAW weight unit '+contract['raw_weight_unit']+'. No bin/group width, unit, or normalization conversion is performed.',
        'integral_reconstructed':False,'variance_from_error_bars':False,'physics_validated':False}


def write_report(observables,output):
    """Portable full-token table; undefined or unavailable values remain visible."""
    estimates=[];rows=[]
    for path,obj in observables.items():
        if obj.get('quantity_kind')!='native_density_estimate':continue
        validate_request(obj['contract']);require(path==obj['contract']['path']==obj['native_final_path'],'native density report path differs')
        require(obj['all_native_bins']==obj['native_finalized']['bins'] and obj['covariance'] is None and obj['variance_from_error_bars'] is False,'complete native density census without fabricated variance/covariance required')
        require(all(b['variance'] is None and b['integrated_sumw'] is None for b in obj['all_native_bins']),'density errors cannot be relabeled as histogram moments')
        estimates.append({'path':path,'observable':obj})
        for b in obj['all_native_bins']:
            errors='; '.join(e['label']+': '+e['down_token']+', '+e['up_token'] for e in b['native_errors'])
            cells=[path,b['bin'],b['low'],b['high'],b['value_token'],errors,obj['contract']['unit'],b['status']]
            rows.append('| '+' | '.join(str(x).replace('|','\\|').replace('\n',' ') for x in cells)+' |')
    if not estimates:return []
    out=Path(output);atomic_json(out/'native-density-estimates.json',{'schema_version':1,'kind':'native_density_estimate_report','estimates':estimates,'covariance':None,'physics_validated':False})
    (out/'native-density-estimates.md').write_text('# Native density estimates\n\n| Observable | Bin | Low | High | Native value token | Signed native errors | Unit | Status |\n|---|---|---|---|---|---|---|---|\n'+'\n'.join(rows)+'\n\nComplete finite/flow rows, exact source definitions, RAW histogram primitives and native labels are retained in native-density-estimates.json. Values are not rescaled or integrated; no variance or event-group covariance is inferred.\n',encoding='utf-8')
    return [{'stem':'native-density-estimates','files':['native-density-estimates.json','native-density-estimates.md'],'normalization':'Exact native density/error/flow tokens, no conversion'}]
