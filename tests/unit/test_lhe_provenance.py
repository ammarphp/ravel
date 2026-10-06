import ast
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

CANDIDATE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CANDIDATE / "src"))
from ravel.physics import lhe_provenance as prov
from ravel.physics import native_event_io as event_io
from ravel.physics import native_pipeline as pipeline


def fixture_events():
    return [
        {"header": [3, 1, weight, 91.0 + i, .007, .12], "particles": [
            [1, -1, 0, 0, 501, 0, 0., 0., 100., 100., 0., 0., 9.],
            [-1, -1, 0, 0, 0, 501, -0., 0., -100., 100., 0., 0., 9.],
            [21, 1, 1, 2, 501, 502, 10. + i, 0., 0., 10. + i, 0., 0., 9.]]}
        for i, weight in enumerate((1., -2.))]


def lhe_bytes(events=None):
    events = fixture_events() if events is None else events
    rows = ['<LesHouchesEvents version="1.0">', '<init>', 'fixture header preserved as bytes', '</init>']
    for e in events:
        rows += ['<event>', ' '.join(map(str, e['header']))]
        rows += [' '.join(map(str, p)) for p in e['particles']]
        rows += ['</event>']
    return ('\n'.join(rows) + '\n</LesHouchesEvents>\n').encode()


def sidecar_rows(events=None):
    events = fixture_events() if events is None else events
    return [dict(type='begin', schema_version=1, requested_events=len(events),
                 floating_precision=17, source='existing_Pythia_getLHAupPtr'),
            *[dict(type='event', loop_index=i, successful_index=i, hepmc_event_number=i, **e)
              for i, e in enumerate(events)],
            dict(type='end', events_written=len(events), attempted=len(events), next_failures=0, complete=True)]


def sidecar_bytes(rows=None):
    return ('\n'.join(json.dumps(x) for x in (sidecar_rows() if rows is None else rows)) + '\n').encode()


def hepmc_bytes():
    return b"HepMC::Version 3.03.01\nHepMC::Asciiv3-START_EVENT_LISTING\nW Weight\nE 0 1 1\nU GEV MM\nP 1 0 21 1 0 0 1 0 1\nE 1 1 1\nU GEV MM\nP 1 0 21 2 0 0 2 0 1\nHepMC::Asciiv3-END_EVENT_LISTING\n"


def artifacts(tmp_path, encoding='plain'):
    lhe, sidecar = tmp_path/'events.lhe', tmp_path/'sidecar.jsonl'
    hepmc = tmp_path/('events.hepmc.gz' if encoding=='gzip' else 'events.hepmc')
    lhe.write_bytes(lhe_bytes()); sidecar.write_bytes(sidecar_bytes())
    if encoding=='gzip': hepmc.write_bytes(gzip.compress(hepmc_bytes(), mtime=0))
    else: hepmc.write_bytes(hepmc_bytes())
    return lhe, sidecar, hepmc


@pytest.mark.parametrize('encoding', ['plain', 'gzip'])
def test_new_generation_positive_signed_identity(tmp_path, encoding):
    paths = artifacts(tmp_path, encoding)
    report = prov.verify_new_generation(*paths, expected_events=2, encoding=encoding)
    assert report['status']=='content_verified'
    assert report['replay_byte_equality_performed'] is False
    assert report['negative_original_weights']==1 and report['joined_events']==2
    assert report['hepmc_content']['particles']==2
    assert report['rows'][1]['original_weight']==-2.
    assert all(prov.pin(path)==report['source_files'][name]
               for name,path in zip(('lhe','sidecar','hepmc'),paths))


@pytest.mark.parametrize('field', range(13))
def test_every_original_particle_field_is_bound(field):
    rows=sidecar_rows()
    rows[1]['particles'][2][field] += 1
    with pytest.raises(ValueError):
        prov.join_lhe_sidecar(io.BytesIO(lhe_bytes()), io.BytesIO(sidecar_bytes(rows)), 2)


@pytest.mark.parametrize('field', range(6))
def test_every_original_header_field_is_bound(field):
    rows=sidecar_rows(); rows[1]['header'][field] += 1
    with pytest.raises(ValueError):
        prov.join_lhe_sidecar(io.BytesIO(lhe_bytes()), io.BytesIO(sidecar_bytes(rows)), 2)


@pytest.mark.parametrize('change', ['swap', 'duplicate', 'absent', 'extra', 'error', 'bool', 'failure', 'negativezero'])
def test_no_ordinal_or_incomplete_sidecar_fallback(change):
    rows=sidecar_rows()
    if change=='swap': rows[1]['header'],rows[2]['header']=rows[2]['header'],rows[1]['header']
    elif change=='duplicate': rows[2]=copy.deepcopy(rows[1])
    elif change=='absent': rows.pop(2)
    elif change=='extra': rows.append({})
    elif change=='error': rows[-1]={'type':'error'}
    elif change=='bool': rows[1]['successful_index']=False
    elif change=='failure': rows[-1]['next_failures']=1
    else: rows[1]['particles'][1][6]=0.
    with pytest.raises(ValueError):
        prov.join_lhe_sidecar(io.BytesIO(lhe_bytes()), io.BytesIO(sidecar_bytes(rows)), 2)


@pytest.mark.parametrize('change', ['extraevent', 'missingevent', 'duplicatecontent', 'xml', 'trailer', 'unterminated'])
def test_original_lhe_scope_is_fail_closed(change):
    data=lhe_bytes()
    if change=='extraevent': data=lhe_bytes(fixture_events()+[fixture_events()[0]])
    elif change=='missingevent': data=lhe_bytes(fixture_events()[:1])
    elif change=='duplicatecontent': data=lhe_bytes([fixture_events()[0]]*2)
    elif change=='xml': data=data.replace(b'</event>', b'<rwgt><wgt id="extra">3</wgt></rwgt>\n</event>',1)
    elif change=='trailer': data+=b'extra\n'
    else: data=data[:-1]
    with pytest.raises(ValueError):
        prov.join_lhe_sidecar(io.BytesIO(data),io.BytesIO(sidecar_bytes()),2)


@pytest.mark.parametrize('old,new', [
    (b'E 1 1 1', b'E 0 1 1'), (b'E 1 1 1', b'E 1 1 2'),
    (b'P 1 0 21 2', b'P 2 0 21 2'), (b'P 1 0 21 2', b'P 1 0 21 nan'),
    (b'U GEV MM\n', b''), (b'HepMC::Asciiv3-END_EVENT_LISTING\n', b''),
    (b'W Weight',b'Z unknown'), (b'E 0 1 1',b'E 0 True 1'),
    (b'HepMC::Version 3.03.01',b'HepMC::Version 2.0.0')])
def test_actual_hepmc_framing_and_particle_count(old,new):
    with pytest.raises(ValueError): prov.scan_hepmc(io.BytesIO(hepmc_bytes().replace(old,new,1)),2)


def test_retained_writer_implicit_vertices_are_not_false_missing_rows():
    fixture=CANDIDATE/'tests/fixtures/hepmc3-implicit-vertices.txt'
    with fixture.open('rb') as stream:
        result=prov.scan_hepmc(stream,1)
    assert result['complete_framing'] and result['particle_populations_verified']
    assert result['events']==1 and result['particles']==1922
    assert result['graph_physics_validated'] is False


def test_full_gzip_decode_required(tmp_path):
    paths=artifacts(tmp_path,'gzip'); paths[2].write_bytes(paths[2].read_bytes()[:-6])
    with pytest.raises((ValueError,EOFError)): prov.verify_new_generation(*paths,expected_events=2,encoding='gzip')


def test_source_replacement_during_verification_rejects(tmp_path,monkeypatch):
    paths=artifacts(tmp_path); old=prov.scan_hepmc
    def changed(*args,**kwargs):
        out=old(*args,**kwargs); paths[0].write_bytes(lhe_bytes()+b'\n');return out
    monkeypatch.setattr(prov,'scan_hepmc',changed)
    with pytest.raises(ValueError,match='changed'): prov.verify_new_generation(*paths,expected_events=2)


def test_file_alias_rejects(tmp_path):
    paths=artifacts(tmp_path); alias=tmp_path/'alias';alias.symlink_to(paths[0])
    with pytest.raises(ValueError,match='Symlink'):prov.verify_new_generation(alias,*paths[1:],expected_events=2)


@pytest.mark.parametrize('encoding',['plain','gzip'])
def test_parent_directory_swapped_only_during_decoded_open(tmp_path,monkeypatch,encoding):
    active,alternate,saved=(tmp_path/n for n in ('active','alternate','saved'))
    active.mkdir();alternate.mkdir();paths=artifacts(active,encoding)
    other=hepmc_bytes().replace(b'21 1 0 0 1 0 1',b'21 9 0 0 9 0 1')
    (alternate/paths[2].name).write_bytes(gzip.compress(other,mtime=0)if encoding=='gzip'else other)
    original_pin=prov.pin(paths[2]);original_identity=prov.file_identity(paths[2])
    real=Path.open;opens=0;swapped=False
    def replacement(path,*args,**kwargs):
        nonlocal opens,swapped
        if path==paths[2]:
            opens+=1
            # Initial pin reads its own file. Only the subsequent decoded open
            # borrows an alternate parent; all later path checks see the original.
            if opens==2:
                active.rename(saved);alternate.rename(active)
                try:stream=real(path,*args,**kwargs)
                finally:active.rename(alternate);saved.rename(active)
                swapped=True;return stream
        return real(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',replacement)
    with pytest.raises(ValueError,match='opened descriptor differs'):
        prov.verify_new_generation(*paths,expected_events=2,encoding=encoding)
    assert swapped and original_pin==prov.pin(paths[2])
    assert original_identity==prov.file_identity(paths[2])


def producer_fixture(tmp_path, encoding='plain', extra=''):
    lhe=tmp_path/'original.lhe';lhe.write_bytes(lhe_bytes())
    card=tmp_path/'shower.cfg';card.write_text(f'Beams:frameType = 4\nBeams:LHEF = {lhe}\nRandom:setSeed = on\n')
    run_card=tmp_path/'run.dat';run_card.write_text('2 = nevents\n0 = ickkw\nFalse = use_syst\n')
    wrapper=tmp_path/'wrapper.cc';wrapper.write_text('synthetic source fixture, no C++ execution\n')
    binary=tmp_path/'fake producer'
    binary.write_text(f'#!{sys.executable}\nimport sys\nfrom pathlib import Path\nPath(sys.argv[2]).write_bytes({hepmc_bytes()!r})\nPath(sys.argv[5]).write_bytes({sidecar_bytes()!r})\n'+extra)
    binary.chmod(0o755)
    return dict(binary=binary,card=card,output=tmp_path/('out.gz' if encoding=='gzip' else 'out.hepmc'),events=2,
                lhe=lhe,sidecar=tmp_path/'out.jsonl',verification=tmp_path/'verified.json',
                wrapper_source=wrapper,run_card=run_card,encoding=encoding)


@pytest.mark.parametrize('encoding',['plain','gzip'])
def test_owned_real_stub_producer_roundtrip(tmp_path,encoding):
    args=producer_fixture(tmp_path,encoding);event_io.shower_original(**args)
    report=json.loads(args['verification'].read_text())
    assert report['producer']['returncode']==0
    assert report['replay_byte_equality_performed'] is False
    assert report['source_files']['hepmc']==prov.pin(args['output'])
    assert not list(tmp_path.glob('.original-lha-*'))
    if encoding=='gzip':
        assert gzip.decompress(args['output'].read_bytes())==hepmc_bytes()
        assert Path(str(args['output'])+'.storage.json').is_file()


@pytest.mark.parametrize('encoding',['plain','gzip'])
def test_actual_new_cli_bootstrap_with_no_inherited_pythonpath(tmp_path,encoding):
    args=producer_fixture(tmp_path,encoding)
    command=[sys.executable,'-B',str(CANDIDATE/'src/ravel/_bootstrap.py'),
             'ravel.physics.native_event_io','shower-original']
    for name,value in args.items():
        command += ['--'+name.replace('_','-'),str(value)]
    env=dict(os.environ);env.pop('PYTHONPATH',None);env['PYTHONDONTWRITEBYTECODE']='1'
    subprocess.run(command,cwd=tmp_path,env=env,check=True,capture_output=True,text=True)
    result=json.loads(args['verification'].read_text())
    assert result['producer']['returncode']==0 and result['joined_events']==2
    assert result['source_files']['hepmc']==prov.pin(args['output'])


@pytest.mark.parametrize('change',['failed', 'mutate_lhe', 'mutate_card', 'mutate_binary', 'no_sidecar'])
def test_owned_producer_failure_or_input_drift_holds_report(tmp_path,change):
    args=producer_fixture(tmp_path)
    if change=='failed': extra='raise SystemExit(7)\n'
    elif change=='no_sidecar': extra='Path(sys.argv[5]).unlink()\n'
    else:
        field={'mutate_lhe':'lhe','mutate_card':'card','mutate_binary':'binary'}[change]
        extra=f'with Path({str(args[field])!r}).open("a") as f:f.write("changed\\n")\n'
    with args['binary'].open('a') as f:f.write(extra)
    with pytest.raises((ValueError,FileNotFoundError,subprocess.CalledProcessError)):event_io.shower_original(**args)
    assert not args['verification'].exists()
    assert list(tmp_path.glob('.original-lha-*'))


@pytest.mark.parametrize('field',['output','sidecar','verification'])
def test_outputs_never_overwrite_even_broken_alias(tmp_path,field):
    args=producer_fixture(tmp_path); args[field].symlink_to(tmp_path/'missing')
    with pytest.raises(ValueError,match='already exists'):event_io.shower_original(**args)
    assert args[field].is_symlink()


@pytest.mark.parametrize('card_line', ['Beams:frameType = 1','Beams:LHEF = relative.lhe',
    'JetMatching:merge = on','Merging:TMS = 50','Beams:LHEFheader = other.lhe',
    'Main:numberOfEvents = 3','Beams:newLHEFsameInit = on', 'random:setseed = off', 'include other.cfg'])
def test_unsupported_actual_shower_source_rejects_before_process(tmp_path,monkeypatch,card_line):
    args=producer_fixture(tmp_path)
    with args['card'].open('a') as f:f.write(card_line+'\n')
    monkeypatch.setattr(event_io.subprocess,'run',lambda *a,**k:pytest.fail('producer must not execute'))
    with pytest.raises(ValueError):event_io.shower_original(**args)


@pytest.mark.parametrize('line',['1 = ickkw','True = use_syst','3 = nevents'])
def test_unsupported_run_scope_before_process(tmp_path,monkeypatch,line):
    args=producer_fixture(tmp_path);args['run_card'].write_text(line+'\n')
    monkeypatch.setattr(event_io.subprocess,'run',lambda *a,**k:pytest.fail('producer must not execute'))
    with pytest.raises(ValueError):event_io.shower_original(**args)


def test_default_cpp_path_and_reviewed_provenance_are_preserved():
    source=(CANDIDATE/'native/src/pythia_shower.cc').read_text()
    observed=source[source.index('int provenanceMain'):source.rindex('int main')]
    assert observed.index('pythia.next()') < observed.index('captured=originalLHA(*lha)') < observed.index('toHepMC.writeNextEvent') < observed.index('toHepMC.event().event_number()')
    assert 'setLHAupPtr' not in source and 'rndm' not in source
    assert 'O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW' in source


def plan_fixture(tmp_path):
    from test_native_dispatch import configuration
    return configuration(tmp_path)


@pytest.mark.parametrize('encoding',['plain','gzip'])
def test_optin_plan_declares_all_outputs_and_dependencies(tmp_path,encoding):
    config=plan_fixture(tmp_path)
    config.write_text(config.read_text().replace('[ravel.native.inputs]',f'lhe_provenance = "original-v1"\nevent_storage = "{encoding}"\n[ravel.native.inputs]'))
    plan=pipeline.build_execution_plan(tmp_path,config)
    stages={s['stage']:s for s in plan['stages']};shower=stages['pythia']
    assert 'shower-original' in shower['command']
    assert shower['depends_on']==['lhe_check']
    assert set(shower['outputs']) >= {plan['lhe_provenance']['sidecar'],plan['lhe_provenance']['verification']}
    assert plan['lhe_provenance']['wrapper_source'] in shower['inputs']
    assert any(p.endswith('lhe_provenance.py') for p in shower['inputs'])
    assert len(shower['outputs'])==(4 if encoding=='gzip' else 3)
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('value',['"auto"','false','0','"none"','[]'])
def test_unknown_optin_never_silently_defaults(tmp_path,value):
    config=plan_fixture(tmp_path);config.write_text(config.read_text().replace('[ravel.native.inputs]',f'lhe_provenance = {value}\n[ravel.native.inputs]'))
    with pytest.raises(ValueError,match='lhe_provenance'):pipeline.build_execution_plan(tmp_path,config)
