"""Synthetic long-job submission records; no scheduler or credentials are used."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.workflow.backends import site_batch as batch


def spec(**site):
    return {'site': {'scheduler': 'htcondor', **site},
            'resources': {'cpus': 1, 'memory_mib': 2000, 'wall_seconds': 7200},
            'argv': ['true'], 'outputs': [], 'env': {}}


def test_declared_class_proxy_and_environment(tmp_path):
    proxy = tmp_path / 'proxy path'
    proxy.touch()
    job = spec(job_length_classes={'brief': 3600, 'extended': 10800},
               proxy_path=str(proxy), environment_allowlist=['A', 'B'], environment={'A': '1', 'B': '2'})
    batch.SiteBackend().validate(job)
    text = batch.render({'spec': job}, tmp_path, 'synthetic-job')
    assert '+JobFlavour = "extended"' in text
    assert f'x509userproxy = "{proxy}"' in text
    assert 'environment = "A=1 B=2"' in text
    assert 'getenv = False' in text


def test_selected_class_refuses_excess_walltime(tmp_path):
    job = spec(job_length_classes={'brief': 3600}, job_flavour='brief')
    with pytest.raises(ValueError, match='wall time'):
        batch.SiteBackend().validate(job)
    with pytest.raises(ValueError, match='wall time'):
        batch.render({'spec': job}, tmp_path, 'synthetic-job')


def test_proxy_owned_by_another_user_is_refused(tmp_path, monkeypatch):
    proxy = tmp_path / 'proxy'
    proxy.touch()
    real_stat = Path.stat

    def wrong_owner(path, *args, **kwargs):
        if path == proxy:
            return SimpleNamespace(st_mode=0o100600, st_uid=batch.os.getuid() + 1)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', wrong_owner)
    with pytest.raises(ValueError, match='owned'):
        batch.SiteBackend().validate(spec(proxy_path=str(proxy)))


def test_unallowlisted_environment_is_refused():
    with pytest.raises(ValueError, match='allowlist'):
        batch.SiteBackend().validate(spec(environment_allowlist=['A'], environment={'B': '2'}))


@pytest.mark.parametrize('site', [
    {'job_length_classes': {}}, {'job_length_classes': {'brief': True}},
    {'job_length_classes': {'brief': -1}}, {'job_length_classes': {'brief': 1.5}},
    {'job_length_classes': {'brief\nqueue': 10000}}, {'job_length_classes': {'brief': '10000'}},
    {'job_flavour': 'undeclared'}, {'job_length_classes': {'brief': 10000}, 'job_flavour': None},
    {'environment_allowlist': 'A'}, {'environment_allowlist': ['A', 'A']},
    {'environment_allowlist': [1]}, {'environment_allowlist': ['A=B']},
    {'environment_allowlist': ['API_KEY']}, {'environment_allowlist': ['OMP_NUM_THREADS']},
    {'environment_allowlist': ['RAVEL_OUTPUT_DIR']},
    {'environment_allowlist': ['A'], 'environment': {'A': '1\ngetenv = True'}},
    {'environment_allowlist': ['A'], 'environment': {'A': '1\rgetenv = True'}},
    {'environment_allowlist': ['A'], 'environment': {'A': '$(HOME)'}},
    {'environment_allowlist': ['A'], 'environment': {'A': 1}}, {'environment': 'A=1'},
])
def test_invalid_long_job_records(site):
    with pytest.raises(ValueError):
        batch.SiteBackend().validate(spec(**site))


@pytest.mark.parametrize('key', ['+JobFlavour', '+JOBFLAVOUR', '+MaxRuntime', 'GETENV', 'environment',
                              'x509userproxy', '+X509UserProxy', 'Request_Memory', '+RequestMemory'])
def test_free_form_options_cannot_bypass_typed_settings(key):
    with pytest.raises(ValueError, match='RAVEL-controlled'):
        batch.SiteBackend().validate(spec(options={key: 'untrusted'}))


def test_walltime_boundary_and_automatic_class_are_site_supplied(tmp_path):
    job = spec(job_length_classes={'longer': 10000, 'exact': 7200}, job_flavour='exact')
    assert '+JobFlavour = "exact"' in batch.render({'spec': job}, tmp_path, 'synthetic-job')
    del job['site']['job_flavour']
    assert batch.long_job_settings(job['site'], 7200)['job_flavour'] == 'exact'
    with pytest.raises(ValueError, match='wall time'):
        batch.long_job_settings(job['site'], 10001)
    # Old site records still render without inventing a site's class or a proxy.
    text = batch.render({'spec': spec()}, tmp_path, 'synthetic-job')
    assert 'JobFlavour' not in text and 'x509userproxy' not in text


def test_proxy_never_opened_and_rechecked_when_rendering(tmp_path, monkeypatch):
    proxy = tmp_path / 'fake-proxy'
    proxy.touch()
    job = spec(proxy_path=str(proxy))
    monkeypatch.setattr(Path, 'open', lambda *a, **k: pytest.fail('proxy contents must not be opened'))
    batch.SiteBackend().validate(job)
    assert str(proxy) in batch.render({'spec': job}, tmp_path, 'synthetic-job')
    proxy.unlink()
    with pytest.raises(ValueError, match='exist'):
        batch.render({'spec': job}, tmp_path, 'synthetic-job')


def test_proxy_must_be_literal_regular_absolute_file(tmp_path):
    ordinary = tmp_path / 'file'
    ordinary.touch()
    link = tmp_path / 'link'
    link.symlink_to(ordinary)
    for path in [str(link), str(tmp_path), str(tmp_path / 'missing'), 'relative', 'bad\npath', '/$(PROXY)']:
        with pytest.raises(ValueError):
            batch.SiteBackend().validate(spec(proxy_path=path))


def test_environment_escaping_and_stage_env_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv('UNDECLARED', 'not-to-export')
    job = spec(environment_allowlist=['A', 'B', 'C'], environment={'A': 'spacey \'quoted\' "value"', 'B': ''})
    job['env'] = {'C': '3'}
    text = batch.render({'spec': job}, tmp_path, 'synthetic-job')
    assert 'environment = "A=\'spacey \'\'quoted\'\' ""value""\' B=\'\' C=3"' in text
    assert 'UNDECLARED' not in text and 'not-to-export' not in text
    job['env']['D'] = '4'
    with pytest.raises(ValueError, match='allowlist'):
        batch.SiteBackend().validate(job)
    job['env'] = {'A': 'different'}
    with pytest.raises(ValueError, match='agree'):
        batch.SiteBackend().validate(job)


def test_slurm_has_explicit_environment_and_no_condor_handoff(tmp_path):
    job = spec(environment_allowlist=['A'], environment={'A': 'one two'})
    job['site']['scheduler'] = 'slurm'
    text = batch.render({'spec': job}, tmp_path, 'synthetic-job')
    assert '#SBATCH --export=NIL' in text
    plan = {'spec': job, 'plan_sha256': 'synthetic', 'readonly_trees': []}
    assert "export A='one two'" in batch.wrapper(plan)
    for field in ['export', 'get-user-env', 'time']:
        job['site']['options'] = {field: 'untrusted'}
        with pytest.raises(ValueError, match='RAVEL-controlled'):
            batch.SiteBackend().validate(job)
    del job['site']['options']
    job['site']['job_length_classes'] = {'extended': 10000}
    with pytest.raises(ValueError, match='htcondor'):
        batch.SiteBackend().validate(job)


def test_readonly_tree_exports_require_declared_names():
    job = spec()
    job['readonly_trees'] = [{'path': '/synthetic/tree', 'env': 'TREE_ROOT'}]
    with pytest.raises(ValueError, match='allowlist'):
        batch.SiteBackend().validate(job)
    job['site']['environment_allowlist'] = ['TREE_ROOT']
    batch.SiteBackend().validate(job)


def test_prepare_accepts_shared_site_record_and_pins_it(monkeypatch, tmp_path):
    monkeypatch.setattr(batch, '_tool', lambda name: {'path': '/synthetic/' + name, 'sha256': '0' * 64})
    job = spec(job_length_classes={'extended': 10000}, environment_allowlist=['A'], environment={'A': '1'})
    job.update(schema_version=1, backend='site', stage='synthetic-stage')
    plan = batch.eb.prepare(job)
    assert plan['spec']['site'] == job['site']
    assert '+JobFlavour = "extended"' in batch.render(plan, tmp_path, 'synthetic-job')


def test_submission_passes_explicit_slurm_export_on_command_line(tmp_path, monkeypatch):
    job = spec(environment_allowlist=['A'], environment={'A': '1'})
    job['site']['scheduler'] = 'slurm'
    plan = {'spec': job, 'plan_sha256': 'synthetic', 'readonly_trees': []}
    backend = batch.SiteBackend()
    calls = []

    def call(plan, handle, name, arguments):
        calls.append((name, arguments))
        return SimpleNamespace(stdout='12345')

    monkeypatch.setattr(backend, '_call', call)
    backend.submit(plan, {'job_dir': str(tmp_path), 'tag': 'synthetic-job'})
    assert calls == [('sbatch', ['--parsable', '--export=NIL', str(tmp_path / 'job.sbatch')])]


@pytest.mark.parametrize('key', ['tim', 'expo', 'get-user-e'])
def test_slurm_option_abbreviations_cannot_bypass_controls(key):
    job = spec(options={key: 'untrusted'})
    job['site']['scheduler'] = 'slurm'
    with pytest.raises(ValueError, match='RAVEL-controlled'):
        batch.SiteBackend().validate(job)
