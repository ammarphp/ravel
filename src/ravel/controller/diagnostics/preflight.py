"""One explicit controller hook to compile and pin diagnostics before execution."""
from __future__ import annotations

from .expected import build_expected
from .projection import project_obligations
from .records import pin_expected, require_expected


def prepare_run(store, route_spec, plan, engagement, *, contexts, instructions=None,
                cards=None, classify=None, ledger=None, store_factory=None, catalogue=None):
    rows = project_obligations(store, contexts, ledger=ledger, store_factory=store_factory,
                               catalogue=catalogue)
    document = build_expected(route_spec, plan, engagement, obligation_rows=rows,
                              instructions=instructions, cards=cards, classify=classify)
    identifier = pin_expected(store, document)
    require_expected(store, plan['sha256'])
    return {'expected_record_id': identifier, 'expected_sha256': document['sha256']}
