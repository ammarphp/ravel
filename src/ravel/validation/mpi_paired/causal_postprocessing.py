"""Compose supplied producer witnesses and paired inference after admission."""
from pathlib import Path
from ravel.validation import diagnostic_plan as plans


def require(ok,message):
    if not ok:raise ValueError(message)


def finalize(*, out, stages, binary, compiled_source, cards, schema,
             expected_settings, expected_masses, expected_pin, selection_sources,
             signal_spec, descriptor, read_json, pin, complete_receipt, settings_checks,
             infer, check_budget, save):
    out=Path(out)
    require(out.is_absolute() and '..' not in out.parts,'absolute owned output required')
    arms=plans.required(descriptor,'arm_artifacts')
    require(set(arms)==set(cards)==set(expected_settings)=={'on','off'},'both paired arms required')
    require(cards['on']!=cards['off'],'distinct intervention cards required')
    stage_ids={stage['id'] for stage in stages}
    require({ident for arm in arms.values() for ident in arm['commands']}==stage_ids,'complete supplied producer population required')
    result={'schema_version':1,'status':'running','active':None,'snapshots':{},'transports':{},'producer_witnesses':{},'inference':None,'error':None,'requires_final_custody':True,'physics_validated':False,'automatic_retry':False}
    def checkpoint(active):
        result['active']=active;save(result);check_budget()
    try:
        for stage in stages:
            ident=stage['id'];checkpoint('producer_witness:'+ident)
            receipt=pin(out/'native-logs'/(ident+'.command.json'))
            result['producer_witnesses'][ident]=complete_receipt(receipt,out/'native-logs'/(ident+'.completed-witness.json'),owned_output_root=out,check_budget=check_budget)
            save(result)
        for arm,artifacts in arms.items():
            checkpoint('transport:'+arm)
            transport=read_json(out/plans.relative(artifacts['transport']))
            command=transport['producer']['command']
            expected=[x.replace('{OUTPUT}',str(out)) for x in artifacts['command']]
            require(command==expected and binary in command and cards[arm] in command,'actual producer binary/card differs')
            result['transports'][arm]=settings_checks.transport(transport,events=descriptor['analyzed_events'],command=command);save(result)
            checkpoint('initialized_settings:'+arm)
            result['snapshots'][arm]=settings_checks.snapshot(out/plans.relative(artifacts['settings']),schema,command=command,compiled_source_path=compiled_source,expected_settings=expected_settings[arm],expected_masses=expected_masses);save(result)
        checkpoint('complete_pair_inference')
        contracts={arm:{'transport_pin':pin(out/plans.relative(artifact['identity'])),'command_pins':[result['producer_witnesses'][ident] for ident in artifact['commands']]} for arm,artifact in arms.items()}
        result['inference']=infer(expected_pin=expected_pin,arms=contracts,selection_sources=selection_sources,signal_spec=signal_spec,descriptor=descriptor,check_budget=check_budget);save(result)
        checkpoint('final_custody_still_required')
        result.update(status='postprocessing_completed',active=None);save(result);check_budget()
    except Exception as exc:
        result.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)});save(result);raise
    return result
