"""four planted manuscripts are flagged from the record, against a manuscript-only arm."""
import pytest

from planted_fixtures import CONDITIONS, MANUSCRIPT, manuscript_run


def arms(tmp_path, condition):
    from ravel.workflow import review_projection_battery
    root = manuscript_run(tmp_path.resolve() / ('run-' + condition), condition)
    return review_projection_battery.manuscript_arms(root, MANUSCRIPT, key='manuscript:' + condition)


def a_codes(value):
    return {f['code'] for f in value['findings'] if f['materiality'] == 'A'}


@pytest.mark.parametrize('condition', CONDITIONS)
def test_planted_manuscript_is_flagged_by_the_record_arm_only(tmp_path, condition):
    result = arms(tmp_path, condition)
    assert condition in a_codes(result['record']), result['record']
    assert result['record']['status'] == 'failed'
    # The same reviewer check, given only the manuscript, cannot see the defect.
    assert result['manuscript_only']['findings'] == []
    assert result['manuscript_only']['outcome'] == 'record_unavailable'


def test_the_four_conditions_score_four_of_four_against_zero(tmp_path):
    record = sum(c in a_codes(arms(tmp_path, c)['record']) for c in CONDITIONS)
    prose = sum(c in a_codes(arms(tmp_path, c)['manuscript_only']) for c in CONDITIONS)
    assert (record, prose) == (4, 0)


def test_clean_manuscript_gives_no_a_finding(tmp_path):
    result = arms(tmp_path, 'clean')
    assert result['record']['status'] == 'passed' and a_codes(result['record']) == set()


def test_a_manuscript_omitting_the_funnel_is_refused(tmp_path):
    assert 'funnel_undisclosed' in a_codes(arms(tmp_path, 'funnel_omitted')['record'])


def test_the_record_arm_never_reads_the_producer_headline(tmp_path):
    from ravel.workflow import review_projection
    result = arms(tmp_path, 'clean')
    manifest, contents = review_projection.load(result['record_packet'])
    assert 'RESULT.md' not in contents and {'research/protocol.json', MANUSCRIPT} <= set(contents)
