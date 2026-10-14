"""Static UFO checks without importing the model, plus a MadGraph import-and-generate check.

``check(ufo, spec=None)`` parses every UFO file with ``ast.parse`` and reads the
Particle, Parameter, Coupling, Lorentz and Vertex objects from their literal
keyword arguments. It refuses:

* Python files that do not parse (for example Python-2 ``raise X, "msg"``);
* Mathematica leftovers in expressions (contexts, ``\\[...]`` named characters,
  ``Global```, ``FR$``, ``Null``, ``Indeterminate``, ``ComplexInfinity``);
* a model without at least one Vertex and one Lorentz structure;
* duplicate PDG codes; a particle whose mass is ZERO while its width is not,
  or whose mass parameter is missing;
* with a ModelSpec: a missing field (by PDG), a charge or spin that differs
  from the spec, or a required coupling that appears in no Coupling used by a
  Vertex.

``madgraph_generate`` runs ``import model`` and one ``generate`` line in a fresh
MadGraph session and requires at least one diagram; the runner is injectable so
tests never start MadGraph.
"""
from __future__ import annotations

import ast
import re
import subprocess
from fractions import Fraction
from pathlib import Path

LEAK = re.compile(r'Global`|FR\$|\\\[|`|\bNull\b|\bIndeterminate\b|\bComplexInfinity\b|\bDirectedInfinity\b')
SPIN = {'scalar': 1, 'fermion': 2, 'vector': 3}


def _call_name(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _objects(tree, factory):
    rows = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call) and _call_name(stmt.value) == factory:
            target = stmt.targets[0]
            var = target.id if isinstance(target, ast.Name) else None
            kw = {k.arg: k.value for k in stmt.value.keywords if k.arg}
            rows[var] = {'kw': kw, 'line': stmt.lineno}
    return rows


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _ref(node):
    """`Param.MX` / `C.GC_1` / `L.FFV1` -> 'MX' / 'GC_1' / 'FFV1'."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _charge(node):
    value = _literal(node)
    if isinstance(value, (int, float)):
        return Fraction(value).limit_denominator(12)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        a, b = _charge(node.left), _charge(node.right)
        return None if a is None or b is None or b == 0 else a / b
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        a = _charge(node.operand)
        return None if a is None else -a
    return None


def check(ufo, *, spec=None):
    ufo = Path(ufo)
    errors, warnings, trees = [], [], {}
    for name in ('particles.py', 'parameters.py', 'couplings.py', 'lorentz.py', 'vertices.py'):
        if not (ufo / name).is_file():
            errors.append(f'{name} is missing')
    for path in sorted(ufo.glob('*.py')):
        text = path.read_text(errors='replace')
        try:
            trees[path.name] = ast.parse(text)
        except SyntaxError as exc:
            errors.append(f'{path.name} line {exc.lineno}: does not parse as Python 3 ({exc.msg})')
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            code = line.split('#', 1)[0]
            if LEAK.search(code):
                errors.append(f'{path.name} line {lineno}: Mathematica leftover in {code.strip()[:80]!r}')
    if errors:
        return {'passed': False, 'errors': errors, 'warnings': warnings}
    particles = _objects(trees['particles.py'], 'Particle')
    params = _objects(trees['parameters.py'], 'Parameter')
    couplings = _objects(trees['couplings.py'], 'Coupling')
    lorentz = _objects(trees['lorentz.py'], 'Lorentz')
    vertices = _objects(trees['vertices.py'], 'Vertex')
    if not vertices:
        errors.append('no Vertex objects')
    if not lorentz:
        errors.append('no Lorentz structures')
    param_names = {_literal(p['kw'].get('name')) for p in params.values()} | {'ZERO'}
    param_vars = set(params) | {'ZERO'}
    by_pdg = {}
    for var, p in particles.items():
        kw = p['kw']
        pdg = _literal(kw.get('pdg_code'))
        if type(pdg) is not int:
            errors.append(f'particle {var}: pdg_code is not a literal integer')
            continue
        if pdg in by_pdg:
            errors.append(f'PDG {pdg} declared by {by_pdg[pdg]["var"]} and {var}')
        mass, width = _ref(kw.get('mass')), _ref(kw.get('width'))
        if mass not in param_vars:
            errors.append(f'particle {var}: mass parameter {mass} is not declared')
        if width not in param_vars:
            errors.append(f'particle {var}: width parameter {width} is not declared')
        if mass == 'ZERO' and width not in (None, 'ZERO'):
            errors.append(f'particle {var}: massless with a nonzero width parameter {width}')
        by_pdg[pdg] = {'var': var, 'spin': _literal(kw.get('spin')), 'charge': _charge(kw.get('charge')),
                       'name': _literal(kw.get('name')), 'mass': mass, 'width': width}
    used_couplings = set()
    for var, v in vertices.items():
        node = v['kw'].get('couplings')
        if isinstance(node, ast.Dict):
            for value in node.values:
                ref = _ref(value)
                if ref:
                    used_couplings.add(ref)
                if ref and ref not in couplings:
                    errors.append(f'vertex {var}: coupling {ref} is not declared')
        else:
            errors.append(f'vertex {var}: couplings are not a literal dictionary')
        lnode = v['kw'].get('lorentz')
        for elt in getattr(lnode, 'elts', []):
            ref = _ref(elt)
            if ref and ref not in lorentz:
                errors.append(f'vertex {var}: Lorentz structure {ref} is not declared')
    used_values = ' '.join(_literal(couplings[c]['kw'].get('value')) or '' for c in used_couplings if c in couplings)
    survival = {}
    if spec is not None:
        for f in spec['fields']:
            row = by_pdg.get(f['pdg'])
            if row is None:
                errors.append(f'field {f["name"]} (PDG {f["pdg"]}) is not in the UFO')
                continue
            want = Fraction(str(f.get('electric_charge', f['hypercharge'])))
            if row['charge'] is not None and row['charge'] != want:
                errors.append(f'field {f["name"]}: UFO charge {row["charge"]} differs from the spec {want}')
            if row['spin'] != SPIN[f['kind']]:
                errors.append(f'field {f["name"]}: UFO spin {row["spin"]} differs from the spec ({SPIN[f["kind"]]})')
            if row['mass'] in (None, 'ZERO'):
                errors.append(f'field {f["name"]}: UFO mass is ZERO but the spec gives {f["mass"]["value"]} GeV')
        for c in spec['required_couplings']:
            pattern = re.compile(r'\b' + re.escape(c) + r'(?:\b|[0-9x])')
            survived = bool(pattern.search(used_values))
            survival[c] = survived
            if not survived:
                errors.append(f'required coupling {c} appears in no coupling used by a vertex')
        for c in spec.get('optional_couplings') or []:
            pattern = re.compile(r'\b' + re.escape(c) + r'(?:\b|[0-9x])')
            survival[c] = bool(pattern.search(used_values))
            if not survival[c]:
                warnings.append(f'optional coupling {c} appears in no vertex')
        declared_params = {_literal(p['kw'].get('name')) for p in params.values()}
        for p in spec['parameters']:
            if p['symbol'] not in declared_params and not any(
                    str(n).startswith(p['symbol']) for n in declared_params if n):
                errors.append(f'spec parameter {p["symbol"]} is not a UFO parameter')
    return {'passed': not errors, 'errors': errors, 'warnings': warnings,
            'counts': {'particles': len(particles), 'parameters': len(params), 'couplings': len(couplings),
                       'lorentz': len(lorentz), 'vertices': len(vertices)},
            'required_coupling_survival': survival, 'declared_parameter_names': sorted(n for n in param_names if n)}


DIAGRAMS = re.compile(r'Total:\s*(\d+)\s+processes?\s+with\s+(\d+)\s+diagrams?')


def madgraph_generate(ufo, process, *, mg5, workdir, runner=None, timeout=600):
    """`import model <ufo>` then `generate <process>`; at least one diagram is required."""
    if not isinstance(process, str) or not process.strip() or '\n' in process or ';' in process:
        raise ValueError('one MadGraph process line is required')
    import shutil
    workdir = Path(workdir).absolute()
    workdir.mkdir(parents=True, exist_ok=False)
    model = workdir / Path(ufo).name
    shutil.copytree(ufo, model)  # MadGraph writes caches next to the model; keep the checked tree untouched
    script = workdir / 'check.mg5'
    script.write_text(f'set auto_update 0\nset automatic_html_opening False\nimport model {model.resolve()}\n'
                      f'generate {process}\n')
    command = [*(mg5 if isinstance(mg5, (list, tuple)) else [mg5]), str(script)]
    command = [str(c) for c in command]
    run = runner or (lambda cmd: subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout))
    completed = run(command)
    output = (completed.stdout or '') + '\n' + (completed.stderr or '')
    (workdir / 'mg5.log').write_text(output)
    found = DIAGRAMS.findall(output)
    diagrams = int(found[-1][1]) if found else 0
    import_ok = completed.returncode == 0 and not re.search(r'\bERROR\b|InvalidCmd|Error:', output)
    errors = []
    if not import_ok:
        errors.append('MadGraph did not import the model cleanly')
    if diagrams < 1:
        errors.append(f'no diagrams for "{process}"')
    return {'passed': not errors, 'errors': errors, 'process': process, 'diagrams': diagrams,
            'returncode': completed.returncode, 'command': command, 'log': str(workdir / 'mg5.log')}
