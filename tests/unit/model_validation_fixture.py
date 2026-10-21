"""Attributed fictional validation records for inert generation controls."""
import hashlib
import json
from pathlib import Path

from ravel.physics import model_admission as admission


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n' if isinstance(data, dict) else data)
    return pin(path)


def supplied_evidence(base, model, process, card, *, restriction='full'):
    binding = admission.generation_binding(model, process, card, restriction=restriction)
    source = write(base / 'validation-source.txt', 'Fictional external model/process/card validation.\n')
    common = {'schema_version': 1, 'binding': binding, 'provenance': [source],
              'qualification': 'Supplied external validation of this exact source point.'}
    return {'admission': write(base / 'admission.json', {**common, 'kind': 'external-model-admission',
                                                       'decision': 'admitted'}),
            'widths': write(base / 'widths.json', {**common, 'kind': 'external-model-widths',
                'status': 'passed', 'parameter_card': pin(card)})}


def record_model_events_validation(c, base):
    c['model_validation'] = supplied_evidence(base,
        Path(c['model_tree']['root']), Path(c['cards']['process']['path']).read_text(),
        Path(c['cards']['parameter']['path']))


def scoped_evidence(g, base, *, auto_widths=None, selected_card=None):
    """Explicit source points for the scoped fake generator's declared outputs."""
    from ravel.physics.model_events import parameter_values, number
    runtime = Path(g['runtime']['madgraph'])
    model = runtime / 'models' / g['model']
    if 'model_origin' in g:
        model = Path(json.loads(Path(g['model_origin']).read_text())['ufo'])
    if not model.is_dir():
        return
    card = Path(g.get('parameter_card', base / 'fixture-card.dat'))
    if 'parameter_card' not in g:
        write(card, 'BLOCK MASS\n 25 125\nDECAY 25 4.07e-03\n')
        g['parameter_card'] = str(card)
    process = '\n'.join([*[f'define {k} = {v}' for k, v in g['definitions'].items()], 'generate ' + g['process']])
    for point in g.get('parameter_points') or [None]:
        selected = selected_card or card
        if point:
            rows = parameter_values(card.read_text())
            for row in point['overrides']:
                key = (row['block'].lower(), tuple(row['code']))
                if row['value'] == 'Auto':
                    value, branches = auto_widths[key[1][0]]
                    rows[key] = number(value)
                    for index, (fraction, daughters) in enumerate(branches, 1):
                        rows[('@branch', (key[1][0], index, *daughters))] = number(fraction)
                else:
                    rows[key] = number(row['value'])
            lines = []
            for block in sorted({k[0] for k in rows} - {'decay', '@branch', '@scale'}):
                lines.append('BLOCK ' + block)
                lines += [' '.join(map(str, codes)) + ' ' + str(v) for (b, codes), v in rows.items() if b == block]
            for (block, codes), value in rows.items():
                if block != 'decay': continue
                lines.append(f'DECAY {codes[0]} {value}')
                lines += [f'{v} {len(c)-2} ' + ' '.join(map(str, c[2:])) for (b, c), v in rows.items()
                          if b == '@branch' and c[0] == codes[0]]
            selected = base / ('point-' + point['id'] + '.dat')
            write(selected, '\n'.join(lines) + '\n')
        identity = point['id'] if point else 'single'
        (point if point else g)['model_validation'] = supplied_evidence(base / ('evidence-' + identity),
            model, process, selected, restriction='default')


def native_evidence(config, build):
    """Bind the explicit native fixture to its attributed inert UFO source."""
    from ravel.physics import native_pipeline
    c = native_pipeline.read_config(config)
    root = config.parent
    raw = (root / c['ravel']['native']['inputs']['process_card']).read_text()
    imported = next(line.removeprefix('import model ') for line in raw.splitlines() if line.startswith('import model '))
    model = build / 'tools/mg5amcnlo/models' / imported
    write(model / 'particles.py', '# attributed inert model source\n')
    process = '\n'.join(line for line in raw.splitlines() if line.startswith(('define ', 'generate ', 'add process ')))
    card = root / c['ravel']['native']['inputs']['param_card']
    evidence = supplied_evidence(root / 'validation', model, process, card, restriction='default')
    def entry(pin):
        return '{path = ' + json.dumps(pin['path']) + ', sha256 = ' + json.dumps(pin['sha256']) + '}'
    declaration = 'model_validation = {admission = ' + entry(evidence['admission']) + ', widths = ' + entry(evidence['widths']) + '}\n'
    config.write_text(config.read_text().replace('[ravel.native.inputs]', declaration + '[ravel.native.inputs]', 1))
