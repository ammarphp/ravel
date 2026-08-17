#!/usr/bin/env python3
"""Generate docs/validation/<case_id>.md from the benchmark gate's own artifacts (spec E3).

Template-generated from framework/benchmark/{cases.json,results.json} so the pages can never
drift from the gate: regenerate with  python3 scripts/gen_validation_pages.py  (also run by
`make claims` indirectly via CI). One page per benchmark case + an index. Stdlib only.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "validation")


def main():
    cases = json.load(open(os.path.join(ROOT, "framework/benchmark/cases.json")))["cases"]
    results = json.load(open(os.path.join(ROOT, "framework/benchmark/results.json")))
    rows = results if isinstance(results, list) else results.get("cases", [])
    if isinstance(rows, dict):
        rows = list(rows.values())
    res = {r["case_id"]: r for r in rows if isinstance(r, dict) and r.get("case_id")}
    os.makedirs(OUT, exist_ok=True)
    index = ["# Benchmark validation pages", "",
             "One page per known-answer benchmark case, generated from the gate's own",
             "`framework/benchmark/{cases.json,results.json}` by `scripts/gen_validation_pages.py`",
             "(regenerate after any `--full` gate re-run; CI checks freshness indirectly via the",
             "claims gate). Δ% = |1 − s95_obs(ours)/s95_obs(published)|.", "",
             "| Case | Analysis | Δ% (obs) | Tier | Page |", "|---|---|---|---|---|"]
    n = 0
    for c in cases:
        cid = c.get("case_id") or c.get("id")
        if not cid or cid not in res:
            continue
        r = res[cid]
        lim = (r.get("metrics") or {}).get("limit") or {}
        ratio = lim.get("s95_ratio_obs") or lim.get("s95_ratio_exp")
        if ratio is None:
            continue
        n += 1
        delta = abs(1 - ratio) * 100
        ana = c.get("analysis") or c.get("inspire") or c.get("routine", "?")
        page = [f"# Benchmark: `{cid}`", "",
                f"- **Analysis**: {ana}",
                f"- **Model point**: {c.get('model', c.get('point', 'see cases.json'))}",
                f"- **Published s95 (obs)**: {c.get('published', {}).get('s95_obs', 'see cases.json')}",
                f"- **Reproduced s95 (obs/exp)**: {lim.get('s95_obs')} / {lim.get('s95_exp')}",
                f"- **s95 ratio (obs)**: {lim.get('s95_ratio_obs')}  →  **Δ = {delta:.1f}%**",
                f"- **Best signal region**: `{lim.get('best_sr')}` "
                f"(matches published choice: {lim.get('best_sr_matches')})",
                f"- **Verdict tier**: {lim.get('tier')} (required: "
                f"{(r.get('required') or {}).get('limit_tier')}); gate ok = "
                f"{(r.get('gate') or {}).get('ok')}",
                f"- **µ95 stability check**: {lim.get('stability_ok')} "
                f"(rtol {(r.get('required') or {}).get('mu95_stability', {}).get('rtol')})",
                f"- **Provenance checks**: {(r.get('metrics') or {}).get('provenance', {}).get('ok')}",
                f"- **Wall time (pyhf re-fit)**: {(r.get('timing') or {}).get('pyhf_s', 0):.1f}s", "",
                *( [f"- **Note**: {c['public_note']}"] if c.get("public_note") else [] ),
                "**Regenerate**:", "```bash",
                f"python3 framework/benchmark/run_benchmark.py --case {cid}", "```", "",
                "Ground truth transcribed from the published analysis (reference + table noted in",
                "`framework/benchmark/cases.json`); the fast gate re-fits the cached artifacts",
                "through the real pyhf layer on every run.", ""]
        open(os.path.join(OUT, f"{cid}.md"), "w").write("\n".join(page))
        index.append(f"| `{cid}` | {ana} | {delta:.1f} | {lim.get('tier')} | "
                     f"[{cid}.md]({cid}.md) |")
    open(os.path.join(OUT, "README.md"), "w").write("\n".join(index) + "\n")
    print(f"wrote {n} case pages + index -> docs/validation/")


if __name__ == "__main__":
    main()
