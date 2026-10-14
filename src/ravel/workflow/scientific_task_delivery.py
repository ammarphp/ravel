"""Whole requested JSON/card/script delivery from existing typed tool artifacts.

No generator/model/native execution or acceptance. Typed provenance is retained;
text tasks receive their requested text, not a JSON proxy. Nullable values must
exist in the committed source tool and cannot stand in for missing observations.
"""
from pathlib import Path
from copy import deepcopy
import json
from ravel.workflow import scientific_artifact as typed

def deliver(request,*,base_dir):
    if type(request) is not dict or set(request)!={'schema_version','format','artifact_request'} or type(request['schema_version']) is not int or request['schema_version']!=1:raise ValueError('closed task delivery/v1 required')
    kind=request['format']
    if kind not in ('json','madgraph_commands','madgraph_run_card'):raise ValueError('explicit supported requested output format required')
    value=typed.compose(request['artifact_request'],base_dir=base_dir)
    if kind=='json':text=value['artifact_text']
    else:
        if set(value['artifact'])!={'lines'} or type(value['artifact']['lines']) is not list or not 1<=len(value['artifact']['lines'])<=64:raise ValueError('complete typed code/text line population required')
        lines=value['artifact']['lines']
        if any(type(line) is not str or not line.strip() or '\n' in line or '\r' in line or '```' in line for line in lines):raise ValueError('literal single-line task text required')
        if kind=='madgraph_run_card' and any('=' not in line or line.lstrip().startswith('set ') for line in lines):raise ValueError('run-card requires value=parameter format')
        text='\n'.join(lines)+'\n'
    if len(text.encode())>request['artifact_request']['contract']['max_artifact_bytes']:raise ValueError('complete task artifact byte ceiling exceeded')
    return {**value,'kind':'scientific_whole_task_artifact','output_format':kind,'artifact_text':text,'typed_internal_artifact':value['artifact'],'requested_format_served':True,'generator_or_native_execution_performed':False,'scientific_acceptance':False,'execution_authorized':False}

def input_pins(request,*,base_dir):return typed.input_pins(request['artifact_request'],base_dir=base_dir)


def from_response(request,response_pin,*,base_dir):
    """Take only declared interpretation strings from the unchanged raw reply.

    Numeric/structured tool fields cannot be overwritten. A complete raw reply
    is retained as an additional basis, even when the declared artifact has no
    interpretation fields. No response means no model-call evidence.
    """
    base=Path(base_dir).resolve(strict=True)
    _,raw=typed._basis_snapshot(response_pin,base)
    fields=request['artifact_request']['contract']['interpretation_fields']
    supplied=deepcopy(request)
    if fields:
        # Parse the already authenticated immutable reply. Keep the existing
        # strict reader's duplicate/nonfinite rules, without another file read.
        def pairs(items):
            out={}
            for key,value in items:
                if key in out:raise ValueError('duplicate JSON field')
                out[key]=value
            return out
        value=json.loads(raw.encode("utf-8"),object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        json.dumps(value,allow_nan=False)
        if type(value) is not dict or any(k not in value or type(value[k]) is not str for k in fields):
            raise ValueError('every declared interpretation field needs a raw JSON string')
        supplied['artifact_request']['interpretation']={k:value[k] for k in fields}
        ignored=sorted(set(value)-set(fields))
    else:
        supplied['artifact_request']['interpretation']={}
        ignored=None
    supplied['artifact_request']['basis'].append(deepcopy(response_pin))
    out=deliver(supplied,base_dir=base)
    typed._basis(response_pin,base)
    return {**out,'model_response_pin':deepcopy(response_pin),
        'model_response_bytes':len(raw.encode()),'model_interpretation_fields_consumed':list(fields),
        'model_fields_not_used_for_tool_values':ignored,
        'model_response_is_authority_for_tool_values':False,
        'actual_provider_call_provenance_checked':False}
