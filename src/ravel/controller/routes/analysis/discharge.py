"""Record the analysis route's obligations in the run's ledger, with the evidence that discharges them.

The ledger (P02) instantiates the P09 rows at plan time (route, inputs, scan, waypoint and
check-in rows) and at each seat attempt (compare and validate rows). The route adapter is their
discharging node: it records ``satisfied`` with evidence when its check holds and ``violated``
with the reason when it refuses. Review-gated rows are satisfied only with a review credit; a
row without its credit stays pending, so the ledger keeps the transition shut. Without an
installed ledger nothing is recorded and nothing is claimed.
"""
from __future__ import annotations

from . import common


def row_of(key) -> str:
    return str(key).split("@", 1)[0]


def pending(store, node, *, rows=None, step=None, point=None) -> list:
    ledger = common.ledger()
    if ledger is None or store is None:
        return []
    try:
        keys = ledger.pending(store, node=node, step=step, point=point)
    except Exception as exc:  # the ledger refuses an unpinned or broken chain; that is its own hold
        if type(exc).__name__ in ("LedgerError", "CatalogueError"):
            return []
        raise
    return [k for k in keys if rows is None or row_of(k) in rows]


LEDGER_REFUSAL = "route-ledger-refusal"


def record(store, node, status, evidence, *, rows=None, step=None, point=None) -> list:
    """Record ``status`` for the pending entries of ``node`` (optionally only ``rows``); returns their keys.

    A change the ledger refuses (for example a review-gated row without its credit) is never forced and
    never ends the run: the refusal is appended to the run store (``route-ledger-refusal``) and the entries
    stay as they were, so the ledger's own gate keeps the transition shut.
    """
    ledger = common.ledger()
    keys = pending(store, node, rows=rows, step=step, point=point)
    if ledger is None or not keys:
        return []
    try:
        ledger.record_many(store, [(key, status, dict(evidence)) for key in keys])
    except Exception as exc:
        if type(exc).__name__ not in ("LedgerError", "CatalogueError"):
            raise
        store.append(LEDGER_REFUSAL, {"node": node, "status": status, "entries": keys[:50],
                                      "reason": str(exc)[:1000], "provider": common.PROVIDER})
        return []
    return keys


def credit(context, purpose="checkin1") -> str | None:
    """A credit id from the controller's review state (all seats credited), or None."""
    reviews = ((context.get("state") or {}).get("reviews") or {}).get(purpose) or {}
    if not reviews or not all(isinstance(v, dict) and v.get("credited") for v in reviews.values()):
        return None
    receipts = sorted({r for v in reviews.values() for r in v.get("receipts") or ()})
    return "review:" + common.digest({"purpose": purpose, "seats": sorted(reviews), "receipts": receipts})


def checkin1_content(store, context, evidence, content) -> str | None:
    """CHECK-IN 1's own rows for a route that binds its reviewable content before the approval.

    C04 is not applicable when the plan declares no check-in variant. A06 and C03 are satisfied only with
    the plan review's credit (every seat credited), a plan with steps and deliverables, and ``content``:
    the digests of the route's own adopted evidence the approval binds. Returns the credit, else None and
    nothing beyond C04 is recorded, so the ledger keeps the CHECK-IN 1 transition shut.
    """
    plan = context.get("plan") or {}
    if not any(c.get("variants") for c in plan.get("checkins") or ()):
        record(store, "authority.ci1", "not_applicable",
               {**evidence, "reason": "not_applicable:route_declares_no_checkin_variant"}, rows={"C04"})
    found = credit(context, "checkin1")
    if not (found and content and plan.get("steps") and plan.get("deliverables")):
        return None
    record(store, "authority.ci1", "satisfied", {**evidence, "credit": found, "content": list(content)},
           rows={"A06", "C03"})
    return found


def checkin1_assumptions(store, context, evidence, credit, stated) -> bool:
    """C14 for a route whose own adopted evidence states its result-sensitive assumptions (``stated``).

    Not applicable only with the plan review's credit, no open ambiguity in the pinned reading and nothing
    stated; anything else leaves the row to the route's reviewers, so the ledger keeps CHECK-IN 1 shut.
    """
    ambiguities = [row for row in (context.get("reading") or {}).get("ambiguities") or ()
                   if type(row) is dict and row.get("status", "open") == "open"]
    if not credit or ambiguities or stated is None or list(stated):
        return False
    record(store, "authority.ci1", "not_applicable",
           {**evidence, "credit": credit, "reason": "not_applicable:no_result_sensitive_assumption"}, rows={"C14"})
    return True


def refusals(store, node, errors, *, step=None, point=None) -> list:
    """Record ``violated`` for the rows the refusals name (a refusal is a ledger event)."""
    by_row = {}
    for item in errors:
        if item.get("row"):
            by_row.setdefault(item["row"], []).append(item["message"])
    keys = []
    for row, messages in sorted(by_row.items()):
        keys += record(store, node, "violated", {"reason": "; ".join(messages)[:1500],
                                                  "mechanism": common.PROVIDER, "label": "route refusal"},
                       rows={row}, step=step, point=point)
    return keys
