"""AST enumeration of every read of the four legacy contract labels under ``src/ravel``.

The labels are ``task_mode``, ``stat_mode``, ``compute_plan`` and ``detector_mode``. Schema-v2
contracts omit them, so each place that reads one must be classified before v2 lands
(``tests/unit/test_label_reads.py``). A *site* is one AST node:

- ``x["task_mode"]`` (``subscript``), ``x.get("task_mode")`` / ``.pop`` / ``.setdefault``;
- ``getattr(x, "task_mode")`` / ``hasattr``; ``x.task_mode`` (``attribute``);
- any other string literal equal to a label name (``literal``): membership tests, tuples of
  field names that a loop indexes with, comparisons with a loop variable. Dict-display keys are
  writes and are not sites, nor is the key of a subscript assignment.

A site's identity does not depend on line numbers, so unrelated edits do not churn the registry:
``<path>::<scope>::<receiver>.<accessor>[<key>]#<n>``, where ``scope`` is the dotted chain of
enclosing classes and functions, ``receiver`` is the source text of the indexed object and ``n``
counts equal identities in source order.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

KEYS = ("task_mode", "stat_mode", "compute_plan", "detector_mode")
REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "src" / "ravel"


def _receiver(node):
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse handles every expression node
        return "?"


def _read(node):
    """Return (receiver, accessor, key) when the node reads a label, else None."""
    if (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
            and isinstance(node.slice, ast.Constant) and node.slice.value in KEYS):
        return _receiver(node.value), "subscript", node.slice.value
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "pop", "setdefault") and node.args
            and isinstance(node.args[0], ast.Constant) and node.args[0].value in KEYS):
        return _receiver(node.func.value), node.func.attr, node.args[0].value
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("getattr", "hasattr") and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant) and node.args[1].value in KEYS):
        return _receiver(node.args[0]), node.func.id, node.args[1].value
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr in KEYS:
        return _receiver(node.value), "attribute", node.attr
    return None


def _consumed_constants(node):
    """Constants that are part of a read already counted, or keys of a dict display."""
    if isinstance(node, ast.Subscript):
        return [node.slice]
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            return node.args[:1]
        return node.args[1:2]
    return []


def enumerate_sites(root=SOURCE):
    """Return [{"id", "path", "scope", "receiver", "accessor", "key", "line"}] in source order."""
    found = []
    for path in sorted(Path(root).rglob("*.py")):
        rel = path.relative_to(Path(root).parents[1]).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        skip = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                skip.update(id(k) for k in node.keys if k is not None)
            if isinstance(node, ast.Subscript) and not isinstance(node.ctx, ast.Load):
                skip.add(id(node.slice))  # x["task_mode"] = ... is a write
            if _read(node):
                skip.update(id(c) for c in _consumed_constants(node))

        def visit(node, scope):
            for child in ast.iter_child_nodes(node):
                inner = scope
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    inner = scope + (child.name,)
                hit = _read(child)
                if hit is None and (isinstance(child, ast.Constant) and child.value in KEYS
                                    and id(child) not in skip):
                    hit = ("<literal>", "literal", child.value)
                if hit:
                    found.append({"path": rel, "scope": ".".join(scope) or "<module>",
                                  "receiver": hit[0], "accessor": hit[1], "key": hit[2],
                                  "line": child.lineno, "col": child.col_offset})
                visit(child, inner)

        visit(tree, ())
    found.sort(key=lambda s: (s["path"], s["line"], s["col"]))
    counts = defaultdict(int)
    for site in found:
        stem = f"{site['path']}::{site['scope']}::{site['receiver']}.{site['accessor']}[{site['key']}]"
        site["id"] = f"{stem}#{counts[stem]}"
        counts[stem] += 1
    return found


if __name__ == "__main__":  # print the current sites, one identity per line
    for s in enumerate_sites():
        print(f"{s['id']}  (line {s['line']})")
