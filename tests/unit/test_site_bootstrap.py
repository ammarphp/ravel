"""Shell bootstrap runs only synthetic command executables on a temporary PATH."""
import os
from pathlib import Path
import subprocess

from site_install_fixture import SOURCE


def tools(tmp_path):
    folder=tmp_path/'fake-bin';folder.mkdir()
    for name,body in {
        'uname':'if [ "$1" = -s ]; then echo Linux; else echo x86_64; fi',
        'git':'echo "git version 2.44.0"',
        'curl':'echo "inert curl must not be used" >&2; exit 99',
        'df':'echo "Filesystem 1024-blocks Used Available Capacity Mounted on"; echo "synthetic 40000000 1 20000000 1% /work"',
        'quota':'echo "Filesystem space quota limit grace files quota limit grace"; echo "synthetic 100M 0 1G 0 0 0 0"',
    }.items():
        path=folder/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o755)
    return folder


def test_bootstrap_forwards_view_and_sets_prefix_caches_before_child(tmp_path):
    fake=tools(tmp_path);prefix=tmp_path/'work'
    bins=prefix/'tools/miniforge3/bin';bins.mkdir(parents=True)
    python=bins/'python';python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE.args"\nenv > "$CAPTURE.env"\n')
    python.chmod(0o755)
    conda=bins/'conda';conda.write_text('#!/bin/sh\nexit 0\n');conda.chmod(0o755)
    result=subprocess.run(['bash',str(SOURCE/'scripts/setup/install.sh'),'--profile','site',
        '--prefix',str(prefix),'--lcg-view','none'],capture_output=True,text=True,
        env=dict(os.environ,PATH=str(fake)+':'+os.environ['PATH'],CAPTURE=str(tmp_path/'capture')))
    assert result.returncode==0,result.stderr
    argv=(tmp_path/'capture.args').read_text()
    assert '--lcg-view\nnone' in argv and '--prefix\n'+str(prefix) in argv
    env=(tmp_path/'capture.env').read_text()
    assert 'APPTAINER_CACHEDIR='+str(prefix/'cache/apptainer') in env
    assert 'APPTAINER_TMPDIR='+str(prefix/'tmp/apptainer') in env
    assert 'TMPDIR='+str(prefix/'tmp') in env


def test_auto_choice_refuses_before_bootstrap_download(tmp_path):
    fake=tools(tmp_path)
    result=subprocess.run(['bash',str(SOURCE/'scripts/setup/install.sh'),'--profile','site',
        '--prefix',str(tmp_path/'work'),'--lcg-view','auto'],capture_output=True,text=True,
        env=dict(os.environ,PATH=str(fake)+':'+os.environ['PATH'],RAVEL_LCG_VIEWS=str(tmp_path/'fake-views')))
    assert result.returncode==2
    assert '--lcg-view none' in result.stderr and 'candidates' in result.stderr
    assert 'Downloading' not in result.stdout and 'inert curl' not in result.stderr


def test_low_home_quota_refuses_before_any_bootstrap_write(tmp_path):
    fake=tools(tmp_path);home=tmp_path/'home';home.mkdir();prefix=home/'tools'
    result=subprocess.run(['bash',str(SOURCE/'scripts/setup/install.sh'),'--profile','site',
        '--prefix',str(prefix),'--lcg-view','none'],capture_output=True,text=True,
        env=dict(os.environ,HOME=str(home),PATH=str(fake)+':'+os.environ['PATH']))
    assert result.returncode==4 and 'work area' in result.stderr
    assert not prefix.exists()
