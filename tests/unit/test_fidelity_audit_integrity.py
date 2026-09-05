"""Published demonstrations must fail integrity checks after data or code drift."""
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_fidelity_audits


def test_current_fidelity_demonstrations_are_bound_to_inputs():
    assert check_fidelity_audits.check() == []


@pytest.mark.parametrize('mutation', ['scan_population', 'native_population', 'native_code_pin'])
def test_tampered_demonstration_is_rejected(tmp_path, mutation):
    source = ROOT / 'evidence/audits'
    for name in ['2026-09-05-native-fidelity', '2026-09-05-scan-fidelity', '2026-09-05-statistical-fidelity']:
        shutil.copytree(source / name, tmp_path / name)
    if mutation == 'scan_population':
        path = tmp_path / '2026-09-05-scan-fidelity/scan__reldiff.json'
        data = json.loads(path.read_text())
        data['planned'] -= 2
    elif mutation == 'native_population':
        path = tmp_path / '2026-09-05-native-fidelity/erjr_differential.json'
        data = json.loads(path.read_text())
        data['changed_events'].pop()
    else:
        path = tmp_path / '2026-09-05-native-fidelity/verification.json'
        data = json.loads(path.read_text())
        data['engine_sha256']['sa_native_core.py'] = '0' * 64
    path.write_text(json.dumps(data))
    assert check_fidelity_audits.check(audits=tmp_path)
