"""Check literal authored command, option and Python-module references against source.

Only code spans and shell code blocks are assertions. Placeholders, variables,
quoted prose and alternative-verb shorthand remain examples rather than invented
literal commands. Parser options are matched within their base command family;
source dispatch aliases and global outcome flags are read from syntax.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import shlex

GENERATED = {'docs/reference/documentation-inventory.md', 'docs/cli/commands.md',
             'docs/reference/component-inventory.md'}


def source_aliases(root):
    source = root / 'src/ravel/cli.py'
    aliases = set()
    if not source.is_file():
        return aliases
    for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Subscript):
            continue
        left = node.left
        if not isinstance(left.value, ast.Name) or left.value.id != 'arguments' or not isinstance(left.slice, ast.Slice):
            continue
        if left.slice.lower is not None and not (isinstance(left.slice.lower, ast.Constant) and left.slice.lower.value == 0):
            continue
        for comparator in node.comparators:
            if isinstance(comparator, (ast.List, ast.Tuple)) and comparator.elts and all(
                    isinstance(child, ast.Constant) and isinstance(child.value, str) for child in comparator.elts):
                aliases.add(tuple(['ravel', *[child.value for child in comparator.elts]]))
    return aliases


def global_options(root):
    """The public dispatch wrapper's explicitly recognized option literals."""
    source = root / 'src/ravel/controller/outcomes.py'
    options = {'--help', '-h', '--version'}
    if source.is_file():
        for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == 'arg':
                for child in node.comparators:
                    if isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value.startswith('--'):
                        options.add(child.value)
    return options


def module_roster(root, value):
    names, exports = set(), {}
    for row in value['entries']:
        if row['kind'] != 'module':
            continue
        name = row['source'].removeprefix('src/').removesuffix('.py').replace('/', '.').removesuffix('.__init__')
        names.add(name)
        path = root / row['source']
        tree = ast.parse(path.read_text(encoding='utf-8')) if path.is_file() else ast.Module(body=[], type_ignores=[])
        exports[name] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                exports[name].add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    if isinstance(target, ast.Name):
                        exports[name].add(target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    exports[name].add(alias.asname or alias.name.split('.')[0])
    return names, exports


def spans(text):
    """Located inline code and complete shell fences, without their prose."""
    fenced = re.compile(r'^(`{3,}|~{3,})([^\n]*)\n(.*?)^\1\s*$', re.M | re.S)
    covered = []
    for match in fenced.finditer(text):
        covered.append((match.start(), match.end()))
        language = match.group(2).strip().lower()
        if language in ('', 'bash', 'sh', 'shell', 'console', 'zsh'):
            yield match.group(3), text.count('\n', 0, match.start(3)) + 1, True
    for match in re.finditer(r'(?<!`)`([^`\n]+)`(?!`)', text):
        if not any(start <= match.start() < end for start, end in covered):
            yield match.group(1), text.count('\n', 0, match.start()) + 1, False


def literal(value):
    return bool(value and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', value))


def settings_namespaces(root):
    """TOML configuration table prefixes are configuration references, not modules."""
    import tomllib
    names = set()
    for path in sorted((root / 'src/ravel/data').rglob('*.toml')):
        try:
            document = tomllib.loads(path.read_text(encoding='utf-8'))
        except tomllib.TOMLDecodeError:
            continue
        for name, child in document.get('ravel', {}).items():
            if isinstance(child, dict):
                names.add('ravel.' + name)
    return names


def errors(root, value):
    root = Path(root)
    commands, options, arity = set(), {}, {}
    for row in value['entries']:
        if row['kind'] not in ('parser', 'command', 'option'):
            continue
        command = row['details']['command']
        if not command.startswith('ravel '):
            continue
        tokens = tuple(command.split())
        commands.add(tokens)
        if row['kind'] == 'option':
            options.setdefault(tokens, set()).update(name for name in row['details']['names'] if name.startswith('-'))
            constraint = row['details'].get('constraints', {})
            action = constraint.get('action', '')
            takes_value = action not in ('store_true', 'store_false', 'count', 'help', 'version') and not str(action).endswith('BooleanOptionalAction') and constraint.get('nargs') != '0'
            for name in row['details']['names']:
                arity[(tokens, name)] = takes_value
            if row['details']['names'][0] in ('command', 'action', 'verb', 'operation', 'subcommand'):
                choices = row['details'].get('dispatch_choices')
                if choices is None:
                    declared = row['details'].get('constraints', {}).get('choices', '')
                    choices = declared.split(', ') if isinstance(declared, str) and not declared.startswith(('source:', 'source declaration at ')) else []
                for choice in choices:
                    if literal(choice):
                        commands.add((*tokens, choice))
    commands |= source_aliases(root)
    for command in list(commands):
        for index in range(2, len(command)):
            commands.add(command[:index])
    global_flags = global_options(root)
    modules, exports = module_roster(root, value)
    settings = settings_namespaces(root)
    findings = []

    def issue(source, line, kind, reference):
        findings.append({'source': source, 'line': line, 'kind': kind, 'reference': reference})

    selected_docs, transforms, layout = None, {}, None
    # Use the repository's declared selection; undistributed teaching/history
    # pages make no assertion about the public command surface.
    try:
        from ravel import evidence_layout
        if (root / evidence_layout.REGISTRY).is_file():
            registry = evidence_layout.load_registry(root)
            selected_docs = {source for source, _ in evidence_layout.selected_files(root, registry=registry)}
            if evidence_layout.source_fields(registry['distribution']):
                import sys
                sys.path.insert(0, str(root / 'scripts'))
                import export_layout as layout
                transforms = layout.load_public_transforms(root)
    except ImportError:
        pass
    paths = [root / 'README.md', root / 'CONTRIBUTING.md', *sorted((root / 'docs').rglob('*.md'))]
    for path in paths:
        if not path.is_file():
            continue
        source = path.relative_to(root).as_posix()
        if selected_docs is not None and source not in selected_docs:
            continue
        if source in GENERATED:
            continue
        text = (layout.public_bytes(root, source, source, transforms).decode('utf-8') if layout else path.read_text(encoding='utf-8'))
        for content, first_line, shell in spans(text):
            for reference in sorted(set(re.findall(r'(?<![\w/.-])ravel(?:\.[A-Za-z_][A-Za-z_0-9]*)+', content))):
                if reference in modules or any(reference == namespace or reference.startswith(namespace + '.') for namespace in settings):
                    continue
                if reference.rsplit('.', 1)[-1] in ('root', 'git', 'json', 'toml', 'yaml', 'md', 'pdf', 'csv', 'yoda') and 'python -m ' not in content:
                    continue
                prefixes = [module for module in modules if reference.startswith(module + '.')]
                parent = max(prefixes, key=len) if prefixes else None
                if parent:
                    suffix = reference[len(parent) + 1:].split('.')[0]
                    if suffix in exports.get(parent, set()):
                        continue
                issue(source, first_line, 'module', reference)
            lines = content.replace('\\\n', ' ').splitlines() if shell else [content]
            for index, command_line in enumerate(lines):
                # A standalone command in a shell block, or an inline command
                # beginning with ravel. Prose that embeds a command is not parsed.
                line = command_line.strip().removeprefix('$ ').strip()
                if not line.startswith('ravel '):
                    continue
                # Compact choices such as `run|status` are syntax descriptions.
                if re.search(r'\b[a-z][a-z-]*\|[a-z]', line):
                    continue
                try:
                    tokens = shlex.split(line, comments=True)
                except ValueError:
                    continue
                if len(tokens) < 2 or not literal(tokens[1]):
                    continue
                base = ('ravel', tokens[1])
                if base not in commands:
                    issue(source, first_line + index, 'command', ' '.join(base))
                    continue
                position = 2
                current = base
                while position < len(tokens):
                    token = tokens[position]
                    if token in ('--', ';', '|', '&&', '||', '#'):
                        break
                    allowed = set(global_flags)
                    for length in range(2, len(current) + 1):
                        allowed.update(options.get(current[:length], set()))
                    if token.startswith('-'):
                        flag = token.split('=', 1)[0]
                        if re.fullmatch(r'--[a-zA-Z][a-zA-Z0-9-]*', flag) and flag not in allowed:
                            issue(source, first_line + index, 'option', ' '.join(base) + ' ' + flag)
                        takes_value = next((arity[(current[:length], flag)] for length in range(len(current), 1, -1)
                                            if (current[:length], flag) in arity), flag not in ('--help', '-h', '--version', '--require-complete'))
                        position += 2 if takes_value and '=' not in token and position + 1 < len(tokens) else 1
                        continue
                    children = {command[len(current)] for command in commands if len(command) > len(current) and command[:len(current)] == current}
                    if children and literal(token):
                        if token not in children:
                            issue(source, first_line + index, 'subcommand', ' '.join([*current, token]))
                            break
                        current += (token,)
                    position += 1
    unique = {(row['source'], row['line'], row['kind'], row['reference']): row for row in findings}
    return [unique[key] for key in sorted(unique)]
