"""Snakemake executable resolution: explicit, environment, PATH; never beside sys.executable."""
import os
import stat

from ravel.workflow import wms_runtime as wms


def script(path, body='#!/bin/sh\necho 9.27.0\n'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def clean(monkeypatch, tmp_path):
    for name in ('RAVEL_SNAKEMAKE', 'RAVEL_TEST_SNAKEMAKE'):
        monkeypatch.delenv(name, raising=False)
    empty = tmp_path / 'empty'
    empty.mkdir()
    monkeypatch.setenv('PATH', str(empty))


def test_empty_when_nothing_is_found(tmp_path, monkeypatch):
    clean(monkeypatch, tmp_path)
    assert wms.snakemake_argv() == [] and wms.snakemake_version([]) is None


def test_resolution_order(tmp_path, monkeypatch):
    clean(monkeypatch, tmp_path)
    on_path = script(tmp_path / 'bin' / 'snakemake')
    test_env = script(tmp_path / 'test' / 'snakemake')
    ravel_env = script(tmp_path / 'ravel' / 'snakemake')
    explicit = script(tmp_path / 'explicit' / 'snakemake')
    monkeypatch.setenv('PATH', str(tmp_path / 'bin'))
    assert wms.snakemake_argv() == [on_path]
    monkeypatch.setenv('RAVEL_TEST_SNAKEMAKE', test_env)
    assert wms.snakemake_argv() == [test_env]
    monkeypatch.setenv('RAVEL_SNAKEMAKE', ravel_env)
    assert wms.snakemake_argv() == [ravel_env]
    assert wms.snakemake_argv(explicit) == [explicit]
    monkeypatch.setenv('RAVEL_SNAKEMAKE', str(tmp_path / 'missing'))
    assert wms.snakemake_argv() == [test_env]


def test_version_is_parsed(tmp_path, monkeypatch):
    clean(monkeypatch, tmp_path)
    assert wms.snakemake_version([script(tmp_path / 's')]) == '9.27.0'
    assert wms.snakemake_version([script(tmp_path / 'bad', '#!/bin/sh\nexit 1\n')]) is None
