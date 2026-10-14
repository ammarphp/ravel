"""Independent matrix-element cross-check through a stubbed execution backend."""
from contextlib import contextmanager
import json
from pathlib import Path
import py_compile

import numpy as np
import pytest

from amplitude_fixtures import build_store, hypotheses
from ravel.physics import amplitude_basis as ab
from ravel.physics import amplitude_crosscheck as cc
from ravel.physics import amplitude_store as store

MELA = {'sqrts_tev': 13, 'reference_mass_gev': 125.0, 'verbosity': 'ERROR',
        'process': ['bkgZZ_SMHiggs', 'JHUGen', 'ZZGG'],
        'resonances': [{'index': 0, 'mass_gev': 125.0, 'width_gev': 0.004}],
        'couplings': {'ghz1': [2.0, 0.0]}, 'call': 'computeP'}


class Backend:
    def __init__(self, transform):
        self.transform, self.specs = transform, []

    def prepare(self, spec, *, base=None):
        self.specs.append(spec)
        return {'spec': spec, 'plan_sha256': 'f' * 64, 'backend': {'local': True}}

    @contextmanager
    def capacity(self, plan, holder, **kwargs):
        yield

    def submit(self, plan, attempt_dir):
        spec = plan['spec']
        stage_dir = Path(spec['inputs'][0]['path']).parent
        points = json.loads((stage_dir / 'points.json').read_text())
        values = self.transform(len(points['points']))
        (stage_dir / 'values.json').write_text(json.dumps({'values': list(values)}))
        return {}

    def observe(self, plan, handle):
        return {'state': 'succeeded'}

    def fetch(self, plan, handle, base):
        return {}


def _task(tmp_path, **changes):
    build_store(tmp_path / 'store')
    doc = {'schema_version': 1, 'kind': 'amplitude-crosscheck', 'store': 'store', 'block': 'b0', 'max_points': 6,
           'tolerance': 1e-9, 'hypothesis': hypotheses()[1], 'mela': MELA,
           'backend': {'kind': 'oci-local', 'program': 'python3', 'workdir': '/work',
                       'resources': {'cpus': 1, 'memory_mib': 1024, 'wall_seconds': 60}}}
    doc.update(changes)
    (tmp_path / 'check.json').write_text(json.dumps(doc))
    return {'input': str(tmp_path / 'check.json')}


def _ravel(tmp_path, n=6):
    manifest = store.load_manifest(tmp_path / 'store')
    block = store.read_block(tmp_path / 'store' / manifest['blocks'][0]['path'])
    basis = ab.Basis(manifest['header']['basis'])
    h = ab.hypothesis(hypotheses()[1], basis)
    return ab.evaluate(block['gram'][:n], ab.coefficients(h, basis, block['observables'][:n, 0]))


@pytest.mark.usefixtures('in_process_backend_seam')
def test_agreement_up_to_one_constant_passes(tmp_path):
    task = _task(tmp_path)
    reference = _ravel(tmp_path)
    backend = Backend(lambda n: reference[:n] / 7.5)
    result = cc.run(task, tmp_path, tmp_path / 'out', backend=backend)
    assert result['status'] == 'passed' and result['comparison']['normalization_constant'] == pytest.approx(7.5)
    spec = backend.specs[0]
    assert spec['argv'] == ['python3', '/work/mela_points.py', '/work/points.json', '/work/mela.json', 'values.json']
    assert spec['resources']['wall_seconds'] == 60


@pytest.mark.usefixtures('in_process_backend_seam')
def test_disagreement_fails(tmp_path):
    reference = None
    task = _task(tmp_path)
    reference = _ravel(tmp_path)
    shaped = lambda n: reference[:n] * (1 + 0.01 * np.arange(n))
    result = cc.run(task, tmp_path, tmp_path / 'out', backend=Backend(shaped))
    assert result['status'] == 'failed' and result['comparison']['max_relative_deviation'] > 1e-3


@pytest.mark.usefixtures('in_process_backend_seam')
def test_weight_changing_call_is_refused(tmp_path):
    with pytest.raises(ValueError, match='compute4FermionWeight'):
        cc.validate_mela({**MELA, 'call': 'compute4FermionWeight'})
    with pytest.raises(ValueError, match='compute4FermionWeight'):
        cc.validate_mela({**MELA, 'couplings': {'compute4FermionWeight': 1}})
    with pytest.raises(ValueError, match='plain name'):
        cc.validate_mela({**MELA, 'couplings': {'ghz1; import os': 1}})


@pytest.mark.usefixtures('in_process_backend_seam')
def test_driver_script_is_valid_python(tmp_path):
    (tmp_path / 'driver.py').write_text(cc.DRIVER)
    py_compile.compile(str(tmp_path / 'driver.py'), doraise=True)
    assert 'compute4FermionWeight' not in cc.DRIVER


@pytest.mark.usefixtures('in_process_backend_seam')
def test_unknown_block_is_refused(tmp_path):
    with pytest.raises(ValueError, match='block'):
        cc.load(_task(tmp_path, block='missing'), tmp_path)
