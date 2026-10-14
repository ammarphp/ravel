"""Actual ordinary prediction producers -> exact SFitter scientific card bundle.

This verifies correspondence and successful execution. It cannot infer theory
order, independent MC groups, uncertainty laws or acceptable EFT applicability.
Those remain the complete source-defined workflow handoff premises and reviews.
"""
import hashlib
from pathlib import Path
from ravel.physics.ma5_saf import Capture
from ravel.workflow import science, physics_review, sfitter_workflow as workflow, agent_graph

def verify(pin,base,config,contract):
    capture=Capture();path,raw=capture.pin(pin,base);doc=workflow._strict_document(raw)
    workflow._closed(doc,('schema_version','kind','workflow','producers','target_sha256'),'producer-to-fit handoff')
    if type(doc['schema_version']) is not int or doc['schema_version']!=1 or doc['kind']!='sfitter_ordinary_producer_to_fit':raise ValueError('actual ordinary producer handoff required')
    wp,wr=capture.pin(doc['workflow'],path.parent);request=workflow._strict_document(wr)
    if doc['target_sha256']!=agent_graph.digest(request['target']):raise ValueError('original whole-study target differs')
    ready=workflow.ready_native(request,wp.parent)
    if any(ready[k]!=config[k] for k in ('datacard','run_card','semantic_manifest')):raise ValueError('fit inputs are not exact current composed scientific bundle')
    docs,phase=workflow._resolve(request,wp.parent)
    if phase is not None:raise ValueError('complete scientific source phases required')
    # Every fitted scan and SM template evidence is actually delivered. Measured
    # extraction may remain a supplied experimental source, not generated data.
    expected=[]
    for row in docs['parameterization']['payload']['rows']:expected.append(row['scan_evidence'])
    for row in docs['sm_template']['payload']['rows']:expected.append(row['evidence'])
    actual={};paths=[path,wp]
    if type(doc['producers']) is not list or not doc['producers']:raise ValueError('whole ordinary production roster required')
    roots=set()
    for row in doc['producers']:
        workflow._closed(row,('rundir','artifacts'),'original production join')
        rd=Path(row['rundir']);rd=rd if rd.is_absolute() else path.parent/rd
        rd=rd.absolute()
        if rd in roots:raise ValueError('duplicate producer namespace')
        roots.add(rd)
        produced=[Path(p) for p in science.review_waypoint_paths(rd)]
        packet=science.packet(rd)
        if packet['lifecycle_verdict']!='PASS' or physics_review.gate_errors(rd,'reuse'):raise ValueError('current successful scoped reusable ordinary producer required')
        if type(row['artifacts']) is not list or not row['artifacts']:raise ValueError('actual produced scientific artifacts required')
        for artifact in row['artifacts']:
            p,b=capture.pin(artifact,path.parent)
            if p not in produced:raise ValueError('claimed scientific input not in original ordinary output census')
            current={'path':str(p),'sha256':hashlib.sha256(b).hexdigest()}
            if str(p) in actual:raise ValueError('duplicate produced scientific member')
            actual[str(p)]=current
        paths+=produced
    wanted={}
    for phase_name,field in (('parameterization','scan_evidence'),('sm_template','evidence')):
        parent=workflow.custody._pin(request['handoffs'][phase_name],wp.parent).parent
        for row in docs[phase_name]['payload']['rows']:
            p,b=capture.pin(row[field],parent);wanted[str(p)]={'path':str(p),'sha256':hashlib.sha256(b).hexdigest()}
    if actual!=wanted:raise ValueError('complete exact scan/SM producer evidence population required')
    for ref in workflow.input_pins(request,wp.parent):
        p=workflow.custody._pin(ref,wp.parent);paths.append(p)
    capture.finish()
    # Fresh ending ordinary checks, not a returned success flag or new baseline.
    for rd in roots:
        if science.packet(rd)['lifecycle_verdict']!='PASS' or physics_review.gate_errors(rd,'reuse'):raise ValueError('ending original producer authority changed')
    capture.finish()
    return {'paths':sorted(set(paths)),'target_sha256':doc['target_sha256'],
            'produced_inputs':list(actual.values()),'physics_validated':False}
