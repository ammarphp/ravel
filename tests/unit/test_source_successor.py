"""Copied-source/nominal source controls; no native command or scientific import."""
from copy import deepcopy
import json
import shutil
from pathlib import Path
import pytest
from ravel.physics import model_events as m, model_event_weights as w, model_event_process
from test_model_events import config,texts,write,lhe


def copied_request(tmp_path):
    c=config(tmp_path/'original',variations=True)
    copies=tmp_path/'copies';copies.mkdir()
    for name,ref in [('madgraph',c['runtime']['madgraph_tree']),('model',c['model_tree'])]:
        shutil.copytree(ref['root'],copies/name)
    return {'config':c,'madgraph':str(copies/'madgraph'),'model':str(copies/'model'),'process':str(tmp_path/'process'),
        'python':c['runtime']['python']['path'],'card_paths':{n:p['path'] for n,p in c['cards'].items() if p},'config_sha256':'a'*64,
        'source_base': str(tmp_path / 'original'),
        'process_observer_sha256':m.bridge._hash(model_event_process.__file__)}


def test_reserved_nominal_id_refuses_ordinary_admission(tmp_path):
    c=config(tmp_path,variations=True);c['weights']['groups'][0]['ids'][0]='nominal';c['weights']['variation_points'][0]['id']='nominal'
    with pytest.raises(ValueError,match='reserved'):m.validate_config(c)


@pytest.mark.parametrize('mutation',['addition','deletion','original-driver','original-config'])
def test_exact_copied_population_is_bound_and_refusal_census_retained(tmp_path,mutation):
    r=copied_request(tmp_path);mg=Path(r['madgraph']);out=tmp_path/'out';out.mkdir()
    if mutation=='addition':(mg/'injected.py').write_text('# new unadmitted source\n')
    elif mutation=='deletion':(mg/'VERSION').unlink()
    elif mutation=='original-driver':(mg/'bin/mg5_aMC').write_text('# changed\n')
    else:
        # A new config is not allowed merely because it is named configuration.
        (mg/'input').mkdir();(mg/'input/mg5_configuration.txt').write_text('unsafe = override\n')
    with pytest.raises(ValueError,match='copied admitted'):
        m._copied_source_custody(r,out,'before-build')
    witness=json.loads((out/'copied-source-before-build.json').read_text());assert witness['mismatches']==['madgraph']
    assert witness['components'][0]['observed']!=witness['components'][0]['expected']


def test_source_generated_cache_is_explicitly_excluded_and_retained(tmp_path):
    r=copied_request(tmp_path);model=Path(r['model']);out=tmp_path/'out';out.mkdir()
    (model/'py3_model.pkl').write_bytes(b'Synthetic generated cache, never imported')
    result=m._copied_source_custody(r,out,'after-build')
    assert not result['mismatches']
    assert any(p['path'].endswith('py3_model.pkl') for p in result['components'][1]['all_returned_files'])


def test_upstream_sets_never_auto_save_copied_configuration(tmp_path):
    c=config(tmp_path);build,launch=m.render_scripts(c,texts(c),model_path=tmp_path/'model',process_path=tmp_path/'proc')
    for script in (build,launch):
        assert all(line.endswith(' --no_save') for line in script.splitlines() if line.startswith('set '))
