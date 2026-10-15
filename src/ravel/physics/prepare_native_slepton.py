#!/usr/bin/env python
"""Render model/process recipes without executing a scientific tool.

The module name is retained for callers. The renderer selects no model, point, PDF,
process population, cut or native input path on its own: a supplied recipe (--recipe)
or a named entry of the shipped model-recipe library (--library, see
data/templates/model_recipes.json) states each choice, and the masses, PDF and run
controls are bound explicitly. Use --rundir for the destination.
"""
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = 'ravel.physics'

import argparse
import json
import math
import re
from pathlib import Path


class MissingInputError(ValueError):
    reason = 'missing-input'

    def __init__(self, field):
        self.field = field
        super().__init__(f'{self.reason}: supplied {field} required')


def required(document, key):
    if key not in document or document[key] is None:
        raise MissingInputError(key)
    return document[key]


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite numeric parameter required')
    return f'{value:g}'


def scalar(value):
    if type(value) is bool:
        return 'True' if value else 'False'
    if type(value) in (int, float):
        return finite(value)
    if type(value) is str and value and not any(x in value for x in ('\n', '\r', '#', '!', '{{')):
        return value
    raise ValueError('single literal card value required')


def source_path(value, base):
    if not isinstance(value, str) or not value or '{{' in value:
        raise ValueError('explicit source path required')
    path = Path(value)
    path = (Path(base)/path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_file() or not path.stat().st_size:
        raise MissingInputError(str(path))
    return path


def render_parameters(text, parameters, bindings):
    if not isinstance(parameters, dict) or not parameters:
        raise MissingInputError('parameters')
    if not isinstance(bindings, list) or not bindings:
        raise MissingInputError('bindings')
    lines = text.splitlines(keepends=True)
    addresses = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError('parameter binding must be an object')
        name = required(binding, 'parameter')
        if name not in parameters:
            raise MissingInputError(f'parameters.{name}')
        value = finite(parameters[name])
        if 'placeholder' in binding:
            if set(binding) != {'parameter', 'placeholder'} or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', str(binding['placeholder'])):
                raise ValueError('closed placeholder binding required')
            token = '{{'+binding['placeholder']+'}}'
            address = ('placeholder', token)
            if address in addresses or token not in ''.join(lines):
                raise ValueError('duplicate or missing parameter placeholder')
            lines = [line.replace(token, value) for line in lines]
        else:
            if set(binding) != {'parameter', 'block', 'indices'}:
                raise ValueError('closed block/indices binding required')
            block = binding['block']; indices = binding['indices']
            if not isinstance(block, str) or not block or type(indices) is not list or not indices or any(type(i) is not int for i in indices):
                raise ValueError('explicit block and integer indices required')
            address = (block.upper(), tuple(indices))
            if address in addresses:
                raise ValueError('duplicate parameter address')
            current = None; matches = []
            for i, line in enumerate(lines):
                tokens = list(re.finditer(r'\S+', line.split('#', 1)[0].split('!', 1)[0]))
                words = [t.group() for t in tokens]
                if not words:
                    continue
                if words[0].upper() == 'BLOCK':
                    current = words[1].upper() if len(words) > 1 else None
                    continue
                if words[0].upper() == 'DECAY':
                    current = None
                    if block.upper() == 'DECAY' and words[1:2] == [str(indices[0])] and len(indices) == 1 and len(tokens) >= 3:
                        matches.append((i, tokens[2]))
                    continue
                if current == block.upper() and words[:len(indices)] == [str(x) for x in indices] and len(tokens) > len(indices):
                    matches.append((i, tokens[len(indices)]))
            if len(matches) != 1:
                raise ValueError(f'parameter card needs exactly one {block} {indices} address')
            i, token = matches[0]
            lines[i] = lines[i][:token.start()]+value+lines[i][token.end():]
        addresses.add(address)
    rendered = ''.join(lines)
    if '{{' in rendered or '}}' in rendered:
        raise ValueError('unresolved parameter-card placeholder')
    return rendered


def render_run(text, controls):
    if not isinstance(controls, dict) or not controls:
        raise MissingInputError('run_controls')
    for key in ('nevents', 'iseed', 'ebeam1', 'ebeam2', 'pdlabel', 'ickkw', 'use_syst'):
        required(controls, key)
    if type(controls['nevents']) is not int or controls['nevents'] <= 0:
        raise ValueError('nevents must be a positive integer')
    if type(controls['iseed']) is not int or controls['iseed'] < 0:
        raise ValueError('iseed must be a nonnegative integer')
    for key in ('ebeam1', 'ebeam2'):
        finite(controls[key])
        if controls[key] <= 0:
            raise ValueError('beam energies must be positive')
    lines = text.splitlines()
    for key, value in controls.items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', str(key)):
            raise ValueError('literal run-card key required')
        found = [i for i, line in enumerate(lines) if not line.lstrip().startswith(('#', '!'))
                 and re.search(rf'=\s*{re.escape(key)}\s*(?:[#!]|$)', line)]
        if len(found) != 1:
            raise ValueError(f'run card needs exactly one {key} assignment')
        lines[found[0]] = f'  {scalar(value)}  = {key}'
    rendered = '\n'.join(lines)+'\n'
    if '{{' in rendered or '}}' in rendered:
        raise ValueError('unresolved run-card placeholder')
    return rendered


def render_recipe(recipe, *, base, rundir):
    """Pure rendering; supplied sources and bindings determine all physics choices."""
    if not isinstance(recipe, dict) or recipe.get('schema_version') != 1:
        raise ValueError('version-1 rendering recipe required')
    paths = {key: source_path(required(recipe, key), base) for key in ('param_template', 'run_template', 'process_card', 'launch_template')}
    parameters = required(recipe, 'parameters'); bindings = required(recipe, 'bindings')
    from jsonschema import validate, ValidationError
    from ..paths import package_data_path
    schema = json.loads(package_data_path('templates', 'card_recipe.schema.json').read_text())
    # Missing required inputs retain their typed refusal before structural validation.
    required(recipe, 'run_controls')
    try:
        validate(recipe, schema)
    except ValidationError as exc:
        raise ValueError(f'invalid rendering recipe: {exc.message}') from exc
    controls = required(recipe, 'run_controls')
    process = paths['process_card'].read_text().rstrip()
    active = [l.split('#', 1)[0].strip() for l in process.splitlines()]
    if not any(l.startswith('import model ') for l in active) or not any(l.startswith('generate ') for l in active):
        raise ValueError('supplied process needs model import and generation definition')
    if any(re.match(r'(?:output|launch|done|quit|exit)\b', l, re.I) for l in active) or '{{' in process:
        raise ValueError('process source must contain definitions only; no output/launch commands')
    for line in active:
        words = line.split()
        if len(words) >= 2 and words[0] == 'set' and words[1] in controls:
            raise ValueError('process setting conflicts with supplied generation controls')
    out = Path(rundir).resolve()/'output'
    # Bare absolute card paths are positional inputs to the generator prompt.
    if any(c in str(out) for c in ('\n', '\r')):
        raise ValueError('single-line output path required')
    mg5 = paths['launch_template'].read_text()
    replacements = {'PROCESS': process, 'PARAM_CARD': str(out/'param_card.dat'),
                    'RUN_CARD': str(out/'run_card.dat'), 'SEED': scalar(required(controls, 'iseed'))}
    for name in ('PROCESS', 'PARAM_CARD', 'RUN_CARD'):
        if mg5.count('{{'+name+'}}') != 1:
            raise ValueError(f'launch template needs exactly one {name} placeholder')
    for name, value in replacements.items():
        mg5 = mg5.replace('{{'+name+'}}', value)
    if '{{' in mg5 or '}}' in mg5:
        raise ValueError('unresolved launch-template placeholder')
    return {'param_card.dat': render_parameters(paths['param_template'].read_text(), parameters, bindings),
            'run_card.dat': render_run(paths['run_template'].read_text(), controls), 'run.mg5': mg5}


LIBRARY_CONTROLS_FROM_PLAN = ('nevents', 'iseed', 'ebeam1', 'ebeam2')


def _template_path(*parts):
    from ..paths import package_data_path
    return package_data_path('templates', *parts)


def library_entry(name):
    """One entry of the shipped model-recipe library, with its recipe document."""
    index = json.loads(_template_path('model_recipes.json').read_text())
    entry = index['recipes'].get(name)
    if entry is None:
        raise ValueError(f'unknown model recipe {name!r}; the library holds: {", ".join(sorted(index["recipes"]))}')
    return entry, json.loads(_template_path(entry['recipe']).read_text())


def library_paths(name):
    """Absolute paths of the shipped templates a library recipe renders from."""
    entry, recipe = library_entry(name)
    paths = {key: str(_template_path(recipe[key]))
             for key in ('param_template', 'run_template', 'process_card', 'launch_template')}
    if 'shower_card' in entry:
        paths['pythia_card'] = str(_template_path(entry['shower_card']))
    return paths


def library_rendering(name, *, masses, pdf):
    """Bind the caller's masses and PDF to a library recipe; every other choice is the recipe's own.

    Returns the rendering fields of a version-1 recipe (parameters, bindings, run controls and
    the masses the rendered card must carry). nevents, iseed and the beam energies come from
    the plan or the command line, never from the library.
    """
    entry, recipe = library_entry(name)
    names = set(recipe['parameters'])
    if not isinstance(masses, dict) or set(masses) != names:
        raise MissingInputError('masses (' + ', '.join(sorted(names)) + ')')
    if pdf is None:
        raise MissingInputError('pdf')
    choice = entry['pdf_choices'].get(pdf)
    if choice is None:
        raise ValueError(f'unknown PDF {pdf!r} for recipe {name}; choices: {", ".join(sorted(entry["pdf_choices"]))}')
    parameters = {key: masses[key] for key in sorted(names)}
    for value in parameters.values():
        finite(value)
    controls = {key: value for key, value in recipe['run_controls'].items()
                if key not in LIBRARY_CONTROLS_FROM_PLAN and key != 'pdlabel'}
    controls.update(choice)
    expected = {str(pdg): parameters[key] for key, meta in entry['parameters'].items() for pdg in meta['pdg']}
    return {'parameters': parameters, 'bindings': json.loads(json.dumps(recipe['bindings'])),
            'run_controls': controls, 'expected_masses': expected}


def prepare_for_plan(cfg, *, rundir, input_file, nevents, seed, ecms, pdf=None, model=None):
    """Native adapter seam: rendering rules with original custody and shower checks.

    The rules are either a supplied ``rendering`` recipe or a named ``library`` entry
    (``[ravel.native] library = ...``) bound to ``[madgraph.masses]`` and an explicit PDF.
    """
    from . import native_effective_config as effective
    native = cfg.get('ravel', {}).get('native', {})
    library = native.get('library')
    defaults = {}
    if library is not None:
        if 'rendering' in native:
            raise ValueError('a library selection and an explicit rendering recipe are exclusive')
        recipe = {'schema_version': 1, **library_rendering(
            library, masses=cfg.get('madgraph', {}).get('masses', {}), pdf=pdf or native.get('pdf'))}
        defaults = library_paths(library)
    else:
        recipe = required(native, 'rendering')
    if required(recipe, 'schema_version') != 1:
        raise ValueError('version-1 native rendering recipe required')
    from ..paths import package_data_path
    schema_path = package_data_path('templates', 'card_recipe.schema.json').resolve()
    if Path(input_file('rendering_schema', schema_path)).resolve() != schema_path:
        raise ValueError('native rendering schema conflicts with the product schema')
    parameters = required(recipe, 'parameters'); bindings = required(recipe, 'bindings')
    declarations = cfg.get('madgraph', {}).get('masses', {})
    targets = {b.get('placeholder', b.get('parameter')): b.get('parameter') for b in bindings if isinstance(b, dict)}
    for name, value in declarations.items():
        parameter = targets.get(name, name)
        if parameter not in parameters or not effective.equivalent(value, parameters[parameter]):
            raise ValueError(f'declared parameter {name} conflicts with rendering binding')
    controls = dict(required(recipe, 'run_controls'))
    authoritative = {'nevents': nevents, 'iseed': seed, 'ebeam1': ecms/2, 'ebeam2': ecms/2}
    for key, value in authoritative.items():
        if key in controls and not effective.equivalent(controls[key], value):
            raise ValueError(f'rendering {key} conflicts with declared generation control')
        controls[key] = value
    selected_pdf = pdf or native.get('pdf')
    expected_label = 'lhapdf' if selected_pdf == 'nnpdf30' else selected_pdf
    if selected_pdf is not None and controls.get('pdlabel') != expected_label:
        raise ValueError('PDF conflicts with explicit rendering control')
    for key, value in cfg.get('madgraph', {}).get('run', {}).get('options', {}).items():
        if key in authoritative or key in ('pdlabel', 'lhaid', 'ickkw', 'use_syst'):
            raise ValueError(f'run option {key} conflicts with declared native generation controls')
        if key in controls and not effective.equivalent(controls[key], value) and library is None:
            raise ValueError(f'run option {key} conflicts with rendering control')
        controls[key] = value
    selected = {key: str(input_file(key, defaults.get(key)))
                for key in ('param_template', 'run_template', 'process_card', 'launch_template')}
    request = {**recipe, **selected, 'schema_version': 1, 'parameters': parameters,
               'bindings': bindings, 'run_controls': controls}
    rendered = render_recipe(request, base=rundir, rundir=rundir)
    actual = effective.assignments(rendered['run_card.dat'], run=True)
    if controls['ickkw'] != 0 or controls['use_syst'] is not False:
        raise ValueError('matching or systematic-weight controls require a different native adapter')
    for key in ('ktdurham', 'ptlund', 'xqcut'):
        if float(actual.get(key, -1)) > 0:
            raise ValueError(f'active matching/merging control {key} requires a different native adapter')
    shower = input_file('pythia_card', defaults.get('pythia_card'))
    rendered['shower.cfg'], translation = effective.translate_shower(cfg, shower,
        lhe=Path(rundir)/'output/madgraph/unweighted_events.lhe', nevents=nevents)
    expected = required(recipe, 'expected_masses')
    if not isinstance(expected, dict) or not expected:
        raise MissingInputError('expected_masses')
    for value in expected.values():
        finite(value)
    # Pre-launch tie between the declared masses and the rendered card bytes.
    masses, current = {}, None
    for line in rendered['param_card.dat'].splitlines():
        words = line.split('#', 1)[0].split()
        if words and words[0].upper() in ('BLOCK', 'DECAY'):
            current = words[1].upper() if words[0].upper() == 'BLOCK' and len(words) > 1 else None
        elif current == 'MASS' and len(words) >= 2:
            masses[words[0].lstrip('+')] = words[1]
    for pdg, value in expected.items():
        if pdg not in masses or not effective.equivalent(masses[pdg], value):
            raise ValueError(f'expected mass {pdg} differs from the rendered parameter card')
    if model is not None:
        from .native_capabilities import MODEL_PDGS
        parents, child = MODEL_PDGS.get(model, ((), None))
        if str(child) in expected and any(str(p) in expected and abs(float(expected[str(p)])) <= abs(float(expected[str(child)])) for p in parents):
            raise ValueError('declared parent must be heavier than the LSP')
    # The pipeline's own process/model admission still checks scientific compatibility.
    return rendered, translation, controls, expected, selected_pdf, {'selection': f'model-recipe library entry {library}' if library is not None else 'supplied rendering recipe',
        'disposition': 'explicit native.inputs.process_card is authoritative'}


def rendered_launch_card(plan, fallback):
    """Effective-card seam; explicit-card adapters retain their own launch protocol."""
    return plan.get('rendered', {}).get('run.mg5', fallback)


def write_shower_cfg(rundir, out, *, cfg, source, nevents, seed=None):
    from .native_effective_config import translate_shower
    if seed is not None:
        cfg = {**cfg, 'madgraph': {**cfg.get('madgraph', {}), 'run': {**cfg.get('madgraph', {}).get('run', {}), 'seed': seed}}}
    text, translation = translate_shower(cfg, source,
        lhe=f'{rundir}/output/PROC_madgraph/Events/run_01/unweighted_events.lhe', nevents=nevents)
    Path(out).write_text(text)
    return translation


def _library_request(args):
    """A full version-1 recipe from a library entry and the command-line bindings."""
    masses = {}
    for item in args.parameter or []:
        name, sep, value = item.partition('=')
        if not sep:
            raise ValueError('--parameter expects NAME=VALUE')
        masses[name] = float(value)
    for key in ('nevents', 'seed', 'pdf'):
        if getattr(args, key) is None:
            raise MissingInputError(key)
    entry, recipe = library_entry(args.library)
    request = {'schema_version': 1, **library_paths(args.library),
               **library_rendering(args.library, masses=masses, pdf=args.pdf)}
    request.pop('pythia_card', None)
    ecms = args.ecms if args.ecms is not None else 2*recipe['run_controls']['ebeam1']
    request['run_controls'].update({'nevents': args.nevents, 'iseed': args.seed,
                                    'ebeam1': ecms/2, 'ebeam2': ecms/2})
    return request, _template_path(entry['recipe'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', help='supplied version-1 JSON rendering recipe')
    parser.add_argument('--library', help='entry of the shipped model-recipe library (data/templates/model_recipes.json)')
    parser.add_argument('--parameter', action='append', metavar='NAME=VALUE',
                        help='library recipe parameter, for example a mass in GeV (repeatable)')
    parser.add_argument('--nevents', type=int, help='library recipe event count')
    parser.add_argument('--seed', type=int, help='library recipe generator seed')
    parser.add_argument('--ecms', type=float, help='library recipe collision energy in GeV (default: the recipe)')
    parser.add_argument('--pdf', help='library recipe PDF choice, as named by the library entry')
    parser.add_argument('--rundir', required=True, help='destination run directory; no tools launched')
    args = parser.parse_args(argv)
    if (args.recipe is None) == (args.library is None):
        parser.error('exactly one of --recipe and --library is required')
    if args.library is not None:
        recipe, path = _library_request(args)
        rendered = render_recipe(recipe, base=path.parent, rundir=args.rundir)
    else:
        path = Path(args.recipe).resolve()
        recipe = json.loads(path.read_text())
        rendered = render_recipe(recipe, base=path.parent, rundir=args.rundir)
    out = Path(args.rundir)/'output'; out.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (out/name).write_text(text)
    from .native_normalization import fingerprint
    from ..workflow.state_io import atomic_json
    atomic_json(out/'rendering_sources.json', {'schema_version': 1, 'recipe': fingerprint(path),
        'sources': [fingerprint(source_path(recipe[k], path.parent)) for k in ('param_template', 'run_template', 'process_card', 'launch_template')],
        'cards': {name: fingerprint(out/name) for name in rendered},
        'runtime_consumption': 'unverified; rendering does not authorize or execute a tool'})
    print(f'prepared recipe -> {out}')


if __name__ == '__main__':
    main()
