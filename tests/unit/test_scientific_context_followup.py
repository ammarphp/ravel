"""a verified CLI context request can continue into an accepted vote."""
from ravel.workflow import scientific_judgment as j, agent_host
from test_transport_trust_boundaries import ReceiptHost
from test_cli_agent_host import stub_path
from test_scientific_context_continuation import PresentedHost, select
from test_scientific_judgment import cycle, prepare
from test_physics_review import run


class PresentedCLIHost(ReceiptHost):
    def __init__(self, stub, pages=None):
        self.presenter = PresentedHost(pages)
        super().__init__(stub=stub, mutate=self.presenter.enrich)

    def execute(self, node, request, control):
        actual = agent_host.AgentHost.from_config({'type': 'responses', 'endpoint': 'https://example.invalid/v1/responses',
                                                  'max_request_bytes': 2_000_000})
        prepared = actual.prepare_model_context(node, request)
        return actual._presented_result(super().execute(node, request, control), prepared['context'])


def test_verified_cli_context_request_then_followup_accepted(cycle, tmp_path, stub_path):
    binding = prepare(cycle, tmp_path / 'initial', 'critic', max_context_reworks=1, evidence_pages=[])
    j.execute_role(binding, PresentedCLIHost(stub_path, select(binding)))
    assert j.consume(cycle, binding)['value']['kind'] == 'scientific_context_request'
    fresh = j.continue_role(binding, tmp_path / 'followup')
    j.execute_role(fresh, PresentedCLIHost(stub_path))
    assert j.consume(cycle, fresh)['verdict'] == 'accept'
