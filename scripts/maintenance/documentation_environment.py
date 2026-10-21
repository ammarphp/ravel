"""Read declared process-environment inputs as syntax, without executing sources.

Literal/constant names and finite source loops become named records. Open names
selected by a caller, credential declaration or runtime record remain typed
boundaries; environment mutation destinations are not configuration reads.
"""
from __future__ import annotations

import ast
from pathlib import Path

from documentation_parsers import Declarations, Expression, Imported


def collect_environment_reads(root, paths):
    root = Path(root)
    rows, dynamic, gaps = {}, {}, {}
    readers = {}

    for path in paths:
        path = Path(path)
        text = path.read_text(encoding='utf-8')
        if 'environ' not in text and 'getenv' not in text:
            continue
        module = path.relative_to(root).as_posix().removesuffix('.py').replace('/', '.').removeprefix('src.')
        reader = readers.get(module) or Declarations(root, path, readers=readers)
        source = path.relative_to(root).as_posix()

        def imported_name(node, env):
            value = reader.value(node, env)
            return value.module + ('.' + value.name if value.name else '') if isinstance(value, Imported) else ''

        def is_environment(node, env):
            if node is None:
                return False
            if env.get('@environment:' + ast.unparse(node)) is True:
                return True
            if imported_name(node, env) == 'os.environ':
                return True
            # Copies are used as editable subprocess environments as well as
            # input snapshots. Only reads from them are retained below.
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == 'copy':
                    return is_environment(node.func.value, env)
                if isinstance(node.func, ast.Name) and node.func.id == 'dict' and node.args:
                    return is_environment(node.args[0], env)
            if isinstance(node, ast.IfExp):
                return is_environment(node.body, env) or is_environment(node.orelse, env)
            return False

        def record(node, name_node, env, access):
            value = reader.value(name_node, env)
            expression = ast.unparse(name_node)
            common = {'source': source, 'line': node.lineno, 'access': access, 'expression': expression}
            if isinstance(value, str) and value:
                row = {**common, 'name': value, 'scope': 'Named process-environment read; acceptance follows the owning source.'}
                rows[(source, node.lineno, value, access)] = row
                return
            # A runtime name is a declared extension boundary, not a list of
            # invented accepted names. Finite constants must resolve or fail.
            names = [child.id for child in ast.walk(name_node) if isinstance(child, ast.Name)]
            finite_claim = bool(names) and all(name.isupper() for name in names)
            row = {**common, 'scope': ('Unresolved source-declared environment-name constant.' if finite_claim else
                   'Runtime-selected environment name; caller/credential/runtime-record keys are outside the finite named-read census.')}
            (gaps if finite_claim else dynamic)[(source, node.lineno, expression)] = row

        def bind(target, value, env):
            if isinstance(target, ast.Name):
                env[target.id] = value
            elif isinstance(target, ast.Attribute):
                key = '@environment:' + ast.unparse(target)
                if value == Imported('os', 'environ'):
                    env[key] = True
                else:
                    env.pop(key, None)
            elif isinstance(target, (ast.Tuple, ast.List)):
                values = value if isinstance(value, (tuple, list)) else [Expression(ast.unparse(child)) for child in target.elts]
                for child, item in zip(target.elts, values):
                    bind(child, item, env)

        def expression(node, env):
            if node is None:
                return
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                def generators(index, local):
                    if index == len(node.generators):
                        for child in ([node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]):
                            expression(child, local)
                        return
                    generator = node.generators[index]
                    expression(generator.iter, local)
                    values = reader.value(generator.iter, local)
                    finite = isinstance(values, (tuple, list, set, dict)) and len(values) <= 4096
                    for item in values if finite else [Expression(ast.unparse(generator.target))]:
                        child = dict(local)
                        bind(generator.target, item, child)
                        for condition in generator.ifs:
                            expression(condition, child)
                        generators(index + 1, child)
                generators(0, dict(env))
                return
            if isinstance(node, ast.Call):
                if imported_name(node.func, env) == 'os.getenv' and node.args:
                    record(node, node.args[0], env, 'getenv')
                elif isinstance(node.func, ast.Attribute) and node.func.attr == 'get' and node.args and is_environment(node.func.value, env):
                    record(node, node.args[0], env, 'get')
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and is_environment(node.value, env):
                record(node, node.slice, env, 'getitem')
            elif isinstance(node, ast.Compare):
                left = node.left
                for operator, right in zip(node.ops, node.comparators):
                    if isinstance(operator, (ast.In, ast.NotIn)) and is_environment(right, env):
                        record(node, left, env, 'contains')
                    left = right
            for child in ast.iter_child_nodes(node):
                if not isinstance(child, (ast.stmt, ast.comprehension)):
                    expression(child, env)

        def statements(body, env, class_context=False):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for default in (*node.args.defaults, *node.args.kw_defaults):
                        expression(default, env)
                    local = dict(env)
                    positional = [*node.args.posonlyargs, *node.args.args]
                    for argument in (*positional, *node.args.kwonlyargs):
                        local[argument.arg] = Expression(argument.arg)
                    defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
                    for argument, default in [*zip(positional, defaults), *zip(node.args.kwonlyargs, node.args.kw_defaults)]:
                        if is_environment(default, env):
                            local[argument.arg] = Imported('os', 'environ')
                    statements(node.body, local)
                    if class_context and node.name == '__init__':
                        env.update({name: value for name, value in local.items() if name.startswith('@environment:')})
                elif isinstance(node, ast.ClassDef):
                    local = dict(env)
                    constructors = [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == '__init__']
                    statements(constructors, local, class_context=True)
                    statements([child for child in node.body if child not in constructors], local, class_context=True)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    expression(node.value, env)
                    value = reader.value(node.value, env)
                    if is_environment(node.value, env):
                        value = Imported('os', 'environ')
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        bind(target, value, env)
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    aliases = {name for name, value in env.items() if value == Imported('os', 'environ')}
                    readers_here = {name for name, value in env.items() if value == Imported('os', 'getenv')}
                    if not any((isinstance(child, ast.Attribute) and child.attr in ('environ', 'getenv')) or
                               (isinstance(child, ast.Name) and child.id in aliases | readers_here)
                               for child in ast.walk(node)):
                        continue
                    expression(node.iter, env)
                    values = reader.value(node.iter, env)
                    finite = isinstance(values, (tuple, list, set, dict)) and len(values) <= 4096
                    for item in values if finite else [Expression(ast.unparse(node.target))]:
                        child = dict(env)
                        bind(node.target, item, child)
                        statements(node.body, child)
                    statements(node.orelse, dict(env))
                elif isinstance(node, (ast.If, ast.While)):
                    expression(node.test, env)
                    statements(node.body, dict(env))
                    statements(node.orelse, dict(env))
                elif isinstance(node, ast.Try):
                    statements(node.body, dict(env))
                    for handler in node.handlers:
                        statements(handler.body, dict(env))
                    statements(node.orelse, dict(env))
                    statements(node.finalbody, dict(env))
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        expression(item.context_expr, env)
                    statements(node.body, dict(env))
                else:
                    expression(node, env)

        statements(reader.tree.body, dict(reader.globals))
    order = lambda row: (row['source'], row['line'], row.get('name', row['expression']))
    return sorted(rows.values(), key=order), sorted(dynamic.values(), key=order), sorted(gaps.values(), key=order)
