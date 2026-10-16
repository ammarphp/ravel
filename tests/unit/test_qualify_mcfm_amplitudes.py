"""The MCFM amplitude qualification runner applies the product checks to a fictional program's output."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

PROGRAM = '''#!{python}
import sys
sys.path[:0] = [{src!r}, {tests!r}]
from pathlib import Path
import os
from amplitude_fixtures import program_output
# Like the driver: enter the card's directory, write outputs to RAVEL_OUTPUT_DIR.
os.chdir(Path(sys.argv[1]).parent)
out = Path(os.environ['RAVEL_OUTPUT_DIR'])
assert Path('process.DAT').read_text() == 'fictional process table'
op, draws, seed, channel = map(int, Path('ravel-control.dat').read_text().split())
assert Path(sys.argv[1]).is_file()
if op == 2:
    assert Path('proposal-grid.bin').read_bytes().startswith(b'fictional-grid')
if op == 0:
    assert len(Path('ravel-points.dat').read_text().splitlines()) == 7 * draws
# The synthetic fixture is not reproducible between calls; a fixed control line returns its first output.
cache = Path(__file__).parent / 'cache' / f'{{op}}-{{draws}}-{{seed}}-{{channel}}'
momenta = None
if op == 0:
    rows = [[float(v) for v in line.split()] for line in Path('ravel-points.dat').read_text().splitlines()]
    momenta = [rows[7 * i:7 * i + 6] for i in range(draws)]
if not cache.is_file():
    cache.parent.mkdir(exist_ok=True)
    # Draws 1 and 3 of a block fall below the program's Z pT safety cut (with leak=True the program stores
    # them) and draw 4 below its small-invariant cut.
    low = (1, 3) if op == 2 else ()
    raw = program_output(op, draws, seed, channel{corrupt}, exclude=low if not {leak} else (),
                         leak=low if {leak} else (), small=(4,) if op == 2 else (), momenta=momenta)
    cache.write_bytes(raw)
(out / 'amplitudes.dat').write_bytes(cache.read_bytes())
if op == 1:
    (out / 'proposal-grid.bin').write_bytes(b'fictional-grid')
'''

CARD = '[general]\nnproc = 131\npart = lo\n[integration]\nseed = 0\nusesobol = .false.\n'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runner():
    spec = importlib.util.spec_from_file_location('qualify_mcfm', REPO / 'scripts/validation/qualify_mcfm_amplitudes.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def installed(tmp_path, corrupt=False, leak=False):
    prefix = tmp_path / 'prefix'
    build = prefix / 'tools/mcfm-build'; build.mkdir(parents=True)
    program = build / 'ravel_mcfm_amplitudes'
    program.write_text(PROGRAM.format(python=sys.executable, src=str(REPO / 'src'), tests=str(HERE),
                                      corrupt=', corrupt=True' if corrupt else '', leak=leak))
    program.chmod(0o755)
    receipt = build / 'build-receipt.json'; receipt.write_text('{}')
    data = build / 'process.DAT'; data.write_text('fictional process table')
    shutil.copytree(REPO / 'addons/gpl/mcfm-amplitudes', prefix / 'addons/mcfm-amplitudes')
    record = prefix / 'installations/mcfm-amplitudes.json'; record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'schema_version': 1, 'kind': 'ravel-amplitude-installation', 'group': 'mcfm-amplitudes',
                                  'program': str(program), 'program_sha256': sha(program),
                                  'build_receipt': str(receipt), 'build_receipt_sha256': sha(receipt),
                                  'runtime_files': [{'path': str(data), 'sha256': sha(data)}],
                                  'env': {'LHAPDF_DATA_PATH': str(tmp_path / 'pdfs')}}))
    card = tmp_path / 'card.ini'; card.write_text(CARD)
    return record, card


def arguments(tmp_path, record, card, *extra):
    return ['--installation', str(record), '--card', str(card), '--work', str(tmp_path / 'work'),
            '--output', str(tmp_path / 'report.json'), '--warmup-draws', '40', '--block-draws', '30',
            '--oracle-points', '5', *extra]


def test_runner_applies_oracle_and_repeat_checks_and_records_the_population(tmp_path):
    record, card = installed(tmp_path)
    code = runner().main(arguments(tmp_path, record, card))
    report = json.loads((tmp_path / 'report.json').read_text())
    result = {c['name']: c['passed'] for c in report['checks']}
    for name in ('warmup-census', 'warmup-safety-cut-applied-at-sampling', 'block-census',
                 'block-safety-cut-applied-at-sampling', 'block-accepted-by-amplitude-integration', 'block-point-oracle',
                 'block-repeat-identical', 'point-evaluation-oracle', 'point-evaluation-applies-safety-cut'):
        assert result[name], name
    # The fictional program draws fresh random points for an evaluation, so its squares cannot match the block's:
    # the comparison discriminates.
    assert result['point-evaluation-reproduces-block-squares'] is False
    assert code == 1 and report['status'] == 'failed'
    assert report['installation']['program_sha256'] == sha(json.loads(record.read_text())['program'])
    assert report['card']['sha256'] == sha(card)
    for stage in ('warmup', 'block', 'block-repeat', 'points'):
        control = (tmp_path / 'work' / stage / 'stage' / 'input.ini').read_text()
        assert 'seed = 0' not in control


def test_runner_reports_a_failed_oracle(tmp_path):
    record, card = installed(tmp_path, corrupt=True)
    runner().main(arguments(tmp_path, record, card))
    result = {c['name']: c['passed'] for c in json.loads((tmp_path / 'report.json').read_text())['checks']}
    assert result['block-point-oracle'] is False


def test_runner_refuses_a_changed_program_and_a_used_work_directory(tmp_path):
    record, card = installed(tmp_path)
    (tmp_path / 'work').mkdir(); (tmp_path / 'work' / 'keep').write_text('fictional')
    with pytest.raises(ValueError, match='new or empty'):
        runner().main(arguments(tmp_path, record, card))
    program = Path(json.loads(record.read_text())['program'])
    program.write_text(program.read_text() + '\n# changed\n')
    with pytest.raises(ValueError, match='differs'):
        runner().main(arguments(tmp_path, record, card))


def test_runner_measures_the_draws_excluded_at_sampling(tmp_path):
    record, card = installed(tmp_path)
    runner().main(arguments(tmp_path, record, card))
    report = json.loads((tmp_path / 'report.json').read_text())
    block = report['safety']['block']
    assert report['safety']['cuts'][0]['id'] == 'z-candidate-pt'
    assert block['excluded'] == 3 and block['attempted'] == 30 and block['stored'] == 27
    assert block['by_cut'] == {'z-candidate-pt': 2, 'small-invariants': 1} and block['weight_unmeasured'] == 1
    assert block['exposure_fraction'] == 3 / 30 and 0 < block['weight_fraction'] < 1 and 0 < block['factor_fraction'] < 1
    rows = {c['name']: c for c in report['checks']}
    assert rows['block-accepted-by-amplitude-integration']['summary']['excluded'] == 3
    assert rows['point-evaluation-applies-safety-cut']['excluded'] == 3
    assert rows['point-evaluation-applies-safety-cut']['measured_references'] == 2


def test_runner_reports_a_program_that_stores_points_below_its_cut(tmp_path):
    record, card = installed(tmp_path, leak=True)
    runner().main(arguments(tmp_path, record, card))
    rows = {c['name']: c for c in json.loads((tmp_path / 'report.json').read_text())['checks']}
    assert rows['block-safety-cut-applied-at-sampling']['passed'] is False
    assert rows['block-safety-cut-applied-at-sampling']['cuts'][0]['stored_below'] == 2
    assert rows['block-accepted-by-amplitude-integration']['passed'] is False
