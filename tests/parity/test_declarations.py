"""P-2, P-4, P-9, P-12 and P-14 per declared transport, plus the structured-output row for the CLI workers."""
from copy import deepcopy
import re

import pytest

from parity_support import cards, cell, declarations, preferences, synthetic_probe, EXECUTABLE_SHA
from ravel.workflow import provider_transport as pt, transport_registry as tr

CLI = declarations('cli-worker') + declarations('cli-oneshot')
ALL = declarations()
VALUES = {'model': 'parity-model', 'effort': 'high', 'schema': '{"type":"object"}', 'workspace': '/synthetic/ws',
          'prompt': 'p', 'prompt_hint': 'hint', 'last_message': '/synthetic/last', 'mcp_config': '/synthetic/mcp.json',
          'role': 'parity-role'}


@pytest.mark.parametrize('document', CLI, ids=lambda d: d['id'])
def test_golden_argv_carries_every_declared_flag_and_a_capability_it_claims(document):
    template = document['argv_template']
    values = {**{name: '1' for name in tr.PLACEHOLDER.findall(' '.join(template))}, **VALUES,
              'effort_config': 'model_reasoning_effort="high"'}           # rendered from effort, as the adapter does
    argv = tr.render_argv(document, values)
    assert argv[0] == template[0] and not any('{' in a and '}' in a and tr.PLACEHOLDER.search(a) for a in argv)
    for flag in tr.template_flags(document):
        assert flag in argv, (document['id'], flag)                 # a missing flag fails the probe, not silently
    capabilities, text = document['capabilities'], ' '.join(template)
    assert capabilities['effort_control'] == ('{effort}' in text or '{effort_config}' in text)
    carrier = next((c for c in ('{effort}', '{effort_config}') if c in template), None)
    schema_carrier = '{schema}' in text or '--output-schema' in text
    assert (capabilities['structured_output'] and document['transport_kind'] == 'cli-worker') <= \
        (schema_carrier or document.get('worker_surface', {}).get('structured_output') == 'validated_text')
    if carrier:                                                       # a flag-form effort drops with its value
        dropped = tr.render_argv(document, {**values, 'effort': None, 'effort_config': None}) if \
            template[template.index(carrier) - 1].startswith('-') else None
        assert dropped is None or ('high' not in ' '.join(dropped) and len(dropped) == len(argv) - 2)


@pytest.mark.parametrize('document', ALL, ids=lambda d: d['id'])
def test_the_child_environment_holds_only_declared_names(document):
    planted = {'FOO_API_KEY': 'planted-secret', 'OTHER_TOKEN': 'planted-secret-2', 'PYTHONPATH': '/x', 'PATH': '/bin',
               'HOME': '/h', **{n: 'declared-value' for n in document['pass_env'] + document['auth']['env_names']}}
    env, names = tr.child_environment(document, planted)
    assert 'FOO_API_KEY' not in env and 'OTHER_TOKEN' not in env and 'PYTHONPATH' not in env
    declared = set(document['pass_env']) | set(document['auth']['env_names'])
    assert set(names) <= set(tr.BASE_ENVIRONMENT) | declared
    assert declared <= set(names)
    assert 'planted-secret' not in repr(names)


def test_undeclared_provider_keys_never_cross_between_routes():
    claude, codex = tr.load('claude-cli-worker-apikey'), tr.load('codex-cli-worker-apikey')
    source = {'ANTHROPIC_API_KEY': 'one', 'CODEX_API_KEY': 'two', 'OPENAI_API_KEY': 'three'}
    assert set(tr.child_environment(claude, source)[0]) == {'ANTHROPIC_API_KEY'}
    assert set(tr.child_environment(codex, source)[0]) == {'CODEX_API_KEY'}
    assert tr.child_environment(tr.load('claude-cli-worker'), source)[0] == {}


@pytest.mark.parametrize('document', [d for d in ALL if d['transport_kind'] in ('http-model', 'ravel-loop')],
                         ids=lambda d: d['id'])
def test_http_auth_variants_declare_a_header_style_the_wire_layer_honours(document):
    auth = document['auth']
    assert auth['kind'] in tr.AUTH_KINDS
    if auth['kind'] == 'none':
        assert pt.headers('chat_completions', None) .keys() == {'Content-Type', 'Accept'}
        return
    assert auth['header_style'] in tr.HEADER_STYLES
    sent = pt.headers('chat_completions', 'token-value', auth['header_style'])
    name = 'Authorization' if auth['header_style'] == 'bearer' else auth['header_style']
    assert sent[name].endswith('token-value') and (name != 'Authorization' or sent[name] == 'Bearer token-value')
    if auth['kind'] == 'env':
        assert auth['env_names'] and all(re.fullmatch(r'[A-Z][A-Z0-9_]*', n) for n in auth['env_names'])
    else:
        assert auth['command'] and not auth['env_names']


def test_a_token_command_is_called_once_per_request_and_its_output_never_leaks(tmp_path):
    program = tmp_path / 'token.sh'
    counter = tmp_path / 'count'
    program.write_text(f'#!/bin/sh\necho x >> {counter}\nprintf "secret-token-value"\n')
    program.chmod(0o700)
    tmp_path.chmod(0o700)
    try:
        pt.check_token_program(str(program))
    except pt.ProviderFailure:
        pytest.skip('sandbox-blocked: an ancestor of the temporary directory is group or world writable')
    assert pt.run_token_command([str(program)]) == 'secret-token-value'
    assert pt.run_token_command([str(program)]) == 'secret-token-value'
    assert counter.read_text().count('x') == 2
    with pytest.raises(pt.ProviderFailure) as failure:
        pt.run_token_command(['token.sh'])
    assert 'secret-token-value' not in str(failure.value)
    identity = pt.auth_identity({'kind': 'command', 'header_style': 'bearer', 'command': [str(program)]})
    assert 'secret-token-value' not in repr(identity) and 'command_sha256' in identity


@pytest.mark.parametrize('document', [d for d in ALL if d['transport_kind'] in ('http-model', 'ravel-loop')],
                         ids=lambda d: d['id'])
def test_local_only_refuses_a_non_loopback_destination_on_every_model_route(parity_env, document):
    card = next(c for c in cards() if c['id'] == 'consult-columnar')
    model = preferences(card, document)['tier_models']['judgment'][document['id']]
    row = cell(card, document, qualified=True, local_models=[model])
    loopback_local = document['billing'] == 'local' and bool(document.get('endpoint')) and tr.is_loopback(document['endpoint'])
    if not loopback_local:
        assert row['status'] == 'refused' and row['missing'], document['id']
        assert any(m.startswith('local_only') for m in row['missing']) or \
            not cell(card, document, qualified=True)['status'] == 'admitted'
    elif row['status'] == 'refused':
        assert not any(m.startswith('local_only') for m in row['missing'])     # refused for another named reason


@pytest.mark.parametrize('document', [d for d in ALL if d['transport_kind'] in tr.CLI_KINDS + ('http-model', 'ravel-loop')],
                         ids=lambda d: d['id'])
def test_a_same_family_role_is_placed_on_every_route_that_can_place_it(parity_env, document):
    base = next(c for c in cards() if c['id'] == 'consult-columnar')
    placed = cell(base, document, qualified=True)
    if placed['status'] != 'admitted':
        assert placed['missing'], document['id']       # an explicit refusal, recorded in the role matrix too
        return
    prefs = preferences(base, document)
    probe = synthetic_probe(document)
    options = dict(probes={document['id']: probe}, executables={document['id']: EXECUTABLE_SHA} if probe else {})
    chosen = tr.select(base, prefs, **options)
    assert chosen['transport_id'] == document['id']
    card = deepcopy(base)
    card['model'] = {**card['model'], 'distinct_family_from': []}
    assert tr.select(card, prefs, **options) == chosen      # an empty retired list changes nothing


FIVE_CLI_WORKERS = ('claude-cli-worker', 'codex-cli-worker', 'gemini-cli-worker', 'opencode-worker',
                    'antigravity-cli-worker')


@pytest.mark.parametrize('transport_id', FIVE_CLI_WORKERS)
def test_structured_output_row_holds_for_each_cli_worker(parity_env, transport_id):
    """enforced where the CLI carries a schema, otherwise validated text; never an unchecked final record."""
    from test_receipt_schema import FINAL, execution_for, receipt_via_finish
    document = tr.load(transport_id)
    surface = document['worker_surface']['structured_output']
    assert surface in tr.STRUCTURED_OUTPUT
    text = ' '.join(document['argv_template'])
    assert (surface == 'enforced') == (document['capabilities']['structured_output'] is True)
    if surface == 'enforced':
        assert '{schema}' in text or '--output-schema' in text or '--json-schema' in text
    ok = receipt_via_finish(parity_env, document)[2]
    assert ok['status'] == 'ok' and ok['final_record']['valid'] is True
    bad = receipt_via_finish(parity_env, document, final={'summary': 'completed flag missing'}, tag='-bad')[2]
    assert bad['status'] == 'failed' and bad['failure']['code'] == 'schema_invalid' and bad['final_record']['valid'] is False
    assert FINAL and execution_for(document)
