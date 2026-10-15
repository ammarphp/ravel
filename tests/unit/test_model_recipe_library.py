"""The shipped model-recipe library renders the cards the former slepton template produced.

The reference below is the former renderer's logic (keyed run-card edits applied after the
configuration's run options, placeholder substitution into the parameter card, the launch
script around the process definitions), applied to the upstream template bytes.
"""
import hashlib
import json
import math
import re
import tomllib
from pathlib import Path

import jsonschema
import pytest

from ravel.physics import prepare_native_slepton as prep
from ravel.workflow import scan_orchestrator as scan

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT/'src/ravel/data/templates'
NAME = 'slepton-bino-isrslep'

# sha256 of the upstream bytes the former renderer read.
UPSTREAM = {
    'slepton_bino_param_template.slha': '6082b13ab708273c8a1bf9d93dbc021c413a18203aaa09dce23b57e41086d371',
    'madgraph_run_default_lo.dat': '6b8b59628e1ed043e39f7058294c524ff1948c59b0c0b249c2102dbccba138f6',
    'pythia8_mg_interface_card.dat': 'fb894838ddef6bc9afccb391f99a81fb0bf8426665d0c9e8ef4d93a6b579b248',
    'slepton_isrslep_generate.mg5': '3331083941396c2b77572bf6e735cb69e9d3987aecdeea3a33961c709e565a89',
}


def old_run_card(nevents, seed, options, pdf, ecms):
    lines = (TEMPLATES/'madgraph_run_default_lo.dat').read_text().splitlines()

    def setkey(key, value):
        found = [i for i, line in enumerate(lines) if not line.lstrip().startswith(('#', '!'))
                 and re.search(rf'=\s*{re.escape(key)}\s*(?:[#!]|$)', line)]
        assert len(found) == 1, key
        lines[found[0]] = f'  {value}  = {key}'

    for key, value in options.items():
        setkey(key, ('True' if value else 'False') if isinstance(value, bool) else str(value))
    setkey('nevents', f'{int(nevents)}')
    setkey('iseed', f'{int(seed)}')
    setkey('ebeam1', f'{ecms/2:g}')
    setkey('ebeam2', f'{ecms/2:g}')
    setkey('ickkw', '0')
    if pdf in ('cteq6l1', 'nn23nlo'):
        setkey('pdlabel', pdf)
    else:
        setkey('pdlabel', 'lhapdf')
        setkey('lhaid', '260000')
    setkey('use_syst', 'False')
    return '\n'.join(lines) + '\n'


def old_cards(m_parent, m_lsp, nevents, seed, options, pdf, ecms, rundir):
    param = ((TEMPLATES/'slepton_bino_param_template.slha').read_text()
             .replace('{{MSLEP}}', f'{m_parent:g}').replace('{{MN1}}', f'{m_lsp:g}'))
    out = Path(rundir).resolve()/'output'
    gen = (TEMPLATES/'slepton_isrslep_generate.mg5').read_text().rstrip()
    launch = f"""{gen}
output output/PROC_madgraph

set run_mode 2
set nb_core 4
launch output/PROC_madgraph
madspin=OFF
shower=OFF
reweight=OFF
done
{out/'param_card.dat'}
{out/'run_card.dat'}
set iseed {int(seed)}
done
"""
    return {'param_card.dat': param, 'run_card.dat': old_run_card(nevents, seed, options, pdf, ecms),
            'run.mg5': launch}


@pytest.fixture(scope='module')
def template_config():
    return tomllib.loads((TEMPLATES/'slepton_scan_template.toml').read_text())


def plan_inputs(cfg, extra=None):
    declared = {**cfg['ravel']['native'].get('inputs', {}), **(extra or {})}

    def input_file(key, fallback=None):
        value = declared.get(key, fallback)
        if not value:
            raise ValueError(f'explicit {key} input is unresolved')
        return Path(value)
    return input_file


def library_cards(masses, pdf, nevents, seed, ecms, tmp_path):
    entry, recipe = prep.library_entry(NAME)
    request = {'schema_version': 1, **prep.library_paths(NAME),
               **prep.library_rendering(NAME, masses=masses, pdf=pdf)}
    request.pop('pythia_card')
    request['run_controls'].update({'nevents': nevents, 'iseed': seed, 'ebeam1': ecms/2, 'ebeam2': ecms/2})
    return prep.render_recipe(request, base=TEMPLATES, rundir=tmp_path)


def test_shipped_templates_are_the_pinned_upstream_bytes():
    for name, digest in UPSTREAM.items():
        assert hashlib.sha256((TEMPLATES/name).read_bytes()).hexdigest() == digest, name
    assert (TEMPLATES/'LICENSE.mapyde.txt').read_text().lstrip().startswith('Apache License')


def test_library_entry_validates_and_every_named_file_ships():
    entry, recipe = prep.library_entry(NAME)
    schema = json.loads((TEMPLATES/'card_recipe.schema.json').read_text())
    jsonschema.validate(recipe, schema)
    for key in ('param_template', 'run_template', 'process_card', 'launch_template'):
        assert (TEMPLATES/recipe[key]).is_file(), key
    assert (TEMPLATES/entry['scan_template']).is_file() and (TEMPLATES/entry['shower_card']).is_file()
    for field in ('process', 'spectrum', 'decays', 'matching', 'pdf_choices', 'parameters'):
        assert entry[field], field
    assert set(entry['pdf_choices']) == {'cteq6l1', 'nn23nlo', 'nnpdf30'}
    assert set(prep.library_paths(NAME)) == {'param_template', 'run_template', 'process_card',
                                             'launch_template', 'pythia_card'}


def test_every_expected_mass_is_a_pdg_of_a_declared_parameter():
    entry, _ = prep.library_entry(NAME)
    rendered = prep.library_rendering(NAME, masses={'MSLEP': 220, 'MN1': 100}, pdf='cteq6l1')
    assert rendered['expected_masses'] == {'1000011': 220, '1000013': 220, '1000015': 220,
                                           '2000011': 220, '2000013': 220, '2000015': 220, '1000022': 100}
    assert set(rendered['parameters']) == set(entry['parameters'])


@pytest.mark.parametrize('masses', [(150, 140), (200, 150), (87.5, 30), (1000, 1)])
@pytest.mark.parametrize('pdf', ['cteq6l1', 'nn23nlo', 'nnpdf30'])
def test_rendered_cards_equal_the_former_template_rendering(masses, pdf, template_config, tmp_path):
    options = template_config['madgraph']['run']['options']
    parent, lsp = masses
    expected = old_cards(parent, lsp, 2500, 13, options, pdf, 13000, tmp_path)
    actual = library_cards({'MSLEP': parent, 'MN1': lsp}, pdf, 2500, 13, 13000, tmp_path)
    assert actual['param_card.dat'] == expected['param_card.dat']
    assert actual['run_card.dat'] == expected['run_card.dat']
    assert actual['run.mg5'] == expected['run.mg5']
    assert '{{' not in actual['param_card.dat'] + actual['run_card.dat'] + actual['run.mg5']


def test_the_native_seam_binds_masses_pdf_and_options_from_the_configuration(template_config, tmp_path):
    cfg = json.loads(json.dumps(template_config))
    cfg['madgraph']['masses'] = {'MSLEP': 200, 'MN1': 150}
    rendered, translation, controls, expected, selected_pdf, selection = prep.prepare_for_plan(
        cfg, rundir=tmp_path, input_file=plan_inputs(cfg), nevents=2500, seed=13, ecms=13000,
        pdf='cteq6l1', model='slepton-bino')
    reference = old_cards(200, 150, 2500, 13, template_config['madgraph']['run']['options'],
                          'cteq6l1', 13000, tmp_path)
    assert rendered['param_card.dat'] == reference['param_card.dat']
    assert rendered['run_card.dat'] == reference['run_card.dat']
    assert rendered['run.mg5'] == reference['run.mg5']
    assert expected['1000022'] == 150 and selected_pdf == 'cteq6l1'
    assert selection['selection'] == f'model-recipe library entry {NAME}'
    assert 'Beams:frameType = 4' in rendered['shower.cfg']


def test_a_configuration_option_overrides_the_library_cut_key_by_key(template_config, tmp_path):
    cfg = json.loads(json.dumps(template_config))
    cfg['madgraph']['masses'] = {'MSLEP': 200, 'MN1': 150}
    cfg['madgraph']['run']['options']['ptj1min'] = 80
    rendered = prep.prepare_for_plan(cfg, rundir=tmp_path, input_file=plan_inputs(cfg), nevents=10,
                                     seed=1, ecms=13000, pdf='nn23nlo', model='slepton-bino')[0]
    assert '  80  = ptj1min' in rendered['run_card.dat']
    assert '  20  = ptj\n' in rendered['run_card.dat']
    # Structural controls are never overridable by an option.
    cfg['madgraph']['run']['options']['ickkw'] = 1
    with pytest.raises(ValueError, match='conflicts'):
        prep.prepare_for_plan(cfg, rundir=tmp_path, input_file=plan_inputs(cfg), nevents=10, seed=1,
                              ecms=13000, pdf='nn23nlo', model='slepton-bino')


@pytest.mark.parametrize('change,error', [
    (lambda c: c['madgraph'].__setitem__('masses', {'MSLEP': 200}), prep.MissingInputError),
    (lambda c: c['ravel']['native'].__setitem__('rendering', {'schema_version': 1}), ValueError),
])
def test_missing_masses_or_a_second_rendering_source_are_refused(template_config, tmp_path, change, error):
    cfg = json.loads(json.dumps(template_config))
    cfg['madgraph']['masses'] = {'MSLEP': 200, 'MN1': 150}
    change(cfg)
    with pytest.raises(error):
        prep.prepare_for_plan(cfg, rundir=tmp_path, input_file=plan_inputs(cfg), nevents=10, seed=1,
                              ecms=13000, pdf='cteq6l1', model='slepton-bino')


def test_no_pdf_is_chosen_for_the_caller(template_config, tmp_path):
    cfg = json.loads(json.dumps(template_config))
    cfg['madgraph']['masses'] = {'MSLEP': 200, 'MN1': 150}
    with pytest.raises(prep.MissingInputError) as caught:
        prep.prepare_for_plan(cfg, rundir=tmp_path, input_file=plan_inputs(cfg), nevents=10, seed=1,
                              ecms=13000, model='slepton-bino')
    assert caught.value.field == 'pdf'
    with pytest.raises(ValueError, match='unknown PDF'):
        prep.library_rendering(NAME, masses={'MSLEP': 200, 'MN1': 150}, pdf='unlisted')
    with pytest.raises(ValueError, match='unknown model recipe'):
        prep.library_entry('no-such-recipe')


def test_the_scan_template_takes_both_masses_from_the_scan_axes(template_config, tmp_path):
    text = (TEMPLATES/'slepton_scan_template.toml').read_text()
    spec = {'subst': {'madgraph.masses.MSLEP': 'm_slepton', 'madgraph.masses.MN1': 'm_lsp'}}
    rendered = tomllib.loads(scan.substitute_toml(text, spec, {'m_slepton': 275.0, 'm_lsp': 90.0}))
    assert rendered['madgraph']['masses'] == {'MSLEP': 275, 'MN1': 90}
    cards = prep.prepare_for_plan(rendered, rundir=tmp_path, input_file=plan_inputs(rendered),
                                  nevents=10, seed=2, ecms=13000, pdf='cteq6l1', model='slepton-bino')[0]
    assert '275  # Msl1' in cards['param_card.dat'] and '90 # Mneu1' in cards['param_card.dat']


def test_the_command_line_writes_the_same_cards(template_config, tmp_path):
    run = tmp_path/'run'
    prep.main(['--library', NAME, '--parameter', 'MSLEP=150', '--parameter', 'MN1=140', '--nevents', '2500',
               '--seed', '13', '--pdf', 'cteq6l1', '--rundir', str(run)])
    reference = old_cards(150, 140, 2500, 13, template_config['madgraph']['run']['options'],
                          'cteq6l1', 13000, run)
    for name, text in reference.items():
        assert (run/'output'/name).read_text() == text
    record = json.loads((run/'output/rendering_sources.json').read_text())
    assert record['runtime_consumption'].startswith('unverified')
    with pytest.raises(SystemExit):
        prep.main(['--library', NAME, '--recipe', 'x.json', '--rundir', str(run)])
    with pytest.raises(prep.MissingInputError):
        prep.main(['--library', NAME, '--parameter', 'MSLEP=150', '--parameter', 'MN1=140',
                   '--nevents', '10', '--seed', '1', '--rundir', str(run)])


def test_decay_rows_are_explicit_for_every_produced_slepton():
    text = (TEMPLATES/'slepton_bino_param_template.slha').read_text()
    for pdg in (1000011, 1000013, 1000015, 2000011, 2000013, 2000015):
        block = re.search(rf'DECAY\s+{pdg}\s.*?(?=\nDECAY|\Z)', text, re.S).group(0)
        assert re.search(r'1\.0+E\+00\s+2\s+1000022\s', block), pdg
    masses = dict(re.findall(r'^\s*(\d{7})\s+(\S+)\s+#', text, re.M))
    assert masses['1000022'] == '{{MN1}}'
    assert all(masses[str(p)] == '{{MSLEP}}' for p in (1000011, 1000013, 1000015, 2000011, 2000013, 2000015))
    assert math.isfinite(float(masses['1000001'].replace('E', 'e')))
