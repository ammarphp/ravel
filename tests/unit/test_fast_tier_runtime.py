"""Exercise the documented isolated developer command and its wall-time budget."""
from pathlib import Path
import json
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]


def test_fast_command_finishes_within_five_minutes(request):
    fast = json.loads((ROOT / 'tests/test_tiers.json').read_text())['fast']
    assert Path(__file__).relative_to(ROOT).as_posix() not in fast
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, 'scripts/maintenance/ci_shards.py', '--tier', 'fast',
         '--run', '--file-timeout', '180'], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
    )
    elapsed = time.monotonic() - started
    request.node.user_properties.append(('fast_tier_wall_seconds', f'{elapsed:.2f}'))
    assert result.returncode == 0, result.stdout
    assert f'CI_SHARD_TOTAL files={len(fast)} failed=0 timed_out=0' in result.stdout
    assert elapsed < 300, result.stdout
