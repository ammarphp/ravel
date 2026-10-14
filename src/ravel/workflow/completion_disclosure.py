"""Computed candidate funnel, data changes and human interventions for delivery."""
from copy import deepcopy
from pathlib import Path
from .completion_claims import selection_record


def required(root):
    root = Path(root)
    return (root / 'research/protocol.json').exists() or (root / 'research/binding.json').exists()


def _bound(pin, inputs, root):
    if type(pin) is not dict or not {'path', 'sha256'} <= pin.keys():
        raise ValueError('source-backed research artifact pin required')
    path = Path(pin['path']); path = path if path.is_absolute() else Path(root) / path
    actual = inputs.capture(path)
    if pin['sha256'] != actual['sha256'] or 'size' in pin and pin['size'] != actual['size']:
        raise ValueError('research disclosure artifact changed')
    return actual


def build(root, *, _inputs=None):
    from .task_completion import _Inputs
    root = Path(root).absolute(); inputs = _inputs or _Inputs(root); own = _inputs is None
    try:
        protocol = inputs.document(inputs.capture(root / 'research/protocol.json'))
        if protocol.get('kind') != 'research-protocol' or protocol.get('schema_version') != 1:
            raise ValueError('bound research protocol required for disclosure')
        regime = protocol.get('regime')
        if regime not in ('open_exploratory', 'closed_scored'):
            raise ValueError('declared research regime required')
        stages = {}
        for row in protocol['stages']:
            if row['id'] in stages: raise ValueError('distinct research stages required')
            stages[row['id']] = (inputs.document(_bound(row['artifact'], inputs, root))
                                 if row.get('artifact') else row)
        ideas = stages.get('ideas', {}).get('ideas', [])
        generated = [r['id'] for r in ideas]
        if len(set(generated)) != len(generated): raise ValueError('distinct generated candidate census required')
        verdicts = stages.get('screen', {}).get('verdicts', [])
        screened = [r['idea'] for r in verdicts]
        if len(set(screened)) != len(screened) or not set(screened) <= set(generated):
            raise ValueError('screened candidates must match generated population')
        if any(r.get('verdict') not in ('discard', 'promote', 'engineer') for r in verdicts):
            raise ValueError('recorded candidate screen verdict required')
        selection = stages.get('validate', {}).get('selection')
        if type(selection) is dict and {'path', 'sha256'} <= selection.keys():
            selection_pin = _bound(selection, inputs, root)
        else:
            # The research protocol owns inline stage records. The immutable stage artifact is
            # its source; a pointer selects just the selection fields.
            selection_path = root / 'research/selection.json'
            if not selection_path.exists(): raise ValueError('trials_unreported: retained selection artifact required')
            selection_pin = inputs.capture(selection_path)
            if selection is not None and inputs.document(selection_pin) != selection:
                raise ValueError('selection artifact differs from protocol selection')
        record = selection_record(selection_pin, base_dir=root, _inputs=inputs, regime=regime)
        source = inputs.document(selection_pin)
        trial_candidates = {r['candidate'] for r in source['trials']}
        if not trial_candidates <= set(screened): raise ValueError('trial candidates missing from disclosed screen')
        selected = record['selected_candidate']
        if selected is not None and (selected not in trial_candidates or any(r['idea'] == selected and r['verdict'] == 'discard' for r in verdicts)):
            raise ValueError('selected candidate must survive disclosed screening')
        funnel = {'generated': len(generated), 'screened': len(screened),
                  'discarded': sum(r['verdict'] == 'discard' for r in verdicts),
                  'selected': int(selected is not None), 'selected_candidate': selected,
                  'rule': record['rule'], 'n_trials': record['n_trials']}
        deltas = []; interventions = []
        delta_path = root / 'research/dataset_manifest_deltas.json'
        if delta_path.exists():
            for row in inputs.document(inputs.capture(delta_path))['deltas']:
                if row.get('operation') not in ('subsampling', 'synthesis', 'transformation') or not row.get('reason'):
                    raise ValueError('dataset change requires operation and reason')
                before_pin = _bound(row['before'], inputs, root); after_pin = _bound(row['after'], inputs, root)
                before = inputs.document(before_pin); after = inputs.document(after_pin)
                if type(before) is not dict or type(after) is not dict: raise ValueError('dataset manifest objects required')
                deltas.append({**deepcopy(row), 'before': before_pin, 'after': after_pin,
                               'changed_fields': sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))})
        else: inputs.absent(delta_path)
        human_path = root / 'research/human_interventions.json'
        if human_path.exists():
            interventions = inputs.document(inputs.capture(human_path))['interventions']
            if type(interventions) is not list or any(type(row) is not dict or row.get('kind') not in
                    ('human_manual', 'human_filtering', 'human_steering') or not row.get('action') or not row.get('reason') for row in interventions):
                raise ValueError('located human intervention records required')
        else: inputs.absent(human_path)
        result = {'schema_version': 1, 'kind': 'computed-research-disclosure', 'candidate_funnel': funnel,
                  'dataset_manifest_deltas': deltas, 'human_interventions': deepcopy(interventions), 'regime': regime,
                  'sources': [inputs.pins[str(root / 'research/protocol.json')], selection_pin]}
        if own: inputs.finish()
        return result
    finally:
        if own: inputs.close()
