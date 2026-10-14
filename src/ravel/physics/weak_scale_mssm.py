"""Released lowMSSM input law and supplied finite parameter grid preparation.

FlexibleSUSY is the existing solver. This module never calculates a spectrum,
selects missing soft terms, or infers a decay or lifetime from a mass splitting.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import model_specific_spectrum as named, model_tool_bridge as custody

NAME = 'lowMSSM-FlexibleSUSY-2.9.0'
OPERATION = 'flexiblesusy-2.9.0-generated-lowMSSM'
PROFILE = Path(__file__).resolve().parents[1]/'data/spectrum/lowmssm-2.9.0.json'
MATRICES = ('TEIN','TDIN','TUIN','MSQ2IN','MSL2IN','MSD2IN','MSU2IN','MSE2IN')
SM_INPUTS = (1,2,3,4,5,6,7,8,11,12,13,14,21,22,23,24)


def input_witness(raw, decays, library):
    named.require(decays is False and library=='none',
        'released lowMSSM has no generated decay implementation; widths remain unknown')
    doc=named.inventory(raw);rows=[]
    expected={'MINPAR':[(3,)],'HMIXIN':[(1,),(101,)],
        'MSOFTIN':[(1,),(2,),(3,)],'SMINPUTS':[(i,) for i in SM_INPUTS],
        'FLEXIBLESUSY':[(i,) for i in range(33)],'MODSEL':[(6,),(12,)]}
    expected.update({b:[(i,j) for i in range(1,4) for j in range(1,4)] for b in MATRICES})
    for block,addresses in expected.items():
        sections=[s for s in doc['sections'] if s['kind']=='block' and s['name']==block]
        named.require(len(sections)==1 and sections[0]['scale'] is None,
            'one explicit unscaled input block required: '+block)
        actual=[tuple(r['codes']) for r in sections[0]['rows'] if r['kind']=='scalar']
        named.require(len(actual)==len(addresses) and set(actual)==set(addresses) and
            all(r['kind']=='scalar' for r in sections[0]['rows']),
            'complete explicit released input population required: '+block)
        for codes in addresses:
            value=named.scalar(doc,{'block':block,'codes':list(codes),'scale':None})
            rows.append({'block':block,'codes':list(codes),'value':value})
    values={(r['block'],tuple(r['codes'])):named.number(r['value']) for r in rows}
    named.require(values['MINPAR',(3,)]>0,'positive explicit TanBeta required')
    named.require(values['MODSEL',(6,)]==values['MODSEL',(12,)]==0,
        'explicit no CKM/PMNS flavour selection and source-default output scale required')
    named.require(values['FLEXIBLESUSY',(12,)]==0 and values['FLEXIBLESUSY',(16,)]==0 and
        values['FLEXIBLESUSY',(23,)]==1 and values['FLEXIBLESUSY',(31,)]==0,
        'force output/positive masses disabled, BSM masses enabled, softsusy loop library explicit')
    named.require(values['FLEXIBLESUSY',(2,)] in (0,1),
        'only the released two-scale solver is built by this operation')
    named.require(values['FLEXIBLESUSY',(0,)]>0,'explicit positive precision goal required')
    for i in range(1,33):
        v=values['FLEXIBLESUSY',(i,)]
        named.require(v>=0 and (i in (14,17,18,19) or v.denominator==1),
            'explicit nonnegative setting, and integral discrete loop/algorithm switch required: '+str(i))
    named.require(values['FLEXIBLESUSY',(15,)]==0,'this bounded spectrum-only provider does not request additional low-energy observables')
    for b in ('MSQ2IN','MSL2IN','MSD2IN','MSU2IN','MSE2IN'):
        named.require(all(values[b,(i,j)]==values[b,(j,i)] for i in range(1,4) for j in range(1,4)),
            'real soft mass-squared input must explicitly be symmetric: '+b)
    for s in doc['sections']:
        if s['kind']=='block' and s['name'].startswith('IM'):
            named.require(all(r['kind']=='scalar' and named.number(r['value'])==0 for r in s['rows']),
                'complex parameter input is unsupported by the released real lowMSSM provider')
        if s['kind']=='block' and s['name'] in ('EXTPAR','FLEXIBLEDECAY','VCKMIN','UPMNSIN'):
            named.require(not s['rows'],'unconsumed model/decay/phase input must not silently select a prescription: '+s['name'])
    named.require(not doc['native_error_rows'],'native error rows cannot become an input point')
    p=json.loads(named.raw_file(PROFILE))
    return {'profile':NAME,'parameters':rows,'all_input':doc,'explicit_decay_settings':None,
        'loop_library':'none','basis':p['conventions'],'input_defaults_selected_by_adapter':False,
        'unknown_input_blocks':[s['name'] for s in doc['sections'] if s['kind']=='block' and s['name'] not in expected],
        'decay_implementation_available':False}


def selected_card(raw, bindings, point):
    """Apply only explicitly supplied address bindings, preserving other bytes."""
    from ravel.workflow.finite_grid import edit_card
    input_witness(raw, False, 'none')
    output, _ = edit_card(raw, bindings, point)
    input_witness(output, False, 'none')
    return output


def prepare_grid(request, *, base_dir, output_dir, presented_pins=None):
    from ravel.workflow.model_spectrum_plan import prepare_grid as prepare
    return prepare(request, base_dir=base_dir, output_dir=output_dir, presented_pins=presented_pins)
