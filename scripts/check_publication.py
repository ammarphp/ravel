#!/usr/bin/env python3
"""Check scoped public claims, generated pages, capability prose, and approval semantics.

This gates registered facts and known drift patterns, not arbitrary natural-language truth.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    failed = False
    for script, args in [('scripts/check_repository.py', []),
                         ('scripts/claims_check.py', []),
                         ('scripts/check_fidelity_audits.py', []),
                         ('scripts/check_rrr_audits.py', []),
                         ('evidence/audits/2026-09-05-rrr-refits/summarize.py', ['--check']),
                         ('evidence/audits/2026-09-06-rrr-waypoint/curate.py', []),
                         ('evidence/audits/2026-09-06-rrr-cut-dependence/verify.py', []),
                         ('evidence/audits/2026-09-06-rrr-event-identity/verify.py', []),
                         ('evidence/audits/2026-09-06-rrr-template-controls/verify.py', []),
                         ('evidence/audits/2026-09-06-rrr-fresh-anchors/verify.py', []),
                         ('evidence/audits/2026-09-05-analysis-landscape/validate_catalog.py', []),
                         ('scripts/gen_validation_pages.py', ['--check']),
                         ('scripts/gen_status.py', ['--check'])]:
        result = subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT)
        failed |= result.returncode != 0
    contract = (ROOT / 'docs/reference/scope.md').read_text()
    required = 'any smoke, full, or scan generation before CHECK-IN 1'
    if required not in contract or 'generation beyond a smoke test' in contract:
        print('publication: FAIL: product-contract generation approval semantics drifted')
        failed = True
    readme = (ROOT / 'README.md').read_text()
    if re.search(r'What is genuinely novel|full limit reproduction|benchmarks reproduced within', readme):
        print('publication: FAIL: obsolete unqualified novelty/reproduction headline')
        failed = True
    version = re.search(r'^version = "([^"]+)"', (ROOT / 'pyproject.toml').read_text(), re.M)
    citation = re.search(r'^version: (.+)$', (ROOT / 'CITATION.cff').read_text(), re.M)
    if not version or not citation or version[1] != citation[1].strip():
        print('publication: FAIL: package/citation version mismatch')
        failed = True
    print('publication: ' + ('FAIL' if failed else 'OK'))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
