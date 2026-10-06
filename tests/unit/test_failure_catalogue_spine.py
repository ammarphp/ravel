from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# each gate class -> the gate id that now catches it. D18 is the umbrella (no single G#).
GATE_FOR = {
    "D4": "G4", "D5": "G11", "D6": "G6", "D7": "G9", "D8": "G8", "D9": "G10",
    "D10": "G12", "D11": "G13", "D12": "G14", "D13": "G15", "D14": "G16",
    "D15": "G17", "D16": "G20",
    # D17 (unaided routing of a fresh session) has no board gate of its own: the routing gate G22
    # blocks its individual steps.
    "D17": "G22",
    "N1": "G22", "N2": "G23", "N3": "G24", "N4": "G25", "N5": "G26", "N6": "G27",
    # N7 = assert-blocked-without-attempt (census obligation, D18 umbrella);
    # N8 = fan-out-before-routing (the route-pending marker + PreToolUse Agent/Task guard, G22 ext)
    "N7": "D18", "N8": "G22",
    # N9 = enforcement-disarm attempt (protect-enforcement.sh, G22-family PreToolUse)
    "N9": "G22",
}
ALL_CODES = list(GATE_FOR) + ["D18"]


def _text():
    return (REPO / "docs" / "reference" / "failure-modes.md").read_text(encoding="utf-8")


def _blocks(text):
    idx = sorted((text.index(f"**{c} —"), c) for c in ALL_CODES if f"**{c} —" in text)
    out = {}
    for i, (pos, c) in enumerate(idx):
        end = idx[i + 1][0] if i + 1 < len(idx) else len(text)
        out[c] = text[pos:end]
    return out


def test_all_gate_classes_present():
    text = _text()
    missing = [c for c in ALL_CODES if f"**{c} —" not in text]
    assert not missing, f"failure catalogue missing gate-class entries (need bold '**Cn —'): {missing}"


def test_each_class_names_its_gate():
    blocks = _blocks(_text())
    missing = [(c, g) for c, g in GATE_FOR.items() if g not in blocks.get(c, "")]
    assert not missing, f"gate-class entries not naming their gate id: {missing}"


def test_umbrella_names_validate_run_state():
    blocks = _blocks(_text())
    d18 = blocks.get("D18", "")
    assert "validate_run_state" in d18 or "umbrella" in d18, \
        "D18 must name the validate_run_state --rundir umbrella"
