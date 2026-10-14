#!/usr/bin/env python
"""Fetch a search's HEPData inputs for the fit, via the endpoints that are reachable.

Empirically (as tested; access policies can change):
  - the JSON API `/record/insNNNN?format=json` is OPEN -- it lists the record's data
    tables and its `record.resources` (the published likelihood + the SimpleAnalysis/
    SModelS/MadAnalysis reinterpretation hooks);
  - the per-table/bulk `/download/...` endpoints are Cloudflare-blocked (HTTP 403), so
    those URLs are NOT script-fetchable here;
  - BUT the resource endpoint `/record/resource/<id>?view=true` is OPEN, so a published
    likelihood archive IS programmatically downloadable (pyhf.contrib.utils.download);
  - AND the internal data endpoint `/record/data/<recid>/<table_id>/<version>` is OPEN
    and serves the full per-table content as JSON (recid + table ids + version all come
    from the open record JSON). Verified 2026-08-28: all 8 tables of ins1009 fetched
    this way while /download/table/... stayed 403.

So the data hierarchy this script supports: a published likelihood downloads directly
(no browser); the COMPLETE numeric tables download via hepdata-cli, falling back to the
open /record/data endpoint when hepdata-cli is unavailable or blocked. The Rivet routine
id encodes the Inspire id: SYN_9009_I1004 -> ins1004.

Integrity contract (no silent corruption): a --tables fetch is VERIFIED after download.
hepdata-cli route: submission.yaml must exist and parse, every declared data_file present
and non-empty. /record/data fallback route: EVERY table listed by the record JSON must
land, parse as JSON, and carry a non-empty values[] list. Both routes print the
table-type classification summary; any failed or partial fetch (API unreachable, download
error, missing/unparseable/empty content, requested likelihood not retrievable) prints a
loud error and exits NONZERO. Exit 0 means every requested artifact landed and verified.

Record lookup: requests go out as a plain HTTP client with `Accept: application/json`
(HEPData's bot filter answers 403 to browser-imitating agents). The record is fetched as
/record/ins<id>; when that fails, the HEPDATA identifiers INSPIRE lists for the paper are
tried (a numeric HEPData record id included). Exit 4 = definitive absence: the record API
served 404 and INSPIRE lists no HEPData record (manifest status ABSENT). Exit 1 = the service
was unreachable or a requested artifact did not land; that is not evidence of absence.

Usage:
  hepdata_fetch.py (--routine NAME | --inspire insNNNN) --out DIR [--download-likelihood] [--tables]
  hepdata_fetch.py --offline-fixture DIR --out DIR [--download-likelihood] [--tables]
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse, json, os, re, ssl, sys, urllib.request, urllib.error

from ravel.workflow import discovery_http

# Requests go out as a plain HTTP client asking for JSON (discovery_http): HEPData's bot
# filter answers 403 to browser-imitating agents. TLS is verified with certifi when present.
_VERIFIED_CTX = discovery_http.SSL_CONTEXT
EXIT_ABSENT = 4          # definitive: HEPData served 404 and INSPIRE lists no record


def _ssl_context():
    """The certifi-verified context when available, else the system default (None).
    Verification is never bypassed."""
    return _VERIFIED_CTX


def _open(url, timeout=30):
    return discovery_http.open_url(url, timeout=timeout)


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
    """--tables FALLBACK via the OPEN internal endpoint (observed 2026-08-28): where
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


def fetch_offline_fixture(fixture_dir, out_dir, *, tables=False, download_likelihood=False):
    """Copy a local record fixture without calling any acquisition transport.

    Layout: record.json, tables/<table-id>.json and likelihoods.json mapping
    resource URLs to lists of relative regular JSON model files. Missing or
    corrupt fixture data fails closed; there is no network fallback. Resources
    remain local files, so this route does not unpack remote archives.
    """
    from pathlib import Path
    from ravel.physics.published_model import _json
    from ravel.workflow.state_io import atomic_json
    import hashlib

    root = Path(fixture_dir).resolve()
    out = Path(out_dir).resolve()
    manifest = {'status':'ERROR', 'record_ref':None, 'tables':[], 'resources':[],
                'likelihoods':[], 'table_files':[], 'figure_index':{}, 'errors':[],
                'network_access':False, 'fixture_files':[]}

    def read(relative):
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise ValueError('fixture paths must be relative and contained: ' + str(relative))
        target = root / path
        if not target.resolve().is_relative_to(root) or any(p.is_symlink() for p in (target, *target.parents) if p != root.parent):
            raise ValueError('fixture path escapes or traverses a symlink: ' + str(relative))
        if not target.is_file() or target.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('fixture member missing or oversized: ' + str(relative))
        raw = target.read_bytes()
        doc = _json(raw)
        manifest['fixture_files'].append({'file':str(path), 'sha256':hashlib.sha256(raw).hexdigest()})
        return doc

    try:
        if out.is_relative_to(root):
            raise ValueError('offline output must be outside the fixture directory')
        rec = read('record.json')
        if not isinstance(rec, dict):
            raise ValueError('fixture record must be an object')
        recid, version, idx = record_data_index(rec)
        if len({tid for tid, name in idx}) != len(idx) or len({re.sub(r'\W+', '_', name).strip('_').lower() for tid,name in idx}) != len(idx):
            raise ValueError('fixture table ids and output names must be unique')
        manifest['record_ref'] = str(recid)
        manifest['version'] = version
        manifest['tables'] = rec['data_tables']
        resources = (rec.get('record') or {}).get('resources', []) + rec.get('resources', [])
        manifest['resources'] = resources
        manifest['likelihoods'] = [dict(r) for r in resources if any(
            key in (r.get('description','') + ' ' + r.get('file_type','')).lower()
            for key in ('likelihood','pyhf','histfactory','statistical model'))]
        # Validate every requested member before copying any artifact.
        pending = []
        if tables:
            if not (out / 'tables').resolve().is_relative_to(out) or (out / 'tables').is_symlink():
                raise ValueError('table output path escapes through symlink')
            served = {}
            for tid, name in idx:
                doc = read(f'tables/{tid}.json')
                if not isinstance(doc, dict) or not doc.get('values'):
                    raise ValueError(f'fixture table {name!r} has no values')
                served[f'https://www.hepdata.net/record/data/{recid}/{tid}/{version}'] = doc
            # This endpoint-shaped lookup serves only captured local bytes.
        if download_likelihood:
            if not manifest['likelihoods']:
                raise ValueError('fixture lists no requested likelihood')
            index = read('likelihoods.json')
            if not isinstance(index, dict):
                raise ValueError('fixture likelihoods.json must map resource URLs to model lists')
            for resource in manifest['likelihoods']:
                paths = index.get(resource['url'])
                if not isinstance(paths, list) or not paths:
                    raise ValueError('fixture likelihood member list missing: ' + resource['url'])
                for relative in paths:
                    if not isinstance(relative, str) or not relative.startswith('models/'):
                        raise ValueError('fixture likelihood path must be under models/')
                    pending.append((relative, read(relative)))
                resource['downloaded'] = list(paths)
        out.mkdir(parents=True, exist_ok=True)
        for relative, doc in pending:
            destination = out / relative
            if not destination.resolve().is_relative_to(out) or destination.is_symlink():
                raise ValueError('output path escapes through symlink')
            atomic_json(destination, doc)
        if tables:
            fetch_tables_via_record_data(rec, str(out), manifest, get_json_fn=served.__getitem__)
            manifest['tables_route'] = 'offline-fixture'
        manifest['status'] = 'OK'
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        manifest['errors'].append(str(exc))
    if out.is_relative_to(root):
        return manifest
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / 'hepdata_manifest.json', manifest)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--routine", help="Rivet routine name, e.g. SYN_9009_I1004")
    g.add_argument("--inspire", help="Inspire id, e.g. ins1004")
    g.add_argument("--offline-fixture", help="local record/tables/model fixture; never accesses the network")
    ap.add_argument("--offline", action="store_true", help="refuse acquisition unless --offline-fixture is supplied")
    ap.add_argument("--out", required=True)
    ap.add_argument("--download-likelihood", action="store_true",
                    help="download + extract any published likelihood via the open resource endpoint")
    ap.add_argument("--tables", action="store_true",
                    help="download the COMPLETE numeric tables (SR yields, cutflows, covariance) via hepdata-cli")
    args = ap.parse_args(argv)
    if args.offline and not args.offline_fixture:
        ap.error('--offline requires --offline-fixture; network acquisition is refused')
    if args.offline_fixture:
        manifest = fetch_offline_fixture(args.offline_fixture, args.out, tables=args.tables,
                                         download_likelihood=args.download_likelihood)
        if manifest['errors']:
            print('ERROR: offline fixture incomplete: ' + '; '.join(manifest['errors']), file=sys.stderr)
            sys.exit(1)
        return
    os.makedirs(args.out, exist_ok=True)

    inspire = args.inspire or inspire_from_routine(args.routine)
    if not inspire:
        sys.exit(f"could not derive Inspire id from '{args.routine}'")
    # HEPData record endpoints want the 'ins'-prefixed form; a bare numeric id is
    # silently treated as a HEPData record id and 404s.
    if re.fullmatch(r"\d+", str(inspire)):
        inspire = f"ins{inspire}"

    manifest = {"inspire": inspire, "routine": args.routine, "status": None, "record_ref": None,
                "tables": [], "resources": [],
                "likelihoods": [], "table_files": [], "bundled_note": None, "errors": []}

    # (1) note the source hierarchy
    if args.routine:
        manifest["bundled_note"] = (
            f"Source hierarchy: published likelihood downloads via the resource endpoint "
            f"(--download-likelihood); the COMPLETE numeric tables download via hepdata-cli "
            f"(--tables); Rivet's bundled REF is the offline counting-path copy when present.")

    # (2) discovery via the open JSON API: ins<id>, then any record id INSPIRE lists
    url = discovery_http.record_json_url(inspire)
    found = discovery_http.fetch_hepdata_record(inspire)
    manifest["lookup_attempts"] = found.get("attempts", [])
    if found["status"] != "OK":
        xcheck = found.get("inspire_xcheck") or {}
        absent = found["http_status"] == 404 and not xcheck.get("hepdata_listed")
        manifest["inspire_xcheck"] = xcheck
        if absent:
            manifest["status"] = "ABSENT"
            json.dump(manifest, open(os.path.join(args.out, "hepdata_manifest.json"), "w"), indent=2)
            corroborated = ("INSPIRE lists no HEPDATA id" if xcheck.get("status") == "OK"
                            else "INSPIRE corroboration unavailable")
            print(f"ABSENT: no HEPData record exists for {inspire} (the record API served 404; "
                  f"{corroborated}). Plan around absence; this is not an outage.", file=sys.stderr)
            sys.exit(EXIT_ABSENT)
        manifest["status"] = "ERROR"
        manifest["errors"].append(f"JSON API fetch failed: {found.get('reason')}")
        json.dump(manifest, open(os.path.join(args.out, "hepdata_manifest.json"), "w"), indent=2)
        print(f"ERROR: HEPData JSON API unreachable ({found.get('reason')}); wrote PARTIAL "
              f"manifest only. This is not evidence of absence. Fall back to Rivet bundled data, "
              f"or fetch via the browser: {url}", file=sys.stderr)
        sys.exit(1)
    rec = found["record"]
    manifest["status"] = "OK"
    manifest["record_ref"] = found["ref"]
    manifest["record_url"] = found["url"]

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
    # ranked figure candidates for the declared figure target (the [judgment] step chooses --
    # never auto).
    # table names come in BOTH styles: "Figure 16a Observed" AND
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
    #     FALLING BACK to the open /record/data endpoint when hepdata-cli is
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
