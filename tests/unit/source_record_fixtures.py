"""Fictional runtime input builders for reviewed source-record interfaces."""
import ast
import hashlib
import json
from pathlib import Path
from ravel.physics import sfitter_higgs_support
from analysis_package_fixtures import selected_source

TRACE_PRODUCER = selected_source('selection-a')


def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def write(path, value):
    Path(path).write_text(json.dumps(value, allow_nan=False))
    return pin(path)


def reviewed(tmp, kind, sources, **fields):
    evidence = tmp/'review.txt'
    evidence.write_text('ANA-0001 synthetic software review; no physical qualification.')
    return {'schema_version':1,'kind':kind,'sources':sources,
            'context':fields.pop('context',{'identity':'ANA-0001','parameters':{'a':[0,1]},'datasets':['sample-a'],'output_format':'json'}),
            'review':{'status':'reviewed','reviewer':'synthetic-reviewer','evidence':[pin(evidence)]},**fields}


def defect_registry(tmp, card, defects=(), resolutions=(), sources=None, context=None, assumptions=None, support=None):
    cp=tmp/'source-card.json'
    sources=sources or {'card':write(cp,card)}
    value=reviewed(tmp,'defect-registry',sources,
        coverage=[{'input_fingerprint':sfitter_higgs_support.fingerprint(card),'assumptions':assumptions or [],'support':support or {}}],
        defects=list(defects),resolutions=list(resolutions),**({'context':context} if context else {}))
    return write(tmp/'defects.json',value)


def card_review(tmp, root, card):
    """Select a synthetic card review in a test run card; no product fallback."""
    path=Path(root)/'sfitter/sfitter/likelihood/sm.py'
    tree=ast.parse(path.read_bytes())
    weights=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='sm_values' for t in n.targets)))
    return defect_registry(tmp,card, sources={'evaluator':pin(path)},
        assumptions=[{'kind':'source_defined_production_law','physics_validated':False}],
        support={'native_production_scaling':{'weights':weights}})


def cutflow(tmp, *, variant=False, native=False):
    selection=tmp/'selection.txt';selection.write_text('ANA-0002 fictional selected predicate producer')
    reference=tmp/'rows.json';reference_pin=write(reference, {'values':[10,8,3,1] if variant else [6,3,1]})
    if native:
        prefix=['bad_jet_veto','baseline_lepton','signal_jet']
        common=['two_signal_leptons','jpsi_veto','min_jet_met_dphi','leading_jet_met_dphi','mll_window',
            'lepton_separation','leading_lepton_pt','jet_count','leading_jet_pt','b_veto','mtautau_veto',
            'same_flavour','opposite_charge','met_preselection']
        mt2=['mt2_lt_'+str(x) for x in (140,130,120,110,105,102,101,'100p5')]
        unavailable={name:'Not represented by fictional producer' for name in ('generator_filter','trigger','author16_veto','truth_matching')}
        flows={band:prefix+common+[f'{q}_{band}' for q in ('met','risr','subleading_pt')]+['mt2_gt_100']+mt2 for band in ('high','low')}
        predicates=list(dict.fromkeys(sum(flows.values(),[])+list(unavailable)))
        membership=[{'flow':band,'through':mt2[0],'regions':['SR_S_'+band+'_eMT2'+c for c in 'abcdefgh'],'exclusive':True} for band in flows]
        reference_rows=[]
    else:
        prefix=['baseline'];unavailable={'unmeasured':'No decision in supplied population'}
        flows={'flow-b' if variant else 'flow-a':['baseline','threshold']+(['final'] if variant else [])}
        predicates=list(next(iter(flows.values())))+list(unavailable);membership=[]
        reference_rows=[{'flow':next(iter(flows)), 'source':'reference','values_pointer':'/values',
                         'rows':[{'index':i,'predicate':k} for i,k in enumerate(['inclusive_normalization']+next(iter(flows.values())))]}]
    if native:
        # The supplied two-pass package selection is the shipped producer of native event traces.
        selection=TRACE_PRODUCER if native is True else Path(native)
    value=reviewed(tmp,'cutflow-definition',{'selection':pin(selection),'reference':reference_pin},
        context={'identity':'ANA-0002' if variant else 'ANA-0001','parameters':{'b':[2,4,6]} if variant else {'a':[0,1]},
                 'datasets':['sample-b','sample-c'] if variant else ['sample-a'],'output_format':'jsonl' if variant else 'json'},
        selection_source='selection',predicates=predicates,unavailable=unavailable,flows=flows,object_preconditions=prefix,
        membership=membership,normalization={'weight_unit':'pb','luminosity_pb_inverse':200 if variant else 100,
            'population_metadata':{},'convention':'supplied original exposure'},references=reference_rows)
    return write(tmp/'cutflow.json',value),value
