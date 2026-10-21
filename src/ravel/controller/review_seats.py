"""Pure review roster and occurrence identities shared with maintenance projections."""
from copy import deepcopy
import hashlib
import json

STEP_IDS = {"plan": "plan_review", "waypoint": "waypoint_review", "attacks": "kill_the_result",
            "final": "final_review", "rdj": "rdj_review"}
CHECKINS = {"plan": "checkin1", "waypoint": "checkin2", "final": "checkin3"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def canonical_role(role):
    """The card id ``role`` names in the role registry: an alias (a host convenience) is never a seat's role. A
    name the registry does not know is kept as it is; the governed step holds it (``role_unregistered``)."""
    if type(role) is not str or not role:
        return role
    from ..workflow import role_registry
    try:
        return role_registry.resolve_names([role])[role]
    except ValueError:
        return role


def checkin_seats(plan, name, default=()):
    """The review seats of check-in ``name``: the plan's declared ``checkins[].seats``, else ``default``, as
    canonical role ids in order (a seat declared twice, under an alias or not, is one seat)."""
    declared = next((c.get("seats") for c in plan.get("checkins") or ()
                     if type(c) is dict and c.get("id") == name and c.get("seats")), None)
    return list(dict.fromkeys(canonical_role(seat) for seat in declared or default))


def review_seat_key(role, n=1):
    """Stable occurrence identity; duplicate declarations alone never create another seat."""
    return canonical_role(role) + (f".{n}" if n > 1 else "")


def review_step_id(purpose, role, n=1, step_id=None):
    identity = (step_id or STEP_IDS[purpose]) + (f".{n}" if n > 1 else "")
    return identity + ("." + canonical_role(role) if purpose == "waypoint" else "")


def review_seat_counts(plan, name):
    row = next((c for c in plan.get("checkins", []) if c.get("id") == name), {})
    counts = row.get("seat_counts", {})
    if counts == {}:
        return {}
    roles = set(checkin_seats(plan, name))
    if (type(counts) is not dict or any(role != canonical_role(role) or role not in roles
            or type(n) is not int or n < 1 for role, n in counts.items())):
        raise ValueError("review_seat_counts_invalid: seat counts require declared canonical roles and positive integers")
    return counts


def review_point_bindings(plan, purpose, role, n=1):
    row = next((c for c in plan.get("checkins", []) if c.get("id") == CHECKINS.get(purpose)), {})
    return [{"point": deepcopy(point), "n": n, "sha256": digest(point)}
            for point in row.get("review_points", [])
            if any(canonical_role(r["role"]) == canonical_role(role) and r["count"] >= n
                   for r in point["roles"])]

