"""Number tracing of delivered documents (D01, E20): tables trace exactly within rounding, prose is labelled."""
from __future__ import annotations

import json

import pytest

from ravel.controller.sink import numbers


def refs(*values):
    found = numbers.References()
    for value in values:
        found.add(value)
    return found.freeze()


@pytest.mark.parametrize('displayed, reference, matches', [
    ('0.123', 0.1234, True), ('0.12', 0.1234, True), ('0.124', 0.1234, False), ('41.7', 41.68, True),
    ('42', 41.6, True), ('42', 41.4, False), ('1.2e-3', 0.00124, True), ('1.2e-3', 0.00126, False),
    ('12.3%', 0.1234, True), ('12.3%', 12.31, True), ('-0.5', 0.5, False), ('1,234', 1234, True),
])
def test_displayed_rounding_decides_a_match(displayed, reference, matches):
    match = numbers.NUMBER.search(displayed)
    assert refs(reference).match(match.groups()) is matches


def test_relative_rounding_declared_by_the_plan_widens_the_match():
    match = numbers.NUMBER.search('100.0')
    assert not refs(100.4).match(match.groups())
    assert refs(100.4).match(match.groups(), relative=0.01)


def test_markdown_table_cells_trace_and_prose_is_labelled():
    text = ('# Result\n\nThe yield is 41.7 events; a cross-check gave 63.2.\n\n'
            '| Region | Yield | Note |\n|---|---|---|\n| SR-2j | 41.7 | 2j |\n| control | 99.9 | x |\n')
    found = numbers.trace(text, '.md', refs(41.7))
    assert [n['text'] for n in found['untraced_table']] == ['99.9']
    assert [n['text'] for n in found['unmatched_prose']] == ['63.2']
    assert found['table_numbers'] == 2  # header and label cells are not numbers of the result


def test_latex_tabular_rows_are_tables():
    text = '\\begin{tabular}{lc}\nRegion & Yield \\\\\n\\hline\nA & 41.7 \\\\\nB & 7.5 \\\\\n\\end{tabular}\n'
    found = numbers.trace(text, '.tex', refs(41.7))
    assert [n['text'] for n in found['untraced_table']] == ['7.5']


def test_identifiers_dates_versions_and_references_are_not_result_numbers():
    text = ('Step s07 of attempt 3 ran on 2026-10-17 at 12:30 with version 1.2.3 (digest 0123456789abcdef). '
            'See Figure 2, Table 1 and [4]. The run CI3 used P8 attacks.\n')
    assert numbers.trace(text, '.md', refs())['prose_numbers'] == 0


def test_discovery_language_is_found_and_negations_are_not():
    text = 'We see no significant excess. This is not evidence for a new particle. We claim a discovery.\n'
    found = numbers.trace(text, '.md', refs())
    assert [d['text'].lower() for d in found['discovery_language']] == ['discovery']


def test_machine_artifacts_supply_reference_values(tmp_path):
    (tmp_path / 'a.json').write_text(json.dumps({'value': 1.5, 'nested': [{'x': '2.25'}], 'flag': True}))
    (tmp_path / 'b.csv').write_text('name,value\nalpha,3.75\n')
    found = numbers.References()
    assert numbers.add_machine(tmp_path / 'a.json', found, 10 ** 6)
    assert numbers.add_machine(tmp_path / 'b.csv', found, 10 ** 6)
    assert not numbers.add_machine(tmp_path / 'missing.json', found, 10 ** 6)
    found.freeze()
    assert set(found.values) == {1.5, 2.25, 3.75}  # booleans are not numbers


def test_a_bound_or_approximate_cell_is_a_table_number():
    text = '| Quantity | Value |\n|---|---|\n| limit | < 3.2 fb |\n| estimate | ~ 7.5 |\n'
    found = numbers.trace(text, '.md', refs(41.7))
    assert [n['text'] for n in found['untraced_table']] == ['3.2', '7.5']
    assert numbers.trace(text, '.md', refs(3.2, 7.5))['untraced_table'] == []


def test_numbers_in_text_cells_are_labelled_like_prose():
    text = '| Quantity | Value |\n|---|---|\n| yield | 99.9 (observed) |\n| region | SR-2j |\n'
    found = numbers.trace(text, '.md', refs(41.7))
    assert found['untraced_table'] == [] and [n['text'] for n in found['unmatched_prose']] == ['99.9']
