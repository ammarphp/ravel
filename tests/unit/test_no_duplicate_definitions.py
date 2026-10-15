"""A later duplicate top-level definition silently replaces the earlier one."""
import ast
import collections
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / 'src' / 'ravel'


def test_no_module_defines_a_top_level_function_or_class_twice():
    duplicates = {}
    for path in sorted(SRC.rglob('*.py')):
        names = collections.Counter(n.name for n in ast.parse(path.read_text()).body
                                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        again = sorted(k for k, v in names.items() if v > 1)
        if again:
            duplicates[str(path.relative_to(SRC))] = again
    assert duplicates == {}
