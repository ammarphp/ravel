"""Evidence for actual source, inventory and launch enforcement."""
from __future__ import annotations
from .seat_rows import _row
from ..confine.resource_mechanisms import valid_resource_mapping


def confinement_rows(launch, reservation, probe):
    """Credit only a finished qualified capsule with recorded enforced limits."""
    if not isinstance(launch, dict) or not launch.get('finished_id') or not launch.get('journal_id'):
        return {}
    plan, finish = launch.get('plan'), launch.get('confinement')
    if (not isinstance(plan, dict) or plan.get('kind') != 'confined' or plan.get('network') != 'none'
            or not plan.get('custody_sha256') or not isinstance(plan.get('qualification'), dict)
            or plan['qualification'].get('confirmed') is not True
            or plan['qualification'].get('backend') != plan.get('backend')
            or not isinstance(finish, dict) or finish.get('errors') != []):
        return {}
    common = {'record': launch['finished_id'], 'started': launch['journal_id'],
              'custody_sha256': plan['custody_sha256'], 'backend': plan.get('backend')}
    rows = {row: _row('satisfied', **common, mechanism='confine.prepare_and_finish') for row in ('T04',)}
    limits, enforced = plan.get('limits'), plan.get('limits_enforced')
    valid_limits = valid_resource_mapping(plan.get('backend'), limits, enforced)
    cpus, wall = (limits.get('cpus'), limits.get('wall_seconds')) if valid_limits else (None, None)
    if (valid_limits
            and isinstance(reservation, dict) and reservation.get('record_id')
            and type((reservation.get('amounts') or {}).get('core_hours')) in (int, float)
            and cpus * wall / 3600 <= reservation['amounts']['core_hours'] + 1e-12):
        rows['E06'] = _row('satisfied', **common, reservation=reservation['record_id'],
                           limits=limits, limits_enforced=enforced, limit_scopes=plan.get('limit_scopes'),
                           mechanism='confine.machine_grant_and_limits')
    if (isinstance(probe, dict) and probe.get('kind') == 'launch' and probe.get('equal') is True
            and probe.get('differences') == []):
        rows['T09'] = _row('satisfied', **common, mechanism='confine.qualified_inventory')
    return rows


def source_admission(store, step, run_dir, inputs, *, attempt):
    """Execute run-bound restriction checks before exposing any native input."""
    from copy import deepcopy
    from pathlib import Path
    from ravel.workflow import restriction_guard
    admitted = []
    root = Path(run_dir)
    for row in inputs:
        relative = row.get('destination') or row.get('path')
        if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
                or '..' in Path(relative).parts or not row.get('artifact') or not row.get('sha256')):
            raise ValueError('native input source admission needs a custody-bound relative path')
        restriction_guard.require('controller-native-input', {'path': str(root / relative)},
                                  rundir=root, output=None)
        admitted.append(deepcopy(row))
    body = {'step_id': step['id'], 'attempt': attempt, 'inputs': admitted,
            'mechanism': 'restriction_guard.require', 'passed': True}
    return {**body, 'record': store.append('native-source-admission', body)}


def authority_rows(store, step, context):
    """Record both actual successful effect checks, for this plan and attempt only."""
    rows = store.scan('step-authority')
    matching = [entry for entry in rows
                if entry['record'].get('step_id') == step['id']
                and entry['record'].get('attempt') == context.get('attempt', 1)]
    if len(matching) < 2:
        return {}
    latest = matching[-2:]
    times = []
    for entry in latest:
        body = entry['record']
        effect = body.get('effect') or {}
        stamp = effect.get('started_ns')
        if (not entry.get('id') or body.get('plan_sha256') != context.get('plan_sha256')
                or effect.get('id') != step['id']
                or (effect.get('pins') or {}).get('plan_sha256') != context.get('plan_sha256')
                or not isinstance(body.get('authority'), dict) or not body['authority']
                or type(stamp) is not int or stamp <= 0):
            return {}
        times.append(stamp)
    if times[0] >= times[1] or latest[0]['id'] == latest[1]['id']:
        return {}
    return {'G05': _row('satisfied', record=latest[-1]['id'], checks=[r['id'] for r in latest],
                        mechanism='authority.authorize_effect', plan_sha256=context.get('plan_sha256'))}


def input_rows(step, context, source, launch, probe, enforced):
    """Close input restrictions only after the admitted input view ran confined."""
    from .seat_rows import na
    if (not isinstance(source, dict) or not source.get('record') or source.get('passed') is not True
            or source.get('mechanism') != 'restriction_guard.require'
            or source.get('step_id') != step['id'] or source.get('attempt') != context.get('attempt', 1)
            or not isinstance(source.get('inputs'), list)
            or (enforced.get('T04') or {}).get('status') != 'satisfied'
            or (enforced.get('T04') or {}).get('evidence', {}).get('mechanism') != 'confine.prepare_and_finish'):
        return {}
    rows = {'C24': _row('satisfied', record=source['record'], launch=launch['finished_id'],
                        mechanism='restriction_guard.require_and_closed_capsule')}
    import sys
    if (isinstance(probe, dict) and probe.get('kind') == 'launch'
            and probe.get('tools') == [sys.executable]):
        rows['E02'] = na('native_probe_uses_only_controller_interpreter', record=launch['finished_id'])
    return rows


def acquisition_rows(launch, source):
    """Retain the guarded controller reader's completed audit, without inventing a child."""
    from .seat_rows import na
    import re
    if (not isinstance(launch, dict) or launch.get('backend') != 'controller-acquisition'
            or not launch.get('finished_id') or not launch.get('journal_id')
            or type(launch.get('exit_status')) is not int or launch['exit_status'] != 0
            or launch.get('timed_out') is not False or not isinstance(source, dict)
            or source.get('passed') is not True or not source.get('record')):
        return {}
    acquired = launch.get('acquisition') or {}
    audit = acquired.get('source_admission') or {}
    requests = audit.get('requests')
    if (acquired.get('source_scope_completed') is not True or type(requests) is not list
            or type(audit.get('bytes')) is not int or audit['bytes'] < 0
            or any(type(row) is not dict or row.get('admission') != 'restriction_guard.require'
                   or not isinstance(row.get('url'), str) or not row['url']
                   or re.fullmatch('[a-f0-9]{64}', str(row.get('descriptor_sha256'))) is None
                   for row in requests)):
        return {}
    proof = {'record': launch['finished_id'], 'started': launch['journal_id'],
             'source_admission': source['record'], 'requests': requests,
             'mechanism': 'controller_acquisition.restriction_guard_and_bounded_http'}
    rows = {row: _row('satisfied', **proof) for row in ('C24', 'E16', 'T05', 'SW22')}
    rows.update(acquisition_quantity_rows(acquired, proof))
    for row in ('G10', 'G14', 'SW27', 'SW17', 'SW34', 'SW35', 'SW36', 'SW37', 'SW38', 'SW24', 'T04', 'T09'):
        rows[row] = na('bounded_controller_source_reader_starts_no_authored_or_native_child', **proof)
    return rows


def gate_rows(store, step, context, prepared, launch):
    """Read stage-review proof only from the actual passed decision's provider record."""
    from . import spec
    from .services import digest
    if not isinstance(launch, dict) or not launch.get('journal_id') or not launch.get('finished_id'):
        return {}
    for entry in reversed(store.scan('gate-provider-check')):
        body = entry['record']
        action = body.get('action') or {}
        pins = action.get('view_pins') or {}
        mapped = (body.get('providers') or {}).get('rdj') or {}
        review = mapped.get('scientific_review') or {}
        if (not entry.get('id') or body.get('gate') != 'launch' or body.get('passed') is not True
                or body.get('action_sha256') != digest(action)
                or action.get('step') != step['id'] or action.get('node_id') != step['id']
                or pins.get('plan_sha256') != context.get('plan_sha256')
                or pins.get('step_sha256') != spec.step_sha256(step)
                or pins.get('attempt') != str(context.get('attempt', 1))
                or pins.get('launch_sha256') != prepared.get('launch_sha256')
                or not prepared.get('native_preflight')
                or pins.get('native_preflight') != prepared['native_preflight']
                or action.get('digest') != digest(pins)
                or mapped.get('action_digest') != action.get('digest') or mapped.get('view_pins') != pins
                or mapped.get('native_preflight') != prepared['native_preflight']
                or review.get('mechanism') != 'controller.native-review-admission'
                or review.get('plan_sha256') != context.get('plan_sha256') or review.get('step_id') != step['id']):
            continue
        mechanism = mapped.get('mechanism')
        if mechanism == 'controller.native_launch.mapping':
            if not mapped.get('approval_context') or not isinstance(mapped.get('approval'), dict) or not mapped['approval']:
                continue
            authority = {'approval_context': mapped['approval_context']}
        elif mechanism == 'controller.native_preparation.mapping':
            from .launch_gate import preparation_implementation
            try:
                implementation = preparation_implementation(step)
            except (ValueError, TypeError, KeyError, OSError):
                continue
            if (implementation is None or mapped.get('preparation_implementation') != implementation
                    or type(mapped.get('preparation_authority')) is not str or not mapped['preparation_authority']
                    or type(mapped.get('mode_record')) is not str or not mapped['mode_record']
                    or 'approval_context' in mapped or 'approval' in mapped):
                continue
            authority = {'preparation_authority': mapped['preparation_authority'], 'mode_record': mapped['mode_record'],
                         'preparation_implementation': implementation}
        else:
            continue
        return {row: _row('satisfied', record=entry['id'], mechanism=mechanism,
                           native_preflight=prepared['native_preflight'], launch=launch['finished_id'],
                           scientific_review=review, **authority) for row in ('G04', 'SW08')}
    return {}


def worker_inventory_rows(observation_id, step, record, prepared):
    """Credit preparation inventory only for its admitted provider and measured broker set."""
    import re
    from . import spec
    if (not observation_id or step.get('kind') is None or spec.branch(step) != 'worker' or step.get('operation')
            or (step.get('parameters') or {}).get('phase') != 'prepare'
            or record.get('status') != 'ok' or record.get('attestation') != 'transport_attested'):
        return {}
    inventory = record.get('tool_inventory') or {}
    belt = prepared.get('toolbelt') or {}
    selected = prepared.get('selection') or {}
    qualified = prepared.get('qualification_record')
    if (not qualified or not selected.get('transport_id') or record.get('transport') != selected['transport_id']
            or re.fullmatch('[a-f0-9]{64}', str(belt.get('manifest_sha256'))) is None
            or not isinstance(belt.get('tools'), list) or not belt['tools']
            or inventory.get('kind') != 'worker' or inventory.get('equal') is not True
            or inventory.get('differences') != [] or inventory.get('mcp_observed') is not True
            or inventory.get('mcp_error') is not None or inventory.get('tools') != sorted(belt['tools'])):
        return {}
    return {'E02': _row('satisfied', record=observation_id, qualification=qualified,
                        transport=selected['transport_id'], toolbelt=belt['manifest_sha256'],
                        mechanism='controller.qualified_provider_and_broker_inventory')}


def acquisition_quantity_rows(acquired, proof):
    """Keep a source handoff uninterpreted; this establishes no physical applicability."""
    from pathlib import PurePosixPath
    import re
    from .services import digest
    from .seat_rows import na
    transport = acquired.get('quantity_transport') or {}
    members = acquired.get('members')
    def inventory(rows):
        return (isinstance(rows, list) and bool(rows)
                and all(isinstance(row, dict) and set(row) == {'path', 'sha256'}
                        and isinstance(row['path'], str) and row['path'] not in ('', '.')
                        and not PurePosixPath(row['path']).is_absolute()
                        and '..' not in PurePosixPath(row['path']).parts
                        and '\\' not in row['path']
                        and re.fullmatch('[a-f0-9]{64}', str(row['sha256'])) is not None for row in rows)
                and len({row['path'] for row in rows}) == len(rows))
    if (transport.get('kind') != 'uninterpreted_source_transfer'
            or transport.get('source_fields_transformed') is not False
            or not inventory(members) or transport.get('members') != members
            or transport.get('inventory_sha256') != digest(members)):
        return {}
    evidence = {**proof, 'mechanism': 'controller_acquisition.uninterpreted_source_transfer',
                'inventory_sha256': transport['inventory_sha256']}
    if transport.get('representation') == 'metadata':
        if (transport.get('source_quantities') != ['text']
                or 'embedded_inventory' in acquired or 'member_inventory' in acquired):
            return {}
        return {'P05': na('metadata_transfer_interprets_no_scientific_quantity', **evidence)}
    population = acquired.get('member_inventory')
    if (transport.get('representation') != 'file_bytes' or transport.get('source_quantities') != ['values']
            or not isinstance(population, list) or not population
            or acquired.get('member_inventory_sha256') != digest(population)
            or 'embedded_inventory' in acquired):
        return {}
    from . import member_manifest
    try:
        member_manifest.rows({member_manifest.KEY: {'schema_version': 1, 'members': population}})
    except (ValueError, TypeError, KeyError):
        return {}
    prefixes = set()
    for row in population:
        found = [item for item in members if item['sha256'] == row['sha256']
                 and (item['path'] == row['blob'] or item['path'].endswith('/' + row['blob']))]
        if len(found) != 1:
            return {}
        prefixes.add(found[0]['path'][:-len(row['blob'])])
    if len(prefixes) != 1:
        return {}
    return {'P05': _row('satisfied', **evidence, member_inventory_sha256=acquired['member_inventory_sha256'],
                        scope='all source member bytes, with no numerical interpretation or field conversion')}
