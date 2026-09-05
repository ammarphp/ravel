#!/usr/bin/env python3
"""Re-render the bundled historical scan and record exact input/output hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.evidence_layout import resolve
from ravel.paths import module_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='new output directory')
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scan = resolve(ROOT, 'evidence/scans/slepton-bino-figure-3/scan.json')
    reference = ROOT / 'evidence/audits/2026-09-05-scan-fidelity/atlas-limit-grid.yaml'
    contour = reference.with_name('atlas-observed-contour.yaml')
    cmd = module_command('ravel.plotting.scan_contour', '--scan', str(scan),
                         '--atlas-limit', str(reference), '--atlas-contour', 'observed=' + str(contour),
                         '--lumi', '139', '--logy', '--out', str(output / 'scan'))
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    # Logs use logical relative inputs so the demonstration does not expose operator paths.
    log = (result.stdout + result.stderr).replace(str(ROOT), '<repository>').replace(str(output), '<output>')
    (output / 'render.log').write_text(log)
    print(log)
    if result.returncode:
        return result.returncode
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    files = [scan, reference, contour, ROOT / 'src/ravel/plotting/scan_contour.py',
             ROOT / 'src/ravel/plotting/mplhep_style.py', ROOT / 'src/ravel/limits.py', Path(__file__)]
    record = {'scope': 'fresh plotting of cached historical scan; no event generation or new likelihood fits',
              'python': platform.python_version(),
              'command': 'python benchmarks/plot_scan_demo.py --out NEW_DIRECTORY',
              'inputs': {str(p.relative_to(ROOT)): sha(p) for p in files},
              'outputs': {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()}}
    (output / 'provenance.json').write_text(json.dumps(record, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
