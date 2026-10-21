"""Read argparse declarations as syntax; never import or execute command modules.

The small evaluator understands literals, finite declaration loops, parser aliases
and local parser helpers. Unknown expressions remain visible source expressions.
Every add_argument/add_parser call is accounted for, including an unresolved call
as a gap rather than silently treating it as a usable command.
"""
from __future__ import annotations

import ast
import json
import re
from itertools import product
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Expression:
    text: str


@dataclass
class Parser:
    key: str
    command: str
    source: str
    scope: str
    line: int
    conditions: tuple = ()


def display(value):
    if isinstance(value, Expression):
        return 'source: ' + value.text
    if isinstance(value, Imported):
        return 'source: ' + value.module + ('.' + value.name if value.name else '')
    if isinstance(value, Parser):
        return value.command
    if isinstance(value, (list, tuple, set)):
        return ', '.join(display(x) for x in value)
    if isinstance(value, dict):
        return '; '.join(str(k) + '=' + display(v) for k, v in value.items())
    return str(value)


@dataclass(frozen=True)
class Imported:
    module: str
    name: str = ''


class Declarations:
    def __init__(self, root, path, commands=(), readers=None, command_modules=None):
        self.root, self.path = Path(root), Path(path)
        self.relative = self.path.relative_to(self.root).as_posix()
        self.text = self.path.read_text(encoding='utf-8')
        self.tree = ast.parse(self.text)
        self.functions = {n.name: n for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.module = self.relative.removesuffix('.py').replace('/', '.').removeprefix('src.')
        self.globals = {'__doc__': ast.get_docstring(self.tree) or ''}
        self.command_modules = command_modules or {}
        self.commands = list(commands) or self.command_modules.get(self.module, [])
        self.forced = {}
        self.conditions = []
        self.data_sources = set()
        self.readers = readers if readers is not None else {}
        self.readers[self.module] = self
        self.resolved = set()
        self.assignments = {}
        self.resolving = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                base = self.module.split('.')[:-node.level] if node.level else []
                target = '.'.join([*base, *([node.module] if node.module else [])])
                for alias in node.names:
                    self.globals[alias.asname or alias.name] = Imported(target, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.globals[alias.asname or alias.name.split('.')[0]] = Imported(alias.name if alias.asname else alias.name.split('.')[0])
        self.rows, self.gaps, self.seen, self.active = {}, {}, set(), set()
        # Only literal bindings are resolved; imports and user code are never run.
        for node in self.tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    if isinstance(target, ast.Name):
                        self.assignments[target.id] = node.value
                value = self.value(node.value, self.globals)
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    self.bind(target, value, self.globals)

    def imported(self, value):
        if not isinstance(value, Imported):
            return value
        module = value.module
        path = self.root / 'src' / Path(*module.split('.'))
        if value.name and (path / (value.name + '.py')).is_file():
            return Imported(module + '.' + value.name)
        source = path.with_suffix('.py')
        if not source.is_file():
            source = path / '__init__.py'
        if not source.is_file():
            return value
        reader = self.readers.get(module)
        if reader is None:
            reader = Declarations(self.root, source, readers=self.readers, command_modules=self.command_modules)
            self.readers[module] = reader
        if value.name and value.name not in reader.functions:
            return reader.value(ast.Name(id=value.name), reader.globals)
        return value

    def data_path(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id == '__file__':
            return str(self.path)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Path' and len(node.args) == 1:
            value = self.data_path(node.args[0])
            return Path(value) if isinstance(value, str) else None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'resolve' and not node.args:
            value = self.data_path(node.func.value)
            return value.resolve() if isinstance(value, Path) else None
        if isinstance(node, ast.Attribute):
            value = self.data_path(node.value)
            if isinstance(value, Path) and node.attr in ('parent', 'parents'):
                return getattr(value, node.attr)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
            value = self.data_path(node.value)
            try:
                return value[node.slice.value]
            except (TypeError, IndexError):
                return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = self.data_path(node.left), self.data_path(node.right)
            if isinstance(left, Path) and isinstance(right, str):
                return left / right
        return None

    def expression(self, node):
        return Expression(ast.unparse(node))

    def bind(self, node, value, env):
        if isinstance(node, ast.Name):
            env[node.id] = self.forced.get(node.id, value)
        elif isinstance(node, (ast.Tuple, ast.List)) and isinstance(value, (tuple, list)):
            for target, child in zip(node.elts, value):
                self.bind(target, child, env)
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            parent = env.get(node.value.id)
            key = self.value(node.slice, env)
            if isinstance(parent, dict) and not isinstance(key, Expression):
                parent[key] = value

    def value(self, node, env):
        if node is None:
            return None
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            value = env.get(node.id, self.globals.get(node.id, self.expression(node)))
            if isinstance(value, Expression) and node.id in self.assignments and node.id not in self.resolving:
                self.resolving.add(node.id)
                value = self.value(self.assignments[node.id], env)
                self.resolving.remove(node.id)
            return self.imported(value)
        if isinstance(node, ast.Attribute):
            parent = self.value(node.value, env)
            if isinstance(parent, Imported):
                return self.imported(Imported(parent.module + ('.' + parent.name if parent.name else ''), node.attr))
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            values = [self.value(child, env) for child in node.elts]
            if any(isinstance(child, ast.Starred) for child in node.elts):
                values = []
                for child in node.elts:
                    v = self.value(child.value if isinstance(child, ast.Starred) else child, env)
                    if isinstance(child, ast.Starred) and isinstance(v, (tuple, list, set, dict)):
                        values.extend(v)
                    else:
                        values.append(v)
            return tuple(values) if isinstance(node, ast.Tuple) else values
        if isinstance(node, (ast.DictComp, ast.ListComp, ast.SetComp)) and len(node.generators) == 1:
            generator = node.generators[0]
            values = self.value(generator.iter, env)
            if isinstance(values, dict):
                values = list(values)
            if isinstance(values, (tuple, list, set)) and len(values) <= 1000:
                result = {} if isinstance(node, ast.DictComp) else []
                for item in values:
                    local = dict(env)
                    self.bind(generator.target, item, local)
                    if isinstance(node, ast.DictComp):
                        key = self.value(node.key, local)
                        if isinstance(key, (str, int)):
                            result[key] = self.value(node.value, local)
                    else:
                        result.append(self.value(node.elt, local))
                return result
        if isinstance(node, ast.Dict):
            result = {}
            for key, child in zip(node.keys, node.values):
                v = self.value(child, env)
                if key is None:
                    if isinstance(v, dict):
                        result.update(v)
                else:
                    k = self.value(key, env)
                    if isinstance(k, (str, int, float, bool, type(None))):
                        result[k] = v
            return result
        if isinstance(node, ast.Subscript):
            parent, key = self.value(node.value, env), self.value(node.slice, env)
            try:
                return parent[key]
            except (TypeError, KeyError, IndexError):
                return self.expression(node)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = self.value(node.left, env), self.value(node.comparators[0], env)
            if not isinstance(left, Expression) and not isinstance(right, Expression):
                try:
                    operation = node.ops[0]
                    if isinstance(operation, ast.Eq): return left == right
                    if isinstance(operation, ast.NotEq): return left != right
                    if isinstance(operation, ast.In): return left in right
                    if isinstance(operation, ast.NotIn): return left not in right
                    if isinstance(operation, ast.Is): return left is right
                    if isinstance(operation, ast.IsNot): return left is not right
                except TypeError:
                    pass
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            value = self.value(node.operand, env)
            if isinstance(value, bool): return not value
        if isinstance(node, ast.IfExp):
            condition = self.value(node.test, env)
            if condition is True: return self.value(node.body, env)
            if condition is False: return self.value(node.orelse, env)
        if isinstance(node, ast.BinOp):
            left, right = self.value(node.left, env), self.value(node.right, env)
            if not isinstance(left, Expression) and not isinstance(right, Expression):
                try:
                    if isinstance(node.op, ast.Add):
                        return left + right
                    if isinstance(node.op, ast.BitOr) and isinstance(left, dict) and isinstance(right, dict):
                        return left | right
                    if isinstance(node.op, ast.BitOr) and isinstance(left, (tuple, list, set)) and isinstance(right, (tuple, list, set)):
                        if all(isinstance(v, (str, int, float)) for v in [*left, *right]):
                            return list(dict.fromkeys([*left, *right]))
                except TypeError:
                    pass
        if isinstance(node, ast.JoinedStr):
            values = [self.value(c.value, env) if isinstance(c, ast.FormattedValue) else self.value(c, env)
                      for c in node.values]
            if not any(isinstance(v, Expression) for v in values):
                return ''.join(map(str, values))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'loads' and isinstance(node.func.value, ast.Name) and node.func.value.id == 'json' and len(node.args) == 1:
                read = node.args[0]
                if isinstance(read, ast.Call) and isinstance(read.func, ast.Attribute) and read.func.attr == 'read_text' and not read.args:
                    path = self.data_path(read.func.value)
                    if isinstance(path, Path):
                        path = path.resolve()
                        if path.is_relative_to(self.root) and path.suffix == '.json' and path.is_file() and path.stat().st_size <= 2_000_000:
                            self.data_sources.add(path.relative_to(self.root).as_posix())
                            return json.loads(path.read_text(encoding='utf-8'))
            args = [self.value(child, env) for child in node.args]
            if isinstance(node.func, ast.Name) and node.func.id == 'released_commands':
                return self.globals.get('FOCUSED_COMMANDS', self.expression(node))
            if isinstance(node.func, ast.Name) and node.func.id in ('tuple', 'list', 'set', 'frozenset', 'sorted', 'str'):
                if len(args) == 1 and not isinstance(args[0], (Expression, Parser)):
                    try:
                        return {'tuple': tuple, 'list': list, 'set': list, 'frozenset': list, 'sorted': sorted, 'str': str}[node.func.id](args[0])
                    except (TypeError, ValueError):
                        pass
            if isinstance(node.func, ast.Attribute):
                obj = self.value(node.func.value, env)
                if isinstance(obj, dict) and node.func.attr in ('items', 'keys', 'values') and not args:
                    return list(getattr(obj, node.func.attr)())
                if isinstance(obj, str) and node.func.attr in ('split', 'replace') and not any(isinstance(v, Expression) for v in args):
                    return getattr(obj, node.func.attr)(*args)
        return self.expression(node)

    def parser_relevant(self, node):
        return any(isinstance(child, ast.Call) and
                   ((isinstance(child.func, ast.Attribute) and child.func.attr in
                     ('ArgumentParser', 'add_argument', 'add_parser', 'add_subparsers', 'add_mutually_exclusive_group', 'add_argument_group'))
                    or isinstance(child.func, ast.Name) and child.func.id in self.functions
                    and ('parser' in child.func.id or child.func.id in ('parser', 'build_parser')))
                   for child in ast.walk(node))

    def record(self, identity, row):
        conditions = [*row.pop('_conditions', ()), *self.conditions]
        unique = {json.dumps(condition, sort_keys=True): condition for condition in conditions}
        if unique:
            row['availability'] = {'kind': 'conditional-source-declaration',
                                   'predicates': list(unique.values()),
                                   'scope': 'Runtime source predicates govern dispatch for this declaration.'}
        old = self.rows.get(identity)
        if old is not None and old.get('program_resolved') is False and row.get('program_resolved') is True:
            self.rows[identity] = row
            return
        if old is not None and old != row:
            # One declaration can be reached through helper calls. Preserve each
            # actual parser context while deduplicating a repeated walk.
            return
        self.rows[identity] = row

    def gap(self, node, reason):
        key = self.relative + ':' + str(node.lineno)
        self.gaps[key] = {'source': self.relative, 'line': node.lineno,
                          'expression': ast.unparse(node), 'reason': reason}

    def call(self, node, env, scope):
        if not isinstance(node, ast.Call):
            return self.value(node, env)
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == 'ArgumentParser':
            kwargs = {k.arg: self.value(k.value, env) for k in node.keywords}
            prog = kwargs.get('prog')
            program_resolved = isinstance(prog, str) or 'prog' not in kwargs
            if not isinstance(prog, str):
                prog = self.commands[0] if self.commands else 'python -m ' + self.module
            key = self.relative + ':' + scope + ':' + 'line-' + str(node.lineno) + ':prog-' + re.sub(r'[^A-Za-z0-9_.-]+', '-', prog)
            parser = Parser(key, prog, self.relative, scope, node.lineno, tuple(self.conditions))
            self.record('parser:' + key, {'id': 'parser:' + key, 'kind': 'parser', 'command': prog,
                        'summary': display(kwargs.get('description', 'Parser declared in ' + scope)),
                        'source': self.relative, 'line': node.lineno, 'scope': scope,
                        'program_resolved': program_resolved, 'program_expression': next((ast.unparse(k.value) for k in node.keywords if k.arg == 'prog'), 'implicit module entry point')})
            self.seen.add(node.lineno)
            return parser
        if isinstance(func, ast.Attribute) and func.attr in ('add_argument', 'add_parser', 'add_subparsers',
                                                               'add_mutually_exclusive_group', 'add_argument_group'):
            owner = self.call(func.value, env, scope) if isinstance(func.value, ast.Call) else self.value(func.value, env)
            self.seen.add(node.lineno)
            if isinstance(owner, Imported):
                imported = self.imported(Imported(owner.module + ('.' + owner.name if owner.name else ''), func.attr))
                reader = self.readers.get(imported.module) if isinstance(imported, Imported) else None
                helper = reader.functions.get(imported.name) if reader else None
                if helper is not None and reader.parser_relevant(helper):
                    local = dict(reader.globals)
                    for parameter, argument in zip(helper.args.args, node.args):
                        local[parameter.arg] = self.call(argument, env, scope)
                    self.resolved.add(node.lineno)
                    inherited_conditions = reader.conditions
                    reader.conditions = [*reader.conditions, *self.conditions]
                    result = reader.walk(helper.body, local, imported.name)
                    reader.conditions = inherited_conditions
                    return result
            if not isinstance(owner, Parser):
                self.gap(node, 'parser owner could not be resolved statically')
                return self.expression(node)
            if func.attr in ('add_subparsers', 'add_mutually_exclusive_group', 'add_argument_group'):
                self.resolved.add(node.lineno)
                return owner
            args = [self.value(a, env) for a in node.args]
            kwargs = {k.arg: self.value(k.value, env) for k in node.keywords}
            if not args or not all(isinstance(a, str) for a in args):
                self.gap(node, 'argument or command name could not be resolved statically')
                return self.expression(node)
            self.resolved.add(node.lineno)
            if func.attr == 'add_parser':
                command = owner.command + ' ' + args[0]
                key = owner.key + '/' + args[0]
                row = {'id': 'command:' + key, 'kind': 'command', 'command': command,
                       'summary': display(kwargs.get('help', kwargs.get('description', 'Subcommand declared by ' + scope))),
                       'source': self.relative, 'line': node.lineno, 'scope': scope,
                       '_conditions': owner.conditions}
                self.record(row['id'], row)
                return Parser(key, command, self.relative, scope, node.lineno, (*owner.conditions, *self.conditions))
            names = args
            if display(kwargs.get('action', '')).endswith('BooleanOptionalAction'):
                names = [*names, *['--no-' + a[2:] for a in args if a.startswith('--')]]
            identity = 'option:' + owner.key + '/' + ','.join(args)
            row = {'id': identity, 'kind': 'option', 'command': owner.command,
                     'names': names, 'summary': display(kwargs.get('help', 'Argument `' + args[0] + '`; see its source constraints.')),
                     'constraints': {k: display(v) for k, v in kwargs.items() if k not in ('help', 'formatter_class')},
                     'source': self.relative, 'line': node.lineno, 'scope': scope, '_conditions': owner.conditions}
            choices = kwargs.get('choices')
            if args[0] in ('command', 'action', 'verb', 'operation', 'subcommand') and isinstance(choices, (tuple, list, set)) and all(isinstance(choice, str) for choice in choices):
                row['dispatch_choices'] = sorted(set(choices))
            self.record(identity, row)
            return self.expression(node)
        if isinstance(func, ast.Name) and func.id in self.functions:
            helper = self.functions[func.id]
            if self.parser_relevant(helper) and func.id not in self.active:
                args = [self.call(a, env, scope) if isinstance(a, ast.Call) else self.value(a, env) for a in node.args]
                local = dict(self.globals)
                for parameter, value in zip(helper.args.args, args):
                    local[parameter.arg] = value
                for keyword in node.keywords:
                    if keyword.arg:
                        local[keyword.arg] = self.value(keyword.value, env)
                self.active.add(func.id)
                result = self.walk(helper.body, local, helper.name)
                self.active.remove(func.id)
                return result
        imported = self.value(func, env)
        if isinstance(imported, Imported) and imported.name:
            self.imported(imported)
            reader = self.readers.get(imported.module)
            helper = reader.functions.get(imported.name) if reader else None
            if helper is not None and (reader.parser_relevant(helper) or imported.name == 'main') and imported.name not in reader.active:
                args = [self.call(a, env, scope) if isinstance(a, ast.Call) else self.value(a, env) for a in node.args]
                local = dict(reader.globals)
                for parameter, value in zip(helper.args.args, args):
                    local[parameter.arg] = value
                inherited = list(reader.commands)
                if self.commands and imported.name == 'main':
                    prefix = self.commands[0]
                    if isinstance(func, ast.Name) and func.id != 'main':
                        candidate = prefix + ' ' + func.id
                        if any(row.get('command') == candidate for unit in self.readers.values() for row in unit.rows.values()):
                            prefix = candidate
                    reader.commands = [prefix]
                reader.active.add(imported.name)
                inherited_conditions = reader.conditions
                reader.conditions = [*reader.conditions, *self.conditions]
                result = reader.walk(helper.body, local, imported.name)
                reader.conditions = inherited_conditions
                reader.active.remove(imported.name)
                reader.commands = list(dict.fromkeys([*inherited, *reader.commands]))
                return result
        # Wrapper helpers may receive a parser built inline. Always retain that
        # declaration even when the wrapper itself has no parser semantics.
        for argument in node.args:
            if isinstance(argument, ast.Call):
                self.call(argument, env, scope)
        return self.value(node, env)

    def walk(self, statements, env, scope):
        result = None
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = self.call(node.value, env, scope)
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    self.bind(target, value, env)
            elif isinstance(node, ast.Expr):
                self.call(node.value, env, scope)
            elif isinstance(node, ast.Return):
                result = self.call(node.value, env, scope)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                values = self.value(node.iter, env)
                if isinstance(values, dict):
                    values = list(values)
                if isinstance(values, (tuple, list, set)) and len(values) <= 1000:
                    for item in values:
                        self.bind(node.target, item, env)
                        self.walk(node.body, env, scope)
                elif self.parser_relevant(node):
                    self.walk(node.body, env, scope)
            elif isinstance(node, (ast.If, ast.While)):
                condition = self.value(node.test, env)
                if condition is True:
                    self.walk(node.body, env, scope)
                elif condition is False:
                    self.walk(node.orelse, env, scope)
                else:
                    for branch, body in (('true', node.body), ('false', node.orelse)):
                        predicate = {'source': self.relative, 'line': node.lineno,
                                     'expression': ast.unparse(node.test), 'branch': branch}
                        self.conditions.append(predicate)
                        self.walk(body, env, scope)
                        self.conditions.pop()
            elif isinstance(node, ast.Try):
                self.walk(node.body, env, scope)
                for handler in node.handlers:
                    self.walk(handler.body, env, scope)
                self.walk(node.orelse, env, scope)
                self.walk(node.finalbody, env, scope)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                self.walk(node.body, env, scope)
        return result

    def extract(self):
        for name, function in self.functions.items():
            if self.parser_relevant(function) or name == 'main':
                conditional = sorted({test.id for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'ArgumentParser'
                                      for keyword in node.keywords if keyword.arg == 'prog'
                                      for expression in ast.walk(keyword.value) if isinstance(expression, ast.IfExp)
                                      for test in [expression.test] if isinstance(test, ast.Name)})
                self.active.add(name)
                for booleans in product((False, True), repeat=min(len(conditional), 3)):
                    self.forced = dict(zip(conditional, booleans))
                    self.walk(function.body, dict(self.globals), name)
                self.forced = {}
                self.active.remove(name)
        # Module-level parsers are also real source surfaces.
        self.walk(self.tree.body, dict(self.globals), '<module>')
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
                    'ArgumentParser', 'add_argument', 'add_parser') and node.lineno not in self.seen:
                self.gap(node, 'declaration was not reached by the static parser walk')
        return list(self.rows.values()), [gap for gap in self.gaps.values() if gap['line'] not in self.resolved]


def extract(root, paths, command_modules=()):
    by_module = {}
    for command, module in command_modules:
        by_module.setdefault(module, []).append('ravel ' + command)
    rows, gaps, readers = [], [], {}
    for path in sorted(paths):
        module = path.relative_to(Path(root) / 'src').as_posix().removesuffix('.py').replace('/', '.') if path.is_relative_to(Path(root) / 'src') else ''
        reader = readers.get(module) or Declarations(root, path, by_module.get(module, []), readers=readers, command_modules=by_module)
        prefixes = list(reader.commands) or [None]
        for prefix in prefixes:
            reader.commands = [prefix] if prefix is not None else []
            found, unresolved = reader.extract()
            rows.extend(found)
            gaps.extend(unresolved)
        reader.commands = [prefix for prefix in prefixes if prefix is not None]
    # Imported parser helpers contribute in their caller's actual parser context.
    all_rows = {row['id']: row for reader in readers.values() for row in reader.rows.values()}
    all_gaps = [gap for reader in readers.values() for gap in reader.gaps.values() if gap['line'] not in reader.resolved]
    return sorted(all_rows.values(), key=lambda row: row['id']), sorted(all_gaps, key=lambda row: (row['source'], row['line']))


def expand_dynamic_programs(root, rows):
    from copy import deepcopy
    output, gaps = [], []
    bounds = {}
    for row in rows:
        if row['kind'] != 'parser' or row.get('program_resolved', True):
            continue
        expression = row.get('program_expression', '')
        tree = ast.parse((Path(root) / row['source']).read_text(encoding='utf-8'))
        node = next((n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.lineno == row['line'] and
                     isinstance(n.func, ast.Attribute) and n.func.attr == 'ArgumentParser'), None)
        program = next((keyword.value for keyword in node.keywords if keyword.arg == 'prog'), None) if node else None
        alternatives = []
        if isinstance(program, ast.BinOp) and isinstance(program.op, ast.Add) and isinstance(program.left, ast.Constant) and isinstance(program.left.value, str):
            for comparison in ast.walk(tree):
                if not isinstance(comparison, ast.Compare) or ast.dump(comparison.left) != ast.dump(program.right):
                    continue
                for comparator in comparison.comparators:
                    if isinstance(comparator, (ast.Set, ast.List, ast.Tuple)) and all(isinstance(v, ast.Constant) and isinstance(v.value, str) for v in comparator.elts):
                        alternatives.extend(program.left.value + v.value for v in comparator.elts)
        if alternatives:
            bounds[(row['source'], row['command'])] = sorted(set(alternatives))
        else:
            gaps.append({'source': row['source'], 'line': row['line'], 'expression': expression,
                         'reason': 'Explicit runtime program prefix is shown under its source/module dispatch context; exact expansion unresolved.'})
    for row in rows:
        alternatives = bounds.get((row['source'], row['command']))
        if alternatives:
            for command in alternatives:
                expanded = deepcopy(row)
                expanded['id'] += ':dispatch-' + command.replace(' ', '-')
                expanded['command'] = command
                expanded['program_resolved'] = True
                output.append(expanded)
        else:
            output.append(row)
    return sorted(output, key=lambda row: row['id']), gaps
