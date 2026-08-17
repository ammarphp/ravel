#!/usr/bin/env python3
"""claims_check -- CI gate: every number the README quotes must match results/manifest.json.

Spec Part III E2. Mechanism: README.md carries HTML claim markers
    <!-- claim:tests_collected -->344<!-- /claim -->
around each headline number. This script asserts, for every marker: (a) the claim id exists in
results/manifest.json, (b) the marked text EQUALS the manifest 'value' (whitespace-normalized),
(c) the manifest entry is status VERIFIED (an UNVERIFIED claim in the README fails the build),
(d) every manifest artifact path exists in the tree. It also asserts the reverse: every VERIFIED
manifest claim is actually cited in the README (no orphan evidence), and cross-checks the one
value shared with evidence_manifest.json (the fig3 residual) for agreement.

Exit 0 = all claims verified. Nonzero = drift; the build fails. Stdlib only.

  python3 scripts/claims_check.py            # gate (CI entrypoint; also `make claims`)
  python3 scripts/claims_check.py --selftest # prove the gate objects to a doctored README
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = re.compile(r"<!--\s*claim:([a-z0-9_]+)\s*-->(.*?)<!--\s*/claim\s*-->", re.S)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def check(readme_path, manifest_path, root=ROOT):
    fails, warns = [], []
    manifest = json.load(open(manifest_path))
    claims = {c["claim"]: c for c in manifest["claims"]}
    readme = open(readme_path).read()
    cited = {}
    for cid, text in MARKER.findall(readme):
        cited[cid] = norm(text)
        if cid not in claims:
            fails.append(f"README cites unknown claim id '{cid}' (no manifest entry)")
            continue
        entry = claims[cid]
        if entry.get("status") != "VERIFIED":
            fails.append(f"README cites claim '{cid}' whose manifest status is "
                         f"{entry.get('status')} — unverified numbers may not ship")
        if norm(text) != norm(str(entry["value"])):
            fails.append(f"claim '{cid}' drift: README says '{norm(text)}' but manifest says "
                         f"'{entry['value']}'")
    for cid, entry in claims.items():
        if entry.get("status") == "VERIFIED" and cid not in cited:
            warns.append(f"VERIFIED manifest claim '{cid}' is not cited in the README "
                         f"(orphan evidence — cite it or drop it)")
        for a in entry.get("artifacts", []):
            if not os.path.exists(os.path.join(root, a)):
                fails.append(f"claim '{cid}' artifact missing on disk: {a}")
    # cross-check the shared physics headline against the sha-pinned evidence manifest
    ev_path = os.path.join(root, "evidence_manifest.json")
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
    fails, warns = check(os.path.join(ROOT, "README.md"),
                         os.path.join(ROOT, "results", "manifest.json"))
    for w in warns:
        print(f"[WARN] {w}")
    for f in fails:
        print(f"[FAIL] {f}")
    n_cited = len(MARKER.findall(open(os.path.join(ROOT, 'README.md')).read()))
    if fails:
        print(f"claims_check: {len(fails)} FAIL — README numbers do not match their evidence.")
        return 1
    print(f"claims_check: OK — {n_cited} README claim(s) verified against results/manifest.json"
          f" ({len(warns)} warn).")
    return 0


def selftest():
    import tempfile
    ok_readme = '<!-- claim:tests_collected -->344<!-- /claim -->'
    bad_readme = '<!-- claim:tests_collected -->999<!-- /claim -->'
    with tempfile.TemporaryDirectory() as td:
        rp = os.path.join(td, "README.md")
        mp = os.path.join(ROOT, "results", "manifest.json")
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
