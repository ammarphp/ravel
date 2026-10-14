"""Read-only hookless check for generation outputs without approved launches."""
from pathlib import Path
import json
import hashlib
from . import launch_authorization


def _generation(path):
    name = path.name.lower()
    return name.endswith(('.lhe', '.lhe.gz', '.hepmc', '.hepmc.gz', '.hepmc3', '.hepmc3.gz',
                          '.root', '.yoda', '.yoda.gz', '.lhco', '.lhco.gz', '.stdhep', '.stdhep.gz'))


def _generator(producer):
    if producer is None:
        return False
    name = producer[1].lower()
    return any(token in name for token in ('madgraph', 'mg5', 'pythia', 'herwig', 'sherpa', 'generate', 'generation'))


def _bound_outputs(root):
    events = launch_authorization._events(root)
    authorized = {e['sequence']: e for e in events if e['event'] == 'authorized'}
    outputs = []
    for event in events:
        if event['event'] != 'launched':
            continue
        auth = authorized.get(event.get('authorization_sequence'))
        if auth is None or event.get('authorization_sha256') != auth['sha256']:
            raise ValueError('launched event has no matching authorization')
        # Reuse the historical fingerprint and approval validator. Never credit
        # an arbitrary entry merely because its filename resembles a journal.
        launch_authorization._historical_errors(auth)
        approval = auth['authorization'].get('approval', {})
        if not approval.get('sha256'):
            continue
        snapshot = json.loads(approval.get('text', '{}'))
        if not snapshot.get('input_fingerprint'):
            continue
        context = auth.get('context', {})
        spec = context.get('stage_spec') or auth['authorization'].get('stage_binding', {})
        cwd = Path(spec.get('cwd') or root)
        if not cwd.is_absolute(): cwd = root / cwd
        for value in spec.get('outputs', []):
            path = Path(value)
            resolved = (path if path.is_absolute() else cwd / path).resolve()
            if not resolved.is_relative_to(root):
                raise ValueError('declared output escapes run')
            outputs.append(resolved)
    return outputs


def gate_errors(rundir: Path, gate: str, action: dict) -> list:
    from .decision_gate import GateError
    root = Path(rundir).resolve()
    from . import rdj_custody, execution, rdj_anchor
    external = rdj_custody.input_snapshot(root) or {}
    generated = []
    stages = execution.load_execution(root)['stages']
    for p in sorted(root.rglob('*')):
        if not p.is_file() or not _generation(p):
            continue
        rel = p.relative_to(root).as_posix()
        # Hash only snapshotted candidates; stage outputs can be multi-GB event files.
        if rel in external and external[rel] == hashlib.sha256(p.read_bytes()).hexdigest():
            continue
        if p.suffix.lower() == '.root':
            # ROOT is also a histogram/container format. Only generator-owned
            # stage output, or an unbound file, is a generation candidate.
            owners = []
            for stage_name, stage in stages.items():
                cwd = Path(stage.get('cwd') or root)
                cwd = cwd if cwd.is_absolute() else root / cwd
                for out in stage.get('outputs', []):
                    target = Path(out); target = (target if target.is_absolute() else cwd / target).resolve()
                    if p.resolve() == target or p.resolve().is_relative_to(target):
                        try:
                            current = rdj_anchor.stage_receipt(root, f"stage:{stage_name}:{stage['attempt_id']}")
                        except (OSError, ValueError, KeyError, TypeError):
                            continue  # An unregistered/stale stage cannot hide an unbound ROOT file.
                        owners.append(current)
            if owners and not any(_generator(rdj_anchor.producer(root, stage)) for stage in owners):
                continue
        generated.append(p)

    if not generated:
        return []
    try:
        bound = _bound_outputs(root)
        missing = [p for p in generated if not any(p.resolve() == b or b.is_dir() and p.resolve().is_relative_to(b) for b in bound)]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [GateError('raw_launch', gate, 'raw_launch', 'Launch journal is invalid: ' + str(exc),
                          'Restore the exact approval-bound launch journal.', tuple(str(p.relative_to(root)) for p in generated))]
    if not missing:
        return []
    return [GateError('raw_launch', gate, 'raw_launch', 'Generation outputs have no approval-bound launch.',
                      'Use the authorized launcher; retain the matching approval fingerprint and output declaration.',
                      tuple(str(p.relative_to(root)) for p in missing))]
