"""Computed research protocol checks; missing producers are reported, not hidden."""
from ravel.workflow import research_protocol as protocol, research_cycle as cycle
from ravel.workflow import experiment_allocator as allocator

CHECKS = ['obligation_coverage', 'allocation', 'seed_to_test', 'excluded_has_signature',
          'confirmation_separation', 'protocol_producers_present']


def validate(check_id, value, *, base_dir):
    """Run one registered check over its typed contract and pinned evidence."""
    name = check_id.removeprefix('check:')
    if name not in CHECKS:
        raise ValueError('unknown research protocol check')
    if name == 'protocol_producers_present':
        return protocol.protocol_producers_present()
    try:
        if name == 'obligation_coverage':
            protocol.obligation_coverage(value['plan'], value['claims'], value['outputs'], base_dir=base_dir)
        elif name == 'allocation':
            allocator.check_allocation(value['case'], value['policy'], value['work_item'], base_dir=base_dir)
        elif name == 'seed_to_test':
            protocol.seed_to_test(value, base_dir=base_dir)
        elif name == 'excluded_has_signature':
            cycle.replay_register(value['events'], base_dir=base_dir)
        elif name == 'confirmation_separation':
            state = protocol._observed_state(base_dir)
            if state is None:
                raise ValueError('confirmation check requires recorded execution observations')
            reads = protocol.verify_selection_journal(state, value['selection_receipt'])
            report = protocol.selection_report(value['selection_receipt'], value['confirmation_pins'],
                                               base_dir=base_dir, state=state)
            protocol._verify_report_reads(value['selection_receipt'], report, reads)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {'valid': False, 'errors': [str(exc)]}
    return {'valid': True, 'errors': []}
