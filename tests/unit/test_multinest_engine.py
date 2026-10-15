"""Isolated nested-sampler adapter contracts with synthetic worker responses."""
import json
import sys

import pytest


def settings(**changes):
    value = {
        'n_live': 128,
        'sampling_efficiency': 0.8,
        'evidence_tolerance': 0.5,
        'constant_efficiency_mode': False,
        'seed': 17,
    }
    value.update(changes)
    return value


@pytest.mark.parametrize('field', ('n_live', 'sampling_efficiency', 'evidence_tolerance',
                                   'constant_efficiency_mode', 'seed'))
def test_unrecorded_setting_is_refused(field):
    from ravel.physics.inference import multinest
    value = settings()
    value.pop(field)
    with pytest.raises(ValueError, match=field):
        multinest.configuration(value)


def test_worker_is_a_subprocess_and_gpl_module_stays_out_of_host(monkeypatch, tmp_path):
    from ravel.physics.inference import multinest
    seen = {}

    def fake_run(argv, **kwargs):
        seen['argv'] = argv
        seen['payload'] = json.loads(kwargs['input'])
        return type('Completed', (), {'returncode': 0, 'stdout': json.dumps({
            'evidence_logz': -3.0, 'evidence_logz_error': 0.2, 'settings': settings()}), 'stderr': ''})()

    result = multinest.run_worker(settings(), interpreter=tmp_path / 'easyscan-python', runner=fake_run)
    assert seen['argv'][0] == str(tmp_path / 'easyscan-python')
    assert seen['payload']['settings'] == settings()
    assert result['evidence_logz_error'] == 0.2
    assert 'pymultinest' not in sys.modules


def test_stats_evidence_is_parsed_and_truncation_refused(tmp_path):
    from ravel.physics.inference import multinest
    stats = tmp_path / 'stats.dat'
    stats.write_text('nested sampling global log-evidence : -12.25 +/- 0.125\n')
    assert multinest.parse_stats(stats) == {'evidence_logz': -12.25, 'evidence_logz_error': 0.125}
    stats.write_text('nested sampling global log-evidence : -12.25 +/-\n')
    with pytest.raises(ValueError, match='truncated'):
        multinest.parse_stats(stats)


def test_reference_comparator_refuses_planted_wrong_row():
    from ravel.physics.inference import multinest
    rows = [
        {'reference_logz': -2.0, 'reference_error': 0.1, 'observed_logz': -2.1, 'observed_error': 0.1},
        {'reference_logz': 1.0, 'reference_error': 0.1, 'observed_logz': 2.0, 'observed_error': 0.1},
    ]
    assert multinest.compare_reference_rows(rows)['status'] == 'failed'


def test_stats_error_exponent_is_kept(tmp_path):
    from ravel.physics.inference import multinest
    stats = tmp_path / 'stats.dat'
    stats.write_text('nested sampling global log-evidence : -1.5E+01 +/- 2.5E-02\n')
    assert multinest.parse_stats(stats) == {'evidence_logz': -15.0, 'evidence_logz_error': 0.025}


def test_worker_has_no_default_launch_path(tmp_path):
    from ravel.physics.inference import multinest
    assert not hasattr(multinest, 'subprocess')
    with pytest.raises(TypeError):
        multinest.run_worker(settings(), interpreter=tmp_path / 'easyscan-python')
