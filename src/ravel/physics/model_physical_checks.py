"""Selected FeynRules checks and a declared independent two-body width witness.

This module builds fixed native API calls, never executes model source. Its
numeric witness is independent arithmetic for a declared interaction; matching
that interaction to the complete source model remains a scientific review.
"""
import json
import math
import re

from ravel.physics import model_tool_bridge as custody

SYMBOL = r'[A-Za-z][A-Za-z0-9$]{0,63}'
SCOPE = ('Returned selected tree two-body partial widths and declared scalar-Dirac '
         'Yukawa reference only; no complete total width, UV or loop validation.')


def _symbol(value):
    if not isinstance(value, str) or not re.fullmatch(SYMBOL, value):
        raise ValueError('literal unindexed Global source symbol required')
    return value


def _number(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError('finite '+('positive ' if positive else 'nonnegative ')+name+' required')
    return value


def field(value):
    custody._keys(value, ('symbol', 'antiparticle'), 'selected field')
    _symbol(value['symbol'])
    if type(value['antiparticle']) is not bool:
        raise ValueError('explicit particle/antiparticle boolean required')
    return value


def validate(request):
    custody._keys(request, ('schema_version', 'hermiticity', 'feynman_gauge', 'partial_widths'), 'physical checks')
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('physical-checks schema1 required')
    if type(request['hermiticity']) is not bool or type(request['feynman_gauge']) is not bool:
        raise ValueError('explicit hermiticity request and source gauge required')
    widths = request['partial_widths']
    custody._keys(widths, ('channels', 'simplify_decays', 'mass_unit', 'width_unit'), 'selected widths')
    if type(widths['simplify_decays']) is not bool or widths['mass_unit'] != 'GeV' or widths['width_unit'] != 'GeV':
        raise ValueError('explicit simplification and declared GeV mass/width convention required')
    channels = widths['channels']
    if not isinstance(channels, list) or len(channels) > 8 or (not channels and not request['hermiticity']):
        raise ValueError('one requested physical check and at most eight two-body channels required')
    seen, identities = set(), set()
    for channel in channels:
        custody._keys(channel, ('id', 'parent', 'daughters', 'reference'), 'selected channel')
        identity = channel['id']
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', identity) or identity in seen:
            raise ValueError('bounded unique channel identity required')
        seen.add(identity); field(channel['parent'])
        daughters = channel['daughters']
        if not isinstance(daughters, list) or len(daughters) != 2:
            raise ValueError('exactly two outgoing daughters required')
        for daughter in daughters: field(daughter)
        key = (json.dumps(channel['parent'], sort_keys=True), tuple(sorted(json.dumps(d, sort_keys=True) for d in daughters)))
        if key in identities: raise ValueError('duplicate selected physical channel')
        identities.add(key)
        reference = channel['reference']
        if reference is None: continue
        custody._keys(reference, ('kind', 'coupling_numerator', 'coupling_denominator', 'color_multiplicity',
            'source_interaction', 'source_basis', 'absolute_tolerance', 'relative_tolerance'), 'width reference')
        if reference['kind'] != 'scalar-dirac-yukawa':
            raise ValueError('supported reference is L_int = -g scalar bar(fermion) fermion')
        _symbol(reference['coupling_numerator']); _symbol(reference['coupling_denominator'])
        if type(reference['color_multiplicity']) is not int or reference['color_multiplicity'] not in (1, 3):
            raise ValueError('explicit singlet or triplet final-state color multiplicity required')
        if not isinstance(reference['source_interaction'], str) or not reference['source_interaction'].strip():
            raise ValueError('declared interaction and source applicability basis required')
        custody._keys(reference['source_basis'], ('path', 'sha256'), 'reference source pin')
        pin = reference['source_basis']
        if not isinstance(pin['path'], str) or not pin['path'] or not isinstance(pin['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', pin['sha256']):
            raise ValueError('exact reference source pin required')
        _number(reference['absolute_tolerance'], 'absolute tolerance')
        _number(reference['relative_tolerance'], 'relative tolerance')
        if daughters[0]['symbol'] != daughters[1]['symbol'] or daughters[0]['antiparticle'] == daughters[1]['antiparticle']:
            raise ValueError('scalar-Dirac reference needs one fermion and its antiparticle')
    return request


def inputs(request, base):
    validate(request)
    return [custody._pin(c['reference']['source_basis'], base) for c in request['partial_widths']['channels'] if c['reference'] is not None]


def _wl_field(value):
    symbol = 'Global`'+value['symbol']
    return 'FeynRules`anti['+symbol+']' if value['antiparticle'] else symbol


def script(request):
    """Source-qualified FeynRules2.3.49 calls; no implicit global width cache."""
    validate(request)
    q = lambda value: json.dumps(value, ensure_ascii=False)
    b = lambda value: 'True' if value else 'False'
    channels = request['partial_widths']['channels']
    lists = ['{'+','.join(_wl_field(v) for v in [c['parent'], *c['daughters']])+'}' for c in channels]
    selected = '{'+','.join(lists)+'}'
    declarations = '{'+','.join('ImportString['+q(json.dumps(c, separators=(',', ':')))+',"RawJSON"]' for c in channels)+'}'
    parameters = sorted({c['reference'][k] for c in channels if c['reference'] is not None
                         for k in ('coupling_numerator', 'coupling_denominator')})
    parameter_values = '<|'+','.join(q(p)+'->num[FeynRules`NumericalValue[Global`'+p+']]' for p in parameters)+'|>'
    return (
        'physicalGaugeBefore=ToString[Global`FeynmanGauge,InputForm];\n'
        'hermRequested='+b(request['hermiticity'])+'; herm=$Failed; hermOK=False;\n'
        'If[hermRequested, hermOK=CheckAbort[Check[herm=FeynRules`CheckHermiticity[lag, FeynRules`FlavorExpand->True];True,False],False]];\n'
        'selectedChannels='+selected+'; channelDeclarations='+declarations+';\n'
        'partialWidthCacheBefore=ToString[OwnValues[FeynRules`FR$PartialWidths],InputForm];\n'
        'selectedSuppliedWidthsBefore=Map[num[FeynRules`NumericalValue[FeynRules`Width[#[[1]]]]]&,selectedChannels];\n'
        'selectedVertices={}; derivedWidths={}; widthsOK=True;\n'
        'If[Length[selectedChannels]>0, widthsOK=CheckAbort[Check[\n'
        ' selectedVertices=FeynRules`FeynmanRules[lag,FeynRules`FlavorExpand->True,FeynRules`MaxParticles->3,\n'
        ' FeynRules`SelectParticles->Map[{#[[1]],FeynRules`anti[#[[2]]],FeynRules`anti[#[[3]]]}&,selectedChannels]];\n'
        ' derivedWidths=FeynRules`ComputeWidths[selectedVertices,System`Save->False,FeynRules`SimplifyDecays->'
        +b(request['partial_widths']['simplify_decays'])+'];True,False],False]];\n'
        'rawWidthRows=If[ListQ[derivedWidths],Map[Function[row,\n'
        ' If[MatchQ[row,{{_,_,_},_}],<|"fields"->Map[ToString[#,InputForm]&,row[[1]]],\n'
        ' "symbolic"->ToString[row[[2]],InputForm],"numeric"->num[FeynRules`NumericalValue[row[[2]]]]|>,\n'
        ' <|"malformed"->ToString[row,InputForm]|>]],derivedWidths],{}];\n'
        'channelRows=MapThread[Function[{selected,declared},Module[{positions,index},\n'
        ' positions=If[ListQ[derivedWidths],Select[Range[Length[derivedWidths]],Function[i,\n'
        ' MatchQ[derivedWidths[[i]],{{_,_,_},_}] && SameQ[derivedWidths[[i,1,1]],selected[[1]]] &&\n'
        ' SameQ[Sort[Rest[derivedWidths[[i,1]]]],Sort[Rest[selected]]]]],{}];\n'
        ' index=If[Length[positions]===1,First[positions]-1,-1];\n'
        ' <|"request"->declared,"resolved_fields"->Map[ToString[#,InputForm]&,selected],\n'
        ' "fields_recognized"->AllTrue[selected,TrueQ[FeynRules`FieldQ[#]]&],\n'
        ' "parent_scalar"->TrueQ[FeynRules`ScalarFieldQ[selected[[1]]]],\n'
        ' "daughters_dirac"->AllTrue[Rest[selected],TrueQ[FeynRules`DiracFieldQ[#]]&],\n'
        ' "masses"->Map[num[FeynRules`NumericalValue[FeynRules`Mass[#]]]&,selected],\n'
        ' "matched_count"->Length[positions],"raw_row_index"->index|>]],{selectedChannels,channelDeclarations}];\n'
        'physicalChecks=<|"schema_version"->1,"request"->ImportString['+q(json.dumps(request,separators=(',', ':')))+',"RawJSON"],\n'
        ' "gauge_before"->physicalGaugeBefore,"gauge_after"->ToString[Global`FeynmanGauge,InputForm],\n'
        ' "hermiticity"-><|"requested"->hermRequested,"message_free"->TrueQ[hermOK],\n'
        ' "returned_list"->ListQ[herm],"vertex_count"->If[ListQ[herm],Length[herm],-1],\n'
        ' "expression"->ToString[herm,InputForm]|>,\n'
        ' "widths_message_free"->TrueQ[widthsOK],"vertices_returned_list"->ListQ[selectedVertices],\n'
        ' "vertex_count"->If[ListQ[selectedVertices],Length[selectedVertices],-1],\n'
        ' "widths_returned_list"->ListQ[derivedWidths],"raw_width_rows"->rawWidthRows,\n'
        ' "channels"->channelRows,"parameters"->'+parameter_values+',\n'
        ' "partial_width_cache_before"->partialWidthCacheBefore,"partial_width_cache_after"->ToString[OwnValues[FeynRules`FR$PartialWidths],InputForm],\n'
        ' "selected_supplied_widths_before"->selectedSuppliedWidthsBefore,"selected_supplied_widths_after"->Map[num[FeynRules`NumericalValue[FeynRules`Width[#[[1]]]]]&,selectedChannels],\n'
        ' "global_partial_width_cache_written"->False,"total_width_card_updated"->False|>;\n')


def _real(record, name, nonnegative=True):
    custody._keys(record, ('real', 'imag'), name)
    real, imag = record['real'], record['imag']
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (real, imag)) or imag != 0 or (nonnegative and real < 0):
        raise ValueError('evaluated real '+name+' required; no absolute-value mass repair')
    return real


def scalar_dirac_width(parent_mass, daughter_mass, coupling, color_multiplicity):
    """Tree on-shell H -> f fbar for L_int=-g H fbar f, summed final colors.

    Initial spin scalar=1; distinguishable Dirac daughters (no 1/2 factor).
    Strictly open two-body channel only. This is not a total-width estimator.
    """
    _number(parent_mass, 'parent mass', positive=True); _number(daughter_mass, 'daughter mass')
    if type(coupling) not in (int, float) or not math.isfinite(coupling): raise ValueError('finite real coupling required')
    if type(color_multiplicity) is not int or color_multiplicity not in (1, 3): raise ValueError('declared color multiplicity required')
    if parent_mass <= 2*daughter_mass: raise ValueError('reference requires a strictly open two-body channel')
    value = color_multiplicity*coupling**2*parent_mass/(8*math.pi)*(1-4*daughter_mass**2/parent_mass**2)**1.5
    if not math.isfinite(value): raise ValueError('reference overflow')
    return value


def _same_json(a,b):
    return json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False)


def witness(observed, request):
    validate(request)
    try:
        custody._keys(observed, ('schema_version', 'request', 'gauge_before', 'gauge_after', 'hermiticity',
            'widths_message_free', 'vertices_returned_list', 'vertex_count', 'widths_returned_list',
            'raw_width_rows', 'channels', 'parameters', 'partial_width_cache_before', 'partial_width_cache_after',
            'selected_supplied_widths_before', 'selected_supplied_widths_after', 'global_partial_width_cache_written', 'total_width_card_updated'), 'physical receipt')
        if type(observed['schema_version']) is not int or observed['schema_version'] != 1 or not _same_json(observed['request'],request):
            raise ValueError('exact requested physical checks required')
        gauge = 'True' if request['feynman_gauge'] else 'False'
        if observed['gauge_before'] != gauge or observed['gauge_after'] != gauge: raise ValueError('declared source gauge changed or unresolved')
        if observed['global_partial_width_cache_written'] is not False or observed['total_width_card_updated'] is not False:
            raise ValueError('unrequested global cache/card width mutation')
        if not isinstance(observed['partial_width_cache_before'],str) or observed['partial_width_cache_before'] != observed['partial_width_cache_after']:
            raise ValueError('global partial-width cache changed')
        before, after=observed['selected_supplied_widths_before'],observed['selected_supplied_widths_after']
        if not isinstance(before,list) or len(before) != len(request['partial_widths']['channels']) or before != after:
            raise ValueError('selected supplied width values changed')
        for value in [*before,*after]: _real(value,'selected supplied total width')
        herm = observed['hermiticity']
        custody._keys(herm, ('requested', 'message_free', 'returned_list', 'vertex_count', 'expression'), 'hermiticity receipt')
        if herm['requested'] is not request['hermiticity']: raise ValueError('hermiticity request differs')
        herm_passed = not request['hermiticity'] or (herm['message_free'] is True and herm['returned_list'] is True
            and type(herm['vertex_count']) is int and herm['vertex_count'] == 0 and herm['expression'] == '{}')
        channels = request['partial_widths']['channels']; rows = observed['raw_width_rows']; measured = observed['channels']
        if not isinstance(rows, list) or len(rows) > 4096 or not isinstance(measured, list) or len(measured) != len(channels):
            raise ValueError('complete bounded returned width and requested-channel populations required')
        if observed['widths_message_free'] is not True or observed['vertices_returned_list'] is not True or observed['widths_returned_list'] is not True:
            raise ValueError('evaluated message-free vertex/width lists required')
        if type(observed['vertex_count']) is not int or observed['vertex_count'] < (1 if channels else 0): raise ValueError('nonvacuous selected vertices required')
        for row in rows:
            custody._keys(row, ('fields', 'symbolic', 'numeric'), 'returned width row')
            if not isinstance(row['fields'], list) or len(row['fields']) != 3 or any(not isinstance(f,str) or not f for f in row['fields']):
                raise ValueError('all returned channel identities required')
            if not isinstance(row['symbolic'],str) or not row['symbolic']: raise ValueError('returned symbolic width required')
            # Unselected channels may be closed and complex. Preserve rather than
            # pretending they were physically qualified or omitting their rows.
            numeric=row['numeric']
            if not isinstance(numeric,dict): raise ValueError('raw numeric/unevaluated width diagnostic required')
            if set(numeric)=={'unevaluated'}:
                if not isinstance(numeric['unevaluated'],str) or not numeric['unevaluated']: raise ValueError('retained unevaluated expression required')
            elif set(numeric)=={'real','imag'}:
                if any(type(v) not in (int,float) or not math.isfinite(v) for v in numeric.values()): raise ValueError('finite raw numeric diagnostic required')
            else: raise ValueError('canonical raw numeric diagnostic required')
        parameters = observed['parameters']
        expected_parameters = {c['reference'][k] for c in channels if c['reference'] is not None for k in ('coupling_numerator','coupling_denominator')}
        if not isinstance(parameters,dict) or set(parameters) != expected_parameters: raise ValueError('exact observed reference parameter population required')
        reports = []
        for channel, measurement in zip(channels, measured):
            custody._keys(measurement, ('request','resolved_fields','fields_recognized','parent_scalar','daughters_dirac','masses','matched_count','raw_row_index'), 'measured channel')
            if not _same_json(measurement['request'],channel) or measurement['fields_recognized'] is not True:
                raise ValueError('resolved source channel differs or unrecognized')
            index = measurement['raw_row_index']; resolved = measurement['resolved_fields']
            if type(measurement['matched_count']) is not int or measurement['matched_count'] != 1 or type(index) is not int or not 0 <= index < len(rows):
                raise ValueError('exactly one actual returned channel required; missing is not zero')
            if not isinstance(resolved,list) or len(resolved) != 3 or any(not isinstance(f,str) or not f for f in resolved): raise ValueError('resolved channel fields required')
            matches = [i for i,r in enumerate(rows) if r['fields'][0] == resolved[0] and sorted(r['fields'][1:]) == sorted(resolved[1:])]
            if matches != [index]: raise ValueError('selected channel does not reconcile to unique retained raw row')
            masses = measurement['masses']
            if not isinstance(masses,list) or len(masses) != 3: raise ValueError('three raw model masses required')
            m, m1, m2 = [_real(v,'mass') for v in masses]
            if m <= m1+m2: raise ValueError('selected width requires a strictly open channel; closed analytic continuation remains diagnostic')
            actual = _real(rows[index]['numeric'],'selected width')
            report = {'id':channel['id'],'raw_row_index':index,'actual_partial_width':actual,'masses': [m,m1,m2],
                'reference':None,'passed':True,'unit':'GeV','complete_total_width':False}
            reference = channel['reference']
            if reference is not None:
                if measurement['parent_scalar'] is not True or measurement['daughters_dirac'] is not True or m1 != m2:
                    raise ValueError('scalar/Dirac and conjugate mass applicability mismatch')
                numerator = _real(parameters[reference['coupling_numerator']], 'Yukawa numerator', False)
                denominator = _real(parameters[reference['coupling_denominator']], 'Yukawa denominator', False)
                if denominator == 0: raise ValueError('zero coupling denominator')
                predicted = scalar_dirac_width(m,m1,numerator/denominator,reference['color_multiplicity'])
                bound = reference['absolute_tolerance']+reference['relative_tolerance']*abs(predicted)
                report.update(reference={'kind':reference['kind'],'predicted':predicted,'coupling':numerator/denominator,
                    'absolute_residual':abs(actual-predicted),'declared_bound':bound,'source_basis':reference['source_basis'],
                    'interaction_applicability':'Caller declaration requires source/model review; numeric match does not prove applicability.'},
                    passed=abs(actual-predicted) <= bound)
            reports.append(report)
        return {'passed':herm_passed and all(r['passed'] for r in reports), 'hermiticity_passed':herm_passed,
            'channels':reports,'retained_raw_channel_count':len(rows),'scope':SCOPE,'physics_validated':False,
            'selected_supplied_total_widths_unchanged':True,'total_width_substitution_requested':False,'total_width_values_certified':False,'complete_total_width_checked':False,'independent_amplitude_evaluation_performed':False}
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        return {'passed':False,'error':str(exc),'scope':SCOPE,'physics_validated':False,
            'complete_total_width_checked':False,'independent_amplitude_evaluation_performed':False}
