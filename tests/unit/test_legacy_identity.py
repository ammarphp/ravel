"""T1: every fixture version-1 contract is decided exactly as before.

The decisions of ``validate``, ``required_stages``, ``checkin_variant``, ``approval_input_paths``,
``verify_approval`` and ``evaluate`` are hashed per contract and compared with the recorded golden
(``legacy_identity.py``). A deliberate change re-records with
``python tests/unit/legacy_identity.py record`` and says why in its commit.
"""
import json

import pytest

import legacy_identity as li


def _golden(kind):
    path = li.GOLDEN[kind]
    if not path.is_file():
        pytest.skip(f"no recorded golden for {kind}")
    return json.loads(path.read_text())["entries"]


def _compare(kind, observed, golden):
    mismatched, compared, changed_inputs = [], 0, []
    for key, entry in observed.items():
        expected = golden.get(key)
        if expected is None:
            continue
        if "inputs" in expected and expected["inputs"] != entry.get("inputs"):
            changed_inputs.append(key)
            continue
        compared += 1
        if entry["record"] != expected["record"]:
            mismatched.append(f"{key}: verdict {expected.get('verdict')} -> {entry.get('verdict')}")
    assert not mismatched, (
        f"{kind}: legacy decisions changed for {len(mismatched)} contract(s); re-record only for a "
        "deliberate, explained change:\n  " + "\n  ".join(mismatched))
    return compared, changed_inputs


def test_fixture_contracts_are_decided_as_recorded():
    golden = _golden("fixtures")
    observed, _ = li.observe("fixtures")
    assert set(observed) == set(golden), "the fixture matrix changed; re-record deliberately"
    compared, _ = _compare("fixtures", observed, golden)
    assert compared == len(golden)
