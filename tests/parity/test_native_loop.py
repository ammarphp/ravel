"""P-10, P-11 and P-1 for the ravel-loop kind: every provider adapter gives the same loop outcome and worker receipt."""
import pytest

from parity_support import declarations
from ravel.workflow import agent_worker as worker
from test_receipt_schema import FINAL, execution_for, receipt_via_finish, schema_of
from test_ravel_loop import ADAPTERS, setup, wire

PRODUCER = {'type': 'object', 'properties': {'completed': {'type': 'boolean'}, 'summary': {'type': 'string'}},
            'required': ['completed', 'summary'], 'additionalProperties': False}


def function_calling(tmp_path, monkeypatch, adapter):
    root = tmp_path / adapter
    root.mkdir()
    script = [wire(adapter, name, args, i) for i, (name, args) in enumerate([
        ('echo', {'n': 1}), ('forbidden', {}), ('echo', {'n': 2}), ('submit_final', FINAL)])]
    loop, sender, effects, _ = setup(root, monkeypatch, script, adapter, max_steps=2, final_schema_override=PRODUCER)
    result = loop.run('perform synthetic work')
    return {'codes': [r['code'] for r in result['action_receipts']], 'final': result['final'], 'effects': effects,
            'model_calls': len(sender.calls), 'turn_receipts': len(result['turn_receipts']),
            'authority': result['framework_values_are_scientific_authority']}, result


def test_every_adapter_gives_the_same_function_calling_outcome(tmp_path, monkeypatch):
    outcomes = {a: function_calling(tmp_path, monkeypatch, a)[0] for a in ADAPTERS}
    reference = outcomes[ADAPTERS[0]]
    assert reference['codes'] == ['ok', 'unknown_tool', 'budget_exhausted', 'ok'] and reference['final'] == FINAL
    assert all(o == reference for o in outcomes.values()), outcomes


@pytest.mark.parametrize('invalid,code', [('{bad', 'malformed_json'),
    ('[{"action":"echo","args":{}},{"action":"echo","args":{}}]', 'multiple_actions'),
    ('{"action":"missing","args":{}}', 'unknown_tool')])
def test_text_protocol_errors_are_typed_and_consume_budget_on_every_adapter(tmp_path, monkeypatch, invalid, code):
    seen = []
    for adapter in ADAPTERS:
        root = tmp_path / adapter
        root.mkdir()
        good = '{"action":"submit_final","args":{"completed":true,"summary":"parity stub"}}'
        loop, sender, effects, _ = setup(root, monkeypatch, [invalid, good], adapter, text=True,
                                         final_schema_override=PRODUCER)
        result = loop.run('synthetic vote')
        seen.append((result['action_receipts'][0]['code'], result['steps'], len(sender.calls), effects, result['final']))
    assert all(s == seen[0] for s in seen)
    assert seen[0] == (code, 2, 2, [], FINAL)


def test_the_loop_result_becomes_the_same_worker_receipt_schema_as_a_cli_worker(tmp_path, monkeypatch, parity_env):
    _, result = function_calling(tmp_path, monkeypatch, ADAPTERS[0])
    usage = {'input_tokens': 2, 'output_tokens': 1, 'cost_usd': None, 'reported': True}
    document = declarations('ravel-loop')[0]
    execution = {**execution_for(document), 'usage': usage}
    _, _, loop_receipt = receipt_via_finish(parity_env, document, execution=execution, final=result['final'])
    cli = declarations('cli-worker')[0]
    cli_receipt = receipt_via_finish(parity_env, cli)[2]
    assert loop_receipt['status'] == 'ok' and loop_receipt['final_record']['valid'] is True
    assert schema_of(loop_receipt) == schema_of(cli_receipt) and set(loop_receipt) == worker.RECEIPT_FIELDS
