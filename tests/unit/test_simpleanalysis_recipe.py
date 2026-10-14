"""Offline source preparation controls; no compiler, image or scientific events."""
from pathlib import Path
import re

import pytest

from ravel import analysis_sources as sources
from ravel.physics import simpleanalysis_container as container
from ravel.physics.simpleanalysis_recipe import offline_external_overlay, prepare_inputs


HEPMC=b'ExternalProject_Add( proj_HEPMC\n  GIT_REPOSITORY https://gitlab.cern.ch/hepmc/HepMC3.git\n  GIT_TAG 3.2.6\n  CMAKE_ARGS -DHEPMC3_ENABLE_ROOTIO=OFF\n)\n'
REST=b'ExternalProject_Add( RestFrames\n   URL https://github.com/crogan/RestFrames/archive/v1.0.1.tar.gz\n   URL_MD5 668e3ca6f301172d7e67b5e85b1ab6d2\n   BUILD_IN_SOURCE 1\n)\n'


def test_offline_transform_retains_actual_build_settings_and_refuses_source_drift():
    for raw,name,expected in [(HEPMC,'HepMC3',b'CMAKE_ARGS -DHEPMC3_ENABLE_ROOTIO=OFF'),(REST,'RestFrames',b'BUILD_IN_SOURCE 1')]:
        changed=offline_external_overlay(raw,name)
        assert expected in changed and b'DOWNLOAD_COMMAND ""' in changed and b'UPDATE_COMMAND ""' in changed
        assert ('../externals/'+name).encode() in changed
        with pytest.raises(ValueError,match='differs'):
            offline_external_overlay(raw.replace(b'3.2.6',b'3.2.7').replace(b'v1.0.1',b'v1.0.2'),name)


def fixture(tmp_path):
    root=tmp_path/'source';root.mkdir()
    files={'CMakeLists.txt':b'project(explicit_source_control)\n','Framework/real.cxx':b'DefineAnalysis(RealAnalysis)\n',
        'Ext_HEPMC/externals.cmake':HEPMC,'Ext_RestFrames/externals.cmake':REST,'Codes/data/model.xml':b'unchanged native data\n'}
    for p,raw in files.items():
        target=root/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    capsule={'schema_version':1,'kind':'analysis-source-capsule','framework':'simpleanalysis','routine':'RealAnalysis',
        'source':{'repository':'supplied','revision':None,'description':'small explicit preparation control'},'root':str(root),
        'files':[{'path':p,'sha256':sources.digest(root/p),'role':'compile' if p.endswith('.cxx') else 'build' if p.endswith('.cmake') or p=='CMakeLists.txt' else 'model'} for p in files],
        'layout':{'include_dirs':[],'asset_dirs':['Codes/data']},'dependencies':[],
        'dependency_review':{'complete':True,'description':'No claim about an actual ATLAS runtime'},
        'submodules':[{'path':'Framework','repository':'https://example.org/framework','revision':'a'*40}]}
    externals={}
    for name in ('HepMC3','RestFrames'):
        ext=tmp_path/name;ext.mkdir();(ext/'source.txt').write_text(name)
        externals[name]={'root':str(ext),'files':container.tree_facts(ext),'archive_sha256':'b'*64,'source_commit':'c'*40}
    guest={'schema_version':1,'setup':{'path':'/release_setup.sh','sha256':'d'*64},
        'tools':{key:{'path':'/usr/bin/'+name,'sha256':'e'*64} for key,name in [('compiler','g++'),('c_compiler','gcc'),('cmake','cmake'),('python','python')]},
        'binary_relative':'qualified-platform/bin/simpleAnalysis','qualification_sha256':'f'*64}
    return root,capsule,externals,guest


def test_prepare_complete_bound_inputs_and_only_two_upstream_download_deltas(tmp_path):
    root,capsule,external,guest=fixture(tmp_path);before=container.tree_facts(root)
    dest=tmp_path/'prepared'
    result=prepare_inputs(capsule,tmp_path,dest,external_sources=external,guest=guest,observer_source=b'bounded observer source\n')
    assert container.tree_facts(root)==before
    assert set(result['routine_bindings'])=={'RealAnalysis'}
    assert [x['path'] for x in result['offline_external_overlays']]==['Ext_HEPMC/externals.cmake','Ext_RestFrames/externals.cmake']
    assert (dest/'work/source/Framework/real.cxx').read_bytes()==(root/'Framework/real.cxx').read_bytes()
    assert (dest/'work/source/Codes/data/model.xml').read_bytes()==(root/'Codes/data/model.xml').read_bytes()
    script=(dest/'run.sh').read_text()
    assert '--parallel 1 --target simpleAnalysis' in script and 'simpleAnalysis -l' in script
    assert 'CMAKE_EXPORT_COMPILE_COMMANDS=ON' in script and 'codemodel-v2' in script
    assert 'git clone' not in script and not re.search(r'\b(?:curl|pip)\b',script)
    assert result['physics_validated'] is False


def test_unresolved_closure_and_changed_external_source_cannot_prepare_admitted_build(tmp_path):
    _,capsule,external,guest=fixture(tmp_path)
    capsule['dependency_review']['complete']=False
    with pytest.raises(ValueError,match='complete external'):
        prepare_inputs(capsule,tmp_path,tmp_path/'bad',external_sources=external,guest=guest,observer_source=b'bounded')
    capsule['dependency_review']['complete']=True
    (Path(external['HepMC3']['root'])/'source.txt').write_text('changed')
    with pytest.raises(ValueError,match='external source changed'):
        prepare_inputs(capsule,tmp_path,tmp_path/'other',external_sources=external,guest=guest,observer_source=b'bounded')


# Actual upstream setup interoperation controls; no native/image processes.
import subprocess
from ravel.physics.simpleanalysis_recipe import guest_programs
from ravel.physics.simpleanalysis_events import guest_program


def programs():
    guest = {'schema_version': 1, 'setup': {'path': '/release_setup.sh', 'sha256': 'a' * 64},
             'tools': {k: {'path': '/qualified/' + k, 'sha256': 'b' * 64} for k in ('compiler', 'c_compiler', 'cmake', 'python')},
             'binary_relative': 'qualified-platform/bin/simpleAnalysis', 'qualification_sha256': 'c' * 64}
    return {'build': guest_programs(guest)['run.sh'], 'events': guest_program(guest, 'RealRoutine')}


@pytest.mark.parametrize('program', ['build', 'events'])
def test_all_vendor_source_boundaries_are_closed(program):
    script = programs()[program]
    sources = list(re.finditer(r'^source (.+)$', script, re.M))
    assert len(sources) == 2
    for match in sources:
        assert script[:match.start()].endswith('set +u\nset +o pipefail\n')
        assert script[match.end():].startswith('\nset -euo pipefail\n')
    assert ' -w 0 ' in script if program == 'events' else '--parallel 1 --target simpleAnalysis' in script


@pytest.mark.parametrize('program', ['build', 'events'])
@pytest.mark.parametrize('source_index', [0, 1])
@pytest.mark.parametrize('case', ['unset_vendor', 'vendor_failure', 'post_source_unset', 'post_source_pipeline', 'vendor_changes_options'])
def test_public_generated_boundary_real_bash(tmp_path, program, source_index, case):
    script = programs()[program]
    setup = tmp_path / 'vendor.sh'
    if case == 'vendor_failure':
        setup.write_text('false\n')
    elif case == 'vendor_changes_options':
        setup.write_text('set +e\nexport RAVEL_VENDOR_EXPORT=observed\n')
    else:
        setup.write_text('export MANPATH="/qualified/vendor:$MANPATH"\nfalse | true\nexport RAVEL_VENDOR_EXPORT=observed\n')
    boundary = list(re.finditer(r'set \+u\nset \+o pipefail\nsource .+\nset -euo pipefail\n', script))[source_index].group()
    boundary = re.sub(r'^source .+$', 'source ' + str(setup), boundary, flags=re.M)
    tail = {'post_source_unset': 'echo "$RAVEL_UNSET_AFTER_SETUP"\n', 'post_source_pipeline': 'false | true\n'}.get(case, 'test "$RAVEL_VENDOR_EXPORT" = observed\nset -o\n')
    p = subprocess.run(['/bin/bash', '-c', 'set -euo pipefail\n' + boundary + tail + '\nprintf FINISHED'],
                       env={'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'LC_ALL': 'C'}, capture_output=True, timeout=5)
    if case in ('vendor_failure', 'post_source_unset', 'post_source_pipeline'):
        assert p.returncode != 0 and b'FINISHED' not in p.stdout
    else:
        assert p.returncode == 0 and b'FINISHED' in p.stdout
        for flag in ('errexit', 'nounset', 'pipefail'):
            assert any(line.split() == [flag.encode(), b'on'] for line in p.stdout.splitlines())
