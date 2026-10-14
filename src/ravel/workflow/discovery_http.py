"""HTTP access to the public discovery services (HEPData, INSPIRE, arXiv, Zenodo).

HEPData sits behind a bot filter that answers 403 to browser-imitating and custom
User-Agents while serving plain HTTP clients normally (observed 2026-10-10: a
`curl`/`python-requests` agent with `Accept: application/json` receives the record JSON).
Requests here therefore identify as a plain client and ask for JSON. A 403 is retried once
per remaining client agent; any other status is returned to the caller unchanged, so a served
404 stays a definitive absence and a 5xx stays an outage.

TLS is always verified (certifi when available, else the system store).
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

CLIENT_AGENTS = ("ravel-hep python-requests/2.32", "ravel-hep curl/8.7")
JSON = "application/json"
HEPDATA = "https://www.hepdata.net"
INSPIRE = "https://inspirehep.net/api/literature"

try:
    import certifi as _certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=_certifi.where())
except Exception:                                   # no certifi: the system default store
    SSL_CONTEXT = None

_urlopen = urllib.request.urlopen                   # replaced by recorded responses in tests


def open_url(url, *, accept=JSON, timeout=30):
    """Open `url` as a plain client; a 403 is retried with the next client agent."""
    blocked = None
    for agent in CLIENT_AGENTS:
        req = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": accept})
        try:
            return _urlopen(req, timeout=timeout, context=SSL_CONTEXT)
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
            blocked = e
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
                raise RuntimeError(
                    "TLS verification failed under this Python (no CA bundle). Install certifi "
                    "in this environment or run under one that has it. Verification is never "
                    "bypassed.") from e
            raise
    raise blocked


def get_json(url, timeout=30):
    with open_url(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def inspire_digits(inspire_id):
    """The numeric INSPIRE id from "ins1012" or "1234567"."""
    m = re.fullmatch(r"(?:ins)?(\d+)", str(inspire_id).strip(), re.I)
    if not m:
        raise ValueError(f"not an INSPIRE id: {inspire_id!r}")
    return m.group(1)


def record_json_url(ref):
    """`ref` is 'ins<INSPIRE id>' or a numeric HEPData record id."""
    return f"{HEPDATA}/record/{ref}?format=json"


def inspire_hepdata_ids(inspire_id, get=None):
    """INSPIRE's external HEPDATA identifiers for a paper (the independent registry of which
    papers have a HEPData record, and under which id)."""
    get = get or get_json
    try:
        rec = get(f"{INSPIRE}/{inspire_digits(inspire_id)}?fields=external_system_identifiers")
        ids = (rec.get("metadata") or {}).get("external_system_identifiers") or []
        hep = [i for i in ids if str(i.get("schema", "")).upper() == "HEPDATA"]
        return {"status": "OK", "hepdata_listed": bool(hep), "ids": hep}
    except Exception as e:
        return {"status": "ERROR", "reason": f"{type(e).__name__}: {e}"[:200]}


def _alternate_refs(xcheck, primary):
    refs = []
    for item in (xcheck or {}).get("ids") or []:
        value = str(item.get("value", "")).strip()
        if re.fullmatch(r"\d+", value):
            ref = value                                  # a HEPData record id
        elif re.fullmatch(r"ins\d+", value, re.I):
            ref = value.lower()
        else:
            continue
        if ref != primary and ref not in refs:
            refs.append(ref)
    return refs


def fetch_hepdata_record(inspire_id, get=None):
    """Fetch a HEPData record JSON for an INSPIRE paper.

    Tries /record/ins<id>; when that fails, asks INSPIRE for the paper's HEPDATA identifiers
    and retries each listed numeric record id (or differing ins id). Returns
    {"status": "OK", "record", "url", "ref", "resolved_via", "attempts"} or
    {"status": "FAILED", "http_status" (of the ins<id> request, None for network trouble),
     "reason", "inspire_xcheck", "attempts"}.
    """
    get = get or get_json
    primary = "ins" + inspire_digits(inspire_id)
    attempts = []

    def attempt(ref):
        url = record_json_url(ref)
        try:
            return get(url), url
        except urllib.error.HTTPError as e:
            attempts.append({"url": url, "http_status": e.code})
        except Exception as e:
            attempts.append({"url": url, "http_status": None,
                             "reason": f"{type(e).__name__}: {e}"[:300]})
        return None, url

    rec, url = attempt(primary)
    if rec is not None:
        return {"status": "OK", "record": rec, "url": url, "ref": primary,
                "resolved_via": "inspire-id", "attempts": attempts}
    first = attempts[0]
    xcheck = inspire_hepdata_ids(primary, get=get)
    for ref in _alternate_refs(xcheck, primary):
        rec, url = attempt(ref)
        if rec is not None:
            return {"status": "OK", "record": rec, "url": url, "ref": ref,
                    "resolved_via": "inspire-hepdata-id", "attempts": attempts,
                    "inspire_xcheck": xcheck}
    return {"status": "FAILED", "http_status": first["http_status"],
            "reason": first.get("reason") or f"HTTP {first['http_status']}",
            "inspire_xcheck": xcheck, "attempts": attempts}


def search_hepdata(query, size=10, get=None):
    """HEPData full-text search -> compact hits."""
    get = get or get_json
    url = (f"{HEPDATA}/search/?q={urllib.parse.quote(query)}&format=json&size={int(size)}")
    doc = get(url)
    hits = []
    for r in doc.get("results") or []:
        arxiv = re.sub(r"(?i)^arxiv:", "", str(r.get("arxiv_id") or "")) or None
        hits.append({"inspire": str(r.get("inspire_id") or "") or None,
                     "hepdata_recid": r.get("recid"), "title": (r.get("title") or "")[:200],
                     "arxiv": arxiv, "collaborations": list(r.get("collaborations") or []),
                     "n_tables": r.get("total_tables"),
                     "analyses": [a.get("analysis") for a in (r.get("analyses") or [])
                                  if isinstance(a, dict)]})
    return {"status": "OK", "url": url, "total": doc.get("total"), "hits": hits}


# A report number in the general analysis-code shape: an optional prefix, a group code, a two- or
# four-digit year field and a number. A prefixed code counts only when its prefix is one of the
# record's own collaborations, so laboratory preprint numbers of the same shape are not analysis codes.
ANALYSIS_CODE = re.compile(r"^(?:([A-Za-z][A-Za-z0-9]*)-)?(?:PAS-)?[A-Z][A-Z0-9]*-(?:\d{2}|\d{4})-\d+[A-Z]?$")


def analysis_codes(report_numbers, collaborations):
    """The report numbers that are analysis codes of the record's collaborations."""
    own = {str(c).casefold() for c in collaborations}
    codes = []
    for value in report_numbers:
        match = ANALYSIS_CODE.match(str(value))
        if match and (match.group(1) is None or match.group(1).casefold() in own):
            codes.append(value)
    return codes


def search_inspire(query, size=10, get=None):
    """INSPIRE literature search -> compact hits with analysis codes from report numbers."""
    get = get or get_json
    url = (f"{INSPIRE}?q={urllib.parse.quote(query)}&size={int(size)}"
           "&fields=control_number,titles,arxiv_eprints,report_numbers,collaborations")
    doc = get(url)
    hits = []
    for h in (doc.get("hits") or {}).get("hits") or []:
        md = h.get("metadata") or {}
        codes = analysis_codes([r.get("value", "") for r in md.get("report_numbers") or []],
                               [c.get("value") for c in md.get("collaborations") or []])
        hits.append({"inspire": str(md.get("control_number") or h.get("id") or "") or None,
                     "title": ((md.get("titles") or [{}])[0].get("title") or "")[:200],
                     "arxiv": next((e.get("value") for e in md.get("arxiv_eprints") or []), None),
                     "analysis_ids": codes,
                     "collaborations": [c.get("value") for c in md.get("collaborations") or []]})
    return {"status": "OK", "url": url,
            "total": (doc.get("hits") or {}).get("total"), "hits": hits}
