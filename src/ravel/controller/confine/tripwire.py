"""Non-disableable substrate assertion for controller launch boundaries."""
import json
from pathlib import Path


def check(root, layer):
    from ravel.workflow import agent_tripwire
    from . import runs
    if runs.owner_of(root) is None:
        return agent_tripwire.check(layer)
    import ravel
    # Installed policy only: no environment-selected table or optional mode switch.
    source = Path(ravel.__file__).parent / 'data/agents/sanctioned.json'
    layers = {row['layer']: row['acting_kinds'] for row in json.loads(source.read_text())['tripwire_layers']}
    current = agent_tripwire.context()
    ok = isinstance(current, dict) and current.get('ravel_kind') in layers.get(layer, ())
    verdict = {'layer': layer, 'ok': ok, 'mode': 'block', 'context': current,
               'reason': None if ok else 'controller launch requires an admitted substrate context'}
    owner = runs.owner_of(root)
    runs.store(owner[0]).append('tripwire', verdict)
    if not ok:
        raise agent_tripwire.TripwireViolation(verdict['reason'])
    return verdict
