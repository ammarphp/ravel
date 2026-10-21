"""Recorded scientific votes for tests, through the governed role route.

A declared reviewer name is advice and never enters the review journal. A test that needs a
recorded critic, verifier or decider decision prepares the actual scientific role, runs it on
an inert transport that reports a fresh observed request without tools, and consumes the bound
response. The graph runner records that dispatch like any other and the default resolver reads
the record. No model, network or native call.
"""
from copy import deepcopy
from pathlib import Path
import uuid

from ravel.workflow import agent_host, execution, physics_review as review, scientific_judgment as judgment
from ravel.workflow.state_io import read_json

ROLE = {'physics_critic': 'critic', 'skeptical_verifier': 'verifier', 'physics_decider': 'synthesizer'}
SUMMARY = 'Synthetic bound review of the recorded evidence'


class ObservedHost:
    """An inert transport reporting an observed fresh request without tools, as an HTTP adapter does."""
    identity = {'fixture': 'inert observed transport; zero native/model/network calls'}

    def __init__(self, *, verdict, summary=SUMMARY, findings=(), closes=(), mutate=None):
        self.verdict, self.summary, self.mutate = verdict, summary, mutate
        self.findings, self.closes = deepcopy(list(findings)), list(closes)

    def execute(self, node, request, control):
        packet = Path(node['packet']['path'])
        manifest = read_json(packet / 'manifest.json')
        entry = next(a for a in manifest['artifacts'] if a['id'] == 'judgment_request')
        contract = read_json(packet / entry['path'])
        case = read_json(contract['case_pin']['path'])
        audit = {'case_sha256': execution.digest(case),
                 'nodes': [{'id': n['id'], 'decision': 'supported', 'reason': 'Synthetic evidence review only',
                            'assumptions': [{'disposition': 'accepted', 'reason': 'Synthetic domain check'}
                                            for _ in n['assumptions']]} for n in case['nodes']],
                 'edges': [{'parent': e['parent'], 'child': e['child'], 'decision': 'supported',
                            'reason': 'Synthetic located link'} for e in case['edges']]}
        value = {'schema_version': 1, 'kind': 'scientific_review', 'subject_sha256': entry['sha256'],
                 'verdict': self.verdict, 'summary': self.summary, 'findings': self.findings, 'closes': self.closes,
                 'claim_scope': contract['claim_scope'] if self.verdict == 'accept' else None,
                 'audit': audit, 'proposal': None, 'proposal_verdict': None}
        if self.mutate:
            self.mutate(value, contract)
        agent_host.validate_public_result(value, node['parameters']['output_schema'])
        result = {'kind': 'model_result', 'value': value,
                  'transport': {'request_id': request['request_id'], 'execution_mode': 'responses_http'},
                  'isolation': {'fresh_request': True, 'parent_transcript_supplied': False,
                                'model_tools_supplied': False},
                  'physics_validated': False, 'execution_authorized': False}
        return control.call('synthetic_response', 'model', {'request_id': request['request_id']},
                            lambda: result, output_tokens=16)


def actors(root, *, retained_study=False):
    if retained_study:
        from ravel.workflow.retained_science_review import pending
        return pending(root)['review']['registration']['policy']['actors']
    return review._read(root)[0]['policy']['actors']


def bound_review(root, *, role, verdict, summary=SUMMARY, findings=(), closes=(), claim_scope=None,
                 retained_study=False, out=None, mutate=None, supporting_artifacts=None):
    """Record one journal review through the governed route; returns the consumer's journal event.

    ``supporting_artifacts`` adds pinned support beside the role's own, as a domain protocol's
    journal caller does; otherwise the ordinary consumer records the role's support.
    """
    root = Path(root)
    out = Path(out) if out is not None else root.parent / ('bound-review-' + uuid.uuid4().hex[:12])
    binding = judgment.prepare_role(root, out, role=ROLE[role], actor_id=actors(root, retained_study=retained_study)[role],
                                    model='control', reasoning_effort='high', max_output_tokens=1024,
                                    max_wall_seconds=20, claim_scope=claim_scope if verdict == 'accept' else None,
                                    allow_control=True, retained_study=retained_study)
    judgment.execute_role(binding, ObservedHost(verdict=verdict, summary=summary, findings=findings,
                                                closes=closes, mutate=mutate))
    if supporting_artifacts is None:
        return judgment.consume(root, binding, allow_control=True)
    verified = judgment.verify_binding(binding, allow_control=True)
    contract, value = verified['contract'], verified['value']
    return review.submit_review(root, role=judgment.ROLE[contract['role']], actor_id=contract['actor_id'],
        verdict=value['verdict'], summary=value['summary'], findings=value['findings'], closes=value['closes'],
        claim_scope=value['claim_scope'], retained_study=retained_study, binding=binding,
        supporting_artifacts=[*verified['supporting_artifacts'], *supporting_artifacts])


def bound_accept(root, *, scope='reproduction', closes=(), retained_study=False):
    """Critic, skeptic and decider accept the stated scope through bound responses."""
    return [bound_review(root, role=role, verdict='accept', claim_scope=scope, closes=closes,
                         retained_study=retained_study)
            for role in ('physics_critic', 'skeptical_verifier', 'physics_decider')]
