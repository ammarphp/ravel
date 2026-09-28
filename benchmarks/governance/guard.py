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

WP12 task bank (design §1.5, §3.4, plan step 6). The claim vocabulary is the task-bank registry's field
registry (``tasks/registry.py``: every artifact field with its artifact kind, type, role, quantile and
unit; a calc result carries the unit its record declares). The stale code for a cited artifact is chosen
by the dependency class of each input kind it derives from (``registry.INPUT_KINDS``): numerical,
conversion (only for fields that depend on that kind, ``registry.ARTIFACT_DEPENDS``), display or none.
Version 2 claims add the unit pb (rescaled to fb for every comparison; the two are one dimension), a
``relation`` and categorical values. A claim whose relation is not ``eq`` on a limit field is supported when
a cited artifact recording that limit (a fit, a conversion) records a status other than ``resolved`` in the
relation's direction (the kernel's ``above_scan`` means greater than its bound, ``below_scan`` less) and the
quantity equals the recorded bound; in fb the bound is divided by the luminosity of any cited record that
carries one (a luminosity record or a conversion; decision E-169). Any other bound, a weaker true one
included ("gt 9 events" at the bound 10), is value_mismatch (design §1.5; E-167). On a numeric field that is
no limit (a CLs diagnostic, a count) a relation is supported when the cited value satisfies it (E-168). A
categorical value is supported when it equals the cited artifact's field exactly. A version 2 claim is
judged against the cited artifacts of its field's own kind when there are any (a fit for a limit, a census
for a count, a calc for a result), and one of them holding the value suffices: the other cited artifacts are
context (the archive's census beside the primary's, a draft beside a new calc; E-169). A figure holds a
limit claim through any value it plots (E-171). A version 2 integer of at least 1000 written with trailing
zeros is read at its last nonzero digit (E-172). An index or ordinal ("event 42", "42nd") is no count in
delivered text (E-175). Supplied JSON inputs license each number into the pool its unit implies
(``registry.INPUT_RECORD_UNITS``, else its key's unit, ``registry.key_unit``). No predicate is specific to a
task family, and ``unresolved_value`` (an ``eq`` claim on a limit whose status is not ``resolved``) is not
adopted (decision E-114): such a claim equal to the recorded bound is supported here and scored by the
evaluator. Version 1 claims are judged exactly as before, every cited holder included (tests/governance: the
v1 golden corpus). Standard library only; the registry is vocabulary, and the guard reads no oracle.
"""
from __future__ import annotations

import bisect
import re
from decimal import Decimal, localcontext

from .canonical import finite_number, require
from .tasks import registry

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
# Generic for every task-bank family (plan step 10): recomputing names no stage chain, since the census and calc
# families have none of fit/convert/report (the version 1 sentence said "recompute through fit/convert/report").
PERMITTED_ACTIONS = ("recompute from the current inputs with the task tool", "retract the claim",
                     "state a refusal with its reason")
DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
MAX_EXPONENT = 1000          # a decimal beyond 1e+-1000 is out of range: it never matches a value
V1_FIELDS = frozenset(registry.V1_ARTIFACT_FIELDS)   # the fields a version 1 claim may name
_INDEXED = re.compile(r"([a-z][a-z0-9_]*)\[([0-4])\]")
# a unit -> (pool, decimal places to the pool's unit): cross sections in fb, integrated luminosities in fb^-1
SCALES = {"events": ("events", 0), "fb": ("fb", 0), "pb": ("fb", 3), "fb^-1": ("inverse_fb", 0),
          "pb^-1": ("inverse_fb", -3)}
# a limit field -> (the limit_status curve, the event-count key holding its value or bound)
LIMITS = {"obs_limit_events": ("observed", "obs_limit_events"), "exp_limits_events": ("expected", "exp_limits_events"),
          "sigma_vis_obs_fb": ("observed", "obs_limit_events"), "sigma_vis_exp_fb": ("expected", "exp_limits_events")}
# a kernel limit status -> the relations a bound with that status supports (the kernel's own reading:
# pyhf_exclude renders above_scan as ">" and below_scan as "<")
BOUND_RELATIONS = {"above_scan": ("gt", "ge"), "below_scan": ("lt", "le")}

# -- unit-bearing numbers in delivered text ----------------------------------------------------
_S = r"[^\S\n]"              # horizontal whitespace; nothing below crosses a line
# Digits grouped in thousands by one separator (a comma, a thin, narrow no-break or no-break space: "33,083.27")
# are one number; the first group starts at 1-9, so a European decimal such as "0,162" is never one (the evaluator's
# reader, audit._DIGITS, reads numbers the same way).
GROUPING = "\u2009\u202f\u00a0"
_DIGITS = r"(?:[1-9]\d{0,2}(?:(?:,\d{3})+|(?:[" + GROUPING + r"]\d{3})+)(?![0-9])(?:\.\d*)?|\d+(?:\.\d*)?|\.\d+)"
_UNGROUP = str.maketrans("", "", "," + GROUPING)
# A scale word between a number and "events" multiplies it ("33.1 thousand events" is 33,100 events).
_SCALE_WORD = re.compile(r"\b(thousand|million|billion)\b", re.I)
SCALE_PLACES = {"thousand": 3, "million": 6, "billion": 9}
_NUMBER = re.compile(        # unsigned decimal, optionally "x 10^n" (\times, \cdot, superscripts)
    r"(?<![A-Za-z0-9.])(" + _DIGITS + r"(?:[eE][+-]?\d+)?)"
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
# An index or an ordinal is no count (decision E-175; the evaluator's reader reads it the same way): "event 42",
# "event #42", "event number 42", "block 42" and "42nd" name one event, so no unit or list join binds them.
_INDEX_BEFORE = re.compile(r"\b(?:event|block)(?:" + _S + r"+(?:number|no\.?))?" + _S + r"*#?" + _S + r"*\Z", re.I)
_ORDINAL_AFTER = re.compile(r"(?:st|nd|rd|th)\b", re.I)
RELATION_CHECK = {"gt": lambda a, b: a > b, "ge": lambda a, b: a >= b, "lt": lambda a, b: a < b,
                  "le": lambda a, b: a <= b}
LIMIT_KEYS = ("obs_limit_events", "exp_limits_events")


def field_spec(field):
    """Return (content key, index or None, role, quantile, unit, dependencies) of a registered artifact field
    (registry.ARTIFACT_FIELDS). unit: events, fb, pb, None (dimensionless or categorical) or "declared" (a
    calc result: the unit its record declares); dependencies: the input kinds its value depends on, None for
    every kind its artifact derives from."""
    require(isinstance(field, str) and field in registry.ARTIFACT_FIELDS, f"unknown artifact_field: {field!r}")
    spec = registry.ARTIFACT_FIELDS[field]
    match = _INDEXED.fullmatch(field)
    key, index = (match.group(1), int(match.group(2))) if match else (field, None)
    return key, index, spec["role"], spec["quantile"], spec["unit"], registry.ARTIFACT_DEPENDS[spec["artifact"]]


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


def _dimension(unit):
    """The pool a unit belongs to (events, fb for cross sections, inverse_fb), or None when it is not unit-bearing."""
    return SCALES[unit][0] if unit in SCALES else None


def _places(claim_unit, field_unit):
    """Decimal places from a claim's unit to the field's unit of the same dimension (pb -> fb: 3; fb -> pb: -3);
    0 for any other pair (a claim in another dimension is compared as written, and flagged unit_mismatch)."""
    if claim_unit in SCALES and field_unit in SCALES and SCALES[claim_unit][0] == SCALES[field_unit][0]:
        return SCALES[claim_unit][1] - SCALES[field_unit][1]
    return 0


def _pool_number(pools, unit, value):
    """Add a Decimal in ``unit`` to its pool (rescaled to the pool's unit); a unit that is not unit-bearing adds
    nothing."""
    if unit in SCALES:
        pool, places = SCALES[unit]
        pools[pool].append(_shift(value, places))


def _pool_claim(pools, unit, value):
    """A claimed or withdrawn quantity's pool: its unit's; with no unit, both events and fb (version 1)."""
    if unit in SCALES:
        _pool_number(pools, unit, value)
    else:
        pools["events"].append(value)
        pools["fb"].append(value)


def _content_numbers(record):
    """[(unit, Decimal)] of the unit-bearing numbers of an artifact's content, by the unit its key implies
    (registry.key_unit); a calc's result carries its declared unit and each binding's value its field's unit."""
    content = record.get("content")
    found = []
    for key, value in (content.items() if isinstance(content, dict) else ()):
        if record.get("kind") == "calc" and key == "result":
            unit = content.get("declared_unit")
        elif record.get("kind") == "calc" and key == "bindings" and isinstance(value, list):
            for binding in value:
                if isinstance(binding, dict) and isinstance(binding.get("field"), str):
                    unit = registry.key_unit(binding["field"].split("[")[0])
                    found += [(unit, Decimal(n)) for n in _numbers(binding.get("value"))]
            continue
        else:
            unit = registry.key_unit(key)
        found += [(unit, Decimal(n)) for n in _numbers(value)]
    return found


def _record_numbers(kind, content):
    """[(unit, Decimal)] of a supplied JSON input record: every number in its kind's unit
    (registry.INPUT_RECORD_UNITS), else each number in the unit of the key holding it."""
    if kind in registry.INPUT_RECORD_UNITS:
        return [(registry.INPUT_RECORD_UNITS[kind], Decimal(n)) for n in _numbers(content)]
    found, stack = [], [(None, content)]
    while stack:
        key, value = stack.pop()
        if isinstance(value, dict):
            stack += list(value.items())
        elif isinstance(value, list):
            stack += [(key, item) for item in value]
        elif finite_number(value):
            found.append((registry.key_unit(key), Decimal(value)))
    return found


def _bound_candidates(record, key, index, unit, luminosities):
    """(statuses, candidates) of a relation claim on one cited artifact: the limit statuses it records for the
    claimed curve and the bound value(s) the claim may equal, in the field's unit (events: the recorded bound;
    fb: the bound divided by each cited luminosity, a cited conversion's included). ``statuses`` is None when the
    artifact records no such limit."""
    curve, events_key = LIMITS[key]
    content = record.get("content")
    present, bound = _field_value(content, events_key, index)
    status = content.get("limit_status") if isinstance(content, dict) else None
    if not present or not isinstance(status, dict):
        return None, []
    state = status.get("observed") if curve == "observed" else (
        status["expected"][index] if isinstance(status.get("expected"), list) and index is not None
        and index < len(status["expected"]) else None)
    if not finite_number(bound):
        return state, []
    if unit == "events":
        return state, [Decimal(bound)]
    with localcontext() as context:
        context.prec = 50
        return state, [Decimal(bound) / divisor for divisor in luminosities]


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
    base = decimal_value(match.group(1).translate(_UNGROUP))
    power = (match.group(2) or match.group(3) or "").translate(_SUPERSCRIPT)
    if base is None or len(power) > 6:
        return None, None
    places += int(power) if power else 0
    value = _shift(base, places)
    if abs(value.adjusted()) > MAX_EXPONENT:
        return None, None
    return value, _shift(_half_unit(base), places)


def _index(text, match):
    """True when a number is an index or an ordinal (_INDEX_BEFORE, _ORDINAL_AFTER), never a count."""
    return _ORDINAL_AFTER.match(text, match.end()) is not None or \
        _INDEX_BEFORE.search(text, max(0, match.start() - 24), match.start()) is not None


def _integer_half(quantity):
    """The half-unit of an integer of at least 1000 written with trailing zeros, at its last nonzero digit ("33100":
    50; decision E-172: its precision is ambiguous), else None."""
    text = quantity.strip() if isinstance(quantity, str) else ""
    if not re.fullmatch(r"[+-]?[1-9]\d{3,}", text) or not text.endswith("0"):
        return None
    return Decimal((0, (5,), len(text) - len(text.rstrip("0")) - 1))


def _plotted(record, key):
    """The Decimal values a figure artifact plots for a limit key (every legend series' ``limit_events``; decision
    E-171: a figure holds a limit claim through any value it plots), else None."""
    content = record.get("content")
    if record.get("kind") != "figure" or key not in LIMIT_KEYS or not isinstance(content, dict) \
            or not isinstance(content.get("legend"), list):
        return None
    values = []
    for entry in content["legend"]:
        found = entry.get("limit_events") if isinstance(entry, dict) else None
        number = decimal_value(found) if isinstance(found, str) else Decimal(found) if finite_number(found) else None
        if number is not None:
            values.append(number)
    return values


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
    numbers = [m for m in _NUMBER.finditer(text) if m.start() not in in_unit and not _index(text, m)]
    starts = [m.start() for m in numbers]
    units = [None] * len(numbers)
    for i, m in enumerate(numbers):
        after = _AFTER.match(text, m.end())
        if after:
            unit = _unit(after.group(2), after.group(3))
            if not after.group(1) or unit[0] == "events":     # words may precede "events" only
                scale = _SCALE_WORD.search(after.group(1))
                units[i] = (unit[0], unit[1] + SCALE_PLACES[scale.group(1).lower()]) if scale else unit
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

    ``current_inputs`` maps a present input kind (registry.INPUT_KINDS) to {"sha256", "content", ...};
    ``artifacts`` maps handles to broker artifact records. Claims of schema version 1 or 2; retracted claims
    are ignored. The submission must already be structurally valid.
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
            _pool_claim(pools, claim["unit"], withdrawn)
    for claim in live:
        cid, quantity = claim["claim_id"], claim["quantity"]
        version2 = claim["schema_version"] == 2
        value = claim["value"] if version2 else None          # a categorical claim's boolean or string
        relation = claim["relation"] if version2 else "eq"
        claimed = decimal_value(quantity)
        if claimed is not None:
            _pool_claim(pools, claim["unit"], claimed)
        cited = []
        for handle in claim["evidence_ids"]:
            if handle in artifacts:
                cited.append((handle, artifacts[handle]))
            else:
                add(cid, "unbound_evidence", "evidence", handle)
        if (quantity is not None or value is not None) and not claim["evidence_ids"]:
            add(cid, "unbound_evidence", "evidence", None)
        spec = field_spec(claim["artifact_field"]) if claim["artifact_field"] is not None else None
        if spec is not None:
            key, index, role, quantile, unit, depends = spec
            if not registry.role_accepted(claim["artifact_field"], claim["role"], claim["expected_quantile"]):
                add(cid, "role_mismatch", "artifact_field", None)
            if unit != "declared" and _dimension(claim["unit"]) != _dimension(unit):
                add(cid, "unit_mismatch", "artifact_field", None)
        else:
            depends = None
            if quantity is not None:
                add(cid, "unbound_evidence", "artifact_field", None)
        for handle, record in cited:
            derived = record["derived_from"]
            stale = sorted(kind for kind in derived if derived[kind] != current.get(kind))
            numerical = [kind for kind in stale if registry.INPUT_KINDS.get(kind) == "numerical"]
            conversion = [kind for kind in stale if registry.INPUT_KINDS.get(kind) == "conversion"
                          and (depends is None or kind in depends)]
            for kind in numerical:
                add(cid, "stale_numerical_dependency", kind, handle)
            for kind in conversion if not numerical else ():
                add(cid, "stale_conversion_dependency", kind, handle)
            if not numerical and not conversion:
                fresh.append(record)
            for kind in stale:
                if registry.INPUT_KINDS.get(kind) == "display":
                    add(cid, "display_outdated", kind, handle)
        if (quantity is not None or value is not None) and spec is not None and cited:
            if relation != "eq" and key in LIMITS:
                _judge_bound(add, pools, claim, claimed, key, index, unit, cited)
                continue
            holders = []
            for handle, record in cited:
                present, found = _field_value(record["content"], key, index)
                plotted = None if present else _plotted(record, key)
                if present or plotted is not None:
                    holders.append((handle, record, [found] if present else plotted))
            if version2:          # judged against the cited artifacts of the field's own kind when there are any
                kind = registry.ARTIFACT_FIELDS[claim["artifact_field"]]["artifact"]
                holders = [h for h in holders if h[1].get("kind") == kind] or holders
            if not holders:
                add(cid, "unbound_evidence", "artifact_field", None)
            judged = []
            for handle, record, found_values in holders:
                target = record["content"].get("declared_unit") if unit == "declared" else unit
                if unit == "declared" and _dimension(claim["unit"]) != _dimension(
                        target if target in SCALES else None):
                    add(cid, "unit_mismatch", "artifact_field", None)
                held = [found for found in found_values if _holds(claim, claimed, value, relation, found, target)]
                judged.append((handle, target, held))
            any_held = any(held for _, _, held in judged)
            for handle, target, held in judged:
                if held and value is None:
                    _pool_number(pools, target, Decimal(held[0]))     # the exact value behind the claim
                elif not held and not (version2 and any_held):
                    # version 1: every cited holder must hold the value (the golden corpus); version 2: one holder of
                    # the field's kind holding it suffices, the others are context (decision E-169)
                    add(cid, "value_mismatch", "artifact_field", handle)

    for record in fresh:          # every value of a fresh cited artifact, by the unit its key implies
        for unit, number in _content_numbers(record):
            _pool_number(pools, unit, number)
    # Supplied inputs, current or prior, may be restated (e.g. "L was updated from ... to ... fb^-1"):
    # they are inputs, not results. A result computed from a superseded input is caught above.
    inputs = [record for record in artifacts.values() if record.get("kind") in registry.INPUT_KINDS]
    inputs += [{"kind": kind, **record} for kind, record in current_inputs.items()]
    for record in inputs:
        content = record.get("content")
        if registry.INPUT_FORMATS.get(record["kind"]) == "json":
            for unit, number in _record_numbers(record["kind"], content):
                _pool_number(pools, unit, number)
        elif isinstance(content, str):
            for pool, number, _ in _prose_numbers(content):
                if number is not None:
                    pools[pool].append(number)
    pools = {pool: sorted(values) for pool, values in pools.items()}
    texts = [(None, "report_text", submission["report_text"])]
    for claim in live:
        texts.append((claim["claim_id"], "claim_text", claim["text"]))
        texts += [(claim["claim_id"], "qualifiers", qualifier) for qualifier in claim["qualifiers"]]
    refusal = submission.get("refusal")
    if isinstance(refusal, dict) and isinstance(refusal.get("text"), str):
        texts.append((None, "refusal_text", refusal["text"]))
    for claim_id, where, text in texts:
        for pool, number, half in _prose_numbers(text):
            if number is None or not _licensed(number, half, pools[pool]):
                add(claim_id, "unclaimed_prose_number", where, None)
    return {"blocking": any(d["blocking"] for d in diagnostics), "diagnostics": diagnostics}


def _judge_bound(add, pools, claim, claimed, key, index, unit, cited):
    """A relation claim (gt, ge, lt, le) on a limit field (design §1.5): supported when a cited artifact that
    records the limit (a fit, a conversion) records a status other than resolved in the claimed direction
    (BOUND_RELATIONS) and the quantity equals its bound (in fb: divided by the luminosity of any cited record that
    carries one, a luminosity record or a conversion; decision E-169, as the evaluator reads it); the other cited
    artifacts are context. Otherwise value_mismatch per artifact recording the limit, or unbound_evidence when none
    does. A weaker true bound ("gt 9 events") is not the recorded bound and is blocked (design §1.5; E-167)."""
    cid = claim["claim_id"]
    luminosities = [Decimal(record["content"]["luminosity_fb"]) for _, record in cited
                    if isinstance(record.get("content"), dict) and finite_number(record["content"].get("luminosity_fb"))
                    and record["content"]["luminosity_fb"] > 0]
    judged, matched = [], []
    for handle, record in cited:
        state, candidates = _bound_candidates(record, key, index, unit, luminosities)
        if state is None:
            continue
        judged.append(handle)
        places = _places(claim["unit"], unit)
        if claimed is not None and claim["relation"] in BOUND_RELATIONS.get(state, ()):
            scaled, half = _shift(claimed, places), _shift(_half_unit(claimed), places)
            matched += [c for c in candidates if _near(scaled, half, c)][:1]
    if not judged:
        add(cid, "unbound_evidence", "artifact_field", None)
    elif matched:
        _pool_number(pools, unit, matched[0])
    else:
        for handle in judged:
            add(cid, "value_mismatch", "artifact_field", handle)


def _holds(claim, claimed, value, relation, found, target):
    """True when one recorded value ``found`` (in ``target``, the field's unit) holds a claim: a categorical value
    exactly (type included); a number within half a unit of the claim's last printed digit (a version 2 integer of at
    least 1000 written with trailing zeros: of its last nonzero digit, E-172); a relation on a field that is no limit
    (a CLs diagnostic, a count) when the recorded value satisfies it (decision E-168)."""
    if value is not None:
        return type(found) is type(value) and found == value
    if claimed is None or not (finite_number(found) or isinstance(found, Decimal)):
        return False
    places = _places(claim["unit"], target)
    scaled, recorded = _shift(claimed, places), Decimal(found)
    if relation != "eq":
        return RELATION_CHECK[relation](recorded, scaled)
    if _near(scaled, _shift(_half_unit(claimed), places), recorded):
        return True
    wide = _integer_half(claim["quantity"]) if claim["schema_version"] == 2 else None
    return wide is not None and _near(scaled, _shift(wide, places), recorded)


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
