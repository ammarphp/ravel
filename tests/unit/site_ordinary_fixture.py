"""Three exact source-pinned fixture definitions, no old suite import."""

def contract(**updates):
    result = {"schema_version": 1, "axes": [{"name": "pt", "unit": "GeV"}],
              "bins": [{"id": "low", "low": [0.], "high": [1.]},
                       {"id": "high", "low": [1.], "high": [3.]}],
              "weight_names": ["nominal"], "input_weight_unit": "pb",
              "representation": "integrated", "normalization": {"kind": "absolute", "scale": 1., "unit": "pb"}}
    result.update(updates)
    return result

def event(id_, fills, weight=1., *, group=None, shard="sample-a", weights=None):
    return {"event_id": str(id_), "group_id": str(id_ if group is None else group), "shard_id": shard,
            "weights": {"nominal": weight} if weights is None else weights, "fills": fills}

def policy():
    return {"schema_version": 1,
        "actors": {"proposer": "worker", "executor": "worker", "physics_decider": "physicist", "skeptical_verifier": "skeptic", "physics_critic": "critic"},
        "max_redos": 2, "allowed_changed_paths": ["inputs/settings.cfg"], "allowed_stages": ["detector"],
        "required_checks": [{"id": "integrity", "kind": "integrity"}, {"id": "agreement", "kind": "scientific"}],
        "claim_scopes": {"diagnostic": {"checks": ["integrity"], "actions": ["delivery"]},
            "reproduction": {"checks": ["integrity", "agreement"], "actions": ["bulk", "delivery", "reuse"]}}}
