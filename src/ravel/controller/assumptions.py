"""Located recorded assumptions shared by review and delivery."""
from copy import deepcopy
import hashlib
import json


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def recorded(store, plan):
    """Every recorded statement with its original value, locator and record digest."""
    assumptions = []

    def collect(value, record, pointer=""):
        if type(value) is dict:
            for key, child in value.items():
                location = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
                if key == "assumptions" and type(child) is list:
                    for number, item in enumerate(child):
                        statement = item.get("statement") if type(item) is dict else item
                        if type(statement) is not str or not statement.strip():
                            raise ValueError("a recorded assumption has no statement: " + record["id"] + location)
                        locator = record["id"] + "#" + location + "/" + str(number)
                        assumptions.append({"id": _digest(locator), "statement": statement,
                                            "locator": locator, "record": record["id"],
                                            "record_digest": record["digest"], "value": deepcopy(item)})
                elif key == "assumptions" and child is not None:
                    raise ValueError("a recorded assumptions field is not a list: " + record["id"] + location)
                else:
                    collect(child, record, location)
        elif type(value) is list:
            for number, child in enumerate(value):
                collect(child, record, pointer + "/" + str(number))

    for kind in ("intake", "judgment-frame", "assumption", "assumptions"):
        for row in store.scan(kind):
            collect(row["record"], row)
            if kind == "intake":
                for field in ("contract_blob", "reading_blob"):
                    if row["record"].get(field):
                        collect(json.loads(store.get_blob(row["record"][field])), row, "/" + field)
    # The current scientific plan, rather than a later temporary judgment-planning plan.
    for row in store.scan("plan"):
        if row["record"].get("plan_sha256") == plan["sha256"] and row["record"].get("blob"):
            collect(json.loads(store.get_blob(row["record"]["blob"])), row)
            break
    return assumptions
