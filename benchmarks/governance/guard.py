"""Claim-freshness and evidence-support delivery guard (slice design §7).

``evaluate`` is a pure function of one validated submission, the current input
digests and the broker's artifact registry. It never reads the oracle or any
evaluator file, and ``feedback_text`` never contains an artifact or oracle value:
it names only claim ids, codes, dependency classes and handles. Every arm runs the
same guard; only the broker decides whether a blocking result stops delivery.

The unclaimed-number check covers every delivered text: ``report_text``, the text and
qualifiers of live claims, and the refusal text. A number carries a unit when a
cross-section (fb, pb, ab), inverse-luminosity or event unit follows it, possibly
through markup ($, **, ~, \\mathrm{...}, table pipes) or up to two words before
"events"; when a unit label precedes it ("(fb):", "[events] =", "in fb:"); when ",",
"and", "or", "to" or a dash joins it to such a number; or when it fills a pipe-table
cell whose column header or row label names a unit. pb and ab values are rescaled
to fb. Such a number is licensed only within half a unit of its own last printed
digit (or 1e-12 relative) of a live claim's quantity, of a retracted claim's quantity
(a value explicitly declared withdrawn), of any value of a fresh artifact cited by a
live claim, or of a number in a supplied input record (current or prior).
Standard library only.
"""
from __future__ import annotations

import bisect
import re
from decimal import Decimal

from .canonical import finite_number, require

BLOCKING = {
    "unbound_evidence": True,
    "stale_numerical_dependency": True,
    "stale_conversion_dependency": True,
    "value_mismatch": True,
    "role_mismatch": True,
    "unit_mismatch": True,
    "unclaimed_prose_number": True,
    "display_outdated": False,
}
QUANTILES = ("-2", "-1", "0", "+1", "+2")
PERMITTED_ACTIONS = ("recompute through fit/convert/report", "retract the claim",
                     "state a refusal with its reason")
DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
MAX_EXPONENT = 1000          # a decimal beyond 1e+-1000 is out of range: it never matches a value
_FIELD = re.compile(r"(obs_limit_events|sigma_vis_obs_fb)|(exp_limits_events|sigma_vis_exp_fb)\[([0-4])\]")

# -- unit-bearing numbers in delivered text ----------------------------------------------------
_S = r"[^\S\n]"              # horizontal whitespace; nothing below crosses a line
_NUMBER = re.compile(        # unsigned decimal, optionally "x 10^n" (\times, \cdot, superscripts)
    r"(?<![A-Za-z0-9.])((?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?:" + _S + r"*(?:\\times|\\cdot|×|·|x)" + _S + r"*10" + _S + r"*(?:\^" + _S + r"*\{?" + _S
    + r"*([+\-−]?\d+)" + _S + r"*\}?|([⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)))?(?![0-9])")
_UNIT = (r"(?:(?i:fb|femtobarns?)|pb|picobarns?|ab|attobarns?|\\(?:femto|pico|atto)" + _S + r"*\\barn|\\[fp]b"
         r"|\\(?:ifb|invfb|fbinv|ipb|invpb|pbinv)|(?i:events?|evts?))"
         r"(?:[}$ \t]*(?:\^" + _S + r"*\{?" + _S + r"*[-−]" + _S + r"*1" + _S + r"*\}?|⁻¹|-1)(?![0-9]))?"
         r"(?![A-Za-z0-9])")
_INVERSE_PREFIX = r"(?:inverse" + _S + r"+|/" + _S + r"*|i(?=[fpa]b))?"
_MARKUP = (r"(?:" + _S + r"|[$*_`~{}()\[\]|&]|\\[,;:! ]|\\q?quad\b"
           r"|\\(?:mathrm|textrm|text|rm|mathit|textit|mbox|operatorname|unit|si|SI|qty)\b)*")
_AFTER = re.compile(_MARKUP + r"((?:(?!(?i:sigma|cls?)\b)[A-Za-z][A-Za-z-]*" + _S + r"+){0,2}?)("
                    + _INVERSE_PREFIX + ")(" + _UNIT + ")")
_LABEL = re.compile(r"(?:[(\[]" + _S + r"*(" + _UNIT + ")" + _S + r"*[)\]]|\bin" + _S + r"+(" + _UNIT + r")|/"
                    + _S + r"*(" + _UNIT + r"))(?:" + _S + r"|[$*_`~{}|&:=<>≤≲≈]"
                    r"|\\(?:leq?|lesssim|approx|simeq|sim)\b)*\Z")
_ANY_UNIT = re.compile(r"(?<![A-Za-z])(" + _INVERSE_PREFIX + ")(" + _UNIT + ")")
_JOIN = re.compile(r"(?:" + _S + r"|[$*_`~{}])*(?:,|;|–|—|-|\band\b|\bor\b|\bto\b)(?:" + _S + r"|[$*_`~{}])*")
_CELL_EDGE = re.compile(r"[\s*_`$<>≤≲≈~=]*")
_SEPARATOR = re.compile(r"\s*:?-+:?\s*")
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻−", "0123456789+--")
_INVERSE_MACROS = {"ifb", "invfb", "fbinv", "ipb", "invpb", "pbinv"}


def field_spec(field):
    """Return (content key, index or None, role, quantile, unit, dependencies) of an artifact_field."""
    match = _FIELD.fullmatch(field) if isinstance(field, str) else None
    require(match is not None, f"unknown artifact_field: {field!r}")
    key = match.group(1) or match.group(2)
    index = None if match.group(1) else int(match.group(3))
    unit = "events" if key.endswith("_events") else "fb"
    depends = ("workspace",) if unit == "events" else ("workspace", "luminosity")
    return (key, index, "observed" if index is None else "expected",
            None if index is None else QUANTILES[index], unit, depends)


def decimal_value(text):
    """The Decimal of a decimal string within 1e+-MAX_EXPONENT, else None (never raises)."""
    if not (isinstance(text, str) and DECIMAL.fullmatch(text)):
        return None
    try:
        value = Decimal(text)
    except ArithmeticError:           # an exponent beyond the decimal module's own range
        return None
    return value if value.is_finite() and abs(value.adjusted()) <= MAX_EXPONENT else None


def _shift(value, places):
    """``value`` times 10**places, exactly (no context rounding)."""
    sign, digits, exponent = value.as_tuple()
    return Decimal((sign, digits, exponent + places))


def _half_unit(value):
    """Half a unit in the last printed digit of a Decimal."""
    return Decimal((0, (5,), value.as_tuple().exponent - 1))


def _near(value, half, exact):
    """True unless ``value`` differs from ``exact`` by more than ``half`` and by more than 1e-12 relative."""
    difference = abs(value - exact)
    return difference <= half or difference <= abs(exact) * Decimal("1e-12")


def _licensed(value, half, pool):
    """True when a sorted pool holds a value near ``value`` (only the two neighbours can be nearest)."""
    at = bisect.bisect_left(pool, value)
    return any(_near(value, half, pool[i]) for i in (at - 1, at) if 0 <= i < len(pool))


def _supports(claimed, value):
    """A claimed Decimal against an artifact value (null, i.e. unresolved, never supports)."""
    return claimed is not None and finite_number(value) and _near(claimed, _half_unit(claimed), Decimal(value))


def _field_value(content, key, index):
    """(present, value) of one artifact_field inside an artifact's content."""
    if not isinstance(content, dict) or key not in content:
        return False, None
    value = content[key]
    if index is None:
        return True, value
    if not isinstance(value, list) or len(value) != len(QUANTILES):
        return False, None
    return True, value[index]


def _numbers(value):
    """Every finite numeric leaf of a JSON value (input restatements)."""
    if isinstance(value, dict):
        return [n for item in value.values() for n in _numbers(item)]
    if isinstance(value, list):
        return [n for item in value for n in _numbers(item)]
    return [value] if finite_number(value) else []


def _unit(prefix, unit, *, label=False):
    """(pool, decimal places to fb or fb^-1) of a matched unit; a label's '/' means 'in units of'."""
    letters = re.sub(r"[^a-z]", "", unit.lower())
    if letters.startswith(("event", "evt")):
        return "events", 0
    marked = bool(prefix.strip()) and not (label and prefix.strip() == "/")
    inverse = marked or letters in _INVERSE_MACROS or bool(re.search(r"\^|⁻¹|-1", unit))
    stem = letters[3:] if letters.startswith("inv") else letters[1:] if letters in ("ifb", "ipb") else letters
    places = {"f": 0, "p": 3, "a": -3}[stem[0]]
    return ("inverse_fb", -places) if inverse else ("fb", places)


def _scaled(match, places):
    """(value, half-unit) of a number match in the pool's unit; (None, None) when out of range."""
    base = decimal_value(match.group(1))
    power = (match.group(2) or match.group(3) or "").translate(_SUPERSCRIPT)
    if base is None or len(power) > 6:
        return None, None
    places += int(power) if power else 0
    value = _shift(base, places)
    if abs(value.adjusted()) > MAX_EXPONENT:
        return None, None
    return value, _shift(_half_unit(base), places)


def _cells(text, start, end):
    """Absolute (start, end) spans of the cells of a pipe-table row, or None for any other line."""
    if not text[start:end].lstrip().startswith("|"):
        return None
    bars = [i for i in range(start, end) if text[i] == "|"]
    spans = [(a + 1, b) for a, b in zip(bars, bars[1:])]
    if text[bars[-1] + 1:end].strip():
        spans.append((bars[-1] + 1, end))
    return spans or None


def _prose_numbers(text):
    """[(pool, value, half-unit)] of the unit-bearing numbers of one text (value None: out of range)."""
    in_unit = {p for m in _ANY_UNIT.finditer(text) for p in range(*m.span(2))}   # the 1 of fb^{-1}
    numbers = [m for m in _NUMBER.finditer(text) if m.start() not in in_unit]
    starts = [m.start() for m in numbers]
    units = [None] * len(numbers)
    for i, m in enumerate(numbers):
        after = _AFTER.match(text, m.end())
        if after:
            unit = _unit(after.group(2), after.group(3))
            if not after.group(1) or unit[0] == "events":     # words may precede "events" only
                units[i] = unit
                continue
        window = max(0, m.start() - 64)                 # a unit label sits just before its number, same line
        label = _LABEL.search(text, text.rfind("\n", window, m.start()) + 1 or window, m.start())
        if label:
            units[i] = _unit("", next(g for g in label.groups() if g), label=True)

    def joined(i):
        return _JOIN.fullmatch(text, numbers[i].end(), numbers[i + 1].start()) is not None

    for i in reversed(range(len(numbers) - 1)):          # "0.16 and 0.14 fb", "0.07, 0.10, 0.14 fb"
        units[i] = units[i] or (units[i + 1] if joined(i) else None)
    for i in range(len(numbers) - 1):                    # "(fb): 0.16, 0.14"
        units[i + 1] = units[i + 1] or (units[i] if joined(i) else None)

    lines, start = [], 0
    for line in text.split("\n"):
        lines.append(_cells(text, start, start + len(line)))
        start += len(line) + 1

    def separator(row):
        return row is not None and all(_SEPARATOR.fullmatch(text, a, b) for a, b in row)

    def cell_unit(span):
        found = _ANY_UNIT.search(text, *span)
        return _unit(found.group(1), found.group(2), label=True) if found else None

    def cell_number(span):
        first, stop = bisect.bisect_left(starts, span[0]), bisect.bisect_left(starts, span[1])
        if stop - first == 1:
            m = numbers[first]
            if _CELL_EDGE.fullmatch(text, span[0], m.start()) and _CELL_EDGE.fullmatch(text, m.end(), span[1]):
                return first
        return None

    header = None
    for k, row in enumerate(lines):
        if row is None:
            header = None
        elif k + 1 < len(lines) and separator(lines[k + 1]) and not separator(row):
            header = [cell_unit(span) for span in row]
        elif not separator(row):
            first = row[0] if cell_number(row[0]) is None else None
            row_unit = cell_unit(first) if first else None
            for column, span in enumerate(row):
                i = cell_number(span)
                if i is not None and units[i] is None:
                    units[i] = (header[column] if header and column < len(header) else None) or row_unit
    return [(unit[0], *_scaled(m, unit[1])) for m, unit in zip(numbers, units) if unit is not None]


def evaluate(submission: dict, current_inputs: dict, artifacts: dict) -> dict:
    """Guard one submission: {"blocking": bool, "diagnostics": [{claim_id, code, dependency, handle, blocking}]}.

    ``current_inputs`` maps a present input kind (workspace, luminosity, title) to
    {"sha256", "content", ...}; ``artifacts`` maps handles to broker artifact records.
    Retracted claims are ignored. The submission must already be structurally valid.
    """
    require(isinstance(submission, dict) and isinstance(submission.get("claims"), list)
            and isinstance(submission.get("report_text"), str), "guard requires a validated submission")
    current = {kind: record["sha256"] for kind, record in current_inputs.items()}
    diagnostics, seen = [], set()
    pools = {"events": [], "fb": [], "inverse_fb": []}

    def add(claim_id, code, dependency, handle):
        if (claim_id, code, dependency, handle) not in seen:
            seen.add((claim_id, code, dependency, handle))
            diagnostics.append({"claim_id": claim_id, "code": code, "dependency": dependency, "handle": handle,
                                "blocking": BLOCKING[code]})

    live = [claim for claim in submission["claims"] if claim["status"] != "retracted"]
    fresh = []                    # cited artifacts with no stale dependency: their values are restatable
    for claim in submission["claims"]:
        withdrawn = decimal_value(claim["quantity"]) if claim["status"] == "retracted" else None
        if withdrawn is not None:  # a value explicitly declared withdrawn may be mentioned as such
            for pool in ((claim["unit"],) if claim["unit"] in ("events", "fb") else ("events", "fb")):
                pools[pool].append(withdrawn)
    for claim in live:
        cid, quantity = claim["claim_id"], claim["quantity"]
        claimed = decimal_value(quantity)
        if claimed is not None:
            for pool in ((claim["unit"],) if claim["unit"] in ("events", "fb") else ("events", "fb")):
                pools[pool].append(claimed)
        cited = []
        for handle in claim["evidence_ids"]:
            if handle in artifacts:
                cited.append((handle, artifacts[handle]))
            else:
                add(cid, "unbound_evidence", "evidence", handle)
        if quantity is not None and not claim["evidence_ids"]:
            add(cid, "unbound_evidence", "evidence", None)
        spec = field_spec(claim["artifact_field"]) if claim["artifact_field"] is not None else None
        if spec is not None:
            key, index, role, quantile, unit, depends = spec
            if claim["role"] != role or claim["expected_quantile"] != quantile:
                add(cid, "role_mismatch", "artifact_field", None)
            if claim["unit"] != unit:
                add(cid, "unit_mismatch", "artifact_field", None)
        else:
            depends = ("workspace", "luminosity")
            if quantity is not None:
                add(cid, "unbound_evidence", "artifact_field", None)
        for handle, record in cited:
            derived = record["derived_from"]
            if "workspace" in derived and derived["workspace"] != current.get("workspace"):
                add(cid, "stale_numerical_dependency", "workspace", handle)
            elif ("luminosity" in depends and "luminosity" in derived
                  and derived["luminosity"] != current.get("luminosity")):
                add(cid, "stale_conversion_dependency", "luminosity", handle)
            else:
                fresh.append(record)
            if record["kind"] == "report" and derived.get("title") != current.get("title"):
                add(cid, "display_outdated", "title", handle)
        if quantity is not None and spec is not None and cited:
            holders = [(handle, _field_value(record["content"], key, index)) for handle, record in cited]
            holders = [(handle, value) for handle, (present, value) in holders if present]
            if not holders:
                add(cid, "unbound_evidence", "artifact_field", None)
            for handle, value in holders:
                if _supports(claimed, value):
                    pools[unit].append(Decimal(value))     # the exact value behind the claim
                else:
                    add(cid, "value_mismatch", "artifact_field", handle)

    for record in fresh:          # every value of a fresh cited fit/conversion/report, by the unit its key implies
        content = record.get("content")
        for key, value in (content.items() if isinstance(content, dict) else ()):
            pool = ("events" if key.endswith("_events") else "fb" if key.startswith("sigma_vis")
                    else "inverse_fb" if key == "luminosity_fb" else None)
            if pool:
                pools[pool] += [Decimal(n) for n in _numbers(value)]
    # Supplied inputs, current or prior, may be restated (e.g. "L was updated from ... to ... fb^-1"):
    # they are inputs, not results. A result computed from a superseded input is caught above.
    inputs = [record for record in artifacts.values() if record.get("kind") in ("workspace", "luminosity", "title")]
    inputs += [{"kind": kind, **record} for kind, record in current_inputs.items()]
    for record in inputs:
        content = record.get("content")
        if record["kind"] == "workspace":
            pools["events"] += [Decimal(n) for n in _numbers(content)]
        elif record["kind"] == "luminosity":
            pools["inverse_fb"] += [Decimal(n) for n in _numbers(content)]
        elif isinstance(content, str):
            for pool, value, _ in _prose_numbers(content):
                if value is not None:
                    pools[pool].append(value)
    pools = {pool: sorted(values) for pool, values in pools.items()}
    texts = [(None, "report_text", submission["report_text"])]
    for claim in live:
        texts.append((claim["claim_id"], "claim_text", claim["text"]))
        texts += [(claim["claim_id"], "qualifiers", qualifier) for qualifier in claim["qualifiers"]]
    refusal = submission.get("refusal")
    if isinstance(refusal, dict) and isinstance(refusal.get("text"), str):
        texts.append((None, "refusal_text", refusal["text"]))
    for claim_id, where, text in texts:
        for pool, value, half in _prose_numbers(text):
            if value is None or not _licensed(value, half, pools[pool]):
                add(claim_id, "unclaimed_prose_number", where, None)
    return {"blocking": any(d["blocking"] for d in diagnostics), "diagnostics": diagnostics}


def subject_diagnostics(diagnostics):
    """The diagnostic fields a subject may see: claim id, code, dependency class and handle."""
    return [{k: d[k] for k in ("claim_id", "code", "dependency", "handle")} for d in diagnostics]


def feedback_text(diagnostics):
    """Diagnostic feedback text, identical in audit and block modes; never contains a value."""
    if not diagnostics:
        return ""
    lines = ["Findings:"]
    for d in diagnostics:
        where = f"claim {d['claim_id']}" if d["claim_id"] is not None else d["dependency"]
        lines.append(f"- {where}: {d['code']} (dependency: {d['dependency']}; "
                     f"handle: {d['handle'] if d['handle'] is not None else 'none'})")
    lines.append("Permitted actions: " + "; ".join(PERMITTED_ACTIONS) + ".")
    return "\n".join(lines)
