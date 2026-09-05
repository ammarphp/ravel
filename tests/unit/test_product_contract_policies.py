import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _pc_text():
    return (REPO / "docs/reference/scope.md").read_text(encoding="utf-8")


def _result_pack_stat_modes():
    src = (REPO / "src" / "ravel" / "workflow" / "result_pack.py").read_text(encoding="utf-8")
    # Capture the whole tuple body up to the closing ')' on its own line. A naive
    # split(')', 1) truncates at the ')' inside an inline comment like '(CR-027 / Option B)'
    # and would see only the first 5 of the 9 modes.
    m = re.search(r"STAT_MODES\s*=\s*\((.*?)\n\)", src, re.DOTALL)
    assert m, "STAT_MODES tuple not found in result_pack.py"
    # Strip inline comments so a ')' inside a comment cannot truncate the parse.
    body = "\n".join(line.split("#", 1)[0] for line in m.group(1).splitlines())
    return re.findall(r'"([^"]+)"', body)


def test_detached_job_policy_row():
    t = _pc_text().lower()
    assert "detached" in t and "heartbeat" in t and "run_state.json" in t, \
        "the N6 detached-job refusal (detached + run_state.json + heartbeat) is not in PRODUCT-CONTRACT"


def test_in_tree_outputs_rule():
    t = _pc_text().lower()
    assert ("under the rundir" in t or "under the run directory" in t) and "scratchpad" in t, \
        "the N2 in-tree-outputs semantics rule is not in PRODUCT-CONTRACT"


def test_skill_precedence_rule():
    t = _pc_text().lower()
    assert "physicist-intake" in t and "precedence" in t, \
        "the N1 skill-precedence refusal is not in PRODUCT-CONTRACT"


def test_stat_mode_enum_mirrored():
    # every canonical stat_mode (all 9, robustly parsed past the inline comments) must be
    # documented in PRODUCT-CONTRACT (§8: enums mirror HERE first)
    t = _pc_text()
    missing = [m for m in _result_pack_stat_modes() if m not in t]
    assert not missing, f"stat_mode enums not mirrored into PRODUCT-CONTRACT: {missing}"
