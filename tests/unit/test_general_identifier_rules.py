"""Identifier rules are general shapes, never lists of collaborations, groups or papers.

Every identifier here is synthetic (years 9xxx, which no real code has).
"""
import pytest

from ravel.validation import verify_smearing
from ravel.workflow import discovery_http, route_prompt

J = '-'.join


@pytest.mark.parametrize('text,code', [
    ('Recast ' + J(['XYZ', 'GRP', '9012', '07']) + ' with this model', J(['XYZ', 'GRP', '9012', '07'])),
    ('use ' + J(['Abc', 'PAS', 'QR', '90', '123']) + ' please', J(['Abc', 'PAS', 'QR', '90', '123'])),
    ('the ' + J(['ANA', '9001', '01']) + ' search', J(['ANA', '9001', '01'])),
    ('the ' + ' '.join(['XYZ', 'GRP', '9012', '07']) + ' search', ' '.join(['XYZ', 'GRP', '9012', '07'])),
])
def test_request_analysis_codes_are_read_by_shape(text, code):
    assert [m.group(1) for m in route_prompt.ANACODE_RE.finditer(text)] == [code]


@pytest.mark.parametrize('text', [
    'a mass of 200 GeV and 150 GeV at 13 TeV', 'Run 2 data, 139 fb-1', 'and B-290 records',
    'with 50 100 GeV cuts', 'dates 2026-10-12',
])
def test_ordinary_text_has_no_analysis_code(text):
    assert list(route_prompt.ANACODE_RE.finditer(text)) == []


def test_report_numbers_count_as_codes_only_under_the_records_own_collaborations():
    numbers = [J(['LAB', 'EP', '9019', '001']), J(['XYZ', 'GRP', '9018', '12']), J(['GRP', '9017', '03']),
               J(['OTHER', 'GRP', '9016', '04']), 'not-a-code']
    assert discovery_http.analysis_codes(numbers, ['XYZ']) == numbers[1:3]
    assert discovery_http.analysis_codes(numbers, []) == [numbers[2]]


@pytest.mark.parametrize('routine,segment', [
    ('XYZ_9012_SUS_FAKE', 'SUS'), ('XYZ_9012_EXOT_FAKE', 'EXOT'), ('XYZ_9012_BSM', 'BSM'),
    ('XYZ_SUSY_9012', 'SUSY'), ('XYZ_9012_I0001', None), ('XYZ_9012_JETS', None),
])
def test_search_routine_segments_abbreviate_search_keywords(routine, segment):
    assert verify_smearing.search_name_segment(routine) == segment


def test_catalogue_builder_reads_analysis_codes_of_any_group():
    from ravel.workflow import analysis_catalog_build as build
    code = J(['QRS', '9015', '22'])
    assert build.analysis_ids('see ' + J(['XYZ', code]) + ' and ' + code) == [code]
    assert build.analysis_ids('no code in ' + J(['XYZ', '9015'])) == []


@pytest.mark.parametrize('text,routine', [
    ('run ' + '_'.join(['XYZ', '9012', 'I0042']) + ' over my sample', '_'.join(['XYZ', '9012', 'I0042'])),
    ('the ' + '_'.join(['SYN', '9256', 'I0256', 'MODE']) + ' routine', '_'.join(['SYN', '9256', 'I0256', 'MODE'])),
])
def test_rivet_routines_are_read_for_any_experiment_token(text, routine):
    assert [m.group(1) for m in route_prompt.RIVET_RE.finditer(text)] == [routine]
    assert not list(route_prompt.RIVET_RE.finditer('a run_2 sample and x_y_z are not routine ids'))


def test_inspire_records_are_read_at_any_length():
    assert [m.group(1) for m in route_prompt.INSPIRE_RE.finditer('record ins42 and INS0010')] == ['42', '0010']
    assert not list(route_prompt.INSPIRE_RE.finditer('an instance of insight'))
