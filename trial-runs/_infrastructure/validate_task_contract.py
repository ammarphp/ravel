#!/usr/bin/env python3
"""Validate a task_contract.json against the binding schema (PRODUCT-CONTRACT.md).

The task contract is the machine artifact that classifies a physicist request BEFORE any
compute: route_prompt.py writes it, this validator gates it, CHECK-IN 1 presents it. A
contract that fails validation must not proceed to generation (charter section 4.4).

Stdlib-only on purpose: any session (any conda env, or none) can run it.

Usage:
  validate_task_contract.py <contract.json>     # exit 0 = valid, exit 1 + itemized errors
  validate_task_contract.py --schema            # print the schema (JSON)
  validate_task_contract.py --selftest          # validate embedded good/bad examples
"""
import json
import sys

TASK_MODES = (
    "survey", "reproduce", "reinterpret", "projection", "scan",
    "summary_plot", "anomaly_search", "no_routine", "unsupported",
)
DETECTOR_MODES = (
    "particle-level", "rivet-smearing", "simpleanalysis-delphes-native", "container",
    "effmap-folded",  # published per-object efficiency maps folded over truth objects (D2)
    "TBD-judgment",   # a weak model may leave the choice to the physicist/CHECK-IN 1
)
STAT_MODES = (  # canonical source: result_pack.py STAT_MODES + the routing placeholder
    "published-likelihood", "simplified-likelihood", "best-sr-counting", "combined-counting",
    "stability-only", "shape-fit", "blocked-shape-fit", "sensitivity-expected-only", "none-survey",
    "TBD-judgment",
)
COMPUTE_PLANS = ("none", "dry", "smoke", "full", "scan")

SCHEMA = {
    "schema_version": 1,
    "required": {
        "prompt": "str — the request, verbatim",
        "task_mode": f"enum {TASK_MODES}",
        "detector_mode": f"enum {DETECTOR_MODES}",
        "stat_mode": f"enum {STAT_MODES}",
        "required_user_inputs": "list[str] — named missing inputs (empty = none missing)",
        "assumptions": "list[str] — numbered-flag material for CHECK-IN 1",
        "compute_plan": f"enum {COMPUTE_PLANS} — the requested LADDER rung, not a promise",
        "approval_required": "const true — heavy compute NEVER starts without CHECK-IN 1 approval",
    },
    "optional": {
        "targets": "obj {model, process, analysis[], arxiv[], inspire[], figures[], "
                   "masses_gev[], lumi_fb}",
        "cost_estimate": "obj — cost_preflight.py output (walltime/disk per ladder rung)",
        "blocking": "list[str] — PRODUCT-CONTRACT section-6 refusal lines this request crosses",
        "escalate": "list[str] — [judgment] points a weak model must hand to the physicist",
        "notes": "str",
    },
}


def validate(c):
    """Return a list of error strings (empty = valid)."""
    errs = []
    if not isinstance(c, dict):
        return ["contract is not a JSON object"]

    def need(key, typ, label):
        v = c.get(key)
        if v is None:
            errs.append(f"missing required field '{key}' ({label})")
            return None
        if typ and not isinstance(v, typ):
            errs.append(f"'{key}' must be {label}, got {type(v).__name__}")
            return None
        return v

    need("prompt", str, "str")
    tm = need("task_mode", str, "str")
    if tm is not None and tm not in TASK_MODES:
        errs.append(f"task_mode {tm!r} not in {TASK_MODES}")
    dm = need("detector_mode", str, "str")
    if dm is not None and dm not in DETECTOR_MODES:
        errs.append(f"detector_mode {dm!r} not in {DETECTOR_MODES}")
    sm = need("stat_mode", str, "str")
    if sm is not None and sm not in STAT_MODES:
        errs.append(f"stat_mode {sm!r} not in {STAT_MODES}")
    for key in ("required_user_inputs", "assumptions"):
        v = need(key, list, "list[str]")
        if v is not None and not all(isinstance(x, str) for x in v):
            errs.append(f"'{key}' entries must all be strings")
    cp = need("compute_plan", str, "str")
    if cp is not None and cp not in COMPUTE_PLANS:
        errs.append(f"compute_plan {cp!r} not in {COMPUTE_PLANS}")
    if c.get("approval_required") is not True:
        errs.append("approval_required must be literally true — the compute block is not optional")

    # cross-field consistency (the rules that make the contract MEAN something)
    if tm == "unsupported" and not c.get("blocking"):
        errs.append("task_mode=unsupported requires 'blocking' to NAME the refusal line "
                    "(PRODUCT-CONTRACT section 6)")
    if sm == "blocked-shape-fit" and cp in ("full", "scan"):
        errs.append("stat_mode=blocked-shape-fit cannot carry compute_plan=full|scan — the "
                    "statistical paradigm is refused; offer the sensitivity-expected-only path")
    if tm in ("survey", "summary_plot") and cp in ("full", "scan"):
        errs.append(f"task_mode={tm} is a no-generation mode; compute_plan must be none|dry|smoke")
    if cp in ("full", "scan") and c.get("cost_estimate") in (None, {}):
        errs.append(f"compute_plan={cp} requires a cost_estimate (run cost_preflight.py)")
    return errs


def selftest():
    good = {
        "prompt": "Initiate: reproduce Figure 3 of the slepton search vs the slepton-bino model",
        "task_mode": "reproduce", "detector_mode": "simpleanalysis-delphes-native",
        "stat_mode": "published-likelihood",
        "required_user_inputs": [], "assumptions": ["F1: NLO+NLL k-factors from the WG grid"],
        "compute_plan": "scan", "approval_required": True,
        "cost_estimate": {"mode": "scan", "points": 52, "walltime_h": [6.5, 10.8]},
    }
    bads = [
        ({**good, "approval_required": False}, "approval_required"),
        ({**good, "task_mode": "discovery"}, "task_mode"),
        ({**good, "task_mode": "unsupported"}, "blocking"),
        ({**good, "stat_mode": "blocked-shape-fit"}, "blocked-shape-fit"),
        ({**good, "compute_plan": "scan", "cost_estimate": None}, "cost_estimate"),
        ({k: v for k, v in good.items() if k != "assumptions"}, "assumptions"),
    ]
    errs = validate(good)
    if errs:
        sys.exit(f"selftest FAILED: the good contract did not validate: {errs}")
    for bad, needle in bads:
        errs = validate(bad)
        if not errs or not any(needle in e for e in errs):
            sys.exit(f"selftest FAILED: expected an error mentioning {needle!r}, got {errs}")
    print(f"validate_task_contract selftest: 1 good + {len(bads)} bad contracts judged correctly.")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--schema":
        print(json.dumps(SCHEMA, indent=2))
        return
    if sys.argv[1] == "--selftest":
        selftest()
        return
    try:
        contract = json.load(open(sys.argv[1]))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"validate_task_contract: cannot read {sys.argv[1]}: {e}")
    errs = validate(contract)
    if errs:
        print(f"INVALID task contract ({sys.argv[1]}):")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    print(f"valid task contract: task_mode={contract['task_mode']} "
          f"detector_mode={contract['detector_mode']} stat_mode={contract['stat_mode']} "
          f"compute_plan={contract['compute_plan']} (approval required)")


if __name__ == "__main__":
    main()
