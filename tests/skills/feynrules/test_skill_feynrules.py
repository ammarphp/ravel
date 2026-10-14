"""feynrules block: the literal Python 2 raise rewrite."""
import ast

SKILL = "feynrules"


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ["python2-raise-rewrite"]


def test_python2_raise_is_rewritten_and_journaled(handbook):
    rewrite = handbook.load(SKILL, "python2-raise-rewrite")["rewrite_ufo_text"]
    source = 'class UFOError(Exception):\n    pass\n\ndef f(x):\n    if x:\n        raise UFOError, "bad value"\n'
    converted, edits = rewrite(source)
    ast.parse(converted)
    assert 'raise UFOError("bad value")' in converted and edits == [(6, "bad value")]
    assert rewrite("x = 1\n") == ("x = 1\n", [])
