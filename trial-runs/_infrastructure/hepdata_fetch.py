#!/usr/bin/env python
"""Fetch a search's HEPData inputs for the fit, via the endpoints that are reachable.

Empirically (tested on this host):
  - the JSON API `/record/insNNNN?format=json` is OPEN -- it lists the record's data
    tables and its `record.resources` (the published likelihood + the SimpleAnalysis/
    SModelS/MadAnalysis reinterpretation hooks);
  - the per-table/bulk `/download/...` endpoints are Cloudflare-blocked (HTTP 403), so
    the numeric table contents are NOT script-fetchable here;
  - BUT the resource endpoint `/record/resource/<id>?view=true` is OPEN, so a published
    likelihood archive IS programmatically downloadable (pyhf.contrib.utils.download).

So the data hierarchy this script supports: a published likelihood downloads directly
(no browser); the raw data tables do not (use Rivet's bundled REF, a reinterpretation
database, or the browser as a last resort for those). The Rivet routine id encodes the
Inspire id: ATLAS_2016_I1458270 -> ins1458270.

Integrity contract (no silent corruption): a --tables fetch is VERIFIED after download
(submission.yaml must exist and parse; the table-type classification summary is printed);
any failed or partial fetch (API unreachable, download error, missing/unparseable
submission.yaml, requested likelihood not retrievable) prints a loud error and exits
NONZERO. Exit 0 means every requested artifact landed and verified.

Usage:
  hepdata_fetch.py (--routine NAME | --inspire insNNNN) --out DIR [--download-likelihood] [--tables]
"""
import argparse, json, os, re, ssl, sys, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def _ssl_context():
    """Default verification, falling back to certifi, then unverified -- the HEPData
    JSON API is a public read-only endpoint, so an unverified context is acceptable
    when the local CA bundle is missing (common in conda/sandbox pythons)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def _open(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    ctx = _ssl_context()
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except urllib.error.URLError as e:
        # CR-021 SSL policy (mining #8): NEVER an unverified fallback. Retry with the
        # certifi bundle (conda envs ship it); if that is unavailable, fail with instructions.
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            if _VERIFIED_CTX is not None:
                return urllib.request.urlopen(req, timeout=timeout, context=_VERIFIED_CTX)
            raise RuntimeError(
                "TLS verification failed and certifi is unavailable under this python. "
                "Re-run inside a conda env (e.g. `<conda> run -n rivet ...`). "
                "Verification is never bypassed (CR-021).") from e
        raise


def inspire_from_routine(name):
    m = re.search(r"_I(\d+)$", name)
    return f"ins{m.group(1)}" if m else None


def get_json(url):
    with _open(url) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--routine", help="Rivet routine name, e.g. ATLAS_2016_I1458270")
    g.add_argument("--inspire", help="Inspire id, e.g. ins1458270")
    ap.add_argument("--out", required=True)
    ap.add_argument("--download-likelihood", action="store_true",
                    help="download + extract any published likelihood via the open resource endpoint")
    ap.add_argument("--tables", action="store_true",
                    help="download the COMPLETE numeric tables (SR yields, cutflows, covariance) via hepdata-cli")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    inspire = args.inspire or inspire_from_routine(args.routine)
    if not inspire:
        sys.exit(f"could not derive Inspire id from '{args.routine}'")
    # HEPData record endpoints want the 'ins'-prefixed form; a bare numeric id is
    # silently treated as a HEPData record id and 404s (S3-census finding, idx8).
    if re.fullmatch(r"\d+", str(inspire)):
        inspire = f"ins{inspire}"

    manifest = {"inspire": inspire, "routine": args.routine, "tables": [], "resources": [],
                "likelihoods": [], "table_files": [], "bundled_note": None, "errors": []}

    # (1) note the source hierarchy
    if args.routine:
        manifest["bundled_note"] = (
            f"Source hierarchy: published likelihood downloads via the resource endpoint "
            f"(--download-likelihood); the COMPLETE numeric tables download via hepdata-cli "
            f"(--tables); Rivet's bundled REF is the offline counting-path copy when present.")

    # (2) discovery via the open JSON API
    url = f"https://www.hepdata.net/record/{inspire}?format=json"
    try:
        rec = get_json(url)
    except Exception as e:
        manifest["errors"].append(f"JSON API fetch failed: {e!r}")
        json.dump(manifest, open(os.path.join(args.out, "hepdata_manifest.json"), "w"), indent=2)
        print(f"ERROR: HEPData JSON API unreachable ({e!r}); wrote PARTIAL manifest only. "
              f"Fall back to Rivet bundled data, or fetch via the Chrome MCP: {url}",
              file=sys.stderr)
        sys.exit(1)

    def _aslist(x):
        return x if isinstance(x, list) else []

    # data tables (HEPData: data_tables[].{name,description,doi,data})
    for t in rec.get("data_tables", []):
        data = t.get("data") if isinstance(t.get("data"), dict) else {}
        manifest["tables"].append({"name": t.get("name"), "doi": t.get("doi"),
                                   "description": (t.get("description") or "")[:160],
                                   "data_url": data.get("json") or data.get("csv")})

    # figure index (cheap discovery pass -- no --tables needed): HEPData table names very
    # often literally carry the paper's figure id ("Figure 16a Observed", "Figure 7 ..."),
    # which is the paper-agnostic figure<->data linkage. Group table names by that leading
    # figure id; figure_target.py `resolve` consumes manifest["figure_index"] to present
    # ranked figure candidates for the declared figure target ([Opus] chooses -- never auto).
    # (CR-008 / trial gap G-AD-04) table names come in BOTH styles: "Figure 16a Observed" AND
    # the underscore family "fig_01", "fig_03_jj", "fig_04a". Accept . _ - or space separators
    # after "fig(ure)" and strip leading zeros so "fig_01a" and "Figure 1a" share the key "1a".
    fig_re = re.compile(r"(?i)^\s*fig(?:ure)?[.\s_-]*0*(\d+[a-z]?)")
    figure_index = {}
    for t in manifest["tables"]:
        m = fig_re.match(t.get("name") or "")
        if m:
            figure_index.setdefault(m.group(1).lower(), []).append(t["name"])
    manifest["figure_index"] = figure_index
    # reinterpretation resources live in record.resources (a list): the published
    # likelihood (file_type HistFactory/pyhf), plus SimpleAnalysis/SModelS/MadAnalysis hooks.
    res = _aslist(rec.get("record", {}).get("resources")) + _aslist(rec.get("resources"))
    for r in res:
        url = r.get("url", "")
        item = {"description": r.get("description", ""), "url": url,
                "type": r.get("file_type", "")}
        manifest["resources"].append(item)
        blob = (item["description"] + " " + url + " " + item["type"]).lower()
        if any(k in blob for k in ("likelihood", "pyhf", "histfactory", "statistical model")):
            # the /download/ table endpoints are Cloudflare-blocked (403), but the resource
            # endpoint /record/resource/<id>?view=true is OPEN -- build that download URL.
            m = re.search(r"/record/resource/(\d+)", url)
            item["download_url"] = (f"https://www.hepdata.net/record/resource/{m.group(1)}?view=true"
                                    if m else url)
            manifest["likelihoods"].append(item)

    # (3) download the likelihood archive via the open resource endpoint (no browser needed).
    if args.download_likelihood and manifest["likelihoods"]:
        try:
            import pyhf.contrib.utils as _U  # handles the tar/zip extraction
            for lk in manifest["likelihoods"]:
                try:
                    _U.download(lk["download_url"], args.out, force=True)
                    lk["downloaded"] = args.out
                    print(f"downloaded + extracted likelihood -> {args.out}  ({lk['download_url']})")
                except Exception as e:
                    lk["downloaded"] = None
                    lk["fetch_via_browser"] = lk["download_url"]
                    manifest["errors"].append(f"download failed for {lk['download_url']}: {e!r}")
                    print(f"download failed ({e!r}); browser fallback URL: {lk['download_url']}")
        except ImportError:
            manifest["errors"].append("pyhf.contrib unavailable -- requested likelihood NOT downloaded")
            print("pyhf.contrib unavailable; likelihood download URLs are in the manifest.")

    # (4) download the COMPLETE numeric tables via hepdata-cli (bypasses the /download/ 403),
    #     then VERIFY: submission.yaml must exist and parse; classify table types and report.
    #     A download with no parseable submission.yaml is treated as corrupt (-> nonzero exit).
    if args.tables:
        tdir = os.path.join(args.out, "tables")
        os.makedirs(tdir, exist_ok=True)
        try:
            from hepdata_cli.api import Client
            Client().download(id_list=[inspire.replace("ins", "")], file_format="yaml",
                              ids="inspire", download_dir=tdir)
            # verification step 1: submission.yaml must exist after the download
            subs = [os.path.join(r, f) for r, _, fs in os.walk(tdir) for f in fs if f == "submission.yaml"]
            if not subs:
                raise RuntimeError(f"download left no submission.yaml under {tdir} -- partial/corrupt fetch")
            # verification step 2: it must parse; classify tables by description (HEPData names them "Table N")
            import yaml as _yaml
            def classify(desc, name):
                d = (desc + " " + name).lower()
                if "cutflow" in d or "cut flow" in d: return "cutflow"
                if "acceptance" in d and "efficien" in d: return "acc-eff"
                if "acceptance" in d: return "acceptance"
                if "efficien" in d: return "efficiency"
                if "covariance" in d or "correlation" in d: return "covariance"
                # exclusion CONTOUR (the published limit BOUNDARY in the mass plane) and the per-point
                # LIMIT grid (cross-section / signal-strength upper limits) -- the two tables the mass-
                # plane overlay + the (mapyde-ATLAS)/ATLAS difference map need (step 8 / scan_contour.py).
                # General keyword buckets (any SUSY exclusion record), not hardwired to one analysis.
                dn = d.replace("-", " ")  # normalize 'cross-section' -> 'cross section', etc.
                if "exclus" in dn and ("contour" in dn or "limit" in dn or "boundary" in dn
                                       or "region" in dn or "sensitivity" in dn):
                    return "exclusion-contour"   # the limit BOUNDARY in the mass plane (e.g. 'exclusion sensitivity')
                if (("upper limit" in dn or "upperlimit" in dn or "cls" in dn.replace(" ", "")
                     or "signal strength" in dn or ("cross section" in dn and "limit" in dn)
                     or "upper cross section" in dn or ("\\sigma" in dn and "limit" in dn))
                        and "acceptance" not in dn):
                    return "limit"              # per-point upper limit grid (e.g. 'upper cross-section limits')
                if ("yield" in d or "number of events" in d) and ("signal region" in d or "sr" in d): return "sr-yields"
                return "table"
            for sub in subs:
                base = os.path.dirname(sub)
                try:
                    docs = list(_yaml.safe_load_all(open(sub, errors="replace")))
                except Exception as e:
                    raise RuntimeError(f"{sub} does not parse as YAML ({e!r}) -- corrupt fetch")
                n_before = len(manifest["table_files"])
                for doc in docs:
                    if isinstance(doc, dict) and doc.get("name") and "description" in doc:
                        kind = classify(doc.get("description") or "", doc["name"])
                        loc = doc.get("data_file") or ""
                        manifest["table_files"].append(
                            {"name": doc["name"], "kind": kind,
                             "description": (doc["description"] or "").replace("\n", " ")[:120],
                             "file": os.path.relpath(os.path.join(base, loc), args.out) if loc else ""})
                if len(manifest["table_files"]) == n_before:
                    raise RuntimeError(f"{sub} parses but declares no tables -- partial/corrupt fetch")
            # verification step 3: every declared data_file must exist and be non-empty
            def _ok(rel):
                try:
                    return os.path.getsize(os.path.join(args.out, rel)) > 0
                except OSError:
                    return False
            missing = [t["name"] for t in manifest["table_files"] if t["file"] and not _ok(t["file"])]
            if missing:
                raise RuntimeError(f"{len(missing)} declared data_file(s) missing/empty "
                                   f"(e.g. {missing[:3]}) -- partial fetch")
            kinds = {}
            for t in manifest["table_files"]:
                kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
            manifest["table_kinds"] = kinds
            print(f"downloaded complete tables -> {tdir}; verified submission.yaml parses; "
                  f"{len(manifest['table_files'])} tables classified: "
                  + ", ".join(f"{k}:{v}" for k, v in sorted(kinds.items())))
        except ImportError:
            manifest["errors"].append("hepdata-cli not installed; run in an env that has it (e.g. reinterp)")
            print("hepdata-cli unavailable; install it (pip install hepdata-cli) to fetch full tables.")
        except Exception as e:
            manifest["errors"].append(f"hepdata-cli table download/verification failed: {e!r}")
            print(f"hepdata-cli table download/verification failed: {e!r}", file=sys.stderr)

    json.dump(manifest, open(os.path.join(args.out, "hepdata_manifest.json"), "w"), indent=2)
    print(f"\nrecord {inspire}: {len(manifest['tables'])} tables, "
          f"{len(manifest['resources'])} resources, {len(manifest['likelihoods'])} likelihood(s); "
          f"figure_index covers {len(manifest['figure_index'])} figure id(s)")
    for lk in manifest["likelihoods"]:
        print(f"  likelihood: {lk['description'][:70]}  {lk['url']}")
    print(f"manifest -> {os.path.join(args.out, 'hepdata_manifest.json')}")
    if manifest["errors"]:
        print("\nERROR: fetch FAILED or PARTIAL -- do NOT use this directory as a complete copy:",
              file=sys.stderr)
        for e in manifest["errors"]:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
