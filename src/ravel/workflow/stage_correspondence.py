"""Adapter-derived stage identities. Labels never supply absent physical fields.

This source compiler does not dispatch, execute or certify a prediction. Native
cards without model/energy coordinates remain explicitly unavailable.
"""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from ravel.physics.ma5_saf import _json, _keys


def _require(condition, message):
    if not condition: raise ValueError(message)


def _document(capture, path, base, overrides, key):
    p, raw = capture.read(path, base)
    return p, deepcopy(overrides.get(key, _json(raw)))


def _pin(capture, pin, base, *, document=False):
    p, raw = capture.pin(pin, base)
    return p, _json(raw) if document else raw


def _energy(pdg, energies):
    if pdg != [2212, 2212] or len(energies) != 2: return None
    a, b = map(lambda x: Decimal(str(x)), energies)
    if not a.is_finite() or a <= 0 or a != b: return None
    return str((a + b) / Decimal(1000))


def _canonical(value, base):
    if type(value) is dict:
        if set(value)=={'path','sha256'}:
            path=Path(value['path']);path=path if path.is_absolute() else Path(base)/path
            return {**value,'path':str(path.absolute())}
        return {k:_canonical(v,base) for k,v in value.items()}
    if type(value) is list:return [_canonical(v,base) for v in value]
    return value


def project(spec, base, capture, *, documents=None):
    """Read complete operative documents and real adapter transitive inputs."""
    from . import science
    mode, task = spec['mode'], spec['task']
    if mode not in ('model-events', 'analyze', 'signal-template', 'native-likelihood',
                    'svj-recipe', 'mass-width-grid', 'llp-plane-recipe', 'mssm-observable-map'):
        return None
    # Actual selected adapter validation, never execution. Capture every
    # original transitive member; substituted documents are checked again by
    # the ordinary preparation/intake after they have been materialized.
    operation_paths=science.task_inputs(spec,base)
    for path in operation_paths:
        capture.stream_pin({'path': str(path), 'sha256': science.execution.file_hash(path)}, base, allow_empty=True)
    overrides = documents or {}
    facts, transport = {}, {}
    unavailable = ['spin','cp','production_interpretation','interference_meaning',
                   'decay_branching_interpretation','coupling_conventions']
    if mode in ('svj-recipe','mass-width-grid','llp-plane-recipe','mssm-observable-map'):
        key='request' if mode=='mssm-observable-map' else 'input'
        p,doc=_document(capture,task[key],base,overrides,key)
        # task_inputs above uses the existing complete population validator and
        # operative source admission, including exact MASS/DECAY/response laws.
        # Retain every supplied document, cell and missing-input declaration.
        documents=[]
        metadata_bytes=0
        for path in sorted(set(operation_paths),key=str):
            if path.suffix.lower()=='.json':
                _,raw=capture.read(str(path),base)
                metadata_bytes+=len(raw)
                _require(metadata_bytes<=64*1024**2,'complete recipe source metadata exceeds64MiB')
                documents.append({'path':str(path),'sha256':science.execution.file_hash(path),
                                  'document':_json(raw)})
        energy=doc.get('energy_tev',doc.get('analysis',{}).get('energy_tev'))
        facts={'document':_canonical(doc,p.parent),'source_documents':documents,
               'energy_tev':None if energy is None else str(Decimal(str(energy))),
               'axes':deepcopy(doc.get('axes',[])), 'cells':deepcopy(doc.get('cells',[])),
               'points':deepcopy(doc.get('points',[])),
               'quantity':'complete_supplied_recipe_source_construction',
               'scientific_quantity_unavailable':True}
        transport={key:{'path':str(p),'sha256':science.execution.file_hash(p)}}
        unavailable += ['model_sha256','mass_gev','width_gev','basis','observable','unit',
                        'physical_prediction_or_inference']
    elif mode == 'model-events':
        from ravel.physics import model_events
        p, doc = _document(capture, task['config'], base, overrides, 'config')
        model_events.validate_config(doc)
        _, parameters = _pin(capture, doc['cards']['parameter'], p.parent)
        _, process = _pin(capture, doc['cards']['process'], p.parent)
        _pin(capture, doc['model_tree']['manifest'], p.parent)
        doc=_canonical(doc,p.parent)
        model_root=Path(doc['model_tree']['root'])
        doc['model_tree']['root']=str(model_root if model_root.is_absolute() else p.parent/model_root)
        facts = {'energy_tev': _energy(doc['generation']['beam_pdg'], doc['generation']['energy_gev']),
                 'model_sha256': doc['model_tree']['manifest']['sha256'],
                 'parameter_values': {block.upper()+'/'+'/'.join(map(str,indices)): str(value)
                                      for (block,indices), value in model_events.parameter_values(parameters.decode()).items()},
                 'process_commands': model_events.process_commands(process.decode(), doc),
                 'generation': deepcopy(doc['generation']), 'shower': deepcopy(doc['shower']),
                 'decay': deepcopy(doc['decay']), 'weights': deepcopy(doc['weights']),
                 'model_tree': deepcopy(doc['model_tree']), 'cards': deepcopy(doc['cards']),
                 'outputs': deepcopy(doc['outputs']), 'quantity': 'generated_events', 'unit': 'events'}
        transport = {'config': {'path': str(p), 'sha256': science.execution.file_hash(p)}}
        unavailable += ['basis', 'observable']
    elif mode == 'analyze':
        from ravel.physics import existing_events
        existing_events.validate(task)
        # Other existing backends remain honestly unprojected until their
        # actual metadata contract is implemented here.
        if task['backend'] not in ('rivet', 'rivet-built'): return None
        p, metadata = _document(capture, task['metadata'], base, overrides, 'metadata')
        facts = {'energy_tev': _energy(metadata['beam_pdg'], metadata['beam_energy_gev']),
                 'metadata': metadata, 'routine': task['routine'], 'backend': task['backend'],
                 'observables': deepcopy(task['observables']),
                 'nominal_weight': task.get('nominal_weight'),
                 'native_weight_cap': task.get('native_weight_cap'),
                 'source': _canonical({k: task[k] for k in ('source_root', 'build_receipt', 'build_plan',
                                                       'grounding', 'options') if k in task},base)}
        for key in ('source_root','build_receipt','build_plan'):
            if key in facts['source']:
                path=Path(facts['source'][key])
                facts['source'][key]=str(path if path.is_absolute() else Path(base)/path)
        transport = {'events': {'path': str(science.regular(task['events'], base)),
                                'sha256': science.execution.file_hash(science.regular(task['events'], base))}}
        unavailable += ['model_sha256', 'mass_gev', 'width_gev', 'basis']
    elif mode == 'signal-template':
        from ravel.physics import signal_templates
        p, doc = _document(capture, task['input'], base, overrides, 'input')
        signal_templates.validate_document(doc)
        doc=_canonical(doc,p.parent)
        tp, template = _pin(capture, doc['template'], p.parent, document=True)
        signal_templates.validate_template(template)
        facts = {'bridge': doc, 'template': template, 'template_constraint': 'nonnegative_signal_template',
                 'quantity': 'signal_template', 'unit': 'expected_events'}
        transport = {'template': {'path': str(tp), 'sha256': doc['template']['sha256']}}
        unavailable += ['model_sha256', 'mass_gev', 'width_gev', 'energy_tev', 'basis', 'observable']
    else:
        from ravel.physics import native_likelihood, eft_functions as eft
        native_likelihood.validate(task)
        p, doc = _document(capture, task['input'], base, overrides, 'input')
        doc=_canonical(doc,p.parent)
        model = doc['model']
        card = next(row for row in model['files'] if row['staged_path'] == model['card'])
        _, raw = _pin(capture, {k: card[k] for k in ('path', 'sha256')}, p.parent)
        facts = {'card': eft.parse_datacard(raw),
                 'model_files': [{key: row[key] for key in ('sha256', 'staged_path')}
                                 for row in model['files']],
                 'regions': deepcopy(model['regions']),
                 'fit': deepcopy(doc['fit']), 'physics_model': deepcopy(model['physics_model']),
                 'signal_replacement': deepcopy(model['signal_replacement']),
                 'expected_data': deepcopy(doc.get('expected_data')), 'quantity': 'native_inference',
                 'construction': None}
        if 'construction' in model:
            _, construction = _pin(capture, model['construction'], p.parent, document=True)
            from ravel.physics import statistical_construction
            statistical_construction.validate(construction)
            facts['construction'] = construction
        transport = {'model_files': deepcopy(model['files'])}
        unavailable += ['model_sha256', 'mass_gev', 'width_gev', 'energy_tev', 'basis', 'observable', 'unit']
    if facts.get('energy_tev') is None and 'energy_tev' not in unavailable: unavailable.append('energy_tev')
    if spec.get('goal_binding') is not None:
        from . import task_completion
        facts['parent_assignment']=task_completion.binding_projection(spec['goal_binding'],base_dir=base)
    capture.finish()
    return {'schema_version': 1, 'mode': mode, 'facts': facts, 'transport': transport,
            'goal_binding': deepcopy(spec.get('goal_binding')),
            'unavailable_typed_fields': sorted(set(unavailable))}


def compare(projection, hypothesis, search, bindings):
    """Compare only closed adapter fields and actual card parameter addresses."""
    _require(type(bindings) is list and 0 <= len(bindings) <= 64,
             'complete bounded operative target bindings required')
    seen = set(); parameters = {}
    required = {'energy_tev'} if projection['mode'] in ('model-events', 'analyze', 'svj-recipe','mass-width-grid','llp-plane-recipe','mssm-observable-map') else set()
    if projection['mode'] == 'model-events': required |= {'model_sha256', 'mass_gev', 'width_gev'}
    facts = projection['facts']
    for binding in bindings:
        _keys(binding, ('field', 'address'), 'operative target binding')
        field, address = binding['field'], binding['address']
        _require(field not in seen, 'duplicate operative target binding')
        seen.add(field)
        if field in ('mass_gev', 'width_gev'):
            _require(projection['mode'] == 'model-events' and type(address) is str and
                     address.startswith('MASS/' if field == 'mass_gev' else 'DECAY/'),
                     'generation target requires its literal MASS/DECAY parameter address')
            parameters[field]=address.split('/',1)[1]
            actual = facts['parameter_values'].get(address)
            _require(actual is not None and Decimal(str(actual)) == Decimal(str(hypothesis[field])),
                     'operative parameter value differs from hypothesis')
        elif field.startswith('coupling/'):
            parts=field.split('/')
            _require(len(parts)==3 and parts[2] in ('real','imag') and projection['mode']=='model-events' and
                     type(address) is str,'literal original generation coupling component required')
            rows=[row for row in hypothesis['couplings'] if row['name']==parts[1]]
            actual=facts['parameter_values'].get(address)
            _require(len(rows)==1 and actual is not None and
                     Decimal(str(actual))==Decimal(str(rows[0][parts[2]])),
                     'operative coupling component differs or is unavailable')
            # Source units, factors and vertex interpretation remain explicit
            # premises: equality is not an inferred coupling conversion.
        elif field == 'energy_tev':
            _require(address is None and facts.get(field) is not None,
                     'actual selected adapter collision energy unavailable')
            _require(Decimal(facts[field]) == Decimal(str(hypothesis[field])) and
                     (search is None or Decimal(facts[field]) == Decimal(str(search['applicability'][field]))),
                     'actual beam energy differs from original hypothesis/search')
        elif field == 'model_sha256':
            _require(address is None and facts.get(field) == hypothesis['model']['sha256'],
                     'operative model manifest differs from original hypothesis model source')
        elif field == 'basis':
            _require(address is None and facts.get(field) == hypothesis['basis'],
                     'actual adapter prediction basis unavailable or different')
        else:
            raise ValueError('unsupported operative field; semantic labels cannot override missing bindings')
    if parameters:
        _require(parameters.get('mass_gev') == parameters.get('width_gev'),
                 'literal mass and width must describe the same declared particle address')
    missing = required - seen
    _require(not missing, 'missing required operative target bindings: ' + ', '.join(sorted(missing)))
    if hypothesis['interference'] == 'included_signed' and projection['mode'] == 'signal-template':
        raise ValueError('positive signal template cannot represent signed interference')
    return {'checked_fields': sorted(seen), 'source_premises': projection['unavailable_typed_fields'],
            'physics_validated': False}


def task_slot(spec, key):
    """The actual adapter determines pathname vs document-pin transport."""
    _require(spec['mode'] == 'analyze' and spec['task'].get('backend') in ('rivet', 'rivet-built') and
             key == 'events' and type(spec['task'].get(key)) is str,
             'unsupported adapter task-path link; only actual supplied Events slot admitted')
    return 'events_path'


def _pin_transport(value):
    # Only an explicit accepted link may relocate an identical committed file.
    # Keep its digest and native staged filename, plus every other law field.
    if type(value) is dict:
        if set(value) in ({'path','sha256'}, {'path','sha256','staged_path'}):
            return {k:v for k,v in value.items() if k!='path'}
        return {k:_pin_transport(v) for k,v in value.items()}
    if type(value) is list:return [_pin_transport(v) for v in value]
    return value


def same_target(original, effective):
    _require(original is not None and effective is not None and original['mode'] == effective['mode'] and
             _pin_transport(original['facts']) == _pin_transport(effective['facts']) and original['goal_binding'] == effective['goal_binding'] and
             original['unavailable_typed_fields'] == effective['unavailable_typed_fields'],
             'accepted handoff changed operative stage target/source population')


def document_slot(spec, document, pointer, slot):
    """Preserve the native staged filename while replacing only a file pin."""
    import re
    if spec['mode']=='native-likelihood' and re.fullmatch(r'/model/files/(0|[1-9][0-9]*)',pointer):
        _keys(slot,('path','sha256','staged_path'),'native file graph handoff slot')
        _require(document['model']['files'][int(pointer.rsplit('/',1)[1])]==slot,
                 'native handoff slot is not an actual ordered model file')
        return {'staged_path':slot['staged_path']}
    _keys(slot,('path','sha256'),'existing source-bound pin handoff slot')
    return {}
