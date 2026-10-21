"""Model admission: the checks a UFO must pass before it is used for generation.

``admit(ufo, ...)`` runs every check it has evidence for and returns one record:

* ``ufo-static``: ``ufo_check.check`` (Python 3 parse, Mathematica leftovers,
  PDG codes, mass and width parameters; spec agreement when a ModelSpec is given);
* ``vertex-quantum-numbers``: every additive quantum number the UFO declares on
  its particles (``charge`` and any extra keyword such as ``LeptonNumber``,
  ``GhostNumber`` or ``Y``) sums to zero over every vertex, all legs incoming;
* ``conjugate-vertices``: every non-ghost vertex has a vertex with the
  conjugate particle content, so the Lagrangian contains its Hermitian conjugate;
* ``spec-charge-census``: the ModelSpec charge census, when a spec is given
  (hypercharge and weak-doublet count of every gauge-basis term, electric
  charge of every physical-field term, colour triality, declared lepton number);
* ``hermiticity-feynrules``: the FeynRules ``CheckHermiticity`` verdict from a
  native receipt (two-gauge checks or derivation physical checks), when given;
* ``mg5-check-gauge``, ``mg5-check-lorentz``, ``mg5-check-permutation``: MadGraph
  ``check <kind> <process>`` on the requested process, each in a fresh session;
* ``ward-identity``: recorded as not evaluated (not part of minimal admission).

Every row states what the check cannot detect. The decision is ``refused`` when
any check fails, ``incomplete`` when a required check has no verdict, and
``admitted`` otherwise. The MadGraph runner is injectable so tests never start
MadGraph.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from ravel.physics import ufo_check

SCHEMA = 1
KIND = 'model-admission'
MG5_CHECKS = ('gauge', 'lorentz', 'permutation')
REQUIRED = ('ufo-static', 'vertex-quantum-numbers', 'conjugate-vertices',
            *(f'mg5-check-{k}' for k in MG5_CHECKS))
STATIC_REQUIRED = ('ufo-static', 'vertex-quantum-numbers', 'conjugate-vertices')
STANDARD_KEYS = {'pdg_code', 'name', 'antiname', 'spin', 'color', 'mass', 'width', 'texname', 'antitexname',
                 'charge', 'line', 'propagating', 'goldstoneboson', 'GoldstoneBoson', 'goldstone', 'propagator',
                 'selfconjugate', 'counterterm', 'loop_particles'}
SUMMARY = re.compile(r'Summary:\s*(\d+)/(\d+)\s+passed,\s*(\d+)/(\d+)\s+failed')
SCOPE = ('Tree-level structural admission of a UFO: static parse, per-vertex additive quantum numbers, conjugate '
         'vertex closure, the ModelSpec hypercharge census and FeynRules Hermiticity when supplied, and MadGraph '
         'gauge, Lorentz and permutation checks on the requested process.')
CANNOT_DETECT = {
    'ufo-static': ['wrong numerical values or wrong analytic coupling expressions',
                   'Lorentz or colour structures that parse but are physically wrong'],
    'vertex-quantum-numbers': ['quantum numbers the UFO does not declare on its particles',
                               'hypercharge in a broken-phase UFO: mass eigenstates carry Y = 0, so the sum is vacuous',
                               'colour flow and non-additive (multiplicative or discrete) symmetries'],
    'conjugate-vertices': ['a conjugate vertex whose coupling is not the complex conjugate of the original',
                           'ghost vertices, which are skipped (the ghost Lagrangian is not Hermitian term by term)'],
    'spec-charge-census': ['terms the ModelSpec does not list; it checks the spec, not the generated UFO',
                                'whether the spec matches the supplied Lagrangian'],
    'hermiticity-feynrules': ['parts of the Lagrangian the receipt did not check (two-gauge checks cover the new terms)',
                              'errors introduced after FeynRules, in the UFO export or by hand edits'],
    'mg5-check-gauge': ['gauge dependence in processes without massive vector bosons, where the check is vacuous',
                        'processes other than the requested one; loop-level gauge invariance'],
    'mg5-check-lorentz': ['Lorentz violation that cancels at the sampled phase-space points',
                          'processes other than the requested one'],
    'mg5-check-permutation': ['errors symmetric under the permutations of external legs MadGraph tries',
                              'processes other than the requested one'],
    'ward-identity': ['not run by minimal admission; gauge-current conservation on the requested process is unchecked'],
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
                          .encode()).hexdigest()


def tree_digest(root):
    """Digest of the {relative path: sha256} map of every regular file outside caches."""
    from ravel.physics.model_tool_bridge import source_tree
    return _digest(source_tree(root)['files'])


class ModelEvidenceError(ValueError):
    """Typed generation prerequisite with an actionable repair."""

    def __init__(self, reason, detail):
        self.reason = 'model_evidence_' + reason
        self.remedy = ('Record accepted admission and width evidence for the current model, complete process '
                       'card and explicit parameter card; renew changed evidence through its original validator '
                       'or supply attributed external validation for that exact point.')
        super().__init__(f'{self.reason}: {detail}; remedy={self.remedy}')


def _evidence_pin(pin, base, files):
    from ravel.physics import model_tool_bridge as custody
    if not isinstance(pin, dict) or not {'path', 'sha256'} <= set(pin):
        raise ModelEvidenceError('absent', 'a pinned evidence record is required')
    try:
        path = custody._pin(pin, base)
    except (ValueError, OSError) as exc:
        raise ModelEvidenceError('stale', str(exc)) from exc
    files.append(path)
    return path


def _evidence_record(path):
    from ravel.physics.model_tool_bridge import _read
    try:
        record = _read(path)
    except (OSError, ValueError) as exc:
        raise ModelEvidenceError('invalid', 'readable evidence JSON required') from exc
    if not isinstance(record, dict):
        raise ModelEvidenceError('invalid', 'evidence record must be an object')
    return record


def _process_commands(raw):
    commands = [' '.join(line.split('#', 1)[0].split()) for line in raw.splitlines()]
    commands = [line for line in commands if line and not line.startswith('import model ')]
    if (not commands or sum(line.startswith('generate ') for line in commands) != 1
            or any(not line.startswith(('define ', 'set ', 'generate ', 'add process ')) for line in commands)
            or any(any(c in line for c in (';', '\\', '\r', '\x00')) for line in commands)):
        raise ValueError('complete literal definition/generate/add-process card required')
    active, cases = [], []
    for line in commands:
        if line.startswith('define '):
            if not re.fullmatch(r'define [A-Za-z0-9_+~\-]+ = [A-Za-z0-9_+~\- ]+', line):
                raise ValueError('literal particle definition required')
            active.append(line)
        elif line.startswith('set '):
            if not re.fullmatch(r'set [A-Za-z0-9_]+ [A-Za-z0-9_./:+~\- ]+', line):
                raise ValueError('literal process setup setting required')
            active.append(line)
        else:
            cases.append((_process_line(line.removeprefix('generate ').removeprefix('add process ')),
                          list(active)))
    if not cases or not next(line for line in commands if line.startswith(('generate ', 'add process '))).startswith('generate '):
        raise ValueError('generate must precede additional processes')
    return commands, cases


def generation_binding(ufo, process, card, *, restriction='full'):
    """Content identity of the model, effective aliases/processes and selected card."""
    if not isinstance(restriction, str) or not re.fullmatch(r'[A-Za-z0-9_\-]+', restriction):
        raise ValueError('literal model restriction identity required')
    imports = [' '.join(line.split('#', 1)[0].split()).removeprefix('import model ')
               for line in process.splitlines() if line.strip().startswith('import model ')]
    suffix = '' if restriction == 'default' else '-' + restriction
    if imports and (len(imports) != 1 or imports[0] not in
                    (Path(ufo).name + suffix, str(Path(ufo).absolute()) + suffix)):
        raise ModelEvidenceError('foreign', 'process card imports another model or restriction')
    commands, _ = _process_commands(process)
    from ravel.physics.model_events import parameter_values
    parameter_values(Path(card).read_text())
    return {'ufo_digest': tree_digest(ufo), 'process_commands': commands,
            'restriction': restriction, 'parameter_card_sha256': _sha(card)}


def _binding(record, expected):
    binding = record.get('generation_binding', record.get('binding'))
    if not isinstance(binding, dict):
        raise ModelEvidenceError('absent', 'receipt requires its model/process/card binding')
    if binding != expected:
        raise ModelEvidenceError('foreign', 'receipt belongs to another model, process, restriction or card')


def accepted_admission(record, expected, base, files):
    """Consume the existing admission verdict and its required-check evidence."""
    if record.get('decision') != 'admitted':
        raise ModelEvidenceError('failed', 'model admission requires an admitted decision')
    _binding(record, expected)
    if record.get('kind') == 'external-model-admission':
        return _external_evidence(record, base, files)
    if record.get('kind') != KIND or type(record.get('schema_version')) is not int or record['schema_version'] != SCHEMA:
        raise ModelEvidenceError('invalid', 'model-admission schema1 required')
    rows = record.get('checks')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ModelEvidenceError('absent', 'required admission checks are required')
    ids = [row.get('id') for row in rows]
    if any(not isinstance(identity, str) for identity in ids):
        raise ModelEvidenceError('invalid', 'admission check identities must be strings')
    if len(set(ids)) != len(ids) or not set(REQUIRED) <= set(ids):
        raise ModelEvidenceError('absent', 'every REQUIRED admission check must occur once')
    if record.get('ufo_digest') != expected['ufo_digest']:
        raise ModelEvidenceError('foreign', 'admission UFO differs from generation')
    if (record.get('refusals') or set(record.get('not_evaluated', ())) & set(REQUIRED)
            or any(row.get('status') == 'fail' or (row.get('id') in REQUIRED and row.get('status') != 'pass') for row in rows)):
        raise ModelEvidenceError('failed', 'required admission checks must pass')
    for row in rows:
        if row['id'].startswith('mg5-check-'):
            cases = row.get('cases', [row])
            if not isinstance(cases, list) or any(not isinstance(case, dict) for case in cases):
                raise ModelEvidenceError('invalid', 'native process check records required')
            if not cases or any(case.get('status') != 'pass' for case in cases):
                raise ModelEvidenceError('failed', 'each process check must pass')
            intended = _process_commands('\n'.join(expected['process_commands']))[1]
            if len(cases) != len(intended):
                raise ModelEvidenceError('foreign', 'admission check population differs from generation')
            for case, (expression, aliases) in zip(cases, intended):
                if not {'process', 'definitions', 'ufo_digest', 'parameter_card_sha256', 'restriction', 'log', 'script', 'parameter_card'} <= set(case):
                    raise ModelEvidenceError('absent', 'native check requires its complete process/card evidence')
                if (case.get('process') != expression or case.get('definitions') != aliases
                        or case.get('ufo_digest') != expected['ufo_digest']
                        or case.get('parameter_card_sha256') != expected['parameter_card_sha256']
                        or case.get('restriction') != expected['restriction']):
                    raise ModelEvidenceError('foreign', 'native check used another process, alias, restriction or card')
                _evidence_pin(case.get('log'), base, files)
                _evidence_pin(case.get('script'), base, files)
                card = _evidence_pin(case.get('parameter_card'), base, files)
                if _sha(card) != expected['parameter_card_sha256']:
                    raise ModelEvidenceError('foreign', 'native check card differs from generation')
    return 'local'


def _external_evidence(record, base, files):
    if type(record.get('schema_version')) is not int or record['schema_version'] != 1:
        raise ModelEvidenceError('invalid', 'external validation schema1 required')
    if not isinstance(record.get('qualification'), str) or not record['qualification'].strip():
        raise ModelEvidenceError('absent', 'external validation requires an explicit qualification')
    provenance = record.get('provenance')
    if not isinstance(provenance, list) or not provenance:
        raise ModelEvidenceError('absent', 'external validation requires original provenance')
    for pin in provenance:
        _evidence_pin(pin, base, files)
    return 'external'


def evidence_request(evidence):
    """Require both receipt pins before expanding native runtime inputs."""
    if not isinstance(evidence, dict) or not {'admission', 'widths'} <= set(evidence):
        raise ModelEvidenceError('absent', 'generation requires admission and width receipt pins')
    if set(evidence) != {'admission', 'widths'}:
        raise ModelEvidenceError('invalid', 'model_validation requires exactly admission and widths')
    return evidence


def generation_evidence(evidence, base, *, ufo, process, card, restriction='full'):
    """Bind admitted model and width records at each generation consumer."""
    from ravel.physics import model_derivation_bridge
    evidence_request(evidence)
    files = []
    try:
        expected = generation_binding(ufo, process, card, restriction=restriction)
    except ModelEvidenceError:
        raise
    except OSError as exc:
        raise ModelEvidenceError('stale', 'current model or parameter card is unavailable') from exc
    except ValueError as exc:
        raise ModelEvidenceError('invalid', str(exc)) from exc
    admission_path = _evidence_pin(evidence['admission'], base, files)
    record = _evidence_record(admission_path)
    origin = accepted_admission(record, expected, admission_path.parent, files)
    width_path = _evidence_pin(evidence['widths'], base, files)
    widths = _evidence_record(width_path)
    if not isinstance(widths, dict) or widths.get('status') != 'passed':
        raise ModelEvidenceError('failed', 'width consistency requires a passed receipt')
    _binding(widths, expected)
    parameter = _evidence_pin(widths.get('parameter_card'), width_path.parent, files)
    if _sha(parameter) != expected['parameter_card_sha256']:
        raise ModelEvidenceError('foreign', 'width receipt selects another parameter card')
    if widths.get('kind') == 'external-model-widths':
        width_origin = _external_evidence(widths, width_path.parent, files)
    elif (widths.get('kind') == 'model-width-consistency' and type(widths.get('schema_version')) is int
          and widths['schema_version'] == 1):
        handoff = _evidence_pin(widths.get('derivation_handoff'), width_path.parent, files)
        try:
            current = model_derivation_bridge.generation_width_receipt(handoff, expected, input_files=files)
        except ModelEvidenceError:
            raise
        except (OSError, ValueError, KeyError) as exc:
            raise ModelEvidenceError('stale', str(exc)) from exc
        if any(widths.get(key) != current[key] for key in ('binding', 'parameter_card', 'widths', 'scope')):
            raise ModelEvidenceError('stale', 'width receipt differs from its current derivation')
        width_origin = 'local'
    else:
        raise ModelEvidenceError('invalid', 'qualified local or external width record required')
    combined = origin if origin == width_origin else 'mixed'
    return {'binding': expected, 'origin': combined, 'checked_here': combined == 'local',
            'admission_origin': origin, 'width_origin': width_origin,
            'admission_scope': record.get('scope', record.get('qualification')),
            'width_scope': widths.get('scope', widths.get('qualification')),
            'receipts': evidence, 'qualifications': [r['qualification'] for r in (record, widths)
                if 'qualification' in r], 'inputs': sorted(set(map(str, files)))}


def scoped_generation_evidence(g, base, model):
    """Consume every scoped point's explicit card, admission and width provenance."""
    from ravel.physics import model_tool_bridge as custody, model_events
    process = '\n'.join([*[f'define {k} = {v}' for k, v in g['definitions'].items()],
                         'generate ' + g['process']])
    restriction = g['model'][len(Path(model).name):].lstrip('-') or 'default'
    reports, files = {}, []
    for point in g.get('parameter_points') or [None]:
        evidence = (point or g).get('model_validation')
        if not isinstance(evidence, dict) or 'widths' not in evidence:
            raise ModelEvidenceError('absent', 'every generated point requires model_validation')
        width_path = _evidence_pin(evidence['widths'], base, files)
        width_record = _evidence_record(width_path)
        selected = _evidence_pin(width_record.get('parameter_card'), width_path.parent, files)
        current = (point or {}).get('parameter_card', g.get('parameter_card') if point is None else None)
        card = custody._regular(current, base) if current is not None else selected
        report = generation_evidence(evidence, base, ufo=model, process=process, card=card,
                                     restriction=restriction)
        effective = model_events.parameter_values(card.read_text())
        for row in (point or {}).get('overrides', []):
            address = (row['block'].lower(), tuple(row['code']))
            if address not in effective or (row['value'] != 'Auto' and effective[address] != model_events.number(row['value'])):
                raise ModelEvidenceError('foreign', 'point override differs from its admitted effective card')
        # Preserve the complete original point while applying its declared edits.
        # Auto selects the independently recorded effective width/branching population.
        if point is not None and 'parameter_card' in g:
            original = model_events.parameter_values(custody._regular(g['parameter_card'], base).read_text())
            effective = model_events.parameter_values(card.read_text())
            auto = set()
            for row in point['overrides']:
                address = (row['block'].lower(), tuple(row['code']))
                if address not in original:
                    raise ModelEvidenceError('foreign', 'override address differs from original card')
                if row['value'] == 'Auto':
                    if address[0] != 'decay':
                        raise ModelEvidenceError('invalid', 'Auto requires a decay address')
                    auto.add(address[1][0]); original.pop(address)
                else:
                    original[address] = model_events.number(row['value'])
            def retained(rows):
                return {k: v for k, v in rows.items() if not
                    ((k[0] in ('decay', '@branch')) and k[1][0] in auto)}
            if retained(original) != retained(effective) or any(('decay', (pdg,)) not in effective for pdg in auto):
                raise ModelEvidenceError('foreign', 'validated point differs from declared card overrides')
        report['parameter_card'] = {'path': str(card), 'sha256': _sha(card)}
        reports[point['id'] if point else 'single'] = report
    return reports


def _row(check_id, status, **detail):
    return {'id': check_id, 'status': status, 'required': check_id in REQUIRED,
            'cannot_detect': CANNOT_DETECT[check_id], **detail}


def _parse(ufo, name):
    return ast.parse((Path(ufo) / name).read_text(errors='replace'))


def particle_table(ufo):
    """Particle variables from particles.py, including ``X = Y.anti()`` with negated quantum numbers."""
    table, problems = {}, []
    for stmt in _parse(ufo, 'particles.py').body:
        if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.targets[0], ast.Name)):
            continue
        var, call = stmt.targets[0].id, stmt.value
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == 'anti' and isinstance(func.value, ast.Name):
            base = table.get(func.value.id)
            if base is None:
                problems.append(f'{var}: anti() of undeclared particle {func.value.id}')
                continue
            table[var] = {'name': base['antiname'], 'antiname': base['name'], 'pdg': -base['pdg'],
                          'spin': base['spin'], 'self_conjugate': False, 'anti': func.value.id,
                          'quantum_numbers': {k: -v for k, v in base['quantum_numbers'].items()}}
            base['anti'] = var
            continue
        if ufo_check._call_name(call) != 'Particle':
            continue
        kw = {k.arg: k.value for k in call.keywords if k.arg}
        name, antiname = ufo_check._literal(kw.get('name')), ufo_check._literal(kw.get('antiname'))
        qn = {}
        for key, node in kw.items():
            if isinstance(node, ast.Constant) and isinstance(node.value, bool):
                continue  # a flag such as GoldstoneBoson = True, not an additive quantum number
            if key == 'charge' or key not in STANDARD_KEYS:
                value = ufo_check._charge(node)
                if value is None:
                    problems.append(f'{var}: quantum number {key} is not a literal number')
                else:
                    qn[key] = value
        if 'charge' not in qn and 'charge' not in kw:
            problems.append(f'{var}: no charge')
        table[var] = {'name': name, 'antiname': antiname, 'pdg': ufo_check._literal(kw.get('pdg_code')),
                      'spin': ufo_check._literal(kw.get('spin')), 'self_conjugate': name == antiname,
                      'anti': var if name == antiname else None, 'quantum_numbers': qn}
    by_name = {row['name']: var for var, row in table.items()}
    for var, row in table.items():
        if row['anti'] is None:
            row['anti'] = by_name.get(row['antiname'])
            if row['anti'] is None:
                problems.append(f'{var}: antiparticle {row["antiname"]} is not declared')
    if problems:
        raise ValueError('; '.join(problems))
    return table


def _vertices(ufo):
    rows = []
    for var, v in ufo_check._objects(_parse(ufo, 'vertices.py'), 'Vertex').items():
        node = v['kw'].get('particles')
        refs = [ufo_check._ref(e) for e in getattr(node, 'elts', [])]
        rows.append({'vertex': var, 'particles': refs})
    return rows


def _fraction_text(value):
    return str(Fraction(value))


def vertex_quantum_numbers(ufo, table=None):
    table = table if table is not None else particle_table(ufo)
    numbers = sorted({k for row in table.values() for k in row['quantum_numbers']})
    vertices = _vertices(ufo)
    violations, undeclared = [], []
    for v in vertices:
        missing = [p for p in v['particles'] if p not in table]
        if missing or not v['particles']:
            undeclared.append({'vertex': v['vertex'], 'particles': missing})
            continue
        for qn in numbers:
            total = sum((table[p]['quantum_numbers'].get(qn, Fraction(0)) for p in v['particles']), Fraction(0))
            if total != 0:
                violations.append({'vertex': v['vertex'], 'quantum_number': qn, 'sum': _fraction_text(total)})
    status = 'fail' if violations or undeclared else 'pass'
    return _row('vertex-quantum-numbers', status, quantum_numbers=numbers, vertices=len(vertices),
                violations=violations, undeclared_particles=undeclared)


def conjugate_vertices(ufo, table=None):
    table = table if table is not None else particle_table(ufo)
    vertices = [v for v in _vertices(ufo) if all(p in table for p in v['particles'])]
    contents = {tuple(sorted(v['particles'])) for v in vertices}
    missing, ghosts = [], 0
    for v in vertices:
        if any(table[p]['spin'] == -1 for p in v['particles']):
            ghosts += 1
            continue
        conjugate = tuple(sorted(table[p]['anti'] for p in v['particles']))
        if conjugate not in contents:
            missing.append({'vertex': v['vertex'], 'particles': sorted(table[p]['name'] for p in v['particles']),
                            'conjugate_particles': sorted(table[p]['name'] for p in conjugate)})
    return _row('conjugate-vertices', 'fail' if missing else 'pass', vertices=len(vertices),
                ghost_vertices_skipped=ghosts, missing=missing)


def hypercharge_check(spec, census=None):
    if census is None:
        if spec is None:
            return _row('spec-charge-census', 'not_evaluated', reason='no ModelSpec was given')
        from ravel.physics import model_authoring
        census = model_authoring.charge_census(spec)
    violations = [{'term': t['term'], 'problems': t['problems']} for t in census['terms'] if not t['passed']]
    return _row('spec-charge-census', 'fail' if violations else 'pass', terms=len(census['terms']),
                violations=violations)


def hermiticity_check(native):
    """FeynRules CheckHermiticity from a two-gauge receipt or a derivation physical-checks receipt."""
    native = native or {}
    gauge = native.get('gauge_checks')
    if isinstance(gauge, dict) and {'feynman', 'unitary'} <= set(gauge):
        verdicts = {}
        for name in ('unitary', 'feynman'):
            row = (gauge.get(name) or {}).get('CheckHermiticity') or {}
            verdicts[name] = row.get('holds') is True and row.get('message_free') is True
        return _row('hermiticity-feynrules', 'pass' if all(verdicts.values()) else 'fail', source='two-gauge checks',
                    verdicts=verdicts, lagrangian=(gauge.get('lagrangians') or {}).get('hermiticity_and_kinetic'))
    herm = (native.get('physical_checks') or {}).get('hermiticity')
    if isinstance(herm, dict) and herm.get('requested') is True:
        holds = (herm.get('message_free') is True and herm.get('returned_list') is True
                 and herm.get('vertex_count') == 0)
        return _row('hermiticity-feynrules', 'pass' if holds else 'fail', source='derivation physical checks',
                    non_hermitian_vertex_count=herm.get('vertex_count'))
    return _row('hermiticity-feynrules', 'not_evaluated', reason='no FeynRules CheckHermiticity receipt was given')


def _process_line(process):
    if not isinstance(process, str) or not process.strip() or '\n' in process or ';' in process:
        raise ValueError('one MadGraph process line is required')
    return process.strip()


def mg5_check(ufo, kind, process, *, mg5, workdir, runner=None, timeout=900,
              parameter_card=None, definitions=(), restriction='full'):
    """``import model`` then ``check <kind> <process>`` in a fresh MadGraph session on a copy of the UFO."""
    if kind not in MG5_CHECKS:
        raise ValueError(f'MadGraph check must be one of {", ".join(MG5_CHECKS)}')
    process = _process_line(process)
    workdir = Path(workdir).absolute()
    workdir.mkdir(parents=True, exist_ok=False)
    model = workdir / Path(ufo).name
    shutil.copytree(ufo, model)  # MadGraph writes caches next to the model; keep the admitted tree untouched
    script = workdir / 'check.mg5'
    card_arg = ''
    if parameter_card is not None:
        card = workdir / 'param_card.dat'
        shutil.copyfile(parameter_card, card)
        card_arg = str(card) + ' '
    selected_model = str(model) + ('-' + restriction if parameter_card is not None and restriction != 'default' else '')
    script.write_text(f'set auto_update 0\nset automatic_html_opening False\nimport model {selected_model}\n'
                      + ''.join(line + '\n' for line in definitions) + f'check {kind} {card_arg}{process}\n')
    model_before = tree_digest(model)
    if model_before != tree_digest(ufo):
        raise ModelEvidenceError('stale', 'native check copy differs from the source UFO')
    card_before = _sha(card) if parameter_card is not None else None
    script_before = _sha(script)
    command = [str(c) for c in (*(mg5 if isinstance(mg5, (list, tuple)) else [mg5]), script)]
    run = runner or (lambda cmd: subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout))
    completed = run(command)
    if (model_before != tree_digest(model) or script_before != _sha(script)
            or (parameter_card is not None and card_before != _sha(card))):
        raise ModelEvidenceError('stale', 'model, card or command changed during native admission')
    output = (completed.stdout or '') + '\n' + (completed.stderr or '')
    log = workdir / 'mg5.log'
    log.write_text(output)
    found = SUMMARY.findall(output)
    detail = {'process': process, 'command': command, 'returncode': completed.returncode, 'ufo_digest': model_before,
              'log': {'path': str(log), 'sha256': _sha(log)}}
    if parameter_card is not None:
        detail.update(parameter_card={'path': str(card), 'sha256': card_before},
                      parameter_card_sha256=card_before, definitions=list(definitions), restriction=restriction,
                      script={'path': str(script), 'sha256': script_before})
    if not found:
        return _row(f'mg5-check-{kind}', 'error', reason='MadGraph printed no check summary', **detail)
    passed, total, failed, _ = (int(x) for x in found[-1])
    failures = re.findall(r'Failed processes:\s*(.+)', output)
    if failed or passed < total:
        status = 'fail'
    elif total < 1 or completed.returncode != 0:
        status = 'error'
    else:
        status = 'pass'
    return _row(f'mg5-check-{kind}', status, passed_count=passed, total=total, failed_count=failed,
                failed_processes=failures, **detail)


def _decide(rows, required):
    refusals = [f'{r["id"]}: {_reason(r)}' for r in rows if r['status'] == 'fail']
    not_evaluated = [r['id'] for r in rows if r['id'] in required and r['status'] not in ('pass', 'fail')]
    decision = 'refused' if refusals else 'incomplete' if not_evaluated else 'admitted'
    return decision, refusals, not_evaluated


def _reason(row):
    if 'cases' in row:
        return '; '.join(case['process'] + ': ' + _reason(case) for case in row['cases'] if case['status'] != 'pass')
    if row['id'] == 'ufo-static':
        return '; '.join(row.get('errors') or [])
    if row['id'] == 'vertex-quantum-numbers':
        parts = [f'{v["vertex"]} {v["quantum_number"]} sums to {v["sum"]}' for v in row['violations']]
        parts += [f'{u["vertex"]} uses undeclared particles {", ".join(map(str, u["particles"]))}'
                  for u in row['undeclared_particles']]
        return '; '.join(parts)
    if row['id'] == 'conjugate-vertices':
        return '; '.join(f'{m["vertex"]} ({" ".join(m["particles"])}) has no conjugate vertex '
                         f'({" ".join(m["conjugate_particles"])})' for m in row['missing'])
    if row['id'] == 'spec-charge-census':
        return '; '.join(f'{v["term"]}: {", ".join(v["problems"])}' for v in row['violations'])
    if row['id'] == 'hermiticity-feynrules':
        return 'FeynRules CheckHermiticity reports non-Hermitian terms'
    return f'{row.get("failed_count")}/{row.get("total")} failed: {", ".join(row.get("failed_processes") or [])}'


def _static_rows(ufo, spec):
    static = ufo_check.check(ufo, spec=spec)
    rows = [_row('ufo-static', 'pass' if static['passed'] else 'fail', errors=static['errors'],
                 warnings=static['warnings'], counts=static.get('counts'))]
    if not all(n in static.get('counts', {}) for n in ('particles', 'vertices')):
        reason = 'the UFO did not parse'
        return rows + [_row(i, 'not_evaluated', reason=reason) for i in ('vertex-quantum-numbers', 'conjugate-vertices')]
    try:
        table = particle_table(ufo)
    except ValueError as exc:
        return rows + [_row(i, 'fail', reason=str(exc), violations=[], undeclared_particles=[], missing=[])
                       for i in ('vertex-quantum-numbers', 'conjugate-vertices')]
    return rows + [vertex_quantum_numbers(ufo, table), conjugate_vertices(ufo, table)]


def _record(ufo, rows, required, **extra):
    decision, refusals, not_evaluated = _decide(rows, required)
    return {'schema_version': SCHEMA, 'kind': KIND, 'ufo': str(Path(ufo).absolute()), 'ufo_digest': tree_digest(ufo),
            **extra, 'decision': decision, 'refusals': refusals, 'not_evaluated': not_evaluated,
            'checks': rows, 'scope': SCOPE}


def static_admission(ufo, *, spec=None):
    """The checks that need no MadGraph: static parse, vertex quantum numbers, conjugate vertices.

    ``decision`` is ``passed`` or ``refused``; this is not an admission.
    """
    rows = _static_rows(ufo, spec)
    record = _record(ufo, rows, STATIC_REQUIRED)
    record['decision'] = 'refused' if record['decision'] == 'refused' else (
        'passed' if record['decision'] == 'admitted' else 'incomplete')
    return record


def admit(ufo, *, spec=None, native=None, mg5=None, process=None, workdir=None, mg5_runner=None, timeout=900,
          parameter_card=None, definitions=(), restriction='full', process_card=None):
    """Run every admission check with available evidence; return the admission record."""
    binding = None
    if process_card is not None:
        if process is not None or definitions:
            raise ValueError('supply process_card or process/definitions')
        raw = Path(process_card).read_text()
    else:
        raw = '\n'.join([*definitions, 'generate ' + process]) if process is not None else None
    cases = _process_commands(raw)[1] if raw is not None else [(process, definitions)]
    if parameter_card is not None:
        if raw is None:
            raise ValueError('explicit process card required with a parameter card')
        binding = generation_binding(ufo, raw, parameter_card, restriction=restriction)
    if mg5 is not None:
        for expression, _ in cases: _process_line(expression)
        if workdir is None:
            raise ValueError('a fresh MadGraph work directory is required')
    rows = _static_rows(ufo, spec)
    rows += [hypercharge_check(spec), hermiticity_check(native)]
    static_failed = any(r['status'] == 'fail' for r in rows)
    for kind in MG5_CHECKS:
        if mg5 is None:
            rows.append(_row(f'mg5-check-{kind}', 'not_evaluated', reason='no MadGraph executable was given'))
        elif static_failed:
            rows.append(_row(f'mg5-check-{kind}', 'not_evaluated', reason='static admission already refused the UFO'))
        else:
            checked = [mg5_check(ufo, kind, expression, mg5=mg5,
                workdir=Path(workdir) / kind / str(index), runner=mg5_runner, timeout=timeout,
                parameter_card=parameter_card, definitions=aliases, restriction=restriction)
                for index, (expression, aliases) in enumerate(cases)]
            row = checked[0] if len(checked) == 1 else _row(f'mg5-check-{kind}',
                'fail' if any(r['status'] == 'fail' for r in checked) else
                'pass' if all(r['status'] == 'pass' for r in checked) else 'error', cases=checked)
            rows.append(row)
    rows.append(_row('ward-identity', 'not_evaluated', reason='not part of minimal admission'))
    if binding is not None and binding != generation_binding(ufo, raw, parameter_card, restriction=restriction):
        raise ModelEvidenceError('stale', 'model or card changed during admission')
    if binding is not None and any(case['ufo_digest'] != binding['ufo_digest']
            for row in rows if row['id'].startswith('mg5-check-') and row['status'] == 'pass'
            for case in row.get('cases', [row])):
        raise ModelEvidenceError('stale', 'native process checks used another source UFO')
    return _record(ufo, rows, REQUIRED, process=process,
                   **({'generation_binding': binding} if binding is not None else {}))


def add_arguments(parser):
    parser.add_argument('--ufo', required=True, type=Path)
    parser.add_argument('--spec', type=Path, help='ModelSpec JSON: spec agreement and the hypercharge census')
    parser.add_argument('--native-checks', type=Path,
                        help='FeynRules receipt with two-gauge checks or physical checks (CheckHermiticity)')
    parser.add_argument('--mg5', help='MadGraph executable for check gauge, lorentz and permutation')
    parser.add_argument('--process', help='the requested process, one MadGraph process line')
    parser.add_argument('--process-card', type=Path, help='complete definition/generate/add-process card')
    parser.add_argument('--parameter-card', type=Path, help='explicit card used by every process check')
    parser.add_argument('--restriction', default='full', help='exact model restriction, or full')
    parser.add_argument('--workdir', type=Path, help='fresh directory for the MadGraph sessions')
    parser.add_argument('--out', type=Path, help='write the admission record here (a new file)')


def command(args):
    spec = json.loads(args.spec.read_text()) if args.spec else None
    native = json.loads(args.native_checks.read_text()) if args.native_checks else None
    if args.mg5 and not (args.process or args.process_card):
        raise SystemExit('--mg5 needs --process or --process-card')
    record = admit(args.ufo, spec=spec, native=native, mg5=args.mg5, process=args.process,
                   workdir=args.workdir or (args.mg5 and Path(args.ufo).absolute().parent / 'admission-mg5'),
                   process_card=args.process_card, parameter_card=args.parameter_card, restriction=args.restriction)
    text = json.dumps(record, indent=2, default=str) + '\n'
    if args.out:
        with Path(args.out).open('x') as handle:
            handle.write(text)
        print(json.dumps({k: record[k] for k in ('decision', 'refusals', 'not_evaluated')}, indent=2))
    else:
        print(text, end='')
    return 0 if record['decision'] == 'admitted' else 1
