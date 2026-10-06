#!/usr/bin/env python3
"""Check scoped public claims, generated pages, capability prose, and approval semantics.

This gates registered facts and known drift patterns, not arbitrary natural-language truth.

Public mode (`--public`, automatic in this repository): a registered check whose script the tree
does not carry is skipped and counted; every other check still runs,
and check_repository, gen_status and gen_validation_pages apply their own public modes.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ravel import evidence_layout


# Scripts with their own explicit public mode; passed --public whenever this check runs in one.
PUBLIC_MODE_SCRIPTS = {'scripts/check_repository.py', 'scripts/gen_validation_pages.py', 'scripts/gen_status.py'}
CHECKS = [('scripts/check_repository.py', []),
          ('scripts/claims_check.py', []),
          ('scripts/check_fidelity_audits.py', []),
          ('scripts/check_rrr_audits.py', []),
          ('evidence/audits/2026-09-05-rrr-refits/summarize.py', ['--check']),
          ('evidence/audits/2026-09-06-rrr-waypoint/curate.py', []),
          ('evidence/audits/2026-09-06-rrr-cut-dependence/verify.py', []),
          ('evidence/audits/2026-09-06-rrr-event-identity/verify.py', []),
          ('evidence/audits/2026-09-06-rrr-template-controls/verify.py', []),
          ('evidence/audits/2026-09-06-rrr-fresh-anchors/verify.py', []),
          ('evidence/audits/2026-09-26-analysis-landscape/verify.py', []),
          ('evidence/audits/2026-09-26-scientific-studies/verify.py', []),
          ('scripts/gen_validation_pages.py', ['--check']),
          ('scripts/gen_status.py', ['--check'])]


def planned_checks(root, public):
    """(script, arguments) to run, and the scripts skipped. Only public mode skips anything, and
    only a script that the tree does not carry."""
    planned, skipped = [], []
    for script, args in CHECKS:
        if public and evidence_layout.is_withheld(script, root):
            skipped.append(script)
            continue
        planned.append((script, [*args, *(['--public'] if public and script in PUBLIC_MODE_SCRIPTS else [])]))
    return planned, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', action='store_true',
                        help='public-tree mode (automatic in a distributed tree)')
    public = parser.parse_args(argv).public or evidence_layout.is_public_tree(ROOT)
    failed = False
    planned, skipped = planned_checks(ROOT, public)
    if skipped:
        print(f'publication: skip {len(skipped)} check(s) whose scripts this tree does not carry')
    for script, args in planned:
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
    print('publication: ' + ('FAIL' if failed else 'OK') + (' (public tree)' if public else ''))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
