"""Read accepted ordinary scientific role calls without manufacturing worker credit.

This adapter returns observations of the original Graph/Host calls and registered
review events. It writes no receipt or registration and grants no new gate or
scientific acceptance authority.
"""
from pathlib import Path
from . import research_controller

from . import agent_graph, physics_review as review, scientific_judgment as judgment
from . import scientific_autonomy, review_context, final_results_review

ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration)
ROLE = {'physics_critic': ('critic', 'physics-critic'),
        'skeptical_verifier': ('verifier', 'skeptical-verifier'),
        'physics_decider': ('synthesizer', 'physics-decider')}


def final_roles(rundir):
    """Exact current accepted CI3 role population, or an explicit unknown result."""
    root = review._root(rundir)
    result = {'status': 'unknown', 'roles': [], 'errors': []}
    try:
        reg, events = review._read(root)
        view = review._view(reg, events)
        if view['state'] != 'accepted' or view['cycle'] is None:
            raise ValueError('current ordinary final review is not accepted')
        cycle = view['cycle']
        final = cycle.get('final_results')
        if final is None:
            raise ValueError('ordinary final review has no accepted CI3 binding')
        checkpoint = final_results_review.gate(root, final['manifest'])
        if set(event['role'] for event in view['reviews']) != set(ROLE):
            raise ValueError('ordinary final review lacks its exact original role population')
        calls, actors = set(), set()
        for event in view['reviews']:
            node_id, role_id = ROLE[event['role']]
            if event['actor_id'] != reg['policy']['actors'][event['role']]:
                raise ValueError('ordinary review changed its declared actor')
            actors.add(event['actor_id'])
            support = event.get('supporting_artifacts', [])
            review._live_pins(root, support)
            candidates, graphs = [], []
            for pin in support:
                path = review._path(root, pin['path'])
                if path.name == agent_graph.SPEC:
                    graphs.append((path.parent, pin))
                if path.suffix != '.json' or path.stat().st_size > 2_000_000:
                    continue
                try:
                    doc = review_context._strict_json_bytes(path.read_bytes())
                except (ValueError, UnicodeError):
                    continue
                if isinstance(doc, dict) and doc.get('kind') == 'scientific_judgment_request' and doc.get('role') == node_id:
                    candidates.append((pin, doc))
            # Support also pins the pre-case action request and may retain
            # predecessor Graphs/packets. Select the current request through
            # its exact displayed packet entry, never its filename alone.
            matches = []
            for graph, _ in graphs:
                spec = review.read_json(graph / agent_graph.SPEC)
                nodes = [node for node in spec['nodes']
                         if node['id'] == node_id and node['role'] == node_id]
                if not nodes:
                    continue
                if len(nodes) != 1:
                    raise ValueError('ordinary final Graph has ambiguous role nodes')
                node = nodes[0]
                packet_path = Path(node['packet']['path'])
                packet = review_context._safe_path(packet_path if packet_path.is_absolute() else root / packet_path)
                context = [pin for pin in support if pin.get('kind') == 'role_context'
                    and review._path(root, pin['path']) == packet / 'manifest.json'
                    and pin['manifest_sha256'] == node['packet']['manifest_sha256']
                    and pin['cycle_id'] == cycle['cycle_id']
                    and pin['cycle_sha256'] == cycle['sha256']]
                if not context:
                    continue
                if len(context) != 1:
                    raise ValueError('ordinary final role has ambiguous context bindings')
                manifest = review_context.verify_packet(packet,
                    expected_manifest_sha256=node['packet']['manifest_sha256'])
                entries = [entry for entry in manifest['artifacts'] if entry['id'] == 'judgment_request']
                if len(entries) != 1:
                    raise ValueError('ordinary final packet lacks its exact displayed request')
                entry = entries[0]
                for request, contract in candidates:
                    if (review._path(root, entry['source_path']) != review._path(root, request['path'])
                            or entry['source_sha256'] != request['sha256']
                            or entry['sha256'] != request['sha256']):
                        continue
                    if (contract['rundir'] == str(root) and contract['actor_id'] == event['actor_id']
                            and contract['cycle_id'] == cycle['cycle_id']
                            and contract['cycle_sha256'] == cycle['sha256']
                            and contract['phase'] == 'result_review' and contract.get('final_results') == final):
                        matches.append((request, contract, graph, node))
            if len(matches) != 1:
                raise ValueError('ordinary review has no unique original request and Graph binding')
            request, contract, graph, node = matches[0]
            for pin in [*contract['source_pins'], *contract['prepared_settings']]:
                scientific_autonomy._document(pin, root, max_bytes=64*1024**2)
            receipt = research_controller.role_receipt(graph, node_id,
                expected_subject_sha256=request['sha256'],
                expected_packet_sha256=node['packet']['manifest_sha256'],
                require_exact_subject=True, allowed_roles={node_id})
            if (receipt['execution_observation'] not in judgment.OBSERVATIONS
                    or receipt['attestation'] == 'self_attested'
                    or not receipt['context_transport_separated']):
                raise ValueError('ordinary final role has no independent observed transport')
            value = receipt['public_value']
            if (value['kind'] != 'scientific_review' or value['subject_sha256'] != request['sha256']
                    or value['verdict'] != event['verdict'] or value['summary'] != event['summary']
                    or value['claim_scope'] != event['claim_scope']):
                raise ValueError('ordinary final registered vote differs from its original worker result')
            if receipt['request_id'] in calls:
                raise ValueError('ordinary final roles reuse a transport request')
            calls.add(receipt['request_id'])
            result['roles'].append({'role': role_id, 'source': 'accepted_ordinary_ci3',
                'cycle_id': cycle['cycle_id'], 'actor_id': event['actor_id'],
                'request': request, 'graph': str(graph), 'request_id': receipt['request_id'],
                'context_manifest_sha256': receipt['context_manifest_sha256'],
                'receipt_sha256': receipt['receipt_sha256'],
                'execution_observation': receipt['execution_observation']})
        if len(actors) != len(ROLE):
            raise ValueError('ordinary final reviewers share a declared actor')
        result.update(status='observed', checkpoint=checkpoint)
    except ERRORS as exc:
        result['errors'].append(str(exc))
    return result
