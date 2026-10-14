"""G8 conformance: census of every agent call site.

Every ``.py`` file under ``src/ravel`` is parsed with ``ast``. Import aliases, literal
``getattr(module, "name")``, simple local bindings, parameter annotations and
same-module constructor helpers are resolved, and each call site is recorded at
function granularity (``module:qualname``) under one of seven sinks:

- S1 model reach: ``AgentHost.execute``, ``provider_transport.request``, the
  ``cli_agent_host`` entry points, a process launch whose argv names a model CLI
  launcher from ``data/transports``, and generic HTTP clients;
- S2 orchestration: LangGraph ``StateGraph``/``compile``/``Send``/``interrupt``/
  ``Command``/``ToolNode``/``create_react_agent``/``entrypoint``/``task``;
- S3 role dispatch: ``agent_graph``, ``research_cycle.execute_graph``, ``agent_worker``;
- S4 provider SDK imports and S5 upstream agent loops (direct or ``import_module``);
- S6 instruction literals under an ``"instructions"`` key;
- S7 calls to ``data/graphs/consequential_sinks.json``.

Sanctions name qualnames, never whole modules (``data/agents/sanctioned.json``). An
S7 call inside an ``effect`` body that names one of the sink's gates is ``substrate``.
Everything else is a ``bypass`` and must appear in ``data/agents/bypass_baseline.json``
with the package that removes it. The baseline only shrinks; its ``enforcement`` is
``report`` (W4), ``block_new`` (W-a) or ``empty`` (W-e, the G8 pass condition).

Syntactic detection is not coverage: the mutation fixtures measure recall and the
runtime tripwire (``workflow/agent_tripwire.py``) catches dynamic paths.

    python -m ravel.validation.check_agent_paths census [--write | --check]
    python -m ravel.validation.check_agent_paths report
    ravel release check --gate G8 [--mode report|block_new|empty] [--out FILE]
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1]
DATA = SRC / "data" / "agents"
CALL_SITES = DATA / "call_sites.json"
SANCTIONED = DATA / "sanctioned.json"
BASELINE = DATA / "bypass_baseline.json"
SINK_LIST = SRC / "data" / "graphs" / "consequential_sinks.json"
TRANSPORTS = SRC / "data" / "transports"
PROVIDERS = SRC / "data" / "gates" / "providers.json"

SINKS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
DISPOSITIONS = ("transport", "substrate", "registered_graph", "cli_entry", "non_model", "bypass")
ROW_FIELDS = ("path", "line", "qualname", "sink", "target", "disposition", "graph_id", "gate", "fix_package")
MODES = ("report", "block_new", "empty")
HOST_SURFACES = ("claude", "codex", "antigravity", "gemini", "opencode")
TRIPWIRE = "ravel.workflow.agent_tripwire.check"

S1_CALLS = frozenset({
    "ravel.workflow.agent_host.AgentHost.execute",
    "ravel.workflow.provider_transport.request",
    "ravel.workflow.cli_agent_host.invoke", "ravel.workflow.cli_agent_host.answer",
    "ravel.workflow.cli_agent_host.answer_graph", "ravel.workflow.cli_agent_host.serve",
})
NET_PREFIXES = ("urllib.request.", "http.client.", "httpx.", "requests.")
NET_INERT = frozenset({"urllib.request.Request", "urllib.request.pathname2url", "urllib.request.url2pathname",
                       "httpx.Timeout", "httpx.Limits", "httpx.URL", "http.client.responses"})
# Process launches and the position of their program/argv argument.
LAUNCH_CALLS = {
    "subprocess.run": 0, "subprocess.Popen": 0, "subprocess.call": 0, "subprocess.check_call": 0,
    "subprocess.check_output": 0, "subprocess.getoutput": 0, "subprocess.getstatusoutput": 0,
    "os.system": 0, "os.popen": 0, "os.execv": 0, "os.execvp": 0, "os.execve": 0, "os.execvpe": 0,
    "os.execl": 0, "os.execlp": 0, "os.spawnv": 1, "os.spawnvp": 1, "os.posix_spawn": 0, "os.posix_spawnp": 0,
    "asyncio.create_subprocess_exec": 0, "asyncio.create_subprocess_shell": 0, "pty.spawn": 0,
    "ravel.workflow.launch_authorization.authorized_popen": 2,
}
LAUNCH_KEYWORDS = ("args", "command", "cmd", "argv")
DESIGN_LAUNCHERS = ("claude", "codex", "gemini", "opencode", "agy", "qwen")
LANGGRAPH_NAMES = frozenset({"StateGraph", "Send", "interrupt", "Command", "ToolNode", "create_react_agent",
                             "entrypoint", "task"})
S3_CALLS = frozenset({
    "ravel.workflow.agent_graph.create", "ravel.workflow.agent_graph.execute",
    "ravel.workflow.agent_graph.prepare_external", "ravel.workflow.agent_graph.deliver_external",
    "ravel.workflow.research_cycle.execute_graph",
    "ravel.workflow.agent_worker.dispatch", "ravel.workflow.agent_worker.dispatch_map",
    "ravel.workflow.work_dispatch.dispatch",
})
S4_MODULES = ("anthropic", "openai", "google.genai", "google.generativeai", "litellm", "langchain_openai",
              "langchain_anthropic", "mistralai", "cohere", "ollama", "claude_agent_sdk", "agents")
S4_PREFIXES = ("langchain_google_",)
S5_MODULES = ("autogen",)
# Retired upstream agent frameworks, named only by the sha256 of their top-level module name.
S5_MODULE_DIGESTS = frozenset({
    "f77a517aa3e6c60468399eb922d3ee5a15920255eb287763c05fdaee19fd95cc",
    "ad90141574cf32aae3f1d5a9219df6b6fa9b22fafee1d984e756512b95f0fa5f",
})
S5_ATTRS = frozenset({"ReviewLoop"})
# Instruction text read from somewhere other than a rendered role card.
INSTRUCTION_SOURCES = frozenset({"ravel.workflow.research_protocol.instruction"})
DYNAMIC_IMPORTS = frozenset({"importlib.import_module", "builtins.__import__", "__import__"})
EFFECT_FACTORY = "ravel.workflow.graph_nodes.effect"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load(path):
    return json.loads(Path(path).read_text())


def load_sanctioned(path=SANCTIONED):
    return _load(path)


def load_baseline(path=BASELINE):
    return _load(path)


@lru_cache(maxsize=None)
def launchers():
    found = set(DESIGN_LAUNCHERS)
    for path in sorted(TRANSPORTS.glob("*.json")):
        value = _load(path).get("launcher")
        if isinstance(value, str) and value:
            found.add(value)
    return frozenset(found)


@lru_cache(maxsize=None)
def _sink_rows():
    return json.dumps(_load(SINK_LIST)["sinks"])


def consequential_sinks():
    """Dotted call target -> gates, for rows naming ``module:qualname`` (broker actions are not calls)."""
    table = {}
    for row in json.loads(_sink_rows()):
        if ":" in row["sink"]:
            module, qualname = row["sink"].split(":", 1)
            table[f"{module}.{qualname}"] = tuple(row["gates"])
    return table


def _matches_module(name, modules, prefixes=()):
    return any(name == m or name.startswith(m + ".") for m in modules) or name.startswith(prefixes or ("\0",))


def _is_s5_module(name):
    return (_matches_module(name, S5_MODULES)
            or hashlib.sha256(name.split(".", 1)[0].encode()).hexdigest() in S5_MODULE_DIGESTS)


def _string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _Census(ast.NodeVisitor):
    """One file. ``effect_runs`` comes from a first pass: function name -> gate named by ``effect(run=...)``."""

    def __init__(self, module, path, *, is_package, launchers, s7, effect_runs=None, watch=()):
        self.module, self.path = module, path
        self.package = module if is_package else module.rpartition(".")[0]
        self.launchers, self.s7, self.watch = launchers, s7, frozenset(watch)
        self.effect_runs = dict(effect_runs or {})
        self.found_runs, self.effect_lambdas = {}, {}
        self.stack, self.scopes, self.effects = [], [{}], []
        self.returns, self.rows, self.watched = {}, [], []
        self.imports_langgraph = False

    # ---- names -----------------------------------------------------------------
    def qualname(self):
        return f"{self.module}:{'.'.join(self.stack) or '<module>'}"

    def bind(self, name, value):
        self.scopes[-1][name] = value

    def lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def absolute(self, module, level):
        if not level:
            return module or ""
        base = self.package.split(".")
        base = base[:len(base) - (level - 1)] if level > 1 else base
        return ".".join(base + ([module] if module else []))

    def resolve(self, node):
        """``("alias", dotted)`` for a name/attribute, ``("instance", dotted)`` for a constructed value."""
        if isinstance(node, ast.Name):
            found = self.lookup(node.id)
            return found if found and found[0] in ("alias", "instance") else None
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value)
            return ("alias", f"{base[1]}.{node.attr}") if base else None
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
                base, attribute = self.resolve(node.args[0]), _string(node.args[1])
                return ("alias", f"{base[1]}.{attribute}") if base and attribute else None
            callee = self.resolve(node.func)
            if callee and callee[0] == "alias":
                return self.returns.get(callee[1], ("instance", callee[1]))
        return None

    def first_token(self, node):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            head = node.elts[0]
            return self.first_token(head.value if isinstance(head, ast.Starred) else head)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.first_token(node.left)
        if isinstance(node, ast.Name):
            found = self.lookup(node.id)
            return found[1] if found and found[0] in ("token", "literal") else None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.split()[0] if node.value.split() else None
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
            text = str(node.values[0].value)
            parts = text.split()
            # f"claude{x}" leaves the program name open; f"claude -p {x}" does not.
            return parts[0] if parts and (len(parts) > 1 or text[-1:].isspace()) else None
        if isinstance(node, ast.Call) and node.args:
            callee = self.resolve(node.func)
            if callee and callee[1] in ("shlex.split", "list", "tuple"):
                return self.first_token(node.args[0])
        return None

    def instruction_literal(self, node):
        """Instruction text the author wrote or read from a prompt file, not one a card renderer produced."""
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str) and bool(node.value.strip())
        if isinstance(node, ast.JoinedStr):
            return any(isinstance(v, ast.Constant) and str(v.value).strip() for v in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            return self.instruction_literal(node.left) or self.instruction_literal(node.right)
        if isinstance(node, ast.Name):
            found = self.lookup(node.id)
            return bool(found and found[0] == "literal")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                return self.instruction_literal(node.func.value)
            callee = self.resolve(node.func)
            return bool(callee and callee[0] == "alias" and callee[1] in INSTRUCTION_SOURCES)
        return False

    # ---- rows ------------------------------------------------------------------
    def emit(self, node, sink, target):
        row = {"path": self.path, "line": node.lineno, "qualname": self.qualname(), "sink": sink, "target": target}
        if sink == "S7":
            row["effect_gate"] = self.effects[-1] if self.effects else False
        self.rows.append(row)

    def import_row(self, node, name):
        if _matches_module(name, S4_MODULES, S4_PREFIXES):
            self.emit(node, "S4", name)
        elif _is_s5_module(name):
            self.emit(node, "S5", name)
        if name == "langgraph" or name.startswith("langgraph."):
            self.imports_langgraph = True

    def visit_Import(self, node):
        for alias in node.names:
            self.import_row(node, alias.name)
            if alias.asname:
                self.bind(alias.asname, ("alias", alias.name))
            else:
                head = alias.name.split(".")[0]
                self.bind(head, ("alias", head))

    def visit_ImportFrom(self, node):
        base = self.absolute(node.module, node.level)
        self.import_row(node, base)
        for alias in node.names:
            if alias.name == "*":
                continue
            if alias.name in S5_ATTRS:
                self.emit(node, "S5", f"{base}.{alias.name}")
            elif not (_matches_module(base, S4_MODULES, S4_PREFIXES) or _is_s5_module(base)):
                self.import_row(node, f"{base}.{alias.name}")  # from google import genai
            self.bind(alias.asname or alias.name, ("alias", f"{base}.{alias.name}"))

    def visit_Attribute(self, node):
        if node.attr in S5_ATTRS:
            self.emit(node, "S5", node.attr)
        self.generic_visit(node)

    def visit_Call(self, node):
        resolved = self.resolve(node.func)
        dotted = resolved[1] if resolved and resolved[0] == "alias" else None
        if dotted is None and isinstance(node.func, ast.Name) and node.func.id == "__import__":
            dotted = "__import__"
        if dotted:
            self.classify(node, dotted)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "compile":
            receiver = self.resolve(node.func.value)
            if receiver and receiver[0] == "instance" and receiver[1].endswith(".StateGraph"):
                self.emit(node, "S2", "langgraph.graph.StateGraph.compile")
            elif receiver is None and self.imports_langgraph:
                self.emit(node, "S2", "StateGraph.compile")
        if dotted == EFFECT_FACTORY or (self.module == "ravel.workflow.graph_nodes" and dotted ==
                                        "ravel.workflow.graph_nodes.effect"):
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            gate = _string(keywords["gate"]) if "gate" in keywords else None
            run = keywords.get("run")
            if isinstance(run, ast.Name):
                self.found_runs[run.id] = gate
            elif isinstance(run, ast.Lambda):
                self.effect_lambdas[id(run)] = gate
        self.generic_visit(node)

    def classify(self, node, dotted):
        if dotted in self.watch:
            self.watched.append(self.qualname())
        if dotted in S1_CALLS:
            self.emit(node, "S1", dotted)
        elif any(dotted.startswith(p) and "." not in dotted[len(p):] for p in NET_PREFIXES) and \
                dotted not in NET_INERT:
            self.emit(node, "S1", dotted)
        if dotted in LAUNCH_CALLS:
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            index = LAUNCH_CALLS[dotted]
            argv = node.args[index] if len(node.args) > index else next(
                (keywords[k] for k in LAUNCH_KEYWORDS if k in keywords), None)
            token = self.first_token(argv) if argv is not None else None
            if token and os.path.basename(token) in self.launchers:
                self.emit(node, "S1", f"launch:{os.path.basename(token)}")
        if dotted.startswith("langgraph.") and dotted.rsplit(".", 1)[-1] in LANGGRAPH_NAMES:
            self.emit(node, "S2", dotted)
        if dotted in S3_CALLS:
            self.emit(node, "S3", dotted)
        if dotted in DYNAMIC_IMPORTS and node.args and _string(node.args[0]):
            name = _string(node.args[0])
            if _matches_module(name, S4_MODULES, S4_PREFIXES):
                self.emit(node, "S4", name)
            elif _is_s5_module(name):
                self.emit(node, "S5", name)
        if dotted in self.s7:
            self.emit(node, "S7", dotted)

    def visit_Dict(self, node):
        for key, value in zip(node.keys, node.values):
            if key is not None and _string(key) == "instructions" and self.instruction_literal(value):
                self.emit(value, "S6", "instructions")
        self.generic_visit(node)

    def _instruction_targets(self, targets, value):
        for target in targets:
            if (isinstance(target, ast.Subscript) and _string(target.slice) == "instructions"
                    and self.instruction_literal(value)):
                self.emit(target, "S6", "instructions")

    def visit_Assign(self, node):
        self.visit(node.value)
        self._instruction_targets(node.targets, node.value)
        for target in node.targets:
            self.visit(target)
            if isinstance(target, ast.Name):
                self.bind_value(target.id, node.value)

    def visit_AugAssign(self, node):
        self.visit(node.value)
        self._instruction_targets([node.target], node.value)
        self.visit(node.target)
        if isinstance(node.target, ast.Name) and self.instruction_literal(node.value):
            self.bind(node.target.id, ("literal", None))

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
            self._instruction_targets([node.target], node.value)
            if isinstance(node.target, ast.Name):
                self.bind_value(node.target.id, node.value)
        self.visit(node.target)

    def bind_value(self, name, value):
        resolved = self.resolve(value)
        if resolved:
            self.bind(name, resolved)
            return
        token = self.first_token(value) if isinstance(value, (ast.List, ast.Tuple, ast.BinOp, ast.Constant,
                                                               ast.JoinedStr)) else None
        if token and isinstance(value, (ast.List, ast.Tuple)) or (token and isinstance(value, ast.BinOp)
                                                                 and isinstance(value.left, (ast.List, ast.Tuple))):
            self.bind(name, ("token", token))
        elif self.instruction_literal(value):
            # A string is both a possible shell command and possible instruction text.
            self.bind(name, ("literal", token))
        else:
            self.bind(name, ("value", None))

    # ---- scopes ----------------------------------------------------------------
    def _decorators(self, node):
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                self.visit(decorator)
                continue
            resolved = self.resolve(decorator)
            if resolved and resolved[0] == "alias":
                self.classify(decorator, resolved[1])
            self.visit(decorator)

    def _function(self, node):
        self._decorators(node)
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
            self.visit(default)
        self.bind(node.name, ("alias", f"{self.module}.{'.'.join(self.stack + [node.name])}"))
        self.stack.append(node.name)
        scope = {}
        arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        for arg in arguments + [a for a in (node.args.vararg, node.args.kwarg) if a]:
            annotation = self.resolve(arg.annotation) if arg.annotation is not None else None
            scope[arg.arg] = ("instance", annotation[1]) if annotation and annotation[0] == "alias" else (
                "value", None)
        self.scopes.append(scope)
        entered = len(self.stack) <= 2 and node.name in self.effect_runs
        if entered:
            self.effects.append(self.effect_runs[node.name])
        for statement in node.body:
            self.visit(statement)
        if entered:
            self.effects.pop()
        self.scopes.pop()
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node):
        gate = self.effect_lambdas.get(id(node), False)
        if gate is not False:
            self.effects.append(gate)
        self.generic_visit(node)
        if gate is not False:
            self.effects.pop()

    def visit_ClassDef(self, node):
        self._decorators(node)
        for base in node.bases:
            self.visit(base)
        self.bind(node.name, ("alias", f"{self.module}.{'.'.join(self.stack + [node.name])}"))
        self.stack.append(node.name)
        self.scopes.append({})
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()
        self.stack.pop()

    def prepare(self, tree):
        """Module-level names, imports and constructor helpers, so order of definition does not matter."""
        for statement in tree.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.bind(statement.name, ("alias", f"{self.module}.{statement.name}"))
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    self.bind(alias.asname or alias.name.split(".")[0],
                              ("alias", alias.name if alias.asname else alias.name.split(".")[0]))
            elif isinstance(statement, ast.ImportFrom):
                base = self.absolute(statement.module, statement.level)
                for alias in statement.names:
                    if alias.name != "*":
                        self.bind(alias.asname or alias.name, ("alias", f"{base}.{alias.name}"))
        for statement in tree.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                returned = [n.value for n in ast.walk(statement) if isinstance(n, ast.Return) and n.value is not None]
                kinds = {self.resolve(v) for v in returned if isinstance(v, ast.Call)}
                if returned and len(kinds) == 1 and None not in kinds and len(returned) == sum(
                        isinstance(v, ast.Call) for v in returned):
                    self.returns[f"{self.module}.{statement.name}"] = next(iter(kinds))
        self.scopes = [dict(self.scopes[0])]


def _module_name(relative: Path):
    parts = list(relative.with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def scan_source(text, *, module, path, is_package=False, watch=()):
    """Unclassified rows of one source text placed at ``module``; raises on a syntax error."""
    tree = ast.parse(text, filename=path)
    options = dict(is_package=is_package, launchers=launchers(), s7=consequential_sinks(), watch=watch)
    first = _Census(module, path, **options)
    first.prepare(tree)
    first.visit(tree)
    second = _Census(module, path, effect_runs=first.found_runs, **options)
    second.effect_lambdas = first.effect_lambdas
    second.prepare(tree)
    second.visit(tree)
    unique = {(r["line"], r["sink"], r["target"], r["qualname"]): r for r in second.rows}
    rows = sorted(unique.values(), key=lambda r: (r["path"], r["line"], r["sink"], r["target"], r["qualname"]))
    return (rows, second.watched) if watch else rows


def classify(rows, sanctioned, baseline=None):
    """Attach the disposition, graph id, gate and fixing package to raw rows."""
    baseline = load_baseline() if baseline is None else baseline
    owners = {(e["qualname"], e["sink"]): e for e in baseline["entries"]}
    sanctions = {}
    for entry in sanctioned["sanctioned"]:
        for sink in entry["sinks"]:
            sanctions[(entry["qualname"], sink)] = entry
    gates = consequential_sinks()
    result = []
    for raw in rows:
        row = {k: raw[k] for k in ("path", "line", "qualname", "sink", "target")}
        row.update(disposition="bypass", graph_id=None, gate=None, fix_package=None)
        effect_gate = raw.get("effect_gate", False)
        sanction = sanctions.get((row["qualname"], row["sink"]))
        if row["sink"] == "S7" and effect_gate is not False:
            row["gate"] = effect_gate
            if effect_gate in gates.get(row["target"], ()):
                row["disposition"] = "substrate"
        elif sanction is not None and (not sanction.get("targets") or row["target"] in sanction["targets"]):
            row.update(disposition=sanction["disposition"], graph_id=sanction.get("graph_id"),
                       gate=sanction.get("gate"))
        if row["disposition"] == "bypass":
            owner = owners.get((row["qualname"], row["sink"]))
            row["fix_package"] = owner["fix_package"] if owner else None
            row["graph_id"] = owner.get("graph_id") if owner else None
        result.append(row)
    return result


def _files(root=SRC):
    return sorted(p for p in Path(root).rglob("*.py") if "__pycache__" not in p.parts)


def census(root=SRC):
    files = _files(root)
    relatives = [p.relative_to(Path(root).parent).as_posix() for p in files]
    rows = []
    for path, relative in zip(files, relatives):
        module, is_package = _module_name(Path(relative))
        rows.extend(scan_source(path.read_text(encoding="utf-8"), module=module, path=relative,
                                is_package=is_package))
    rows = classify(rows, load_sanctioned())
    summary = Counter(f"{r['sink']}:{r['disposition']}" for r in rows)
    return {"schema_version": 1, "kind": "agent-call-sites", "generator": "ravel.validation.check_agent_paths",
            "files_scanned": len(files), "files_sha256": digest(relatives),
            "summary": dict(sorted(summary.items())), "rows": rows}


def render(document) -> bytes:
    return (json.dumps(document, indent=1, sort_keys=True) + "\n").encode()


def compare(document, baseline):
    bypasses = {}
    for row in document["rows"]:
        if row["disposition"] == "bypass":
            bypasses.setdefault((row["qualname"], row["sink"]), row)
    listed = {(e["qualname"], e["sink"]) for e in baseline["entries"]}
    new = [{"qualname": q, "sink": s, "path": bypasses[(q, s)]["path"], "line": bypasses[(q, s)]["line"],
            "target": bypasses[(q, s)]["target"]} for q, s in sorted(set(bypasses) - listed)]
    stale = [{"qualname": q, "sink": s} for q, s in sorted(listed - set(bypasses))]
    by_package = Counter(e["fix_package"] for e in baseline["entries"])
    return {"new_bypasses": new, "stale_entries": stale, "baseline_entries": len(baseline["entries"]),
            "by_fix_package": dict(sorted(by_package.items()))}


# ---- graph introspection (test 4) -------------------------------------------------------

def _dominated(builder, target, gate_name):
    """Whether a gate node for ``gate_name`` lies on every static path from START to ``target``."""
    successors = {}
    for start, end in builder.edges:
        successors.setdefault(start, set()).add(end)
    for starts, end in builder.waiting_edges:
        for start in starts:
            successors.setdefault(start, set()).add(end)
    for source, found in builder.branches.items():
        for spec in found.values():
            successors.setdefault(source, set()).update((spec.ends or {}).values())
    blocked = {n for n, spec in builder.nodes.items()
               if (spec.metadata or {}).get("ravel_kind") == "gate" and spec.metadata.get("gate") == gate_name}
    seen, frontier = set(), ["__start__"]
    while frontier:
        node = frontier.pop()
        if node in seen or node in blocked:
            continue
        seen.add(node)
        frontier.extend(successors.get(node, ()))
    return target not in seen


def _materialized(graph_id, instance, scope_root):
    """Create the retained root a builder reads from its instance, as the real creator would.

    ``introspection_roots`` in ``data/agents/sanctioned.json`` holds the synthetic agent-graph
    specification of a graph whose builder loads a retained root; the root is created under
    the walk's own scope with ``agent_graph.create``, never a path outside it."""
    declared = load_sanctioned().get("introspection_roots", {}).get(graph_id)
    if declared is None:
        return instance
    from ravel.workflow import agent_graph
    root = scope_root / "introspection-root" / graph_id.replace(".", "-")
    root.parent.mkdir(parents=True, exist_ok=True)
    agent_graph.create(root, declared["spec"])
    instance[declared["instance_key"]] = root  # the builder reads the root as a Path
    return instance


def introspect_graph(row, *, scope_root):
    """Build one registered graph with its synthetic instance and walk it (§7.2 test 4)."""
    from ravel.workflow import graph_nodes, graph_registry, graph_substrate as gs, role_registry
    problems, dominance, consequential = [], {}, []
    instance = load_sanctioned().get("introspection_instances", {}).get(row["id"])
    if instance is None:
        return {"problems": [f"{row['id']}: no introspection instance in data/agents/sanctioned.json"],
                "gate_dominance": {}, "consequential_effects": []}
    instance = _materialized(row["id"], dict(instance), Path(scope_root))
    ctx = gs.BuildContext(scope_root=Path(scope_root), graph_id=row["id"], version=row["version"],
                          instance=instance, row=row)
    builder = graph_registry.builder(row)(ctx)
    expected = None if row["structure_sha256"] == graph_registry.PIN else row["structure_sha256"]
    try:
        compiled = gs.finish(builder, row["id"], expected_structure=expected)
    except Exception as exc:  # a refusal is the finding
        return {"problems": [f"{row['id']}: build refused: {exc}"], "gate_dominance": {}, "consequential_effects": []}
    problems.extend(gs.lint_graph(compiled))
    if expected is not None and compiled.structure_sha256 != expected:
        problems.append(f"{row['id']}: structure digest differs from the registry row")
    names = {n for n in builder.nodes if not n.startswith("__")}
    for required in graph_nodes.REQUIRED_NODES:
        if required not in names:
            problems.append(f"{row['id']}: no {required} node")
    for source, found in builder.branches.items():
        for name, spec in found.items():
            if spec.ends is None:
                problems.append(f"{row['id']}: branch {name} from {source} has no path_map")
    for name in sorted(names):
        spec = builder.nodes[name]
        metadata = spec.metadata or {}
        runnable = type(getattr(spec, "runnable", None)).__name__
        if runnable == "ToolNode" and not _gated_tool_node(spec.runnable):
            problems.append(f"{row['id']}: tool node {name} does not wrap calls with ravel_gate")
        if runnable.endswith("ChatModel") and runnable != "RavelTransportChatModel":
            problems.append(f"{row['id']}: model node {name} is {runnable}, not RavelTransportChatModel")
        if metadata.get("ravel_kind") == "effect" and metadata.get("gate"):
            consequential.append(name)
            dominance[name] = _dominated(builder, name, metadata["gate"])
    for role in row.get("roles", []):
        try:
            role_registry.load(role)
        except Exception as exc:
            problems.append(f"{row['id']}: role {role} has no registered card ({exc})")
    providers = {p["id"] for p in _load(PROVIDERS)["providers"]}
    for gate_name, gate in row.get("gates", {}).items():
        missing = sorted(set(gate.get("required_providers", [])) - providers)
        if missing:
            problems.append(f"{row['id']}: gate {gate_name} requires unknown providers {missing}")
    schemas = set(graph_registry.schema_ids())
    for kind in row.get("interrupts", []):
        if kind not in schemas:
            problems.append(f"{row['id']}: interrupt {kind} has no registered response schema")
    for kind in builder.__dict__.get("_ravel_interrupts", {}).values():
        # The framework's own interrupts (reconcile evidence, proposer answers) are in every builder.
        if kind not in row.get("interrupts", []) and kind not in graph_nodes.UNGATED_INTERRUPTS:
            problems.append(f"{row['id']}: interrupt {kind} is not declared on the registry row")
        if kind not in schemas:
            problems.append(f"{row['id']}: interrupt {kind} has no registered response schema")
    module = row["module"]
    for site in _load(CALL_SITES)["rows"] if CALL_SITES.exists() else ():
        if site["qualname"].startswith(module + ":") and site["sink"] == "S7" and site["disposition"] == "bypass":
            problems.append(f"{row['id']}: consequential call {site['qualname']} outside a gated effect")
    return {"problems": problems, "gate_dominance": dominance, "consequential_effects": consequential}


def _gated_tool_node(node):
    from ravel.workflow import tool_gate
    return isinstance(getattr(node, "_wrap_tool_call", None) or getattr(node, "wrap_tool_call", None), tool_gate.Gate)


def per_use_builders():
    """Per-use builders (``agent``, ``ravel_loop``, item subgraphs) available for the walk.

    None is registered at this base; the loop transport and the research board add them here with stub transports."""
    return []


# ---- runtime tripwire (test 5) ----------------------------------------------------------

def tripwire_coverage(document=None):
    """Which lowest-layer callables call ``agent_tripwire.check`` in their own body."""
    covered, missing = [], []
    for layer in load_sanctioned()["tripwire_layers"]:
        module, qualname = layer["callable"].split(":", 1)
        relative = Path(*module.split(".")).with_suffix(".py")
        path = SRC.parent / relative
        _, watched = scan_source(path.read_text(encoding="utf-8"), module=module, path=relative.as_posix(),
                                 watch=(TRIPWIRE,))
        (covered if f"{module}:{qualname}" in watched else missing).append(layer["layer"])
    return {"covered": covered, "missing": missing}


def tripwire_chains():
    """Workload chains and fixtures to run under ``RAVEL_AGENT_TRIPWIRE=1``; none at this base."""
    return []


# ---- host surfaces (test 6) -------------------------------------------------------------

def host_surface_problems():
    from ravel.workflow import role_registry
    problems = []
    capabilities = role_registry.host_capabilities()["surfaces"]
    cards = [c for c in role_registry.all_cards() if c["requires"]["attestation_min"] == "transport"]
    for surface in HOST_SURFACES:
        files = role_registry.render(surface)
        paths = role_registry.profile_paths(surface)
        for card in cards:
            content = files.get(paths[card["id"]], "")
            redirect = f"Do not perform this role here. Run `ravel work dispatch --role {card['id']}`."
            if redirect not in content:
                problems.append(f"{surface}/{card['id']}: profile lacks the work dispatch redirect")
            if "Contract:" in content:
                problems.append(f"{surface}/{card['id']}: profile carries the role contract and can run locally")
            for key in capabilities.get(surface, {}).get("redirect_fields", {}):
                if key not in content:
                    problems.append(f"{surface}/{card['id']}: profile lacks the no-spawn field {key}")
    return problems


# ---- gate record ------------------------------------------------------------------------

def gate_record(mode=None):
    baseline = load_baseline()
    mode = mode or baseline["enforcement"]
    document = census()
    report = compare(document, baseline)
    current = CALL_SITES.exists() and CALL_SITES.read_bytes() == render(document)
    chains = tripwire_chains()
    coverage = tripwire_coverage(document)
    reasons = []
    if not current:
        reasons.append("call_sites.json is not the regenerated census")
    if report["new_bypasses"]:
        reasons.append(f"{len(report['new_bypasses'])} bypass rows are not in the baseline")
    if report["stale_entries"]:
        reasons.append(f"{len(report['stale_entries'])} baseline entries no longer match a call site")
    if report["baseline_entries"]:
        reasons.append(f"the bypass baseline still holds {report['baseline_entries']} entries")
    if coverage["missing"]:
        reasons.append("lowest layers without the tripwire: " + ", ".join(coverage["missing"]))
    if not chains:
        reasons.append("no runtime tripwire record for any fixture chain (awaits workload chains)")
    reasons.append("tests/conformance/test_agent_paths.py results are recorded by the gate runner, not here")
    passed = not reasons
    return {"gate": "G8", "mode": mode, "passed": passed, "census_current": current,
            "files_scanned": document["files_scanned"], "summary": document["summary"],
            "baseline_entries": report["baseline_entries"], "by_fix_package": report["by_fix_package"],
            "new_bypasses": len(report["new_bypasses"]), "stale_entries": len(report["stale_entries"]),
            "new_bypass_rows": report["new_bypasses"], "stale_entry_rows": report["stale_entries"],
            "tripwire_layers": coverage, "tripwire_chains": chains, "blocking_reasons": reasons,
            "claim": "Static census plus mutation recall; not proof that no dynamic path escapes."}


def _exit_code(record):
    if record["mode"] == "report":
        return 0
    if record["mode"] == "block_new":
        return 1 if (record["new_bypasses"] or record["stale_entries"] or not record["census_current"]) else 0
    return 0 if record["passed"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ravel release", description="G8 agent call-site conformance")
    commands = parser.add_subparsers(dest="command", required=True)
    regenerate = commands.add_parser("census", help="regenerate src/ravel/data/agents/call_sites.json")
    regenerate.add_argument("--write", action="store_true")
    regenerate.add_argument("--check", action="store_true")
    commands.add_parser("report", help="bypass comparison against the baseline")
    check = commands.add_parser("check", help="release gate record (G8 only until REL-G)")
    check.add_argument("--gate", required=True)
    check.add_argument("--mode", choices=MODES)
    check.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "census":
        document = render(census())
        if args.write:
            CALL_SITES.write_bytes(document)
            return 0
        if args.check:
            current = CALL_SITES.exists() and CALL_SITES.read_bytes() == document
            if not current:
                print("call_sites.json is stale; rerun with --write", file=sys.stderr)
            return 0 if current else 1
        sys.stdout.write(document.decode())
        return 0
    if args.command == "report":
        print(json.dumps(compare(census(), load_baseline()), indent=1, sort_keys=True))
        return 0
    if args.gate.upper() != "G8":
        print(f"gate {args.gate}: this command records G8 only", file=sys.stderr)
        return 2
    record = gate_record(args.mode)
    text = json.dumps(record, indent=1, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    sys.stdout.write(text)
    return _exit_code(record)


if __name__ == "__main__":
    raise SystemExit(main())
