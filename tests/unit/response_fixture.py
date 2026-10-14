"""Explicit fictional diagnostic policies for preservation controls."""
import copy
from ravel.physics import compressed_validation as cv
from ravel.physics import truth_reco_response as truth

def contract():
    return {'schema_version':1,'study_id':'ANA-0001','parameter_grid':[{'coordinate':1}],'datasets':['DATA-0001'],'output_format':'jsonl.gz','pt_edges':[0,2,3,4,5,7,10,15,20,30,50,100,None],'abs_eta_edges':[0,.8,1.37,1.52,2.,2.47,2.5,None],'flavours':[{'pid':11,'label':'electron','branch':'Electron'},{'pid':13,'label':'muon','branch':'Muon'}],'parent_relations':[{'parent_pid':p,'child_pid':p%1000000,'same_sign':True} for p in (1000011,2000011,1000013,2000013)] + [{'parent_pid':p,'child_pid':11,'same_sign':True} for p in (1000015,2000015)],'ancestor_categories':[{'id':'tau_ancestor','pids':[15]}],'origin_labels':{'direct':'direct_parent','descendant':'other_parent_descendant','other':'other_origin'},'stable_pids':[1000022],'topology':[{'kind':'allowed_roots','value':[1000011,2000011,1000013,2000013]},{'kind':'root_count','value':2},{'kind':'opposite_signed_pair','value':True},{'kind':'stable_count','value':2},{'kind':'direct_count','value':2}]}

_DEFINITION = []


def native_definition():
    """The fictional reviewed cutflow definition bound to the shipped trace-producing selection."""
    if not _DEFINITION:
        import tempfile
        from pathlib import Path
        from source_record_fixtures import cutflow
        _DEFINITION.append(cutflow(Path(tempfile.mkdtemp(prefix='ravel-definition-')), native=True)[1])
    return _DEFINITION[0]


def join_contract():
    from source_record_fixtures import TRACE_PRODUCER
    value=native_definition()
    return {'predicates':list(value['predicates']),'regions':{'SR_S_high_eMT2a':['two_signal_leptons']},'unavailable':list(value['unavailable']),'sources':{'selection_source_sha256':truth.fingerprint(TRACE_PRODUCER),'diagnostic_source_sha256':truth.fingerprint(cv.__file__)}}

def ancestry_contract():
    rules=[('ambiguous_ancestry','ambiguous',[],[]),('special_via_descendant','root_via',[1000015,2000015],[15]),('other_via_descendant','ancestor',[],[15]),('other_special_descendant','root',[1000015,2000015],[]),('direct_parent','direct',[],[]),('other_origin','other',[],[])]
    trace=join_contract();trace['regions']={'SR':['two_signal_leptons'],'CR':['two_signal_leptons']}
    return {'response':contract(),'root_selector':{'minimum_abs_pid':1000000,'modulus':1000000,'remainders':[11,13,15]},'categories':[{'id':'contains_special','any_root_pids':[1000015,2000015]},{'id':'ordinary_only','any_root_pids':[]},{'id':'unresolved_topology','any_root_pids':[]}],'unresolved_category':'unresolved_topology','reco_rules':[{'id':name,'kind':kind,'root_pids':roots,'via_pids':via} for name,kind,roots,via in rules],'overlays':{'any_reco_special_via_descendant':'special_via_descendant','any_reco_other_via_descendant':'other_via_descendant','any_reco_ambiguous_ancestry':'ambiguous_ancestry'},'join':{'trace':trace,'state_field':'rjr_status','passed_state':'solved','failed_state':'not_reached','object_preconditions':list(native_definition()['object_preconditions']),'flavour_flags':{'isee':0,'ismm':1},'selected_predicate':'two_signal_leptons','selected_count':2,'objects_field':'leptons','flavour_field':'flavour'}}
