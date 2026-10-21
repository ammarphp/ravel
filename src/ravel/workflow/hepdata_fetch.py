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

import argparse, hashlib, json, os, re, ssl, sys, urllib.request, urllib.error
from contextlib import contextmanager
from pathlib import Path
import stat

from ravel.workflow import private_files, streaming_json

from ravel.workflow import discovery_http, acquisition_http
from ravel.workflow.restriction_guard import SourceRestricted, require as _require

def require(*args, **kwargs):
    """Retain early source-policy refusals in a governed acquisition scope."""
    try:
        return _require(*args, **kwargs)
    except Exception as exc:
        state = acquisition_http.current()
        if state is not None:
            state.remember(exc)
        raise


# Requests go out as a plain HTTP client asking for JSON (discovery_http): HEPData's bot
# filter answers 403 to browser-imitating agents. TLS is verified with certifi when present.
_VERIFIED_CTX = discovery_http.SSL_CONTEXT
EXIT_ABSENT = 4          # definitive: HEPData served 404 and INSPIRE lists no record


def _ssl_context():
    """The certifi-verified context when available, else the system default (None).
    Verification is never bypassed."""
    return _VERIFIED_CTX


def _open(url, timeout=30):
    require('hepdata_fetch', {'url': url})
    return discovery_http.open_url(url, timeout=timeout)


def inspire_from_routine(name):
    m = re.search(r"_I(\d+)$", name)
    return f"ins{m.group(1)}" if m else None


METADATA_BYTES = 16 << 20
MAX_FIXTURE_MEMBERS = 10000


def _get_json_bytes(url):
    """Bounded catalogue/record metadata; table payloads use the file stream path."""
    require('hepdata_fetch', {'url': url})
    raw = bytearray()
    with _open(url) as response:
        while chunk := response.read(min(streaming_json.CHUNK, METADATA_BYTES - len(raw) + 1)):
            raw.extend(chunk)
            if len(raw) > METADATA_BYTES:
                raise streaming_json.JSONRefused('json_metadata_limit', 'record metadata exceeds 16 MiB')
    raw = bytes(raw)
    return raw, json.loads(raw)


@contextmanager
def _ordinary(path):
    path = Path(path)
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('source path traverses a symbolic link: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('source must be an ordinary file without hard links: ' + str(path))
        yield source, before
        after = os.fstat(source.fileno())
    fields = ('st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink', 'st_mode')
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise ValueError('source changed while captured: ' + str(path))


class _Hashed:
    def __init__(self, source):
        self.source, self.digest, self.size = source, hashlib.sha256(), 0
    def read(self, size):
        raw = self.source.read(size)
        self.digest.update(raw)
        self.size += len(raw)
        return raw


def _pin_json(path):
    with _ordinary(path) as (source, info):
        reader = _Hashed(source)
        summary = streaming_json.summarize(reader)
    if reader.size != info.st_size:
        raise ValueError('source size changed while captured')
    return {'path': str(path), 'sha256': reader.digest.hexdigest(), 'size': reader.size}, summary


def _verify_pin(pin):
    with _ordinary(pin['path']) as (source, _):
        reader = _Hashed(source)
        while reader.read(streaming_json.CHUNK):
            pass
    if reader.size != pin['size'] or reader.digest.hexdigest() != pin['sha256']:
        raise ValueError('fixture source changed after validation: ' + pin['path'])


def _copy_pin(pin, destination):
    private_files.mkdir(Path(destination).parent)
    created = False
    try:
        with _ordinary(pin['path']) as (source, info):
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         stat.S_IMODE(info.st_mode) & 0o600)
            created = True
            reader = _Hashed(source)
            with os.fdopen(fd, 'wb') as target:
                while chunk := reader.read(streaming_json.CHUNK):
                    target.write(chunk)
        if reader.size != pin['size'] or reader.digest.hexdigest() != pin['sha256']:
            raise ValueError('fixture source changed after validation: ' + pin['path'])
    except BaseException:
        if created:
            Path(destination).unlink(missing_ok=True)
        raise


def _download_table(url, destination):
    """Retain the exact response in an exclusive private file, then validate all JSON."""
    private_files.mkdir(Path(destination).parent)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        digest = hashlib.sha256()
        with os.fdopen(fd, 'wb') as target, _open(url) as response:
            while chunk := response.read(streaming_json.CHUNK):
                digest.update(chunk)
                target.write(chunk)
        pin, summary = _pin_json(destination)
        if pin['sha256'] != digest.hexdigest():
            raise ValueError('downloaded table changed before validation')
        return pin['sha256'], summary
    except BaseException:
        Path(destination).unlink(missing_ok=True)
        raise


def _custom_json_bytes(document):
    """Only small supplied dictionaries use the compatibility serializer.

    Admit a conservative 16 MiB encoded-size bound before serializing; traversal
    retains only the active container identities and never another payload tree.
    """
    remaining, active = METADATA_BYTES, set()
    def visit(value, depth=0):
        nonlocal remaining
        if isinstance(value, str):
            remaining -= 6 * len(value) + 2
        elif value is None or isinstance(value, bool):
            remaining -= 5
        elif isinstance(value, int):
            if value.bit_length() > 13600:
                raise streaming_json.JSONRefused('json_number_limit', 'custom integer exceeds numeric token ceiling')
            remaining -= value.bit_length() // 3 + 3
        elif isinstance(value, float):
            remaining -= 32
        elif isinstance(value, (dict, list, tuple)):
            if depth >= streaming_json.MAX_DEPTH:
                raise streaming_json.JSONRefused('json_depth_limit', 'custom container nesting exceeds ceiling')
            identity = id(value)
            if identity in active:
                raise ValueError('circular custom JSON dictionary')
            active.add(identity)
            try:
                remaining -= 2 + 2 * len(value)
                if isinstance(value, dict):
                    for key, child in value.items():
                        visit(key, depth + 1)
                        remaining -= 2
                        visit(child, depth + 1)
                else:
                    for child in value:
                        visit(child, depth + 1)
            finally:
                active.remove(identity)
        else:
            raise TypeError('custom JSON dictionary contains an unsupported value')
        if remaining < 0:
            raise streaming_json.JSONRefused('json_metadata_limit', 'custom JSON encoded-size bound exceeds 16 MiB')
    visit(document)
    return json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8')


def _table_row(name, destination, out_dir, url, summary, digest, *, preserved):
    return {'name': name, 'kind': classify(summary['description'], name),
            'description': summary['description'].replace('\n', ' ')[:120],
            'file': os.path.relpath(destination, out_dir), 'endpoint': url, 'doi': summary['doi'],
            'output_sha256': digest, 'source_sha256': digest if preserved else None,
            'source_bytes_preserved': preserved}


def get_json(url):
    return _get_json_bytes(url)[1]


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
    require('hepdata_fetch', {'record': rec, 'identifiers': {'inspire': [manifest['inspire']]} if manifest.get('inspire') else {}}, output=out_dir)
    source_bytes_preserved = get_json_fn is None
    recid, version, idx = record_data_index(rec)
    tdir = os.path.join(out_dir, "tables")
    private_files.mkdir(tdir)
    n_before = len(manifest["table_files"])
    for tid, name in idx:
        url = f"https://www.hepdata.net/record/data/{recid}/{tid}/{version}"
        slug = re.sub(r"\W+", "_", name).strip("_").lower()
        if not slug:
            raise ValueError('table name produces an empty output filename')
        dest = os.path.join(tdir, f"{slug}_data.json")
        created = False
        try:
            if source_bytes_preserved:
                output_sha256, summary = _download_table(url, dest)
                created = True
            else:
                doc = get_json_fn(url)
                raw = _custom_json_bytes(doc)
                import io
                summary = streaming_json.summarize(io.BytesIO(raw))
                output_sha256 = hashlib.sha256(raw).hexdigest()
                private_files.write(dest, raw, exclusive=True)
                created = True
            if not summary['object'] or not summary['values_nonempty']:
                raise RuntimeError(f"table {name!r} ({url}) returned no values[] -- partial/corrupt fetch")
        except Exception as exc:
            if created:
                Path(dest).unlink(missing_ok=True)
            raise RuntimeError(f"table {name!r} ({url}) failed to download/validate ({exc!r}) -- partial fetch") from exc
        manifest['table_files'].append(_table_row(name, dest, out_dir, url, summary, output_sha256,
                                                   preserved=source_bytes_preserved))
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
    require('hepdata_fetch', {'identifiers': {'inspire': [inspire if str(inspire).startswith('ins') else 'ins' + str(inspire)]}}, output=out_dir)
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
    """Validate every requested local JSON member before copying exact source bytes.

    Only bounded record/index metadata is parsed into Python objects. Payloads are
    streamed through the strict validator, retained as path/digest/size pins, and
    reverified before and during private copying. No network fallback is permitted.
    """
    require('hepdata_fetch', {'path': str(fixture_dir), 'identity_unresolved': True}, output=out_dir)
    from ravel.physics.published_model import _json
    from ravel.workflow.state_io import atomic_json

    original = Path(fixture_dir).absolute()
    root = original.resolve()
    out_original = Path(out_dir).absolute()
    out = out_original.resolve()
    manifest = {'status': 'ERROR', 'record_ref': None, 'tables': [], 'resources': [],
                'likelihoods': [], 'table_files': [], 'figure_index': {}, 'errors': [],
                'network_access': False, 'fixture_files': []}
    pins, seen_files = [], set()

    def locate(relative):
        if (type(relative) is not str or not relative or '\\' in relative
                or any(part in ('', '.', '..') for part in relative.split('/'))
                or any(ord(char) < 32 for char in relative)):
            raise ValueError('fixture paths must be relative and contained: ' + str(relative))
        path = Path(relative)
        if path.is_absolute() or not path.parts:
            raise ValueError('fixture paths must be relative and contained: ' + relative)
        target = root / path
        if not target.resolve().is_relative_to(root) or any(part.is_symlink() for part in (target, *target.parents)):
            raise ValueError('fixture path escapes or traverses a symlink: ' + relative)
        require('hepdata_fetch', {'path': str(target)}, output=out_dir)
        return target

    def remember(relative, pin):
        if len(pins) >= MAX_FIXTURE_MEMBERS:
            raise streaming_json.JSONRefused('fixture_member_limit', 'offline fixture exceeds 10000 members')
        if relative in seen_files:
            raise ValueError('fixture member is declared more than once: ' + relative)
        seen_files.add(relative)
        pins.append(pin)
        manifest['fixture_files'].append({'file': relative, 'sha256': pin['sha256']})

    def metadata(relative):
        target = locate(relative)
        with _ordinary(target) as (source, info):
            raw = source.read(METADATA_BYTES + 1)
        if len(raw) > METADATA_BYTES:
            raise streaming_json.JSONRefused('json_metadata_limit', 'fixture metadata exceeds 16 MiB')
        doc = _json(raw)
        remember(relative, {'path': str(target), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
        return doc

    def payload(relative):
        target = locate(relative)
        pin, summary = _pin_json(target)
        remember(relative, pin)
        return pin, summary

    try:
        if any(part.is_symlink() for part in (original, *original.parents)):
            raise ValueError('fixture root traverses a symbolic link')
        if any(part.is_symlink() for part in (out_original, *out_original.parents)):
            raise ValueError('output path escapes through symlink')
        if out.is_relative_to(root):
            raise ValueError('offline output must be outside the fixture directory')
        rec = metadata('record.json')
        if not isinstance(rec, dict):
            raise ValueError('fixture record must be an object')
        recid, version, idx = record_data_index(rec)
        slugs = [re.sub(r'\W+', '_', name).strip('_').lower() for tid, name in idx]
        if (len({tid for tid, name in idx}) != len(idx) or len(set(slugs)) != len(idx) or '' in slugs):
            raise ValueError('fixture table ids and output names must be unique and nonempty')
        manifest['record_ref'], manifest['version'] = str(recid), version
        manifest['tables'] = rec['data_tables']
        resources = (rec.get('record') or {}).get('resources', []) + rec.get('resources', [])
        manifest['resources'] = resources
        manifest['likelihoods'] = [dict(row) for row in resources if any(
            key in (row.get('description', '') + ' ' + row.get('file_type', '')).lower()
            for key in ('likelihood', 'pyhf', 'histfactory', 'statistical model'))]
        pending, table_rows = [], []
        if tables:
            for (tid, name), slug in zip(idx, slugs):
                pin, summary = payload(f'tables/{tid}.json')
                if not summary['object'] or not summary['values_nonempty']:
                    raise ValueError(f'fixture table {name!r} has no values')
                destination = out / 'tables' / (slug + '_data.json')
                pending.append((pin, destination))
                url = f'https://www.hepdata.net/record/data/{recid}/{tid}/{version}'
                table_rows.append(_table_row(name, destination, out, url, summary, pin['sha256'], preserved=True))
        if download_likelihood:
            if not manifest['likelihoods']:
                raise ValueError('fixture lists no requested likelihood')
            index = metadata('likelihoods.json')
            if not isinstance(index, dict):
                raise ValueError('fixture likelihoods.json must map resource URLs to model lists')
            for resource in manifest['likelihoods']:
                paths = index.get(resource['url'])
                if not isinstance(paths, list) or not paths:
                    raise ValueError('fixture likelihood member list missing: ' + resource['url'])
                for relative in paths:
                    if not isinstance(relative, str) or not relative.startswith('models/'):
                        raise ValueError('fixture likelihood path must be under models/')
                    pin, _ = payload(relative)
                    pending.append((pin, out / relative))
                resource['downloaded'] = list(paths)
        # Recheck every source pin before creating the first artifact, including metadata.
        for pin in pins:
            _verify_pin(pin)
        for pin, destination in pending:
            if not destination.resolve().is_relative_to(out) or any(part.is_symlink() for part in (destination, *destination.parents)):
                raise ValueError('output path escapes through symlink')
            if destination.exists():
                raise ValueError('offline output destination already exists: ' + str(destination))
        private_files.mkdir(out)
        for pin, destination in pending:
            _copy_pin(pin, destination)
        if tables:
            manifest['table_files'] = table_rows
            kinds = {}
            for row in table_rows:
                kinds[row['kind']] = kinds.get(row['kind'], 0) + 1
            manifest['table_kinds'] = kinds
            manifest['tables_route'] = 'offline-fixture'
        manifest['status'] = 'OK'
    except SourceRestricted:
        raise
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        manifest['errors'].append(str(exc))
    if out.is_relative_to(root):
        return manifest
    # Preserve the typed error manifest without following an unsafe output alias.
    if any(part.is_symlink() for part in (out_original, *out_original.parents)):
        return manifest
    private_files.mkdir(out)
    atomic_json(out / 'hepdata_manifest.json', manifest)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--routine", help="Rivet routine name, e.g. SYN_9009_I1004")
    g.add_argument("--inspire", help="Inspire id, e.g. ins1004")
    g.add_argument("--offline-fixture", help="local record/tables/model fixture; never accesses the network")
    ap.add_argument("--offline", action="store_true", help="require a local fixture or mirror")
    ap.add_argument("--offline-mirror", help="local source mirror directory (requires --inspire)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--download-likelihood", action="store_true",
                    help="download + extract any published likelihood via the open resource endpoint")
    ap.add_argument("--tables", action="store_true",
                    help="download the COMPLETE numeric tables (SR yields, cutflows, covariance) via hepdata-cli")
    args = ap.parse_args(argv)
    if args.offline_mirror and not args.inspire:
        ap.error('--offline-mirror requires --inspire')
    mirror_record = None
    if args.offline_mirror:
        from pathlib import Path
        try:
            digits = discovery_http.inspire_digits(args.inspire)
        except ValueError as exc:
            ap.error(str(exc))
        mirror_record = Path(args.offline_mirror).resolve() / 'hepdata' / ('ins' + digits)
    local_record = str(mirror_record) if mirror_record is not None else args.offline_fixture
    identity = args.inspire or inspire_from_routine(args.routine or '')
    # Without --tables or --download-likelihood the online route reads record metadata only.
    scope = {} if args.tables or args.download_likelihood else {'classes': ['public-metadata'], 'quantities': ['text']}
    require('hepdata_fetch', {'path': local_record, 'identity_unresolved': True} if local_record else
            {'identifiers': {'inspire': [identity if str(identity).startswith('ins') else 'ins' + str(identity)]}, **scope},
            output=args.out)
    if args.offline and not local_record:
        ap.error('--offline requires --offline-fixture or --offline-mirror; network acquisition is refused')
    if mirror_record is not None and not mirror_record.is_dir():
        print('ERROR: offline mirror has no record for ins' + digits, file=sys.stderr)
        sys.exit(1)
    if local_record:
        manifest = fetch_offline_fixture(local_record, args.out, tables=args.tables,
                                         download_likelihood=args.download_likelihood)
        if mirror_record is not None:
            from ravel.workflow.state_io import atomic_json
            manifest['source'] = 'local-mirror'
            manifest['network_access'] = False
            if not Path(args.out).resolve().is_relative_to(mirror_record.resolve()):
                atomic_json(Path(args.out) / 'hepdata_manifest.json', manifest)
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
            if acquisition_http.current() is None:
                import pyhf.contrib.utils as _U  # legacy ungoverned client
                download = lambda url, output: _U.download(url, output, force=True)
            else:
                download = acquisition_http.download_archive
            for lk in manifest["likelihoods"]:
                try:
                    download(lk["download_url"], args.out)
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
            if acquisition_http.current() is not None:
                fetch_tables_via_record_data(rec, args.out, manifest)
                manifest["tables_route"] = "record-data-endpoint"
            else:
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
