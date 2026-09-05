#!/usr/bin/env python3
"""Generate all registered validation pages, or check exact freshness with --check."""
import argparse
import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validation_summary import ROOT, load_baseline, summarize


def render(root=ROOT):
    cases, results, baseline = load_baseline(root)
    summary = summarize(cases, results)
    stats, axe = summary['statistical_layer'], summary['acceptance_layer']
    index = ['# Benchmark validation', '',
             'Generated from the committed historical `benchmarks/{cases.json,results.json}`.',
             f"Baseline timestamp: `{baseline.get('generated', 'not recorded')}`. These pages do not claim a fresh replay.", '',
             f'All {len(cases)} registered cases are listed, including failures and unscorable comparisons.',
             f"The {stats['comparisons']} observed model-independent S95 comparisons span "
             f"{stats['distinct_searches']} distinct searches; their worst deviation is {stats['worst_delta_pct']:.1f}%.",
             'This tests the statistical/data-input layer. It does not establish detector selection or end-to-end fidelity.',
             f"Acceptance is scorable in {axe['scorable']} cases and unscorable in {axe['unscorable']}; "
             f"recorded cert verdicts are {axe['verdict_counts']}.",
             'Acceptance certification, the regression tier, and numerical stability are separate judgments.', '',
             'The end-to-end mass-plane result is recorded separately in the',
             '[flagship scan](../../evidence/scans/slepton-bino-figure-3/RESULT.md): 24.9% median same-basis',
             'cross-section-limit residual over 50 reference-matched cells from a 52-point scan.', '',
             '| Case | Observed S95 deviation | Acceptance verdict | Baseline gate |',
             '|---|---|---|---|']
    pages = {}
    for c in cases:
        cid = c['case_id']
        r = results[cid]
        metrics = r.get('metrics') or {}
        lim, cert = metrics.get('limit') or {}, metrics.get('axe')
        ratio = lim.get('s95_ratio_obs')
        delta = f'{abs(1-ratio)*100:.1f}%' if ratio is not None else 'unscorable'
        cert_label = cert.get('cert_verdict', 'missing') if cert else 'unscorable'
        index.append(f"| [{cid}](cases/{cid.replace("_", "-")}.md) | {delta} | {cert_label} | {r.get('status')} |")
        page = [f'# Benchmark: `{cid}`', '',
                f"- Analysis: `{c['analysis_id']}`; routine: `{c['routine']}`.",
                f"- Model: {c.get('model', 'see registry')}; masses (parent, LSP): "
                f"({c['m_parent']}, {c['m_lsp']}) GeV.",
                f"- Historical baseline timestamp: `{baseline.get('generated', 'not recorded')}`.",
                f"- Recorded regression status: {r.get('status')}; gate ok: {r.get('gate', {}).get('ok')}.", '',
                '## Statistical layer', '',
                'Metric: driving-signal-region model-independent S95, measured in events.',
                f'Observed ratio: {ratio}; deviation |1 − ratio|: {delta}.',
                f"Observed/expected S95 from the replay: {lim.get('s95_obs')} / {lim.get('s95_exp')}.",
                f"Best signal region: `{lim.get('best_sr')}`; limit tier: {lim.get('tier')}.",
                f"Observed cross-section-limit ratio (when available): {lim.get('sigma_ul_ratio_obs')}.",
                f"Numerical stability against the stored baseline: {lim.get('stability_ok')}.",
                'Stability measures repeatability, not agreement with the experiment.', '',
                '## Selection acceptance and efficiency', '']
        if cert:
            page += [f"Certification verdict: {cert_label}; regression tier: {cert.get('tier')}.",
                     f"Recorded residual: {100*cert['residual']:.2f}%.",
                     'A regression gate can pass its historically locked floor while certification is WARN or FAIL.']
        else:
            page += ['Unscorable: no published acceptance reference is certified by this benchmark.',
                     'A successful S95 comparison does not fill this gap.']
        if c.get('public_note'):
            page += ['', c['public_note']]
        page += ['', '## Reproduce', '', '```bash',
                 f'python3 scripts/run.py ravel.validation.benchmark --case {cid}', '```', '',
                 "The public quickstart ships the fast case's cached inputs. Other cases require the",
                 'development evidence named in the registry; absent inputs must produce a failure.',
                 'This command re-fits cached inputs. Fresh generation and detector validation are separate work.', '']
        pages[f'cases/{cid.replace(chr(95), chr(45))}.md'] = '\n'.join(page)
    pages['README.md'] = '\n'.join(index) + '\n'
    return pages, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        pages, summary = render()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f'validation pages: FAIL: {exc}', file=sys.stderr)
        return 1
    outputs = {ROOT / 'docs/validation' / name: text for name, text in pages.items()}
    outputs[ROOT / 'evidence/validation-summary.json'] = json.dumps(summary, indent=2, allow_nan=False) + '\n'
    stats, axe = summary['statistical_layer'], summary['acceptance_layer']
    verdicts = axe['verdict_counts']
    body = (f"{summary['registry_cases']} cases are registered in the historical benchmark baseline. "
            f"{stats['comparisons']} compare observed model-independent S95 in events, with a worst "
            f"residual of {stats['worst_delta_pct']:.1f}%. Acceptance is separately scorable in "
            f"{axe['scorable']} cases ({verdicts['PASS']} PASS, {verdicts['WARN']} WARN, "
            f"{verdicts['FAIL']} FAIL), and unscorable in {axe['unscorable']}. These are historical "
            "measurements, not a fresh end-to-end reproduction claim. All cases, including failed "
            "certifications, appear in [validation pages](../validation/README.md).\n")
    status = ROOT / 'docs/development/status.md'
    status_text = status.read_text()
    pattern = r'(<!-- VALIDATION-STATUS:BEGIN -->\n).*?(<!-- VALIDATION-STATUS:END -->)'
    if len(re.findall(pattern, status_text, re.S)) != 1:
        print('validation pages: FAIL: missing or duplicated STATUS validation markers')
        return 1
    outputs[status] = re.sub(pattern, lambda m: m[1] + body + m[2], status_text, flags=re.S)
    stale = []
    for path, text in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text() != text:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    extra = set((ROOT / 'docs/validation/cases').glob('*.md')) - set(outputs)
    stale.extend(str(p.relative_to(ROOT)) + ' (unregistered page)' for p in sorted(extra))
    if stale:
        print('validation pages: FAIL: ' + ', '.join(stale))
        return 1
    print(f'validation pages: OK ({len(pages)-1} cases, index, scoped summary)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
