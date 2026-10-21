"""Host row qualification composes with an observed controller run."""
import sys

from ravel.controller import ledger, testing
from ravel.controller.authority import standing
from ravel.controller.confine import host_rows
from test_composition_wave_a import run as composed_run  # noqa: F401


def test_host_source_records_join_the_observed_controller(composed_run):
    store, _ = composed_run
    reader, _, _ = standing._snapshot(store)
    failure = {}

    def trace(frame, event, value):
        if frame.f_code is host_rows._sources.__code__ and event == 'return' and value is None:
            failure.update(line=frame.f_lineno, selection=frame.f_locals.get('selection'),
                           inventory=frame.f_locals.get('inventory'),
                           observation=frame.f_locals.get('o'),
                           matched_observations=len(frame.f_locals.get('matches') or []))
        return trace

    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        sources = host_rows._sources(reader)
    finally:
        sys.settrace(previous)
    assert sources is not None, failure
    with testing.seams(False, controller=True):
        rows = host_rows.evidence(store)
    assert set(rows) == set(host_rows.ROWS) | {'SW30'}, rows
    assert all(row['evidence']['record'] for row in rows.values())
    mechanisms = {'C23', 'SW04', 'G02', 'ROUTE-research', 'SW30', 'V09', *host_rows.ROWS}
    unmet = {row.get('id') for row in ledger.gate(store, 'deliver[accepted]')}
    assert mechanisms.isdisjoint(unmet), mechanisms & unmet
