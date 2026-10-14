"""rivet-routine block on own routine text."""
SKILL = "rivet-routine"


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ["routine-data-files"]


def test_missing_onnx(handbook, tmp_path):
    missing = handbook.load(SKILL, "routine-data-files")["missing_onnx"]
    assert missing("void init() { book(_h, 1, 1, 1); }", "MY_2024_I1", [tmp_path]) == []
    assert missing("_nn = getONNX(name());", "MY_2024_I1", [tmp_path]) == ["MY_2024_I1.onnx"]
    (tmp_path / "MY_2024_I1.onnx").write_bytes(b"\0")
    assert missing("_nn = getONNX(name());", "MY_2024_I1", [tmp_path]) == []
    assert missing('_nn = getONNX("other");', "MY_2024_I1", [tmp_path]) == ["other.onnx"]
