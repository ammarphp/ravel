"""Synthetic policy siblings; no real source acquisitions."""
from pathlib import Path
import pytest
from ravel.setup import manifest

ROOT=Path(__file__).resolve().parents[2]


def check(doc, **kwargs):
    from ravel.setup.licence_policy import check
    return check(doc, **kwargs)


def group(licences=None,steps=None):
    return {'groups':[{'id':'synthetic-group','depends_on':[],
                      'licenses':licences or [], 'steps':steps or []}]}


def nr():
    return dict(component='synthetic-restricted',spdx='LicenseRef-synthetic',redistribute=False,
                import_into_ravel='never',container_publish='never')


def test_acquisition_without_licence_is_refused():
    assert check(group(steps=[dict(id='source',kind='git',dest='{TOOLS}/synthetic')]))


@pytest.mark.parametrize('copy', ['COPY synthetic-restricted /opt/tool',
    'copy ["vendor/synthetic-restricted", "/opt/tool"]',
    'COPY --from=builder /opt/synthetic-restricted/ /opt/tool',
    'COPY vendor/ /opt/vendor', 'COPY . /opt/all', 'COPY synthetic-* /opt/all',
    'COPY synthetic-\\\n restricted /opt/tool'])
def test_container_copy_of_restricted_tool_is_refused(copy):
    doc=group([nr()],[dict(id='source',kind='archive',dest='vendor/synthetic-restricted')])
    assert check(doc,containerfiles={'synthetic':copy})


@pytest.mark.parametrize('python', ['{REPO}/.venv/bin/python','/tmp/root/.venv/bin/python'])
def test_gpl_module_in_host_venv_is_refused(python):
    doc=group([dict(component='synthetic-module',spdx='GPL-3.0-only')],
              [dict(id='install',kind='pip',python=python,requirements=['synthetic-module==1.0'])])
    assert check(doc)


def test_isolated_gpl_module_and_unrelated_copy_pass():
    doc=group([dict(component='synthetic-module',spdx='GPL-3.0-only')],
              [dict(id='install',kind='pip',python='{REPO}/.venv-synthetic/bin/python',requirements=['synthetic-module==1.0'])])
    assert check(doc)==[]
    assert check(group([nr()]),containerfiles={'synthetic':'COPY adapter.py /opt/adapter.py'})==[]


def test_current_manifest_passes_without_mutation():
    doc,_=manifest.load(ROOT)
    assert check(doc)==[]


def test_lint_is_wired_into_manifest_validation():
    doc,_=manifest.load(ROOT)
    acquired=next(g for g in doc['groups'] if any(s['kind']=='git' for s in g['steps']))
    acquired['licenses']=[]
    with pytest.raises(manifest.ManifestError,match='licence'):
        manifest.validate(doc)


@pytest.mark.parametrize('kind',['miniforge','pdf_sets'])
def test_data_and_bootstrap_acquisitions_need_licences(kind):
    assert check(group(steps=[dict(id='source',kind=kind)]))
