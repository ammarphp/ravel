#!/usr/bin/env python3
"""claims_check -- CI gate: every number the results page quotes must match evidence/claims.json.

Spec Part III E2. Mechanism: results.md carries HTML claim markers
    <!-- claim:tests_collected -->344<!-- /claim -->
around each headline number. This script asserts, for every marker: (a) the claim id exists in
evidence/claims.json, (b) the marked text EQUALS the manifest 'value' (whitespace-normalized),
(c) the manifest entry is status VERIFIED (an UNVERIFIED claim in the results page fails the build),
(d) every manifest artifact path exists in the tree. It also asserts the reverse: every VERIFIED
manifest claim is actually cited in the results page (no orphan evidence), and cross-checks the one
value shared with evidence/manifest.json (the fig3 residual) for agreement.

Exit 0 = all claims verified. Nonzero = drift; the build fails. Stdlib only.

  python3 scripts/claims_check.py            # gate (CI entrypoint; also `make claims`)
  python3 scripts/claims_check.py --selftest # prove the gate objects to a doctored results page
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ravel.evidence_layout import resolve
from validation_summary import benchmark_headline, load_baseline, summarize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_RESULTS = "docs/validation/results.md"
MARKER = re.compile(r"<!--\s*claim:([a-z0-9_]+)\s*-->(.*?)<!--\s*/claim\s*-->", re.S)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def check(readme_path, manifest_path, root=ROOT, require_all=True):
    fails, warns = [], []
    manifest = json.load(open(manifest_path))
    claims = {c["claim"]: c for c in manifest["claims"]}
    if len(claims) != len(manifest["claims"]):
        fails.append("duplicate manifest claim id")
    readme = open(readme_path).read()
    cited = {}
    for cid, text in MARKER.findall(readme):
        if cid in cited:
            fails.append(f"duplicate results page claim marker '{cid}'")
        cited[cid] = norm(text)
        if cid not in claims:
            fails.append(f"results page cites unknown claim id '{cid}' (no manifest entry)")
            continue
        entry = claims[cid]
        if entry.get("status") != "VERIFIED":
            fails.append(f"results page cites claim '{cid}' whose manifest status is "
                         f"{entry.get('status')} — unverified numbers may not ship")
        if norm(text) != norm(str(entry["value"])):
            fails.append(f"claim '{cid}' drift: results page says '{norm(text)}' but manifest says "
                         f"'{entry['value']}'")
    for cid, entry in claims.items():
        if require_all and entry.get("status") == "VERIFIED" and cid not in cited:
            fails.append(f"VERIFIED manifest claim '{cid}' is not cited in the results page")
        for a in entry.get("artifacts", []):
            if not resolve(root, a.rstrip("/")).exists():
                message = f"claim '{cid}' artifact missing on disk: {a}"
                # An uncited historical/unverified claim may reference an intentionally
                # private archive. A published VERIFIED claim has no such exemption.
                (fails if entry.get("status") == "VERIFIED" else warns).append(message)
    # Numerical agreement between two hand-edited strings is insufficient: derive the
    # benchmark headline's value AND metric scope from its actual baseline artifacts.
    if "benchmarks_reproduced" in claims:
        try:
            cases, results, _ = load_baseline(root)
            expected = benchmark_headline(summarize(cases, results))
            if claims["benchmarks_reproduced"]["value"] != expected:
                fails.append(f"benchmark scope/value drift: expected '{expected}'")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            fails.append(f"benchmark source invalid: {exc}")
    # cross-check the shared physics headline against the sha-pinned evidence manifest
    if "rrr_anchor_limits" in claims:
        try:
            record = json.loads((Path(root) / "evidence/audits/2026-09-06-rrr-waypoint/waypoint.json").read_text())
            point = record["reference_point"]
            result = record["results"]["anchor20k"]
            expected = (
                f"{result['conditional_observed_sigma95_fb']:.2f} fb observed and "
                f"{result['conditional_median_expected_sigma95_fb']:.2f} fb median expected "
                f"at {point['m_parent_GeV']:g}/{point['m_lsp_GeV']:g} GeV")
            if claims["rrr_anchor_limits"]["value"] != expected:
                fails.append(f"RRR waypoint scope/value drift: expected '{expected}'")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            fails.append(f"RRR waypoint source invalid: {exc}")
    if any(name in claims for name in ("rrr_pool_limits", "rrr_cut_rate_ratio")):
        try:
            record = json.loads((Path(root) / "evidence/audits/2026-09-06-rrr-cut-dependence/data/evidence.json").read_text())
            pools = [fit for fit in record["native"] if fit["id"] == "pooled_60k"]
            regions = [row for row in record["lower"]["rows"] if row["category"] == "SR_high"]
            if len(pools) != 1 or len(regions) != 1:
                raise ValueError("Unique pooled result and high-region comparison required")
            fit = pools[0]
            ratio = regions[0]["lower_over_nominal"]["selected_rate"]
            interval = ratio["conditional_plus_integration_95pct_interval"]
            expected = {
                "rrr_pool_limits": (
                    f"{fit['sigma95_fb']['observed']:.2f} fb observed and "
                    f"{fit['sigma95_fb']['expected_median']:.2f} fb median expected from the "
                    f"{fit['original_events']:,}-event pool at "
                    f"{record['catalog']['m_parent_GeV']:g}/{record['catalog']['m_lsp_GeV']:g} GeV"),
                "rrr_cut_rate_ratio": (
                    f"a high-region rate ratio of {ratio['ratio']:.3f} "
                    f"(conditional 95% interval {interval[0]:.3f}–{interval[1]:.3f})"),
            }
            for name, value in expected.items():
                if name in claims and claims[name]["value"] != value:
                    fails.append(f"RRR control scope/value drift: {name}: expected '{value}'")
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            fails.append(f"RRR control source invalid: {exc}")
    ev_path = os.path.join(root, "evidence/manifest.json")
    if os.path.exists(ev_path) and "fig3_residual" in claims:
        ev = json.load(open(ev_path))
        heads = [c for c in ev["claims"]
                 if c.get("claim_id") == "HEADLINE_fig3_scan_same_basis_residual"]
        if heads:
            want = re.search(r"([0-9.]+)\s*%", str(claims["fig3_residual"]["value"]))
            have = re.search(r"([0-9][0-9.]*)\s*-\s*([0-9.]+)\s*%|([0-9.]+)%",
                             heads[0].get("headline", ""))
            if want and have:
                v = float(want.group(1))
                lo, hi = (float(have.group(1)), float(have.group(2))) if have.group(1) \
                    else (float(have.group(3)),) * 2
                if not (lo - 0.6 <= v <= hi + 0.6):
                    fails.append(f"fig3 residual disagrees with evidence_manifest headline: "
                                 f"{v}% vs '{heads[0]['headline']}'")
    return fails, warns


def main():
    fails, warns = check(os.path.join(ROOT, PUBLIC_RESULTS),
                         os.path.join(ROOT, "evidence", "claims.json"))
    readme_fails, readme_warns = check(os.path.join(ROOT, "README.md"),
                                      os.path.join(ROOT, "evidence", "claims.json"), require_all=False)
    fails.extend("README: " + failure for failure in readme_fails)
    warns.extend("README: " + warning for warning in readme_warns)
    for w in warns:
        print(f"[WARN] {w}")
    for f in fails:
        print(f"[FAIL] {f}")
    n_cited = len(MARKER.findall(open(os.path.join(ROOT, PUBLIC_RESULTS)).read()))
    if fails:
        print(f"claims_check: {len(fails)} FAIL — results page numbers do not match their evidence.")
        return 1
    print(f"claims_check: OK — {n_cited} results page claim(s) verified against evidence/claims.json"
          f" ({len(warns)} warn).")
    return 0


def selftest():
    import tempfile
    claims = json.load(open(os.path.join(ROOT, "evidence", "claims.json")))["claims"]
    entry = next(c for c in claims if c["status"] == "VERIFIED")
    ok_readme = f'<!-- claim:{entry["claim"]} -->{entry["value"]}<!-- /claim -->'
    bad_readme = f'<!-- claim:{entry["claim"]} -->DOCTORED<!-- /claim -->'
    with tempfile.TemporaryDirectory() as td:
        rp = os.path.join(td, "results.md")
        mp = os.path.join(ROOT, "evidence", "claims.json")
        open(rp, "w").write(bad_readme)
        fails, _ = check(rp, mp)
        assert any("drift" in f for f in fails), "gate failed to object to a doctored number"
        open(rp, "w").write(ok_readme)
        fails, _ = check(rp, mp)
        assert not any("drift" in f for f in fails), f"gate objected to a correct number: {fails}"
    print("claims_check selftest: PASS (objects to drift, accepts the true value)")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
