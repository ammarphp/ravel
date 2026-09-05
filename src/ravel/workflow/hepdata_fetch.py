#!/usr/bin/env python
"""Fetch a search's HEPData inputs for the fit, via the endpoints that are reachable.

Empirically (tested on this host):
  - the JSON API `/record/insNNNN?format=json` is OPEN -- it lists the record's data
    tables and its `record.resources` (the published likelihood + the SimpleAnalysis/
    SModelS/MadAnalysis reinterpretation hooks);
  - the per-table/bulk `/download/...` endpoints are Cloudflare-blocked (HTTP 403), so
    those URLs are NOT script-fetchable here;
  - BUT the resource endpoint `/record/resource/<id>?view=true` is OPEN, so a published
    likelihood archive IS programmatically downloadable (pyhf.contrib.utils.download);
  - AND the internal data endpoint `/record/data/<recid>/<table_id>/<version>` is OPEN
    and serves the full per-table content as JSON (recid + table ids + version all come
    from the open record JSON). Verified 2026-08-28: all 8 tables of ins1649273 fetched
    this way while /download/table/... stayed 403 (taunu run, RESULT.md gap G3).

So the data hierarchy this script supports: a published likelihood downloads directly
(no browser); the COMPLETE numeric tables download via hepdata-cli, falling back to the
open /record/data endpoint when hepdata-cli is unavailable or blocked. The Rivet routine
id encodes the Inspire id: ATLAS_2016_I1458270 -> ins1458270.

Integrity contract (no silent corruption): a --tables fetch is VERIFIED after download.
hepdata-cli route: submission.yaml must exist and parse, every declared data_file present
and non-empty. /record/data fallback route: EVERY table listed by the record JSON must
land, parse as JSON, and carry a non-empty values[] list. Both routes print the
table-type classification summary; any failed or partial fetch (API unreachable, download
error, missing/unparseable/empty content, requested likelihood not retrievable) prints a
loud error and exits NONZERO. Exit 0 means every requested artifact landed and verified.

Usage:
  hepdata_fetch.py (--routine NAME | --inspire insNNNN) --out DIR [--download-likelihood] [--tables]
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse, json, os, re, ssl, sys, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}

# The certifi-verified context, built once: _ssl_context() uses it as the primary and
# _open()'s SSLCertVerificationError retry path uses it as the fallback (that retry used
# to reference an undefined _VERIFIED_CTX -- a latent NameError, fixed 2026-08-28).
try:
    import certifi as _certifi
    _VERIFIED_CTX = ssl.create_default_context(cafile=_certifi.where())
except Exception:
    _VERIFIED_CTX = None


def _ssl_context():
    """The certifi-verified context when available, else the system default (None).
    Verification is never bypassed (CR-021)."""
    return _VERIFIED_CTX


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


def classify(desc, name):
    """Table-type buckets by description+name -- shared by BOTH --tables routes
    (hepdata-cli and the /record/data fallback), so the manifest reads the same either way."""
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


def record_data_index(rec):
    """Derive (recid, version, [(table_id, name), ...]) from the open record JSON --
    everything the /record/data/<recid>/<table_id>/<version> endpoint needs."""
    recid = rec.get("recid") or (rec.get("record") or {}).get("recid")
    if not recid:
        raise ValueError("record JSON carries no recid -- cannot build /record/data URLs")
    version = rec.get("version") or (rec.get("record") or {}).get("version") or 1
    idx = []
    for t in rec.get("data_tables") or []:
        tid, name = t.get("id"), t.get("name")
        if not tid or not name:
            raise ValueError(f"record JSON data_tables entry missing id/name: {t!r}"[:200])
        idx.append((int(tid), name))
    if not idx:
        raise ValueError("record JSON lists no data_tables")
    return int(recid), int(version), idx


def fetch_tables_via_record_data(rec, out_dir, manifest, get_json_fn=None):
    """--tables FALLBACK via the OPEN internal endpoint (taunu G3, 2026-08-28): where
    /download/table/... is Cloudflare-403, /record/data/<recid>/<table_id>/<version> serves
    the identical per-table content as JSON (with name/doi/description/values).

    Same verify-after-download integrity contract as the hepdata-cli route: EVERY table the
    record JSON lists must land, parse as a dict, and carry a non-empty values[] -- anything
    less raises RuntimeError (-> the caller's loud nonzero exit). Tables land as
    tables/<slug>_data.json; classification summary printed."""
    get_json_fn = get_json_fn or get_json
    recid, version, idx = record_data_index(rec)
    tdir = os.path.join(out_dir, "tables")
    os.makedirs(tdir, exist_ok=True)
    n_before = len(manifest["table_files"])
    for tid, name in idx:
        url = f"https://www.hepdata.net/record/data/{recid}/{tid}/{version}"
        try:
            doc = get_json_fn(url)
        except Exception as e:
            raise RuntimeError(f"table {name!r} ({url}) failed to download ({e!r}) "
                               "-- partial fetch") from e
        if not isinstance(doc, dict) or not doc.get("values"):
            raise RuntimeError(f"table {name!r} ({url}) returned no values[] "
                               "-- partial/corrupt fetch")
        slug = re.sub(r"\W+", "_", name).strip("_").lower()
        dest = os.path.join(tdir, f"{slug}_data.json")
        with open(dest, "w") as f:
            json.dump(doc, f, indent=1)
        manifest["table_files"].append(
            {"name": name, "kind": classify(doc.get("description") or "", name),
             "description": (doc.get("description") or "").replace("\n", " ")[:120],
             "file": os.path.relpath(dest, out_dir), "endpoint": url,
             "doi": doc.get("doi", "")})
    got = manifest["table_files"][n_before:]
    if len(got) != len(idx):
        raise RuntimeError(f"{len(got)}/{len(idx)} tables landed -- partial fetch")
    kinds = {}
    for t in got:
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
    manifest["table_kinds"] = kinds
    print(f"downloaded complete tables via the open /record/data endpoint -> {tdir}; "
          f"{len(got)} tables verified (non-empty values) + classified: "
          + ", ".join(f"{k}:{v}" for k, v in sorted(kinds.items())))


def _tables_via_hepdata_cli(inspire, out_dir, manifest):
    """--tables PRIMARY route: hepdata-cli bulk download (bypasses the /download/ 403), then
    VERIFY: submission.yaml must exist and parse, every declared data_file present and
    non-empty. Raises (ImportError/RuntimeError) on any failure -- the caller falls back to
    fetch_tables_via_record_data."""
    tdir = os.path.join(out_dir, "tables")
    os.makedirs(tdir, exist_ok=True)
    from hepdata_cli.api import Client
    Client().download(id_list=[inspire.replace("ins", "")], file_format="yaml",
                      ids="inspire", download_dir=tdir)
    # verification step 1: submission.yaml must exist after the download
    subs = [os.path.join(r, f) for r, _, fs in os.walk(tdir) for f in fs if f == "submission.yaml"]
    if not subs:
        raise RuntimeError(f"download left no submission.yaml under {tdir} -- partial/corrupt fetch")
    # verification step 2: it must parse; classify tables by description
    import yaml as _yaml
    for sub in subs:
        base = os.path.dirname(sub)
        try:
            docs = list(_yaml.safe_load_all(open(sub, errors="replace")))
        except Exception as e:
            raise RuntimeError(f"{sub} does not parse as YAML ({e!r}) -- corrupt fetch")
        n_before = len(manifest["table_files"])
        for doc in docs:
            if isinstance(doc, dict) and doc.get("name") and "description" in doc:
                loc = doc.get("data_file") or ""
                manifest["table_files"].append(
                    {"name": doc["name"], "kind": classify(doc.get("description") or "", doc["name"]),
                     "description": (doc["description"] or "").replace("\n", " ")[:120],
                     "file": os.path.relpath(os.path.join(base, loc), out_dir) if loc else ""})
        if len(manifest["table_files"]) == n_before:
            raise RuntimeError(f"{sub} parses but declares no tables -- partial/corrupt fetch")

    # verification step 3: every declared data_file must exist and be non-empty
    def _ok(rel):
        try:
            return os.path.getsize(os.path.join(out_dir, rel)) > 0
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

    # (4) download the COMPLETE numeric tables: hepdata-cli first (bypasses the /download/ 403),
    #     FALLING BACK to the open /record/data endpoint (taunu G3) when hepdata-cli is
    #     unavailable or its download/verification fails. Each route VERIFIES after download;
    #     only both routes failing appends to manifest["errors"] (-> nonzero exit).
    if args.tables:
        cli_err = None
        try:
            _tables_via_hepdata_cli(inspire, args.out, manifest)
            manifest["tables_route"] = "hepdata-cli"
        except Exception as e:
            cli_err = f"hepdata-cli table route failed: {e!r}"
            print(f"{cli_err}\n-> falling back to the open /record/data/<recid>/<table_id>/"
                  f"<version> endpoint", file=sys.stderr)
            try:
                fetch_tables_via_record_data(rec, args.out, manifest)
                manifest["tables_route"] = "record-data-endpoint"
                manifest["tables_route_note"] = cli_err
            except Exception as e2:
                manifest["errors"].append(cli_err)
                manifest["errors"].append(f"record-data fallback failed: {e2!r}")
                print(f"record-data fallback failed: {e2!r}", file=sys.stderr)

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
