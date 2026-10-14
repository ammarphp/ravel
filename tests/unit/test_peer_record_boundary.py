"""The same intended-byte boundary in the actual observer's raw journal."""
import json
import pytest
from ravel.physics import parameter_space_sampling_observer as ob
from test_parameter_space_sampling import observer_fixture


def test_changed_evaluation_begin_record_refuses_before_underlying_call(tmp_path, monkeypatch):
    observer = ob.Observer(observer_fixture(tmp_path))
    actual = ob.atomic_json
    changed = []
    calls = []
    def intercept(path, payload):
        actual(path, payload)
        if payload['kind'] == 'evaluation-begin':
            value = json.loads(path.read_bytes())
            value['arguments'] = [[42]]
            path.write_text(json.dumps(value, allow_nan=False))
            changed.append(str(path))
    monkeypatch.setattr(ob, 'atomic_json', intercept)
    fn = observer.likelihood(lambda *args: calls.append(args) or -1)
    try:
        fn([.5])
    except (RuntimeError, ValueError, OSError):
        assert calls == []
        return
    (tmp_path / 'record-boundary-witness.json').write_text(json.dumps({
        'changed_records': changed, 'actual_underlying_calls': calls,
        'retained_begin_record': json.loads(__import__('pathlib').Path(changed[0]).read_bytes()),
        'scope': 'actual observer with inert likelihood; no scientific call'}, indent=2))
    assert calls == [], 'changed begin record was accepted and underlying call continued'
