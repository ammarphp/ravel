"""Enumerate registered graph node declarations without importing graph code.

This is a bounded syntax interpreter, not a graph builder. It follows local
declaration helpers and finite source vocabularies; runtime-dependent node names
remain explicit gaps. Callback and lambda bodies are declarations only when the
builder actually invokes them as a node-registration helper.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import json
from pathlib import Path

from documentation_parsers import Declarations, Expression, Imported


LIMIT = 1000


@dataclass
class Function:
    reader: object
    node: object
    env: dict


@dataclass(frozen=True)
class Builder:
    pass


class GraphDeclarations(Declarations):
    """The parser evaluator plus finite graph-vocabulary expressions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.globals['__file__'] = str(self.path.resolve())

    def imported(self, value):
        if not isinstance(value, Imported):
            return value
        path = self.root / 'src' / Path(*value.module.split('.'))
        if value.name and (path / (value.name + '.py')).is_file():
            return Imported(value.module + '.' + value.name)
        source = path.with_suffix('.py')
        if not source.is_file():
            source = path / '__init__.py'
        if not source.is_file():
            return value
        reader = self.readers.get(value.module)
        if reader is None:
            reader = GraphDeclarations(self.root, source, readers=self.readers)
            self.readers[value.module] = reader
        if hasattr(self, 'data_loader'):
            reader.data_loader = self.data_loader
        if value.name and value.name not in reader.functions:
            return reader.value(ast.Name(id=value.name), reader.globals)
        return value

    def value(self, node, env):
        if isinstance(node, ast.Attribute):
            parent = self.value(node.value, env)
            if isinstance(parent, Path) and node.attr in ('parent', 'parents', 'name', 'stem'):
                return getattr(parent, node.attr)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            result = []

            def expand(index, local):
                if len(result) > LIMIT:
                    raise ValueError('comprehension bound')
                if index == len(node.generators):
                    if isinstance(node, ast.DictComp):
                        result.append((self.value(node.key, local), self.value(node.value, local)))
                    else:
                        result.append(self.value(node.elt, local))
                    return
                generator = node.generators[index]
                values = self.value(generator.iter, local)
                if generator.is_async or not isinstance(values, (tuple, list, set, dict)) or len(values) > LIMIT:
                    raise ValueError('unresolved comprehension iterable')
                for item in values:
                    child = dict(local)
                    self.bind(generator.target, item, child)
                    conditions = [self.value(test, child) for test in generator.ifs]
                    if any(type(condition) is not bool for condition in conditions):
                        raise ValueError('unresolved comprehension condition')
                    if all(conditions):
                        expand(index + 1, child)
            try:
                expand(0, dict(env))
                if isinstance(node, ast.DictComp):
                    return dict(result)
                return set(result) if isinstance(node, ast.SetComp) else result
            except (ValueError, TypeError):
                return self.expression(node)
        if isinstance(node, ast.Call):
            args = [self.value(arg, env) for arg in node.args]
            function = self.value(node.func, env)
            loader = getattr(self, 'data_loader', None)
            if loader is not None and isinstance(function, Imported):
                data = loader(function)
                if data is not None:
                    return data
            if ((isinstance(node.func, ast.Name) and node.func.id == 'Path') or
                    isinstance(function, Imported) and function.module == 'pathlib' and function.name == 'Path'):
                if args and all(isinstance(arg, (str, Path)) for arg in args):
                    return Path(*args)
            if isinstance(node.func, ast.Name) and node.func.id == 'range' and all(type(arg) is int for arg in args):
                try:
                    values = range(*args)
                    return list(values) if len(values) <= LIMIT else self.expression(node)
                except (ValueError, TypeError):
                    pass
            if isinstance(node.func, ast.Attribute):
                parent = self.value(node.func.value, env)
                if isinstance(parent, Path) and node.func.attr == 'resolve' and not args:
                    return parent.resolve()
                if isinstance(parent, str) and node.func.attr == 'replace' and all(isinstance(arg, str) for arg in args):
                    try:
                        return parent.replace(*args)
                    except TypeError:
                        pass
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = self.value(node.left, env), self.value(node.right, env)
            if isinstance(left, Path) and isinstance(right, str):
                return left / right
        return super().value(node, env)


class NodeDeclarations:
    def __init__(self, root, registration, readers):
        self.root = Path(root).resolve()
        self.registration, self.readers = registration, readers
        self.rows, self.gaps, self.active = {}, {}, set()
        self.data_cache = {}

    def gap(self, reader, node, reason):
        key = (reader.relative, node.lineno, ast.unparse(node), reason)
        self.gaps[key] = {'graph': self.registration['id'], 'source': reader.relative,
                          'line': node.lineno, 'expression': ast.unparse(node), 'reason': reason}

    def reader_for(self, imported):
        module = imported.module
        if module in self.readers:
            reader = self.readers[module]
            reader.data_loader = self.imported_data
            return reader
        path = self.root / 'src' / Path(*module.split('.'))
        source = path.with_suffix('.py')
        if not source.is_file():
            source = path / '__init__.py'
        if source.is_file():
            reader = GraphDeclarations(self.root, source, readers=self.readers)
            self.readers[module] = reader
            reader.data_loader = self.imported_data
            return reader
        return None

    def imported_data(self, imported):
        key = (imported.module, imported.name)
        if key in self.data_cache:
            return self.data_cache[key]
        reader = self.reader_for(imported)
        if reader is not None and imported.name in reader.functions:
            self.data_cache[key] = self.data_function(reader, reader.functions[imported.name])
            return self.data_cache[key]
        return None

    def relevant(self, reader, node, seen=(), env=None):
        """Ignore callback bodies; follow only explicit local helper calls."""
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Lambda):
            return self.relevant(reader, node.value, seen, env)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            children = [node.body] if isinstance(node, ast.Lambda) else node.body
        else:
            children = ast.iter_child_nodes(node)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == 'add_node':
                    return True
                if node.func.attr == 'add':
                    function = reader.value(node.func, env or reader.globals)
                    if (isinstance(function, Imported) and function.name == 'add'
                            and function.module.endswith('.graph_nodes')):
                        return True
            if isinstance(node.func, ast.Name):
                if node.func.id == 'add':
                    return True
                alias = (env or {}).get(node.func.id)
                if isinstance(alias, Imported) and alias.name == 'add' and alias.module.endswith('.graph_nodes'):
                    return True
                if isinstance(alias, Function) and node.func.id not in seen:
                    if self.relevant(alias.reader, alias.node, (*seen, node.func.id), alias.env):
                        return True
                helper = reader.functions.get(node.func.id)
                if helper is not None and helper.name not in seen and self.relevant(reader, helper, (*seen, helper.name)):
                    return True
        return any(self.relevant(reader, child, seen, env) for child in children
                   if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)))

    def data_function(self, reader, function):
        """Read a declaration loader's JSON and matching source-owned fragments.

        The composition vocabulary comes from the loader's imported composer's
        FILES table. No callable, validation hook or filesystem mutation runs.
        """
        loads = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'read_json' and len(node.args) == 1]
        if len(loads) != 1:
            return None
        assignments = [node for node in function.body if isinstance(node, ast.Assign)
                       and node.value is loads[0] and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)]
        returned = function.body[-1].value if isinstance(function.body[-1], ast.Return) else None
        if len(assignments) != 1 or returned is None:
            return None
        binding = assignments[0].targets[0].id
        plain = isinstance(returned, ast.Name) and returned.id == binding
        composed = (isinstance(returned, ast.Call) and isinstance(returned.func, ast.Name)
                    and len(returned.args) == 2 and isinstance(returned.args[0], ast.Name)
                    and returned.args[0].id == binding)
        if not plain and not composed:
            return None
        path = reader.value(loads[0].args[0], reader.globals)
        if not isinstance(path, Path) or not path.resolve().is_relative_to(self.root):
            return None
        try:
            if path.stat().st_size > 2_000_000:
                return None
            document = json.loads(path.read_text(encoding='utf-8'))
            if composed:
                imported = reader.globals.get(returned.func.id)
                composer = self.reader_for(imported) if isinstance(imported, Imported) else None
                if (composer is None or imported.name not in composer.functions
                        or reader.value(returned.args[1], reader.globals) != path):
                    return None
                files = composer.globals.get('FILES')
                if not isinstance(files, dict) or document.get('kind') not in files:
                    return None
                # Locate the composer's declared registration folder in its AST.
                folders = {n.value for n in ast.walk(composer.tree) if isinstance(n, ast.Constant)
                           and isinstance(n.value, str) and n.value.endswith('/registration')}
                if len(folders) != 1:
                    return None
                fragment = self.root / 'src/ravel/data' / next(iter(folders)) / files[document['kind']]
                if fragment.is_file():
                    if not fragment.resolve().is_relative_to(self.root) or fragment.stat().st_size > 2_000_000:
                        return None
                    addition = json.loads(fragment.read_text(encoding='utf-8'))
                    if addition.get('kind') != 'registry-registration' or addition.get('target') != document['kind']:
                        return None
                    for key, extra in addition['append'].items():
                        if isinstance(document.get(key), dict) and isinstance(extra, dict):
                            if set(document[key]) & set(extra):
                                return None
                            document[key].update(extra)
                        elif isinstance(document.get(key), list) and isinstance(extra, list):
                            document[key].extend(extra)
                        else:
                            return None
            return document
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def value(self, reader, node, env, origin=None):
        if node is None:
            return None
        if isinstance(node, ast.Lambda):
            return Function(reader, node, dict(env))
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if node.id in reader.functions:
                return Function(reader, reader.functions[node.id], dict(env))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'add_node':
                parent = self.value(reader, node.func.value, env)
                if isinstance(parent, Builder):
                    self.record(reader, node, self.value(reader, node.args[0], env) if node.args else None, origin)
                    return None
                self.gap(reader, node, 'Node-registration receiver is unresolved')
                return reader.expression(node)
            function = self.value(reader, node.func, env)
            if isinstance(function, Imported):
                if function.name == 'StateGraph' and function.module == 'langgraph.graph':
                    return Builder()
                if function.name == 'add' and function.module.endswith('.graph_nodes'):
                    self.record(reader, node, self.value(reader, node.args[1], env) if len(node.args) > 1 else None, origin)
                    return None
                target_reader = self.reader_for(function)
                if target_reader is not None and function.name in target_reader.functions:
                    target = target_reader.functions[function.name]
                    data = self.data_function(target_reader, target)
                    if data is not None:
                        return data
                    if self.relevant(target_reader, target):
                        function = Function(target_reader, target, dict(target_reader.globals))
            if isinstance(function, Function) and self.relevant(function.reader, function.node, env=function.env):
                args = [self.value(reader, arg, env) for arg in node.args]
                keywords = {arg.arg: self.value(reader, arg.value, env) for arg in node.keywords if arg.arg}
                site = (reader, node) if isinstance(function.node, ast.Lambda) else origin
                return self.invoke(function, args, keywords, site)
            if isinstance(node.func, ast.Name) and node.func.id == 'add':
                self.gap(reader, node, 'Node-registration helper is unresolved')
        return reader.value(node, env)

    def record(self, reader, node, name, origin):
        if origin is not None:
            reader, node = origin
        if not isinstance(name, str):
            self.gap(reader, node, 'Node name is not a finite source string')
            return
        key = (name, reader.relative, node.lineno)
        self.rows[key] = {'graph': self.registration['id'], 'name': name, 'source': reader.relative,
                          'line': node.lineno, 'builder': self.registration['builder']}

    def invoke(self, function, args, keywords, origin=None):
        reader, node = function.reader, function.node
        key = (reader.relative, node.lineno)
        if key in self.active or len(self.active) > 32:
            self.gap(reader, node, 'Recursive or over-depth declaration helper')
            return reader.expression(node)
        self.active.add(key)
        env = dict(function.env)
        parameters = [*node.args.posonlyargs, *node.args.args]
        defaults = [None] * (len(parameters) - len(node.args.defaults)) + list(node.args.defaults)
        for index, (parameter, default) in enumerate(zip(parameters, defaults)):
            env[parameter.arg] = args[index] if index < len(args) else keywords.get(
                parameter.arg, self.value(reader, default, env) if default else Expression(parameter.arg))
        for parameter, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            env[parameter.arg] = keywords.get(parameter.arg, self.value(reader, default, env))
        try:
            if isinstance(node, ast.Lambda):
                return self.value(reader, node.body, env, origin)
            return self.statements(reader, node.body, env, origin)[1]
        finally:
            self.active.remove(key)

    def statements(self, reader, body, env, origin=None):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                env[node.name] = Function(reader, node, dict(env))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                continue  # Declarations has already resolved import aliases as syntax.
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = self.value(reader, node.value, env, origin)
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    reader.bind(target, value, env)
            elif isinstance(node, ast.Expr):
                self.value(reader, node.value, env, origin)
            elif isinstance(node, ast.Return):
                return True, self.value(reader, node.value, env, origin)
            elif isinstance(node, ast.For):
                values = self.value(reader, node.iter, env)
                if isinstance(values, (tuple, list, set, dict)) and len(values) <= LIMIT:
                    for item in values:
                        reader.bind(node.target, item, env)
                        returned, value = self.statements(reader, node.body, env, origin)
                        if returned:
                            return True, value
                elif any(self.relevant(reader, child, env=env) for child in node.body):
                    self.gap(reader, node, 'Node-declaring loop iterable is not finite source data')
            elif isinstance(node, ast.If):
                condition = self.value(reader, node.test, env)
                if type(condition) is bool:
                    returned, value = self.statements(reader, node.body if condition else node.orelse, env, origin)
                    if returned:
                        return True, value
                else:
                    relevant = any(self.relevant(reader, child, env=env) for child in [*node.body, *node.orelse])
                    if relevant:
                        self.gap(reader, node.test, 'Runtime condition controls node declarations')
                    for branch in (node.body, node.orelse):
                        self.statements(reader, branch, dict(env), origin)
            elif isinstance(node, (ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)):
                if self.relevant(reader, node, env=env):
                    self.gap(reader, node, 'Unsupported control flow contains node declarations')
        return False, None


def collect_graph_nodes(root, registrations):
    """Return (node rows, unresolved source gaps) for registered builder functions."""
    root = Path(root).resolve()
    rows, gaps, readers = [], [], {}
    for registration in sorted(registrations, key=lambda row: row['id']):
        collector = NodeDeclarations(root, registration, readers)
        reader = collector.reader_for(Imported(registration['module']))
        if reader is None or registration['builder'] not in reader.functions:
            gaps.append({'graph': registration['id'], 'source': 'src/' + registration['module'].replace('.', '/') + '.py',
                         'line': 1, 'expression': registration['builder'], 'reason': 'Registered builder source is unavailable'})
            continue
        builder = reader.functions[registration['builder']]
        collector.invoke(Function(reader, builder, dict(reader.globals)), [], {})
        if not collector.rows and not collector.gaps:
            collector.gap(reader, builder, 'No node declarations resolved from the registered builder')
        rows.extend(collector.rows.values())
        gaps.extend(collector.gaps.values())
    return sorted(rows, key=lambda row: (row['graph'], row['name'], row['source'], row['line'])), sorted(
        gaps, key=lambda row: (row['graph'], row['source'], row['line'], row['expression']))
