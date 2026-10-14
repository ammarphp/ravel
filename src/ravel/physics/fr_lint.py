"""Static lint of FeynRules model source (.fr), tokenizer-based; never evaluates the source.

Errors stop the model before FeynRules runs:

* unbalanced brackets, strings or comments;
* calls that read, write or execute outside the model (Get, Import, Run, ...),
  or the << / >> file operators;
* a missing M$ModelName; duplicate or one-character ClassNames; ClassNames,
  particle names, PDG codes or class indices that collide with SM.fr;
* external parameters without BlockName, OrderBlock (scalar) or Value, and
  duplicate LHA addresses;
* when a ModelSpec is given: every field, parameter and Lagrangian term of the
  spec must be present, every new field named in an operator must be listed in
  that term's field census, and every required coupling must appear in a term.

Warnings flag identifiers used in the Lagrangian that are declared nowhere.
"""
from __future__ import annotations

import re

FORBIDDEN = {'Get', 'Needs', 'Import', 'Export', 'Put', 'PutAppend', 'Run', 'RunProcess', 'StartProcess',
             'RunThrough', 'SetDirectory', 'ResetDirectory', 'CreateDirectory', 'DeleteDirectory', 'DeleteFile',
             'CopyFile', 'RenameFile', 'CreateFile', 'OpenWrite', 'OpenAppend', 'OpenRead', 'ReadList', 'ReadString',
             'URLFetch', 'URLRead', 'URLExecute', 'URLDownload', 'URLSubmit', 'Install', 'LinkLaunch', 'Uncompress',
             'ToExpression', 'Symbol', 'Environment', 'SetEnvironment', 'SystemOpen', 'DeclarePackage', 'Encode',
             'Decrypt', 'LoadModel', 'WriteUFO', 'Quit', 'Exit', 'Abort'}
FORBIDDEN_OPERATORS = {'<<', '>>', '>>>'}
BUILTINS = {'Block', 'Module', 'ExpandIndices', 'FlavorExpand', 'SU2W', 'SU2D', 'HC', 'CC', 'DC', 'del', 'FS', 'Ga',
            'ProjM', 'ProjP', 'Eps', 'T', 'f', 'dSUN', 'Index', 'IndexDelta', 'I', 'Sqrt', 'Pi', 'Conjugate', 'Cos',
            'Sin', 'Tan', 'ArcSin', 'ArcCos', 'ArcTan', 'Exp', 'Log', 'Abs', 'Re', 'Im', 'True', 'False', 'Sigma',
            'LSM', 'LGauge', 'LFermions', 'LHiggs', 'LYukawa', 'LGhost', 'PauliSigma', 'Ta', 'right', 'left',
            'FeynmanGauge', 'If', 'Not', 'anti', 'Colour', 'Gluon', 'Generation', 'Spin', 'Lorentz'}
SM_CLASSNAMES = {'A', 'Z', 'W', 'G', 'ghA', 'ghZ', 'ghWp', 'ghWm', 'ghG', 'B', 'Wi', 'ghB', 'ghWi', 'vl', 'l', 'uq',
                 'dq', 'LL', 'lR', 'QL', 'uR', 'dR', 'H', 'G0', 'GP', 'Phi'}
SM_CLASS_MEMBERS = {'ve', 'vm', 'vt', 'e', 'mu', 'ta', 'u', 'c', 't', 'd', 's', 'b', 'Wbar', 'GPbar'}
TOKEN = re.compile(r'''
    (?P<comment>\(\*) |
    (?P<string>") |
    (?P<number>\d+\.?\d*(?:\*\^-?\d+)?|\.\d+) |
    (?P<name>[A-Za-z$][A-Za-z0-9$`]*) |
    (?P<op>>>>|<<|>>|:=|->|:>|==|\[\[|\]\]|[\[\]{}()]|[^\s\w]|_) |
    (?P<space>\s+)
''', re.VERBOSE)


def tokenize(text):
    """Tokens (kind, value, line) with comments and strings consumed; raises on unterminated ones."""
    tokens, i, line = [], 0, 1
    while i < len(text):
        m = TOKEN.match(text, i)
        if not m:
            raise ValueError(f'line {line}: unexpected character {text[i]!r}')
        kind = m.lastgroup
        if kind == 'comment':
            depth, j = 1, m.end()
            while depth and j < len(text):
                if text.startswith('(*', j):
                    depth, j = depth + 1, j + 2
                elif text.startswith('*)', j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            if depth:
                raise ValueError(f'line {line}: unterminated comment')
            line += text.count('\n', i, j)
            i = j
            continue
        if kind == 'string':
            j = m.end()
            while j < len(text) and text[j] != '"':
                j += 2 if text[j] == '\\' else 1
            if j >= len(text):
                raise ValueError(f'line {line}: unterminated string')
            tokens.append(('string', text[m.end():j], line))
            line += text.count('\n', i, j + 1)
            i = j + 1
            continue
        value = m.group()
        if kind != 'space':
            tokens.append((kind, value, line))
        line += value.count('\n')
        i = m.end()
    return tokens


def _balance(tokens):
    pairs = {']': '[', '}': '{', ')': '('}
    stack, errors = [], []
    for kind, value, line in tokens:
        if kind != 'op':
            continue
        if value in ('[[', ']]'):
            value = value[0]
            for _ in range(2):
                if value == '[':
                    stack.append(('[', line))
                elif not stack or stack.pop()[0] != '[':
                    errors.append(f'line {line}: unbalanced ]')
            continue
        if value in '[{(':
            stack.append((value, line))
        elif value in pairs:
            if not stack or stack[-1][0] != pairs[value]:
                errors.append(f'line {line}: unbalanced {value}')
            else:
                stack.pop()
    errors += [f'line {line}: unclosed {b}' for b, line in stack]
    return errors


def _rules(tokens):
    """Yield (key, value_tokens, line) for each `Key -> value` at any depth (value up to , or closing bracket)."""
    out = []
    for i, (kind, value, line) in enumerate(tokens):
        if kind == 'op' and value == '->' and i > 0 and tokens[i - 1][0] == 'name':
            depth, j, vals = 0, i + 1, []
            while j < len(tokens):
                k, v, _ = tokens[j]
                if k == 'op' and v in '[{(' and v:
                    depth += 1
                elif k == 'op' and v in (']', '}', ')', ']]'):
                    if depth == 0:
                        break
                    depth -= 1
                elif k == 'op' and v == ',' and depth == 0:
                    break
                vals.append(tokens[j])
                j += 1
            out.append((tokens[i - 1][1], vals, line))
    return out


def _classes(tokens):
    """Class blocks `X[n] == { ... }` with their rules."""
    blocks = []
    for i in range(len(tokens) - 5):
        k, v, line = tokens[i]
        if (k == 'name' and v in ('S', 'F', 'V', 'U', 'T', 'R') and tokens[i + 1][1] == '['
                and tokens[i + 2][0] == 'number' and tokens[i + 3][1] == ']' and tokens[i + 4][1] == '=='
                and tokens[i + 5][1] == '{'):
            depth, j = 0, i + 5
            while j < len(tokens):
                if tokens[j][1] in ('[', '{', '('):
                    depth += 1
                elif tokens[j][1] in (']', '}', ')'):
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            body = tokens[i + 6:j]
            rules = {}
            for key, vals, _ in _rules(body):
                rules.setdefault(key, vals)
            blocks.append({'kind': v, 'index': int(float(tokens[i + 2][1])), 'line': line, 'rules': rules})
    return blocks


def _parameters(tokens):
    """Parameter blocks `name == { ParameterType -> ... }`."""
    out = []
    for i in range(len(tokens) - 3):
        k, v, line = tokens[i]
        if k == 'name' and tokens[i + 1][1] == '==' and tokens[i + 2][1] == '{':
            depth, j = 0, i + 2
            while j < len(tokens):
                if tokens[j][1] in ('[', '{', '('):
                    depth += 1
                elif tokens[j][1] in (']', '}', ')'):
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            rules = {}
            for key, vals, _ in _rules(tokens[i + 3:j]):
                rules.setdefault(key, vals)
            if 'ParameterType' in rules:
                out.append({'symbol': v, 'line': line, 'rules': rules})
    return out


def _text(vals):
    return ''.join(v for _, v, _ in vals)


def sm_inventory(sm_text):
    """ClassNames, particle names, PDGs and class indices declared by the supplied SM.fr."""
    tokens = tokenize(sm_text)
    names, particles, pdgs, indices = set(), set(), set(), set()
    for block in _classes(tokens):
        indices.add((block['kind'], block['index']))
        r = block['rules']
        if 'ClassName' in r:
            names.add(_text(r['ClassName']))
        for key in ('ParticleName', 'AntiParticleName'):
            for kind, value, _ in r.get(key, []):
                if kind == 'string':
                    particles.add(value.lower())
        for kind, value, _ in r.get('PDG', []):
            if kind == 'number':
                pdgs.add(int(float(value)))
    return {'class_names': names, 'particle_names': particles, 'pdgs': pdgs, 'class_indices': indices}


def lint(text, *, spec=None, sm_text=None):
    errors, warnings = [], []
    try:
        tokens = tokenize(text)
    except ValueError as exc:
        return {'passed': False, 'errors': [str(exc)], 'warnings': []}
    errors += _balance(tokens)
    for kind, value, line in tokens:
        if kind == 'name' and value.split('`')[-1] in FORBIDDEN:
            errors.append(f'line {line}: {value} is not allowed in model source')
        if kind == 'op' and value in FORBIDDEN_OPERATORS:
            errors.append(f'line {line}: the {value} file operator is not allowed in model source')
        if kind == 'name' and '`' in value:
            errors.append(f'line {line}: context-qualified symbol {value} is not allowed in model source')
    if not any(k == 'name' and v == 'M$ModelName' for k, v, _ in tokens):
        errors.append('M$ModelName is not set')
    if spec is not None and spec.get('extends', 'SM') == 'SM':
        for kind, value, line in tokens:
            if kind == 'name' and value in ('M$GaugeGroups', 'IndexRange', 'M$vevs'):
                errors.append(f'line {line}: an extension of SM.fr must not redeclare {value}; '
                              'new gauge groups are outside this tier')
    from ravel.physics import model_authoring as ma
    if sm_text is not None:
        inv = sm_inventory(sm_text)
    else:
        inv = {'class_names': SM_CLASSNAMES, 'particle_names': ma.SM_PARTICLE_NAMES, 'pdgs': ma.SM_PDGS,
               'class_indices': ma.SM_CLASS_INDICES}
    classes = _classes(tokens)
    seen_names, seen_pdgs, seen_idx, seen_particles = {}, {}, set(), set()
    for block in classes:
        r = block['rules']
        where = f'line {block["line"]}'
        key = (block['kind'], block['index'])
        if key in inv['class_indices']:
            errors.append(f'{where}: class index {block["kind"]}[{block["index"]}] collides with SM.fr')
        if key in seen_idx:
            errors.append(f'{where}: class index {block["kind"]}[{block["index"]}] used twice')
        seen_idx.add(key)
        name = _text(r.get('ClassName', []))
        if not name:
            errors.append(f'{where}: class without ClassName')
            continue
        if len(name) < 2:
            errors.append(f'{where}: one-character ClassName {name!r} collides with MadGraph and Python names')
        if name in inv['class_names'] or name in SM_CLASS_MEMBERS:
            errors.append(f'{where}: ClassName {name} collides with SM.fr')
        if name in seen_names:
            errors.append(f'{where}: ClassName {name} declared twice')
        seen_names[name] = block
        if r.get('Unphysical') and _text(r['Unphysical']) == 'True':
            continue
        pdg_tokens = [v for k, v, _ in r.get('PDG', []) if k == 'number']
        if not pdg_tokens:
            errors.append(f'{where}: {name} has no PDG code')
        for v in pdg_tokens:
            pdg = int(float(v))
            if pdg in inv['pdgs']:
                errors.append(f'{where}: PDG {pdg} of {name} collides with SM.fr')
            if pdg in seen_pdgs:
                errors.append(f'{where}: PDG {pdg} used by {name} and {seen_pdgs[pdg]}')
            seen_pdgs[pdg] = name
        for key2 in ('ParticleName', 'AntiParticleName'):
            for k, v, _ in r.get(key2, []):
                if k == 'string':
                    if v.lower() in inv['particle_names']:
                        errors.append(f'{where}: particle name {v!r} collides with SM.fr')
                    if key2 == 'ParticleName' and v.lower() in seen_particles:
                        errors.append(f'{where}: particle name {v!r} used twice')
                    seen_particles.add(v.lower())
        for key2 in ('Mass', 'Width'):
            if key2 not in r:
                errors.append(f'{where}: {name} has no {key2}')
    params = _parameters(tokens)
    addresses = {}
    declared = set(seen_names) | {n + 'bar' for n in seen_names}
    for p in params:
        r = p['rules']
        declared.add(p['symbol'])
        if _text(r['ParameterType']) == 'External':
            if 'BlockName' not in r:
                errors.append(f'line {p["line"]}: external parameter {p["symbol"]} has no BlockName')
            if 'Value' not in r:
                errors.append(f'line {p["line"]}: external parameter {p["symbol"]} has no Value')
            if 'Indices' not in r:
                if 'OrderBlock' not in r:
                    errors.append(f'line {p["line"]}: external parameter {p["symbol"]} has no OrderBlock')
                else:
                    addr = (_text(r.get('BlockName', [])).upper(), _text(r['OrderBlock']))
                    if addr in addresses:
                        errors.append(f'line {p["line"]}: LHA address {addr} used by {p["symbol"]} and {addresses[addr]}')
                    addresses[addr] = p['symbol']
        elif 'Value' not in r:
            errors.append(f'line {p["line"]}: internal parameter {p["symbol"]} has no Value')
    for block in classes:
        r = block['rules']
        for key2 in ('Mass', 'Width'):
            vals = [v for k, v, _ in r.get(key2, []) if k == 'name']
            if vals:
                declared.add(vals[0])
    if spec is not None:
        errors += _against_spec(text, tokens, spec, seen_names, {p['symbol'] for p in params})
        sm_known = set(ma.SM_SYMBOLS) | set(ma.SM_FIELDS) | {f + 'bar' for f in ma.SM_FIELDS}
        for term in spec['lagrangian_terms']:
            for kind, value, line in tokenize(term['operator']):
                if (kind == 'name' and value not in declared and value not in sm_known and value not in BUILTINS
                        and value not in ma.DUMMIES):
                    warnings.append(f'term {term["id"]}: identifier {value} is declared nowhere')
    return {'passed': not errors, 'errors': errors, 'warnings': sorted(set(warnings))}


def _against_spec(text, tokens, spec, class_names, param_symbols):
    errors = []
    names = [v for k, v, _ in tokens if k == 'name']
    model_name = None
    for i, (k, v, _) in enumerate(tokens):
        if k == 'name' and v == 'M$ModelName' and i + 2 < len(tokens) and tokens[i + 2][0] == 'string':
            model_name = tokens[i + 2][1]
    if model_name != spec['name']:
        errors.append(f'M$ModelName {model_name!r} differs from the spec name {spec["name"]!r}')
    new_fields = {f['name'] for f in spec['fields']}
    for f in sorted(new_fields - set(class_names)):
        errors.append(f'spec field {f} has no particle class')
    for f in sorted(set(class_names) - new_fields):
        errors.append(f'particle class {f} is not in the spec')
    for p in spec['parameters']:
        if p['symbol'] not in param_symbols:
            errors.append(f'spec parameter {p["symbol"]} is not declared in M$Parameters')
    for term in spec['lagrangian_terms']:
        ops = tokenize(term['operator'])
        from ravel.physics.model_authoring import SM_FIELDS
        known = new_fields | set(SM_FIELDS)
        used = {v[:-3] if v.endswith('bar') and v[:-3] in known else v for k, v, _ in ops if k == 'name'}
        listed = {e['field'] for e in term['fields']}
        for f in sorted((used & new_fields) - listed):
            errors.append(f'term {term["id"]}: field {f} appears in the operator but not in the field census')
        for f in sorted(listed - used):
            errors.append(f'term {term["id"]}: census field {f} does not appear in the operator')
        for c in term['couplings']:
            if c not in used:
                errors.append(f'term {term["id"]}: coupling {c} does not appear in the operator')
        if term['operator'].strip() not in text:
            errors.append(f'term {term["id"]}: operator text is not in the model source')
    used_couplings = {c for t in spec['lagrangian_terms'] for c in t['couplings']}
    for c in spec['required_couplings']:
        if c not in used_couplings:
            errors.append(f'required coupling {c} appears in no Lagrangian term')
    return errors
