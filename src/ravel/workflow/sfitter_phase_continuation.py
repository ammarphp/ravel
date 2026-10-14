"""Advance a supplied SFitter source phase through its existing review gate.

This prepares the next ordinary conductor context, never a production job,
vote, correction budget or approval for a fit. Manual-card workflow intake
remains distinct from this reviewed conductor continuation operation.
"""
import copy
import hashlib
import json
from pathlib import Path

from ravel.physics.ma5_saf import Capture
from . import sfitter_conductor as conductor, sfitter_workflow as workflow
from . import physics_review as review
from .state_io import atomic_json


def _write(path, value, generated, base):
    raw = (json.dumps(value, indent=2, allow_nan=False)+'\n').encode('utf-8')
    atomic_json(path, value)
    generated.read(path, base, hashlib.sha256(raw).hexdigest())
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def _members(out, capture):
    capture.ordinary(out, directory=True)
    paths = list(out.rglob('*'))
    for path in paths:
        capture.ordinary(path, directory=path.is_dir())
    return {p.relative_to(out).as_posix() for p in paths}


def _accepted(root, request, report, request_pin, capture):
    """Current ordinary gate plus the exact domain evidence of all three roles."""
    errors = review.gate_errors(root, 'reuse')
    if errors:
        raise ValueError('SFitter phase reuse refuses: '+'; '.join(errors))
    reg, events = review._read(root)
    view = review._view(reg, events)
    if (view['state'] != 'accepted' or len(view['reviews']) != 3 or
            any(row['claim_scope'] != request['claim_scope'] for row in view['reviews'])):
        raise ValueError('Exact accepted domain scope and all original review roles required')
    contexts={pin['path']:pin for row in view['reviews'] for pin in row.get('supporting_artifacts',[]) if pin.get('kind')=='role_context'}
    if contexts:
        capture=workflow._capture_review_sources([{'root':str(root),'support':list(contexts.values())}],root,capture)
    for row in view['reviews']:
        if row['actor_id'] != reg['policy']['actors'][row['role']]:
            raise ValueError('Original registered review actor required')
        support = row.get('supporting_artifacts', [])
        if request_pin not in support:
            raise ValueError('All three actual reviews must bind this exact domain request')
        matched = []
        for pin in support:
            # Keep the complete typed role commitment in the journal/view.
            # The ordinary gate authenticates its cycle and full indexed copy
            # census; bound_paths below captures every child for ending checks
            # and the next context. Capture.pin remains a strict file-pair API.
            review._support_shape(pin)
            path, raw = capture.pin({k: pin[k] for k in ('path', 'sha256')}, root)
            # Evidence may be source text/binary. Only exact domain reports
            # are candidates; every supplied artifact remains byte-bound.
            try:
                value = workflow._strict_document(raw)
            except (ValueError, UnicodeError):
                continue
            if isinstance(value, dict) and value.get('kind') == 'sfitter_domain_review':
                matched.append(value)
        if report not in matched:
            raise ValueError('Every registered role must bind the complete current domain report')
    paths = review.bound_paths(root)
    pins = []
    for path in paths:
        actual, raw = capture.read(path, root)
        pins.append({'path': str(actual), 'sha256': hashlib.sha256(raw).hexdigest()})
    return view, pins, capture


def advance(adoption_pin, protocol_request_pin, base, rundir, output):
    """Exact accepted source phase -> a fresh next phase context; zero dispatch."""
    out = conductor._fresh(output)
    root = review._root(rundir)
    path, request, capture = conductor._review_request(adoption_pin, protocol_request_pin, base)
    for module in (__file__, conductor.__file__, workflow.__file__, review.__file__):
        capture.pin(workflow._pin(Path(module)), base)
    protocol = conductor._domain_protocol()
    capture.pin(workflow._pin(Path(protocol.__file__)), base)
    report = protocol.context(request, path.parent)
    phase_index = workflow.PHASES.index(request['stage'])
    phase_concerns = {c['id'] for c in report['concerns']
                      if workflow.PHASES.index(c['owner_phase']) <= phase_index}
    if not phase_concerns <= set(request['required_concerns']):
        raise ValueError('Narrow accepted scope cannot advance an incomplete owning phase')
    if any(c['material'] and c['status'] != 'pass' for c in report['concerns']):
        raise ValueError('Material failed/unknown domain concerns require owning-phase rework')
    for pin in report['inputs']:
        capture.pin(pin, path.parent)
    exact_request_pin = {'path': str(path), 'sha256': hashlib.sha256(capture.files[path][1]).hexdigest()}
    view, journal_pins, capture = _accepted(root, request, report, exact_request_pin, capture)
    wp, raw = capture.pin(request['workflow'], path.parent)
    current = workflow._strict_document(raw)
    _, next_phase = workflow._resolve(current, wp.parent)
    if next_phase is None:
        raise ValueError('Datacard phases complete; ordinary native study intake remains required')
    conductor._protect(out, root, path.parent, wp.parent,
                       workflow.custody._regular(current['upstream_tree']['root'], wp.parent, directory=True))
    current = workflow._absolute_pins(copy.deepcopy(current), wp.parent)
    current['upstream_tree']['root'] = str(workflow.custody._regular(current['upstream_tree']['root'], wp.parent, directory=True))
    # Retain live original journal/input identities in the next study input
    # graph. A later journal append/hold does not silently become old approval.
    ap, adoption_raw = capture.pin(adoption_pin, base)
    retained = [*current['sources'], exact_request_pin,
                {'path': str(ap), 'sha256': hashlib.sha256(adoption_raw).hexdigest()}, *journal_pins]
    current['sources'] = list({p['path']: p for p in retained}.values())
    if getattr(capture,'review_contexts',None):
        current['retained_review_contexts']=copy.deepcopy(capture.review_contexts)
    capture.finish()
    out.mkdir(parents=True)
    generated = Capture()
    next_request = _write(out/'workflow.json', current, generated, out)
    next_context = conductor.prepare(next_request, out, out/'next-phase-context')
    generated.pin(next_context, out)
    receipt = {'schema_version': 1, 'kind': 'sfitter_reviewed_phase_continuation',
        'completed_source_phase': request['stage'], 'next_phase': next_phase,
        'workflow': next_request, 'context': next_context,
        'prior_review': {'rundir': str(root), 'cycle_id': view['cycle']['cycle_id'],
                         'claim_scope': request['claim_scope'],
                         'review_events': [r['sha256'] for r in view['reviews']]},
        'domain_request': exact_request_pin, 'retained_journal_inputs': journal_pins,
        'required_phase_concerns': sorted(phase_concerns),
        'remaining_warnings': report['warnings'],
        'execution_authorized': False, 'physics_validated': False,
        'production_calls_dispatched': 0, 'old_votes_carried': []}
    _write(out/'continuation-receipt.json', receipt, generated, out)
    expected = {'workflow.json', 'next-phase-context', 'next-phase-context/context.json', 'continuation-receipt.json'}
    if _members(out, generated) != expected:
        raise ValueError('Unexpected continuation output membership')
    ending, ending_pins, capture = _accepted(root, request, report, exact_request_pin, capture)
    if ending != view or ending_pins != journal_pins:
        raise ValueError('Accepted phase changed during continuation')
    capture.finish()
    generated.finish()
    if _members(out, generated) != expected:
        raise ValueError('Ending continuation output membership changed')
    return receipt


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adoption', required=True)
    parser.add_argument('--domain-request', required=True)
    parser.add_argument('--rundir', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    result = advance(workflow._pin(Path(args.adoption)), workflow._pin(Path(args.domain_request)),
                     Path.cwd(), args.rundir, args.output)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
