"""Current closed source import law only; no native calibration or fit."""
from pathlib import Path
import hashlib, sys
import pytest
from ravel.physics import regional_calibration as c, statistical_construction as r
from test_continuous_shape_calibration import fixture, bundle

def test_current_eight_member_package_imports_with_dijet_calibration(tmp_path):
    assert len(c.SHAPE_SOURCE_MEMBERS)==8
    assert c.SHAPE_SOURCE_MAX_BYTES==8*1048576
    assert c.SUPPORTED_SHAPES==('normalized_exponential','normalized_power','normalized_dijet')
    d,q=fixture(tmp_path);root,binding=bundle(tmp_path,d)
    source=Path(r.__file__).parent/'continuous_dijet_shapes.py'
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    assert binding['files']['physics/continuous_dijet_shapes.py']['sha256']==sha
    assert sum(row['bytes'] for row in binding['files'].values())<=c.SHAPE_SOURCE_MAX_BYTES
    saved={name:module for name,module in sys.modules.items() if name=='ravel' or name.startswith('ravel.')}
    for name in saved:sys.modules.pop(name)
    try:
        c.bind_shape_sources(root,binding)
        staged=sys.modules['ravel.physics.continuous_dijet_shapes']
        assert sys.modules['ravel.physics.statistical_construction'].continuous_dijet_shapes is staged
        assert Path(staged.__file__).is_relative_to(root)
        assert hashlib.sha256(Path(staged.__file__).read_bytes()).hexdigest()==sha
        c.check_shape_sources(root,binding)
        assert list(c.means(d,q['truths'][0]['point']).values())==pytest.approx(r.mean_jet(d,q['truths'][0]['point'])['means'])
        assert not list(root.rglob('*.pyc'))
    finally:
        for name in list(sys.modules):
            if name=='ravel' or name.startswith('ravel.'):sys.modules.pop(name)
        sys.modules.update(saved)
    d['terms'][0]['shape']['kind']='unsupported_shape'
    with pytest.raises(ValueError,match='unknown continuous calibration shape'):
        c._shape_fractions(d,{name:0 for name in d['auxiliary']['names']})
