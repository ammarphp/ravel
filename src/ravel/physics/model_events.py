"""Explicit full-UFO MG5 generation, decays, shower matching and multiweights.

Uses existing source custody, ordinary approval, supervisor and native executor.
The generator and its integrated shower supply the amplitudes and events. This
module never substitutes an unmatched sample or invents a coefficient/UFO map.
"""
import argparse
import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ravel.physics import model_tool_bridge as bridge
from ravel.physics import pythia_cards
from ravel.physics.model_event_weights import require, scan, scan_hepmc2_weights, number
from ravel.validation import core as validation_core

SCHEMES = {'unmerged_lo': 'LO', 'mlm': 'LO', 'ckkw_l': 'LO', 'mcatnlo': 'NLO', 'fxfx': 'NLO'}
CARD_NAMES = {'process': 'proc_card.dat', 'parameter': 'param_card.dat', 'run': 'run_card.dat',
              'pythia': 'pythia8_card.dat', 'shower': 'shower_card.dat', 'madspin': 'madspin_card.dat', 'reweight': 'reweight_card.dat'}
SCOPE = 'source_bound_generated_event_delivery'


def authenticated_text(path, expected=None):
    p=bridge._regular(str(path),Path.cwd());before=p.stat()
    require(before.st_size<=2*1024**2,'scientific document exceeds 2MiB bound')
    with p.open('rb') as stream:
        opened=os.fstat(stream.fileno());raw=stream.read(2*1024**2+1);closed=os.fstat(stream.fileno())
    after=p.stat();identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(opened)==identity(closed)==identity(after),'scientific source changed during consumption')
    require(expected is None or hashlib.sha256(raw).hexdigest()==expected,'consumed source bytes differ from pin')
    return raw.decode('utf-8')


def keys(obj, names, label):
    try:
        validation_core.closed_object(dict(obj) if isinstance(obj, dict) else obj, names, field=label)
    except ValueError:
        validation_core.fail(label, obj, 'exactly ' + ', '.join(sorted(names)),
                             message=label + ' requires exactly ' + ', '.join(sorted(names)))


def text(value, label):
    require(type(value) is str and value.strip() and len(value) <= 4096 and '\n' not in value and '\r' not in value, label + ' requires literal single-line text')
    return value


def positive(value, label):
    message = label + ' must be finite and positive'
    try:
        # Preserve the original Decimal path for arbitrarily large finite ints.
        checked = number(value) if type(value) is int else validation_core.finite_number(value, field=label)
        if checked <= 0:
            raise ValueError(message)
    except ValueError:
        if type(value) is float and (value != value or abs(value) == float('inf')):
            message = 'nonfinite LHE number'
        validation_core.fail(label, value, 'finite positive number', message=message)


def assignments(raw, *, style='run', native_lo_empty_strings=False):
    """Parse actual supplied/observed card literals without executing a card."""
    require(type(native_lo_empty_strings) is bool, 'native LO empty-string mode must be Boolean')
    require(not native_lo_empty_strings or style == 'run', 'native LO empty-string mode requires run-card syntax')
    if style == 'pythia':
        parsed = pythia_cards.parse(raw)
        require(not parsed['channel_commands'], 'ordered Pythia channels require the typed card parser')
        return parsed['settings']
    result = {}
    for line in raw.splitlines():
        line = line.split('#', 1)[0].split('!', 1)[0].strip()
        if not line:
            continue
        require('=' in line, 'unparsed setting in ' + style + ' card: ' + line)
        left, right = map(str.strip, line.rsplit('=', 1) if style == 'run' else line.split('=', 1))
        key, value = (right.lower(), left) if style == 'run' else (left.lower(), right)
        # MG5 2.9.27 RunCardLO's three str defaults are written bare when empty.
        # Retain these actual values only in the explicit observed-LO route;
        # unknown, numeric/Boolean and supplied-card blanks remain refused.
        native_empty = native_lo_empty_strings and key in ('issgridfile', 'aloha_flag', 'matrix_flag')
        require(re.fullmatch(r'[a-zA-Z0-9_:]+', key) and (value or native_empty) and key not in result, 'duplicate or malformed card setting')
        result[key] = value
    return result


def literal(value):
    lowered = value.lower()
    if lowered in ('true', '.true.', 'on'): return True
    if lowered in ('false', '.false.', 'off'): return False
    try:
        return number(value)
    except Exception:
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list): return [literal(str(x)) for x in parsed]
        except (ValueError, SyntaxError):
            pass
        return value.strip("'\"")


def matches(rows, expected, label, *, native_run_lists=False):
    for key, value in expected.items():
        require(key.lower() in rows, label + ' differs at ' + key)
        actual, declared = literal(rows[key.lower()]), literal(str(value))
        if native_run_lists and isinstance(declared, list) and not isinstance(actual, list):
            # MG2.9.27 RunCard.write emits numeric lists without brackets.
            # Only an explicitly declared list uses this ordered comparison;
            # no unknown setting, scalar, or native card row is discarded.
            items = [x.strip() for x in rows[key.lower()].split(',')]
            require(all(items), label + ' has malformed list at ' + key)
            actual = [literal(x) for x in items]
            require(all(isinstance(x, Decimal) or type(x) is bool for x in actual)
                    and all(isinstance(x, Decimal) or type(x) is bool for x in declared),
                    label + ' requires finite numeric/Boolean list at ' + key)
        if native_run_lists and isinstance(declared, list):
            require(isinstance(actual, list) and len(actual) == len(declared)
                    and all((type(a) is bool and type(d) is bool)
                            or (isinstance(a, Decimal) and isinstance(d, Decimal))
                            for a, d in zip(actual, declared)),
                    label + ' differs in list type/population at ' + key)
        require(actual == declared, label + ' differs at ' + key)


def parameter_values(raw):
    """Literal SLHA values/scales/branching rows; no Auto or computed widths."""
    values={};block=None;decay=None;branch=0
    for line in raw.splitlines():
        tokens=line.split('#',1)[0].split()
        if not tokens:continue
        head=tokens[0].lower()
        if head=='block':
            require(len(tokens)>=2,'explicit parameter block required');block=tokens[1].lower();decay=None
            if len(tokens)>2:
                suffix=''.join(tokens[2:]);require(suffix.upper().startswith('Q='),'only explicit SLHA block-scale metadata allowed')
                address=('@scale',(block,));value=number(suffix[2:]);require(value>0,'positive block scale required')
            else:continue
        elif head=='decay':
            require(len(tokens)==3 and tokens[2].lower()!='auto','explicit finite widths required; no automatic width computation')
            decay=int(tokens[1]);block=None;branch=0;address=('decay',(decay,));value=number(tokens[2]);require(value>=0,'nonnegative explicit width required')
        elif block is not None:
            require(len(tokens)>=2,'explicit external parameter address and value required')
            address=(block,tuple(int(x) for x in tokens[:-1]));value=number(tokens[-1])
        else:
            require(decay is not None and len(tokens)>=3,'parameter row outside a literal block or decay table')
            count=int(tokens[1]);require(count>0 and len(tokens)==count+2,'complete supplied branching population required')
            branch+=1;address=('@branch',(decay,branch,*map(int,tokens[2:])));value=number(tokens[0]);require(value>=0,'nonnegative supplied branching ratio required')
        require(address not in values,'duplicate supplied parameter identity');values[address]=value
    require(values,'complete explicit parameter card required');return values


def validate_config(c):
    keys(c, ('schema_version', 'source', 'runtime', 'model_tree', 'cards', 'generation', 'shower', 'decay',
             'reweight', 'weights', 'outputs', 'max_seconds', 'max_ram_mib', 'assumptions', *(['conventions'] if 'conventions' in c else []), *(['spectrum_origin'] if 'spectrum_origin' in c else []), *(['parameter_observation'] if 'parameter_observation' in c else []), *(['operative_seed_observation'] if 'operative_seed_observation' in c else []), *(['pre_shower_lhe_transform'] if 'pre_shower_lhe_transform' in c else []), *(['generator_reuse'] if 'generator_reuse' in c else []), *(['integration_checkpoint'] if 'integration_checkpoint' in c else [])), 'model-events configuration')
    require(c['schema_version'] == 1 and type(c['schema_version']) is int, 'model-events schema1 required')
    if 'integration_checkpoint' in c:
        from . import native_integration_checkpoint
        native_integration_checkpoint.validate(c['integration_checkpoint'])
        require('generator_reuse' not in c and 'pre_shower_lhe_transform' not in c,
                'same-run survey checkpoint is separate from static reuse and split shower')
        require(c['generation']['order'] == 'LO' and 'operative_seed_observation' in c,
                'regular released LO checkpoint requires complete operative seed observation')
    from . import generation_conventions
    generation_conventions.declaration(c.get('conventions', {}))
    text(c['source'], 'source')
    if 'generator_reuse' in c:
        from . import generator_reuse
        generator_reuse.validate(c['generator_reuse'])
    if 'parameter_observation' in c:
        from ravel.physics import model_event_parameters
        model_event_parameters.validate(c['parameter_observation'])
    require(isinstance(c['assumptions'], list) and c['assumptions'] and all(type(x) is str and x.strip() for x in c['assumptions']), 'explicit physics applicability assumptions required')
    require(type(c['max_seconds']) is int and 1 <= c['max_seconds'] <= 86400, 'native time ceiling required')
    require(type(c['max_ram_mib']) is int and 64 <= c['max_ram_mib'] <= 65536, 'native RAM ceiling required')
    keys(c['runtime'], ('madgraph_tree', 'python', 'python_manifest', 'dependencies', 'options'), 'runtime')
    require(isinstance(c['runtime']['dependencies'], list), 'runtime dependency trees required')
    for dep in c['runtime']['dependencies']:
        keys(dep, ('role', 'tree'), 'runtime dependency'); text(dep['role'], 'runtime role')
    require(len({x['role'] for x in c['runtime']['dependencies']}) == len(c['runtime']['dependencies']), 'duplicate runtime dependency role')
    keys(c['runtime']['options'], ('fortran_compiler', 'cpp_compiler', 'pythia8_path', 'mg5amc_py8_interface_path', 'lhapdf'), 'native options')
    keys(c['cards'], CARD_NAMES, 'supplied cards')
    for name in ('process', 'parameter', 'run'):
        require(c['cards'][name] is not None, 'explicit ' + name + ' card required')
    g = c['generation']
    keys(g, ('order', 'scheme', 'events', 'seed', 'beam_type', 'beam_pdg', 'energy_gev', 'jet_token', 'jet_multiplicities',
             'run_settings', 'scale_pdf'), 'generation')
    require(g['scheme'] in SCHEMES and g['order'] == SCHEMES[g['scheme']], 'explicit compatible perturbative order and matching regime required')
    if 'operative_seed_observation' in c:
        from ravel.physics import model_event_seed
        model_event_seed.validate(c['operative_seed_observation'])
        require(g['order']=='LO', 'operative seed observation requires released LO lifecycle')
    require(type(g['events']) is int and 1 <= g['events'] <= 1000000, 'bounded new-event ceiling required')
    require(type(g['seed']) is int and 1 <= g['seed'] <= 30000081, 'explicit MG seed required')
    for name in ('beam_type', 'beam_pdg', 'energy_gev'):
        require(type(g[name]) is list and len(g[name]) == 2, 'two explicit ' + name + ' values required')
    require(all(type(v) is int and v in (-1, 0, 1) for v in g['beam_type']), 'explicit MG beam type required')
    require(all(type(v) is int and v != 0 for v in g['beam_pdg']), 'explicit beam PDG required')
    from ravel.physics.beam_content import beam_errors
    mismatch = beam_errors(g['beam_pdg'], {'lpp1': g['beam_type'][0], 'lpp2': g['beam_type'][1]})
    require(not mismatch, 'beam type disagrees with the beam particle: ' + '; '.join(mismatch))
    for v in g['energy_gev']: positive(v, 'beam energy')
    require(isinstance(g['jet_multiplicities'], list) and g['jet_multiplicities'] and all(type(x) is int and x >= 0 for x in g['jet_multiplicities']) and sorted(set(g['jet_multiplicities'])) == g['jet_multiplicities'], 'unique ordered explicit jet multiplicities required')
    require(type(g['run_settings']) is dict and all(type(k) is str for k in g['run_settings']), 'operative run settings required')
    require(g['scale_pdf'] in ('none', 'lo_systematics', 'nlo_on_the_fly', 'nlo_systematics'), 'explicit scale/PDF prescription required')
    require((g['order'] == 'LO' and g['scale_pdf'] in ('none', 'lo_systematics')) or
            (g['order'] == 'NLO' and g['scale_pdf'] in ('none', 'nlo_on_the_fly', 'nlo_systematics')), 'scale/PDF prescription differs from perturbative order')
    s = c['shower']
    keys(s, ('backend', 'settings', 'merging_scale_gev', 'max_jets', 'process', 'minimum_returned_events'), 'shower')
    require(s['backend'] in ('OFF', 'PYTHIA8') and isinstance(s['settings'], dict), 'explicit integrated shower choice required')
    require(type(s['max_jets']) is int and s['max_jets'] == max(g['jet_multiplicities']), 'shower maximum jet population differs from process declaration')
    require(type(s['minimum_returned_events']) is int and 0 <= s['minimum_returned_events'] <= g['events'], 'explicit shower-return bound required')
    if s['backend'] == 'OFF':
        require(g['scheme'] == 'unmerged_lo' and s['minimum_returned_events'] == 0 and c['cards']['pythia'] is None and c['cards']['shower'] is None, 'requested matching/NLO cannot become unshowered LO')
    else:
        require(s['minimum_returned_events'] > 0, 'positive returned shower population required')
        require(c['cards']['pythia' if g['order'] == 'LO' else 'shower'] is not None, 'explicit selected shower card required')
        require(c['runtime']['options']['pythia8_path'] is not None, 'bound integrated PYTHIA8 prefix required')
        require(g['order']!='LO' or c['runtime']['options']['mg5amc_py8_interface_path'] is not None,
                'LO integrated shower requires its explicitly source-bound MG5aMC_PY8 interface')
    if g['scheme'] in ('mlm', 'ckkw_l', 'fxfx'):
        text(g['jet_token'], 'jet token'); positive(s['merging_scale_gev'], 'matching/merging scale')
        require(len(g['jet_multiplicities']) >= 2, 'merged sample requires complete multiple jet populations')
    else:
        require(s['merging_scale_gev'] is None, 'unmerged regime cannot inherit matching/merging scale')
    if g['scheme'] == 'ckkw_l': text(s['process'], 'explicit Pythia merging hard process')
    d = c['decay']
    keys(d, ('mode', 'spinmode', 'seed', 'commands'), 'decay')
    require(d['mode'] in ('OFF', 'MADSPIN'), 'explicit decay mechanism required')
    if d['mode'] == 'OFF':
        require(d['spinmode'] is None and d['seed'] is None and d['commands'] == [] and c['cards']['madspin'] is None, 'disabled MadSpin cannot carry a decay card')
    else:
        require(d['spinmode'] in ('madspin', 'full', 'onshell', 'none') and type(d['seed']) is int and d['seed'] > 0 and d['commands'] and c['cards']['madspin'] is not None, 'explicit MadSpin mode, seed, channels and card required')
        require(all(re.fullmatch(r'decay [A-Za-z0-9_+~\-]+ > [A-Za-z0-9_+~\- ,>{}]+', x) for x in d['commands']), 'bounded literal MadSpin decay declarations required')
    rw = c['reweight']
    keys(rw, ('mode', 'weight_ids'), 'reweight')
    require(rw['mode'] in ('OFF', 'LO', 'NLO', 'NLO_tree'), 'explicit matrix-element reweight mode required')
    require(type(rw['weight_ids']) is list and len(set(rw['weight_ids'])) == len(rw['weight_ids']), 'unique reweight names required')
    require((rw['mode'] == 'OFF' and rw['weight_ids'] == [] and c['cards']['reweight'] is None) or
            (rw['mode'] != 'OFF' and rw['weight_ids'] and c['cards']['reweight'] is not None), 'reweight switch/card mismatch')
    require(rw['mode'] in ('OFF', 'LO') or g['order'] == 'NLO', 'NLO reweight requires actual NLO generation')
    keys(c['weights'], ('groups', 'variation_points', 'sampling_law'), 'weights')
    require(c['weights']['sampling_law'] in ('unknown', 'generator_signed_events'), 'explicit sampling-law boundary required')
    ids = []
    for group in c['weights']['groups']:
        keys(group, ('name', 'combine', 'ids'), 'weight group'); text(group['name'], 'weight group')
        require(group['combine'] is None or type(group['combine']) is str, 'literal combine convention required')
        require(group['ids'] and all(type(x) is str and re.fullmatch(r'[A-Za-z0-9_.:+\-]+', x) for x in group['ids']), 'weight ids required')
        ids.extend(group['ids'])
    require(len(ids) == len(set(ids)) and 'nominal' not in ids and set(rw['weight_ids']) <= set(ids), 'duplicate/reserved/missing planned weight identities')
    require((g['scale_pdf'] != 'none' or rw['mode'] != 'OFF') == bool(ids), 'requested multiweights cannot be silently disabled')
    points = c['weights']['variation_points']
    require(isinstance(points, list) and len(points) == len(ids) and {x.get('id') for x in points} == set(ids), 'every declared weight requires exact variation-point semantics')
    for point in points:
        keys(point, ('id', 'kind', 'definition', 'source'), 'weight variation')
        require(point['kind'] in ('scale', 'pdf', 'parameter'), 'declared weight kind required')
        require(type(point['definition']) is dict and point['definition'], 'literal variation definition required')
        fields = {'scale': ('mu_r_factor', 'mu_f_factor', 'normalization'),
                  'pdf': ('set', 'member', 'lhaid', 'normalization'),
                  'parameter': ('basis', 'flavour', 'scale_gev', 'normalization', 'components', 'expansion', 'ufo_mapping')}[point['kind']]
        keys(point['definition'], fields, 'variation definition')
        require(point['definition']['normalization'] == 'absolute_lhe_weight', 'no implicit nominal weight ratios')
        if point['kind'] == 'parameter':
            require(point['definition']['expansion'] == 'full_matrix_element', 'ordinary ME reweight is a full matrix element; isolated linear/quadratic terms require a separate source-backed projection')
            text(point['definition']['basis'],'coefficient basis');text(point['definition']['flavour'],'flavour convention');positive(point['definition']['scale_gev'],'coefficient scale')
            require(point['definition']['components'] and point['definition']['ufo_mapping'], 'explicit coefficient components and UFO map required; WCxf output alone is not a mapping')
            for row in point['definition']['components']:
                keys(row, ('name', 'real', 'imag'), 'complex coefficient'); text(row['name'], 'coefficient'); number(row['real']); number(row['imag'])
            for row in point['definition']['ufo_mapping']:
                keys(row, ('coefficient', 'component', 'block', 'codes', 'factor', 'unit'), 'explicit UFO mapping')
                text(row['coefficient'], 'mapped coefficient'); text(row['block'], 'SLHA block'); text(row['unit'], 'mapping unit'); number(row['factor'])
                require(row['component'] in ('real','imag'),'explicit complex component for each real external UFO parameter required')
                require(row['codes'] and all(type(x) is int for x in row['codes']), 'external SLHA address required')
            components={row['name']:row for row in point['definition']['components']}
            require(len(components)==len(point['definition']['components']),'duplicate coefficient identity')
            mapping=point['definition']['ufo_mapping']
            require(all(row['coefficient'] in components for row in mapping),'UFO mapping names an undeclared coefficient')
            require(len({(row['block'].lower(),tuple(row['codes'])) for row in mapping})==len(mapping),'duplicate external parameter address')
            require({row['coefficient'] for row in mapping}==set(components),'incomplete coefficient-to-UFO mapping')
            require(all(not number(row['imag']) or any(x['coefficient']==row['name'] and x['component']=='imag' for x in mapping) for row in components.values()),'nonzero imaginary coefficients require an explicit imaginary external parameter mapping')
        if point['kind'] == 'scale':
            positive(point['definition']['mu_r_factor'], 'renormalization variation'); positive(point['definition']['mu_f_factor'], 'factorization variation')
        if point['kind'] == 'pdf':
            text(point['definition']['set'], 'PDF set'); require(type(point['definition']['member']) is int and point['definition']['member'] >= 0 and type(point['definition']['lhaid']) is int, 'exact PDF member identity required')
    keys(c['outputs'], ('lhe_relative', 'hepmc_relative', 'max_decoded_lhe_bytes','shower_weight_map'), 'outputs')
    weight_map=c['outputs']['shower_weight_map']
    require(type(weight_map) is list,'explicit shower weight mapping required')
    for row in weight_map:
        keys(row,('hepmc_name','lhe_id'),'shower weight mapping');text(row['hepmc_name'],'actual shower weight name')
        require(row['lhe_id'] is None or row['lhe_id'] in ids,'shower mapping names an undeclared LHE weight')
    if s['backend']=='OFF':require(not weight_map,'disabled shower cannot carry weight observations')
    else:
        require(len({x['hepmc_name'] for x in weight_map})==len(weight_map) and
                [x['lhe_id'] for x in weight_map].count(None)==1 and
                len(weight_map)==len(ids)+1 and {x['lhe_id'] for x in weight_map if x['lhe_id'] is not None}==set(ids),
                'complete unique nominal and all-variation shower weight mapping required')
    for key in ('lhe_relative', 'hepmc_relative'):
        value = c['outputs'][key]
        if value is None:
            require(key == 'hepmc_relative' and s['backend'] == 'OFF', 'required native stream cannot be omitted')
        else:
            require(type(value) is str and not Path(value).is_absolute() and value.startswith('Events/') and '..' not in Path(value).parts, 'literal contained generated output path required')
    require(type(c['outputs']['max_decoded_lhe_bytes']) is int and 1 <= c['outputs']['max_decoded_lhe_bytes'] <= 4 * 1024**3, 'finite LHE decoded byte ceiling required')
    if 'pre_shower_lhe_transform' in c:
        from ravel.physics import svj_preshower
        svj_preshower.validate(c)
    return c


def diagnostic_presentation(result):
    if result.get('status_scope') != 'source_bound_generated_event_delivery' or result.get('physics_validated') is not False:
        raise ValueError('generator delivery cannot acquire physics certification')
    return {'status_scope': result['status_scope'], 'generated_events': result['generated_events']}, (
        'Complete source-bound generated-event and signed multiweight delivery. Matching-scale stability, '
        'decay, EFT validity, detector response and calibrated inference require their own evidence.')


def validate(task):
    keys(task, ('config', *(['composition'] if isinstance(task, dict) and 'composition' in task else [])), 'model-events task')
    text(task['config'], 'config path')
    if 'composition' in task:
        from .event_inference_contract import generation_declaration
        generation_declaration(task['composition'])


def _load(task, base, *, expected=None):
    validate(task); path = bridge._regular(task['config'], base)
    from ravel.workflow.state_io import _unique
    return path, validate_config(json.loads(authenticated_text(path,expected),object_pairs_hook=_unique,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite configuration'))))


def output_policy(config=None):
    # Exact source-owned command streams only; scientific files remain strict.
    labels=('build','generate-decay-shower-reweight') if config is None or 'pre_shower_lhe_transform' not in config else ('build','hard-generate','shower-reentry')
    return {'schema_version':1,'allow_empty_directory_members':[
        {'path':'outputs/attempt-1/'+label+'-'+stream+'.log','role':'incidental_log'}
        for label in labels for stream in ('stdout','stderr')]}


def validate_scope(spec):
    require(spec['schema_version'] == 2 and spec['max_attempts'] == 1 and spec['review_policy']['policy']['max_redos'] == 0,
            'new generated events require a prospective one-attempt zero-redo ordinary review')


def execution_seconds(task, base): return _load(task, base)[1]['max_seconds']
def event_ceiling(task, base): return _load(task, base)[1]['generation']['events']


def process_commands(raw, c):
    commands, multiplicities = [], []
    for line in raw.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line: continue
        require(not any(x in line for x in (';', '\\', '"', "'")), 'process card cannot carry shell or external commands')
        if line.startswith('define '):
            require(re.fullmatch(r'define [A-Za-z0-9_+~\-]+ = [A-Za-z0-9_+~\- ]+', line), 'literal particle definition required')
        else:
            require(line.startswith(('generate ', 'add process ')), 'process card contains a non-process operation')
            expression = line.removeprefix('generate ').removeprefix('add process ')
            require(re.fullmatch(r'[A-Za-z0-9_+~\- ><^/=,@.\[\]]+', expression), 'unsupported executable process syntax')
            require(('[QCD]' in expression) == (c['generation']['order'] == 'NLO'), 'process perturbative syntax differs from requested order')
            require(expression.count('>') == 1 and ',' not in expression, 'decay chains must be declared through the separate MadSpin card')
            final = expression.split('>', 1)[1].split('[')[0].split('@')[0].split('/')[0]
            multiplicities.append(final.split().count(c['generation']['jet_token']))
        commands.append(line)
    require(commands and sum(x.startswith('generate ') for x in commands) == 1 and commands[0].startswith(('define ', 'generate ')), 'one initial process generation required')
    require(sorted(set(multiplicities)) == c['generation']['jet_multiplicities'], 'literal process jet population differs from requested regime')
    from . import generation_conventions
    generation_conventions.parse_process_card(raw)
    return commands


def exported_process_commands(raw):
    """Observe MG2.9.27 ProcCard's literal continuation format without execution.

    ProcCard.write splits logical commands at 70 characters with a trailing
    backslash. ProcCard.read rstrips physical lines and concatenates fragments
    without inserting spaces. Comments are removed only after that join, as in
    the command interpreter; no case, token, path or restriction normalization.
    """
    commands, pending = [], ''
    continuing = False
    # Match text-file universal newlines, without treating embedded Unicode
    # separators as additional native commands.
    normalized = raw.replace('\r\n', '\n').replace('\r', '\n')
    physical_lines = normalized.split('\n')
    if normalized.endswith('\n'):
        physical_lines.pop()  # A final newline is not an additional file line.
    for physical in physical_lines:
        line = physical.rstrip()
        if line.endswith('\\'):
            pending += line[:-1]
            continuing = True
            continue
        line = (pending + line).split('#', 1)[0].strip()
        pending, continuing = '', False
        if not line:
            continue
        require(not any(x in line for x in ('\\', ';', '"', "'", '\x00')),
                'malformed or compound native exported process command')
        commands.append(line)
    require(not continuing, 'unterminated native exported process continuation')
    return commands


def observe_exported_process(raw, intended_process, c, *, model_path, identity_observation=None):
    """Retain the complete logical history and exact model/process comparisons."""
    commands = exported_process_commands(raw)
    expected = process_commands(intended_process, c)
    processes = [x for x in commands if x.split()[0] == 'generate'
                 or x.split()[:2] == ['add', 'process']]
    expected_processes = [x for x in expected if x.startswith(('generate ', 'add process '))]
    models = [x for x in commands if x.split()[0] == 'import']
    expected_model = 'import model ' + str(model_path) + '-full'
    definitions = [x for x in expected if x.startswith('define ')]
    # A restoration after generation cannot certify the definition used when
    # diagrams were constructed. Bind each actual process to its prospective
    # effective definitions, retaining every command and its chronological use.
    expected_states, active = [], {}
    for row in expected:
        if row.split()[0] == 'define': active[row.split()[1]] = row
        else: expected_states.append(dict(active))
    definition_checks, active, process_index = [], {}, 0
    for index, row in enumerate(commands):
        if row.split()[0] == 'define':
            require(len(row.split()) >= 3, 'malformed native particle definition')
            active[row.split()[1]] = row
        elif row.split()[0] == 'generate' or row.split()[:2] == ['add', 'process']:
            premise = expected_states[process_index] if process_index < len(expected_states) else None
            observed = {name: active.get(name) for name in (premise or {})}
            definition_checks.append({'command_index': index, 'process': row,
                                      'expected': premise, 'observed': observed,
                                      'matched': premise is not None and observed == premise})
            process_index += 1
    definitions_matched = (len(definition_checks) == len(expected_states)
                           and all(row['matched'] for row in definition_checks))
    return {'commands': commands, 'expected_processes': expected_processes,
            'observed_processes': processes, 'expected_model': expected_model,
            'observed_model_commands': models, 'expected_definitions': definitions,
            'definition_checks': definition_checks,
            'continuation_semantics': 'MG5_2.9.27_ProcCard_literal_concatenation',
            'exported_history_matches': processes == expected_processes and models == [expected_model],
            'alias_identity_status': 'observed' if identity_observation is not None else 'unobserved',
            'exported_history_is_unique_alias_identity': False,
            'matched': processes == expected_processes and models == [expected_model] and
                (identity_observation['matched'] if identity_observation is not None else not definitions)}


def check_cards(c, texts, *, observed=False):
    g, s = c['generation'], c['shower']
    process_commands(texts['process'], c)
    parameter_values(texts['parameter'])
    rows = assignments(texts['run'], native_lo_empty_strings=observed and g['order'] == 'LO')
    expected = {'nevents': g['events'], 'iseed': g['seed'], 'lpp1': g['beam_type'][0], 'lpp2': g['beam_type'][1],
                'ebeam1': g['energy_gev'][0], 'ebeam2': g['energy_gev'][1], 'ickkw': {'unmerged_lo':0,'mlm':1,'ckkw_l':0,'mcatnlo':0,'fxfx':3}[g['scheme']]}
    matches(rows, g['run_settings'], 'declared run settings', native_run_lists=True)
    matches(rows, expected, 'run card')
    scale = g['scale_pdf']
    if g['order'] == 'LO':
        matches(rows, {'use_syst': scale == 'lo_systematics'}, 'LO systematics')
        if scale == 'lo_systematics':
            matches(rows, {'systematics_program':'systematics'}, 'LO systematics backend')
            require('systematics_arguments' in rows and rows['systematics_arguments'] not in ("[]", "['']"), 'explicit scale/PDF arguments required')
        if g['scheme'] == 'mlm':
            require('xqcut' in rows and literal(rows['xqcut']) > 0, 'positive MLM matrix-element matching cut required')
        if g['scheme'] == 'ckkw_l':
            require(sum(literal(rows.get(k, '-1')) > 0 for k in ('ktdurham', 'ptlund')) == 1, 'one explicit CKKW-L matrix-element cut required')
        if s['backend'] == 'PYTHIA8':
            py = pythia_cards.parse(texts['pythia'])['settings']
            declared={k:v for k,v in s['settings'].items() if not observed or k.lower()!='hepmcoutput:file'}
            matches(py, declared, 'declared Pythia settings')
            matches(py, {'Main:numberOfEvents':g['events']}, 'Pythia card')
            filename=Path(c['outputs']['hepmc_relative']).name.removesuffix('.gz')
            require(literal(py.get('hepmcoutput:file','')) in (('auto',filename) if observed else ('auto',)),
                    'Pythia output differs from declared automatic-to-literal filename transformation')
            # Prevent implicit matching/merging guesses even if the intended field is absent.
            if g['scheme'] == 'mlm':
                matches(py, {'JetMatching:qCut':s['merging_scale_gev'], 'JetMatching:nJetMax':s['max_jets'],
                             'JetMatching:merge':True,'JetMatching:scheme':1}, 'MLM shower')
            elif g['scheme'] == 'ckkw_l':
                matches(py, {'Merging:TMS':s['merging_scale_gev'], 'Merging:Process':s['process'], 'Merging:nJetMax':s['max_jets']}, 'CKKW-L shower')
            else:
                require(not literal(py.get('jetmatching:merge','off')) and literal(py.get('merging:tms','-1')) <= 0, 'unmerged sample cannot activate shower matching/merging')
    else:
        matches(rows, {'parton_shower':'PYTHIA8'}, 'NLO shower')
        shower = assignments(texts['shower'], style='shower')
        matches(shower, s['settings'], 'NLO shower card')
        if g['scheme'] == 'fxfx': matches(shower, {'Qcut':s['merging_scale_gev'], 'njmax':s['max_jets']}, 'FxFx shower')
        else: require(literal(shower.get('qcut','-1')) <= 0, 'MC@NLO cannot silently activate FxFx merging')
        if scale in ('nlo_systematics', 'nlo_on_the_fly'):
            require('rw_rscale' in rows and 'rw_fscale' in rows and 'reweight_pdf' in rows and 'reweight_scale' in rows, 'complete NLO scale/PDF weight controls required')
            require(any(literal(rows[k]) not in (False, [False]) for k in ('reweight_scale','reweight_pdf')), 'NLO scale/PDF variations are disabled')
        if scale == 'nlo_systematics': matches(rows, {'store_rwgt_info':True, 'systematics_program':'systematics'}, 'NLO stored systematics')
        if scale == 'none':
            matches(rows, {'reweight_scale':False, 'reweight_pdf':False}, 'NLO disabled systematics')
    d = c['decay']
    if d['mode'] == 'MADSPIN':
        lines = [line.split('#',1)[0].strip() for line in texts['madspin'].splitlines()]
        lines = [x for x in lines if x]
        allowed = [f"set spinmode {d['spinmode']}", f"set seed {d['seed']}", *d['commands'], 'launch']
        require(lines == allowed, 'MadSpin card differs from exact mode/seed/decay declarations')
    rw = c['reweight']
    if rw['mode'] != 'OFF':
        lines = [x.split('#',1)[0].strip() for x in texts['reweight'].splitlines()]
        lines = [x for x in lines if x]
        require(lines and lines[0] == 'change mode ' + rw['mode'], 'explicit reweight mode required')
        require(all(re.fullmatch(r'(change mode (LO|NLO|NLO_tree)|set [A-Za-z0-9_]+ [A-Za-z0-9_.+\- ]+|launch --rwgt_name=[A-Za-z0-9_.:+\-]+)', x) for x in lines), 'reweight card contains an undeclared process/model/script operation')
        suffix={'LO':'','NLO':'_nlo','NLO_tree':'_tree'}[rw['mode']]
        names = [x.split('=',1)[1]+suffix for x in lines if x.startswith('launch --rwgt_name=')]
        require(names == rw['weight_ids'], 'complete ordered native reweight identities differ from declaration (including NLO suffix)')
        points={p['id']:p for p in c['weights']['variation_points']}
        nominal=parameter_values(texts['parameter']);sets={};identity=None
        def check_point():
            if identity is None:return
            require(points[identity]['kind']=='parameter','ME reweight requires declared parameter-point semantics')
            definition=points[identity]['definition'];components={x['name']:x for x in definition['components']}
            expected={}
            for row in definition['ufo_mapping']:
                address=(row['block'].lower(),tuple(row['codes']))
                require(address in nominal,'declared reweight address absent from source parameter card')
                expected[address]=number(components[row['coefficient']][row['component']])*number(row['factor'])
            require(sets==expected,'native reweight card settings differ from exact declared coefficient/UFO point')
        for line in lines[1:]:
            if line.startswith('launch '):
                check_point();identity=line.split('=',1)[1]+suffix;sets={}
            else:
                require(identity is not None,'parameter edits must follow their MadGraph launch command')
                tokens=line.split();require(tokens[0]=='set' and len(tokens)>=4,'literal block/code/value reweight edit required')
                address=(tokens[1].lower(),tuple(int(x) for x in tokens[2:-1]))
                require(address not in sets,'duplicate reweight parameter edit')
                sets[address]=number(tokens[-1])
        check_point()
        if rw['mode'] in ('NLO','NLO_tree'):
            matches(rows, {'store_rwgt_info':True}, 'NLO reweight information')
    result = {'run': rows, 'shower': pythia_cards.parse(texts['pythia'])['settings'] if texts.get('pythia') else
              assignments(texts['shower'],style='shower') if texts.get('shower') else {}, 'decay':d, 'reweight':rw}
    if texts.get('pythia'):
        parsed = pythia_cards.parse(texts['pythia'])
        if parsed['channel_commands']:
            result['ordered_pythia_card'] = parsed
    return result


def inputs(task, base):
    path, c = _load(task, base)
    files = [path]
    for tree in [c['runtime']['madgraph_tree'], c['model_tree'], *[x['tree'] for x in c['runtime']['dependencies']]]:
        root, manifest, members = bridge._tree(tree, path.parent); files += [manifest, *members]
    mgroot = bridge._regular(c['runtime']['madgraph_tree']['root'], path.parent, directory=True)
    require(re.search(r'^version\s*=\s*2\.9\.27\s*$', (mgroot/'VERSION').read_text(), re.M), 'this source protocol targets pinned MG5 2.9.27')
    if 'operative_seed_observation' in c:
        from ravel.physics import model_event_seed
        files += model_event_seed.source_inputs(mgroot)
    if 'integration_checkpoint' in c:
        from . import native_integration_checkpoint
        files += native_integration_checkpoint.source_inputs(mgroot)
        admitted = native_integration_checkpoint.admit(c,path.parent)
        files += [Path(x) for x in admitted['inputs']]
    modelroot = bridge._regular(c['model_tree']['root'],path.parent,directory=True)
    require(all((modelroot/name).is_file() for name in ('__init__.py','parameters.py','particles.py','vertices.py','couplings.py','object_library.py','lorentz.py')), 'full unrestricted source UFO required')
    python = bridge._pin(c['runtime']['python'],path.parent); files.append(python)
    require(os.access(python,os.X_OK), 'native interpreter is not executable')
    support = bridge._pin(c['runtime']['python_manifest'],path.parent); files.append(support)
    doc = bridge._read(support)
    require(doc['python_sha256'] == c['runtime']['python']['sha256'] and doc['files'], 'full native Python support census required')
    files += [bridge._pin(row,path.parent) for row in doc['files']]
    dependency_paths = set(map(str, files))
    dependency_roots = {str(bridge._regular(x['tree']['root'],path.parent,directory=True)) for x in c['runtime']['dependencies']}
    for name, value in c['runtime']['options'].items():
        if value is None:
            require(name not in ('fortran_compiler','cpp_compiler'), 'compiler tool input required')
        else:
            p = bridge._regular(value,path.parent,directory=name.endswith('_path'))
            require(str(p) in dependency_roots if name.endswith('_path') else str(p) in dependency_paths, 'unbound native option ' + name)
            require(not re.search(r'[\s;\'"\\]',str(p)), 'MG option paths require literal safe command paths')
    texts = {}
    for name, pin in c['cards'].items():
        if pin is not None:
            p = bridge._pin(pin,path.parent); require(p.stat().st_size <= 2*1024**2, 'card exceeds source bound')
            texts[name] = authenticated_text(p,pin['sha256']); files.append(p)
    check_cards(c,texts)
    from . import generation_conventions
    generation_conventions.model_events_record(c,texts['process'],path.parent)
    if 'parameter_observation' in c:
        from ravel.physics import model_event_parameters
        model_sources, parameter_inputs = model_event_parameters.source_inputs(c['parameter_observation'], modelroot, mgroot)
        model_event_parameters.projection(c['parameter_observation'], texts['parameter'], model_sources)
        files += parameter_inputs
    for point in c['weights']['variation_points']: files.append(bridge._pin(point['source'],path.parent))
    if 'spectrum_origin' in c:
        from .model_specific_spectrum import origin_inputs
        files += origin_inputs(c['spectrum_origin'],path.parent,c['cards']['parameter'],c['model_tree'])
    if 'pre_shower_lhe_transform' in c:
        from ravel.physics import svj_preshower
        files += svj_preshower.inputs(c,path.parent,modelroot=modelroot,mgroot=mgroot,texts=texts)
    files += list(Path(__file__).resolve().parents[1].rglob('*.py'))
    if 'generator_reuse' in c:
        from . import generator_reuse
        reuse=generator_reuse.probe(c,path.parent,texts)
        files += [Path(x) for x in [*reuse['inputs'],*reuse['compatibility']['toolchain_inputs']]]
    return sorted(set(files))


def render_scripts(c, texts, *, model_path, process_path):
    for path in (model_path, process_path):
        require(not re.search(r'[\s;\'"\\]',str(path)), 'MG requires literal safe private paths')
    build = ['set automatic_html_opening False --no_save', 'set run_mode 0 --no_save', 'set nb_core 1 --no_save']
    build += ['set ' + key + ' ' + str(value) + ' --no_save' for key,value in c['runtime']['options'].items() if value is not None]
    if 'parameter_observation' in c: build += ['set complex_mass_scheme False --no_save']
    build += ['import model ' + str(model_path) + '-full', *process_commands(texts['process'],c), 'output ' + str(process_path)]
    launch = ['set automatic_html_opening False --no_save', 'set run_mode 0 --no_save', 'set nb_core 1 --no_save']
    if 'parameter_observation' in c: launch += ['set complex_mass_scheme False --no_save']
    launch += ['launch ' + str(process_path) + ' -n ravel']
    if c['generation']['order'] == 'NLO': launch += ['order=NLO', 'fixed_order=OFF']
    launch += ['shower=' + c['shower']['backend'], 'madspin=' + ('ON' if c['decay']['mode'] == 'MADSPIN' else 'OFF'),
               'reweight=' + ('ON' if c['reweight']['mode'] != 'OFF' else 'OFF')]
    launch += ['madanalysis=OFF'] if c['generation']['order'] == 'NLO' else ['detector=OFF', 'analysis=OFF']
    launch += ['0', '0']
    launch='\n'.join(launch)+'\n'
    if 'pre_shower_lhe_transform' in c:
        from ravel.physics import svj_preshower
        launch=svj_preshower.hard_launch(c,launch)
    return '\n'.join(build)+'\n', launch


def _approved(task, output):
    for rd in (Path(output).absolute(), *Path(output).absolute().parents):
        if (rd/'inputs/science-plan.json').is_file():
            from ravel.workflow import science
            selected = science.verify_worker(rd); spec = science.execution_spec(rd)
            require(spec['mode'] == 'model-events' and spec['task'] == task and Path(output).resolve() == (rd/selected['output_directory']).resolve(), 'generator differs from its approved worker task/output')
            validate_scope(spec)
            return rd, selected
    raise ValueError('new generation requires exact ordinary approved worker authority')


def _generated_pin(path):
    p = bridge._regular(str(path),Path.cwd())
    return {'path':str(p),'sha256':bridge._hash(p),'size':p.stat().st_size}


def _snapshot_tree(root):
    root = Path(root)
    require(not any(x.is_symlink() for x in (root,*root.parents)), 'generated root cannot traverse aliases')
    result = []
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(), 'generated output cannot contain a symlink')
        if p.is_file(): result.append(_generated_pin(p))
    require(len(result) <= 100000, 'generated artifact population exceeds contract')
    return result


def _command(argv, cwd, out, journal, label):
    guard_request = out / 'shower-guard-request.json'
    if label in ('generate-decay-shower-reweight', 'shower-reentry'):
        require(guard_request.is_file(), 'lhe_check pre-shower guard declaration missing')
    if label in ('generate-decay-shower-reweight', 'shower-reentry') and bridge._read(guard_request).get('backend') != 'OFF':
        # Intercept the shower inside the original integrated native launch;
        # the phase/reuse/checkpoint/SVJ drivers remain the original targets.
        index = next(i for i, value in enumerate(argv[1:], 1) if not value.startswith('-'))
        argv = [*argv[:index], str(out / 'native-shower-guard.py'), str(guard_request),
                bridge._hash(guard_request), *argv[index:]]
    row = {'command':argv,'cwd':str(cwd),'phase':label,'state':'running'}
    with journal.open('a') as stream: stream.write(json.dumps(row)+'\n');stream.flush()
    start=time.monotonic()
    with (out/(label+'-stdout.log')).open('x') as stdout, (out/(label+'-stderr.log')).open('x') as stderr:
        # The existing native executor owns this entire inherited process group.
        proc=subprocess.run(argv,cwd=cwd,stdout=stdout,stderr=stderr,check=False)
    row.update(state='completed',returncode=proc.returncode,wall_seconds=time.monotonic()-start)
    with journal.open('a') as stream: stream.write(json.dumps(row)+'\n');stream.flush()
    require(proc.returncode == 0, label+' failed; retained native command logs are authoritative')
    return row


def check_weight_definitions(c,population):
    """Match MG's actual scale/PDF labels, not the positional weight IDs alone."""
    native={x['id']:x for x in population['native_weight_header_definitions']}
    for point in c['weights']['variation_points']:
        row=native[point['id']];definition=point['definition'];attrs=row['attributes']
        if point['kind']=='scale':
            for tag,field in (('MUR','mu_r_factor'),('MUF','mu_f_factor')):
                if tag in attrs:value=attrs[tag]
                else:
                    found=re.findall(r'\b'+tag+r'\s*=\s*([+\-0-9.eEdD]+)',row['description'],re.I)
                    require(len(found)==1,'native scale weight lacks an unambiguous '+tag+' definition');value=found[0]
                require(number(value)==number(definition[field]),'native scale weight differs from its declared coefficient point')
        elif point['kind']=='pdf':
            if 'PDF' in attrs:value=attrs['PDF']
            else:
                found=re.findall(r'\bPDF\s*=\s*([0-9]+)',row['description'])
                require(len(found)==1,'native PDF weight lacks an unambiguous LHAPDF identity');value=found[0]
            require(int(value)==definition['lhaid'],'native PDF weight differs from the declared LHAPDF member identity')
        else:
            # The exact launch/set protocol was checked before and after run.
            # Native card-diff text is retained in addition to these declarations.
            require(row['description'],'native parameter reweight header must retain its card difference')


def _copied_source_custody(request, output, phase):
    """Admitted copied members remain exact; only derived Python caches are excluded.

    Generated process trees are separate. MG's source-supported --no_save
    switch keeps explicit runtime settings in this session without rewriting
    copied input/mg5_configuration.txt. No arbitrary source/config exemption.
    """
    c=request['config'];base=Path(request.get('source_base',Path.cwd()))
    rows=[];mismatches=[]
    for name,spec in (('madgraph',c['runtime']['madgraph_tree']),('model',c['model_tree'])):
        origin,manifest,members=bridge._tree(spec,base)
        expected=bridge._read(manifest);copied=Path(request[name])
        derivation=None
        if name=='madgraph' and 'source_preparation' in request:
            from ravel.physics import model_event_source
            expected,witness=model_event_source.expected(request,output)
            derivation={'record':request['source_preparation'],'transformations':witness['transformations']}
        observed=bridge.source_tree(bridge._regular(str(copied),Path.cwd(),directory=True))
        # Persist the returned copied census before any mismatch adjudication.
        rows.append({'component':name,'admitted_manifest':_generated_pin(manifest),
                     'origin':str(origin),'copied_root':str(copied),'expected':expected,
                     'observed':observed,'all_returned_files':_snapshot_tree(copied),
                     'explicit_copied_derivation':derivation,
                     'derived_cache_policy':sorted(bridge.EXCLUDED)+['*.pyc','*.pyo','*.pkl']})
        if expected!=observed:mismatches.append(name)
    witness={'schema_version':1,'phase':phase,'components':rows,'mismatches':mismatches}
    bridge._write(Path(output)/('copied-source-'+phase+'.json'),witness)
    require(not mismatches,'copied admitted scientific source/driver changed at '+phase+': '+','.join(mismatches))
    return witness


def native_worker(request_path, output):
    request=bridge._read(request_path); c=validate_config(request['config']); out=Path(output)
    mg, model, process=map(Path,(request['madgraph'],request['model'],request['process']))
    from ravel.workflow.generation_efficiency import machine_observation
    operational_machine=machine_observation()
    bridge._write(out/'model-events-operational-observation.json',{'schema_version':1,
        'kind':'generation_operational_observation','configuration_sha256':request['config_sha256'],
        'machine':operational_machine,'scope':'Observed native host/environment, not OS authentication or a lease.'})
    if 'operative_seed_observation' in c:
        from ravel.physics import model_event_seed
        model_event_seed.source_inputs(mg)
    # Do not import UFO, MG, Pythia or LHAPDF into this observation process.
    texts={name:authenticated_text(path,c['cards'][name]['sha256']) for name,path in request['card_paths'].items()}
    build,launch=render_scripts(c,texts,model_path=model,process_path=process)
    (out/'build.mg5').write_text(build);(out/'launch.mg5').write_text(launch)
    journal=out/'command-observations.jsonl'
    python=request['python']; command=[python,'-I','-B',str(mg/'bin/mg5_aMC')]
    if c['shower']['backend'] != 'OFF':
        from ravel.validation import science_shower_guard, lhe_check
        for name, module in (('native-shower-guard.py', science_shower_guard), ('native-lhe-check.py', lhe_check)):
            source = Path(module.__file__).resolve()
            (out / name).write_bytes(authenticated_text(source, request['delivery_helper_sha256'][str(source)]).encode())
        bridge._write(out / 'shower-guard-request.json', {
            'backend': c['shower']['backend'],
            'madgraph': str(mg), 'process': str(process), 'order': c['generation']['order'],
            'api': science_shower_guard.source_contract(mg, c['generation']['order']),
            'helper': _generated_pin(out / 'native-lhe-check.py'),
            'parameter_card': _generated_pin(request['card_paths']['parameter']), 'output': str(out / 'shower-input.lhe_check.json')})
    else:
        bridge._write(out / 'shower-guard-request.json', {'backend': 'OFF'})
    _copied_source_custody(request,out,'before-build')
    parameter_sources = None
    if 'parameter_observation' in c:
        from ravel.physics import model_event_parameters
        parameter_sources, _ = model_event_parameters.source_inputs(c['parameter_observation'], model, mg)
        model_event_parameters.projection(c['parameter_observation'], texts['parameter'], parameter_sources)
    from ravel.physics import model_event_process as process_observer
    observer_driver=out/'native-process-observer.py'
    observer_driver.write_bytes(authenticated_text(process_observer.__file__,request['process_observer_sha256']).encode('utf-8'))
    observer_request={'schema_version':1,'commands':process_commands(texts['process'],c),
        'build':_generated_pin(out/'build.mg5'),'commitment':{
            'build_sha256':bridge._hash(out/'build.mg5'),'model_import':'import model '+str(model)+'-full',
            'observer_sha256':bridge._hash(observer_driver),'intended_config_sha256':request['config_sha256']}}
    bridge._write(out/'native-process-observer-request.json',observer_request)
    process_journal=out/'generation-process-definitions.jsonl'
    reuse=request.get('reuse_admission'); reuse_export=None; reuse_static=None; reuse_origin=None; reuse_helper_pin=None
    checkpoint=request.get('checkpoint_admission')
    if checkpoint is not None:
        from . import native_integration_checkpoint, generator_reuse
        require(native_integration_checkpoint.admit(c,request['source_base']) == checkpoint,
                'same-run checkpoint origin changed before worker consumption')
        if checkpoint['state']=='continue':native_integration_checkpoint.verify_claim(checkpoint,request['checkpoint_reservation'],request['checkpoint_current_task'],request['source_base'],out,native=True)
    if reuse is not None:
        from ravel.physics import generator_reuse
        current=generator_reuse.probe(c,request['source_base'],texts)
        require(current==reuse,'admitted reusable process candidate changed before native consumption')
    if checkpoint is not None and checkpoint['state'] == 'continue':
        start=time.monotonic(); record=checkpoint['record']
        roots={'process':str(process),'madgraph':str(mg),'model':str(model),**request['checkpoint_dependency_roots']}
        native_integration_checkpoint.materialize(record,process,roots,limits=c['integration_checkpoint'])
        reuse_origin=record['original']['export_origin']
        observer_request=reuse_origin['observer_request']
        generator_reuse.write_document(out/'checkpoint-original-observer-request.json',observer_request)
        generator_reuse.write_bytes(process_journal,bytes.fromhex(reuse_origin['process_journal_hex']))
        generator_reuse.write_bytes(out/'checkpoint-original-build.mg5',bytes.fromhex(reuse_origin['build_hex']))
        (out/'build-stdout.log').write_text('Authenticated completed-survey process materialization; fresh native setup follows.\n')
        generator_reuse.write_bytes(out/'build-stderr.log',b'')
        observations=[{'phase':'build','state':'completed','wall_seconds':time.monotonic()-start,
            'execution_kind':'authenticated_same_run_materialization','native_export_invoked':False,
            'origin':checkpoint['checkpoint_pin']}]
    elif reuse is not None and reuse['state'] in ('export-reuse','export-and-static-reuse'):
        start=time.monotonic();record=reuse['record']
        roots={'process':str(process),'madgraph':str(mg),'model':str(model),**request['reuse_dependency_roots']}
        # Actual old observer bytes/commitments are preserved, never relabelled as a fresh export.
        generator_reuse.materialize(record['export'],process,roots)
        reuse_origin=record['origin']
        observer_request=reuse_origin['observer_request']
        generator_reuse.write_document(out/'reuse-original-observer-request.json',observer_request)
        generator_reuse.write_bytes(process_journal,bytes.fromhex(reuse_origin['process_journal_hex']))
        generator_reuse.write_bytes(out/'reuse-original-build.mg5',bytes.fromhex(reuse_origin['build_hex']))
        (out/'build-stdout.log').write_text('Authenticated export/static artifact materialization; no native export invocation.\n')
        generator_reuse.write_bytes(out/'build-stderr.log',b'')
        observations=[{'phase':'build','state':'completed','wall_seconds':time.monotonic()-start,
            'execution_kind':'authenticated_artifact_materialization','native_export_invoked':False,
            'origin':reuse['capsule_pin'],'static_objects_reused':reuse['static'] is not None}]
    else:
        observations=[_command([python,'-O','-I','-B',str(observer_driver),str(mg),
            str(out/'native-process-observer-request.json'),str(process_journal),
            bridge._hash(out/'native-process-observer-request.json')],mg,out,journal,'build')]
    _copied_source_custody(request,out,'after-build')
    generated_process=process/'Cards/proc_card_mg5.dat'
    protocol=authenticated_text(generated_process)
    from ravel.workflow.state_io import _unique
    rows=[json.loads(line,object_pairs_hook=_unique,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite native process observation')))
          for line in authenticated_text(process_journal).splitlines()]
    process_identity=process_observer.verify(rows,observer_request['commands'],observer_request['commitment'])
    process_identity['source']=_generated_pin(process_journal)
    bridge._write(out/'generation-process-identity.json',process_identity)
    imported_model=(Path(reuse_origin['model_path']) if checkpoint is not None and checkpoint['state']=='continue' else
        model if reuse_origin is None else generator_reuse.model_import_path(reuse,model))
    exported=observe_exported_process(protocol,texts['process'],c,model_path=imported_model,identity_observation=process_identity)
    actual_lines=exported['commands']
    bridge._write(out/'observed-process.json',{'source':_generated_pin(generated_process),**exported})
    require(exported['matched'],
            'native exported process/model restriction differs from exact intended protocol')
    if reuse is not None:
        # Export snapshot precedes cards, seeds and every production launch.
        roots={'process':str(process),'madgraph':str(mg),'model':str(model),**request['reuse_dependency_roots']}
        try:
            reuse_export=generator_reuse.capture_export(process,out/'reusable-export',c['generator_reuse'],roots)
            protocol_rows=[x for x in reuse_export['rows'] if x['relative']=='Cards/proc_card_mg5.dat']
            require(len(protocol_rows)==1 and protocol_rows[0]['blob']['sha256']==hashlib.sha256(protocol.encode()).hexdigest(),'export protocol changed between observation and reuse capture')
        except (OSError,ValueError) as exc:
            generator_reuse.write_document(out/'generator-reuse-unavailable.json',{'state':'unavailable','phase':'prelaunch-export','reason':str(exc)})
        generator_reuse.write_document(out/'generator-reuse-selection.json',{'state':reuse['state'],
            'reason':reuse.get('reason'),'compatibility':reuse['compatibility'],
            'origin':reuse.get('capsule_pin'),'no_integration_or_rng_state':True})
    (process/'Cards').mkdir(exist_ok=True)
    rendered={}
    for name,path in request['card_paths'].items():
        if name=='process': continue
        destination=process/'Cards'/CARD_NAMES[name]
        data=authenticated_text(path,c['cards'][name]['sha256']).encode('utf-8');destination.write_bytes(data)
        require(destination.read_bytes()==data,'rendered scientific card changed')
        rendered[name]=_generated_pin(destination)
    bridge._write(out/'rendered-settings.json',{'cards':rendered,'intended':c,'restriction_applied':False})
    if reuse is not None and reuse_origin is not None and reuse['static'] is not None:
        generator_reuse.apply_static(reuse['static'],process)
    _copied_source_custody(request,out,'before-generate')
    if parameter_sources is not None:
        require(not (process/'Source/MODEL/param_card_rule.dat').exists(),
                'dependent-writer contract cannot authorize generated restriction rules')
    split=None
    if 'pre_shower_lhe_transform' in c:
        from ravel.physics import svj_preshower
        split=svj_preshower.execute_split(request,out,texts=texts,process_identity=process_identity,
            observations=observations,journal=journal,command=command)
    else:
        from ravel.physics import model_event_phases
        phase_contract = None
        if c['generation']['order'] == 'LO':
            try:
                phase_contract = model_event_phases.source_contract(mg)
            except (OSError, ValueError, SyntaxError):
                # Native execution remains available with its admitted limits;
                # unsupported phase granularity cannot calibrate production.
                phase_contract = None
        if checkpoint is not None: require(phase_contract is not None,'checkpoint requires exact native phase API')
        if phase_contract is None:
            observations.append(_command([*command,str(out/'launch.mg5')],mg,out,journal,'generate-decay-shower-reweight'))
        else:
            phase_driver=out/'native-phase-observer.py'
            phase_driver.write_bytes(authenticated_text(model_event_phases.__file__,request['phase_observer_sha256']).encode('utf-8'))
            phase_request={'apis':phase_contract,'launch':_generated_pin(out/'launch.mg5')}
            if reuse_export is not None and reuse['compatibility']['static_toolchain_bound']:
                reuse_driver=out/'native-generator-reuse.py'
                reuse_helper_pin=generator_reuse.write_bytes(reuse_driver,authenticated_text(generator_reuse.__file__,request['reuse_helper_sha256']).encode())
                try: build_api=generator_reuse.build_api(mg)
                except (OSError,ValueError,SyntaxError): build_api=None
                if build_api is not None:
                    phase_request['reuse_capture']={'helper':reuse_helper_pin,'api':build_api,
                        'export':_generated_pin(out/'reusable-export/export.json'),
                        'process':str(process),'destination':str(out/'reusable-static'),
                        'static_sha256':reuse['compatibility']['static_sha256']}

            if checkpoint is not None:
                checkpoint_driver=out/'native-integration-checkpoint.py'
                checkpoint_driver.write_bytes(authenticated_text(native_integration_checkpoint.__file__,request['checkpoint_helper_sha256']).encode())
                storage_driver=out/'native-checkpoint-storage.py'
                storage_driver.write_bytes(authenticated_text(generator_reuse.__file__,request['checkpoint_storage_sha256']).encode())
                roots={'process':str(process),'madgraph':str(mg),'model':str(model),**request['checkpoint_dependency_roots']}
                original={**request['checkpoint_origin'],'export_origin':{
                    'model_path':str(imported_model),'observer_request':observer_request,
                    'process_journal_hex':authenticated_text(process_journal).encode().hex(),
                    'build_hex':(out/'build.mg5').read_bytes().hex() if reuse_origin is None else reuse_origin['build_hex']}}
                checkpoint_request={'policy':c['integration_checkpoint'],'config':c,'original':original,
                    'madgraph':str(mg),'process':str(process),'roots':roots,
                    'destination':str(out/'integration-checkpoint'),
                    'stdout':str(out/'generate-decay-shower-reweight-stdout.log')}
                if checkpoint['state']=='continue':
                    checkpoint_request.update(record=checkpoint['record'],checkpoint_pin=checkpoint['checkpoint_pin'])
                phase_request['integration_checkpoint']={'helper':_generated_pin(checkpoint_driver),
                    'storage_helper':_generated_pin(storage_driver),'request':checkpoint_request}
            phase_path=out/'native-phase-observer-request.json';bridge._write(phase_path,phase_request)
            phase_journal=out/'model-events-phase-observations.jsonl'
            # Match the released bin's default optimization choice; never
            # disable its assertions when create_release.py retains debug mode.
            optimized=[] if (mg/'bin/create_release.py').exists() else ['-O']
            if checkpoint is not None and checkpoint['state']=='continue':native_integration_checkpoint.verify_claim(checkpoint,request['checkpoint_reservation'],request['checkpoint_current_task'],request['source_base'],out,native=True)
            observations.append(_command([python,*optimized,'-I','-B',str(phase_driver),str(mg),str(phase_path),
                str(phase_journal),bridge._hash(phase_path)],mg,out,journal,'generate-decay-shower-reweight'))
            phase_rows=model_event_phases.final_rows(phase_journal,phase_contract)
            build_timing={k:observations[0][k] for k in ('phase','state','wall_seconds')}
            build_timing['nested']=False
            if reuse is not None and reuse_origin is not None:
                build_timing.update(execution_kind='authenticated_artifact_materialization',
                    native_export_invoked=False,origin=reuse['capsule_pin'])
            if checkpoint is not None and checkpoint['state']=='continue':
                build_timing.update(execution_kind='authenticated_same_run_materialization',native_export_invoked=False,origin=checkpoint['checkpoint_pin'])
            bridge._write(out/'model-events-phase-timing.json',{'schema_version':1,
                'kind':('source_same_run_continuation_phase_observation' if checkpoint is not None and checkpoint['state']=='continue' else 'source_native_phase_observation'),'configuration_sha256':request['config_sha256'],
                'complete':all(x['state']=='completed' for x in phase_rows), 'machine':operational_machine,
                'phases':[build_timing,*phase_rows], 'source_apis':phase_contract,
                'journal':_generated_pin(phase_journal),'observer':_generated_pin(phase_driver),
                'interpretation':'Source API intervals; survey/refine are mixed adaptation/generation. No inferred integrator error, acceptance, instability, unweight or reweight coverage.'})
            require(bridge._hash(phase_driver)==request['phase_observer_sha256'], 'native phase observer changed')
            if reuse_helper_pin is not None:
                require(_generated_pin(reuse_driver)==reuse_helper_pin,'native static capture helper changed')
    # Observations are saved before any success adjudication.
    observed={name:(process/'Cards'/CARD_NAMES[name]).read_text() for name in request['card_paths'] if name!='process'}
    observed['process']=texts['process']
    if parameter_sources is not None:
        observed['parameter'] = authenticated_text(process/'Cards/param_card.dat')
    bridge._write(out/'observed-settings.json',{'cards':observed,'commands':observations,'generated_process':actual_lines,'intended_config_sha256':request['config_sha256']})
    from ravel.physics import model_event_commitment
    generated_commitment=model_event_commitment.snapshot(process)
    artifacts=[{k: row[k] for k in ('path','sha256','size')} for row in generated_commitment['files']]
    bridge._write(out/'generated-member-commitment.json',generated_commitment)
    bridge._write(out/'generated-artifact-census.json',{'files':artifacts})
    _copied_source_custody(request,out,'after-generate')
    seed_observation=None
    continuation_seed=(native_integration_checkpoint.seed_evidence(checkpoint,out/'generate-decay-shower-reweight-stdout.log')
        if checkpoint is not None and checkpoint['state']=='continue' else None)
    checked_observed=observed
    if 'operative_seed_observation' in c and split is None:
        seed_observation=model_event_seed.observe(c,texts['run'],observed['run'],
            supplied_process=texts['process'],mgroot=mg,model_path=imported_model,process_root=process,
            process_identity=process_identity,stdout_path=out/'generate-decay-shower-reweight-stdout.log',artifacts=artifacts,**({'continuation':continuation_seed} if continuation_seed is not None else {}))
        bridge._write(out/'operative-seed-observation.json',seed_observation)
        # Consume the authentic complete banner; do not rewrite the ending
        # mutable card. observe checks every ending nonseed field separately.
        checked_observed=dict(observed,run=seed_observation['operative_run_card'])
    if split is not None:
        checked_config,checked_observed,ending_rows=svj_preshower.checked_cards(c,split,observed)
        checked_settings=check_cards(checked_config,checked_observed,observed=True)
        checked_settings['run']=ending_rows
    else:
        checked_settings=check_cards(c,checked_observed,observed=True)
    if seed_observation is not None:
        checked_settings['run']=seed_observation['ending_run_card_rows']
    if texts.get('pythia'):
        comparison = pythia_cards.compare(texts['pythia'], observed['pythia'],
            hepmc_filename=Path(c['outputs']['hepmc_relative']).name.removesuffix('.gz'))
        bridge._write(out/'ordered-pythia-card-observation.json', comparison)
        require(comparison['matched'], 'native Pythia ordered decay or particle settings differ from supplied card')
    parameter_observation = None
    if parameter_sources is not None:
        current_sources, _ = model_event_parameters.source_inputs(c['parameter_observation'], model, mg)
        require(current_sources == parameter_sources, 'dependent parameter source changed')
        parameter_observation = model_event_parameters.compare(c['parameter_observation'], texts['parameter'],
            observed['parameter'], current_sources, restriction_present=(process/'Source/MODEL/param_card_rule.dat').exists())
        bridge._write(out/'parameter-card-observation.json', parameter_observation)
        require(parameter_observation['matched'], 'native nominal card differs from exact source-derived/writer contract')
    else:
        require(parameter_values(observed['parameter'])==parameter_values(texts['parameter']), 'native changed nominal physical parameter card')
    labels=('build','generate-decay-shower-reweight') if split is None else ('build','hard-generate','shower-reentry')
    combined='\n'.join((out/(label+'-stdout.log')).read_text(errors='replace')+'\n'+(out/(label+'-stderr.log')).read_text(errors='replace') for label in labels)
    if c['reweight']['mode'] in ('NLO','NLO_tree'):
        require(not re.search(r'(switch(?:ing|ed)?|fall(?:ing)? back|fallback|change(?:d)?)\s+(?:to\s+)?LO',combined,re.I), 'requested NLO reweight reported a fallback to LO')
    lhe=bridge._regular(str(process/c['outputs']['lhe_relative']),process)
    from ravel.validation.lhe_check import check_science
    science_lhe_check = check_science(lhe, param_card=request['card_paths']['parameter'],
                                    output=out / 'generated-lhe.lhe_check.json')
    scan_options={} if split is None else {'allow_equal_encodings':True}
    population=scan(lhe,expected_events=c['generation']['events'],expected_groups=c['weights']['groups'],
        maximum_bytes=c['outputs']['max_decoded_lhe_bytes'],journal_path=out/'event-weights.jsonl',**scan_options)
    if split is not None:
        require(population==split['transform']['derived_shower_input_population'],'installed complete derived LHE population differs from verified transport')
        check_weight_definitions(c,split['transform']['original_population'])
    bridge._write(out/'generated-population.json',population)
    check_weight_definitions(c,population)
    require(population['init']['beam_pdg']==c['generation']['beam_pdg'] and
            list(map(Decimal,population['init']['energy_gev']))==list(map(number,c['generation']['energy_gev'])), 'actual generated beam identity/energy differs from intended collider')
    shower=None
    if c['shower']['backend']!='OFF':
        stream=bridge._regular(str(process/c['outputs']['hepmc_relative']),process)
        # Native MG/Pythia currently writes HepMC2; it is retained as the actual
        # full stream, never relabelled as an independently qualified HepMC3 trace.
        shower_names=[x['hepmc_name'] for x in c['outputs']['shower_weight_map']] if split is None else [x['hepmc_name'] for x in split['declared_complete_stream_census']['streams']]
        shower=scan_hepmc2_weights(stream,names=shower_names,
            minimum_events=c['shower']['minimum_returned_events'],maximum_events=c['generation']['events'],
            maximum_bytes=c['outputs']['max_decoded_lhe_bytes'],journal_path=out/'shower-weights.jsonl',
            beam_pdg=c['generation']['beam_pdg'],energy_gev=c['generation']['energy_gev'])
        shower.update(file=_generated_pin(stream),declared_weight_map=c['outputs']['shower_weight_map'],
                      weight_map_independently_qualified=False)
        if split is not None:
            shower.update(declared_complete_stream_census=split['declared_complete_stream_census'],
                normalization_semantics_independently_qualified=False,physical_hard_to_shower_association='unknown')
        bridge._write(out/'shower-population.json',shower)
    for pin in artifacts:
        require(_generated_pin(pin['path'])==pin,'generated artifact changed after scientific observation')
    require(_generated_pin(process_journal)==process_identity['source'],'generation-time identity changed after observation')
    require(bridge._hash(observer_driver)==observer_request['commitment']['observer_sha256'],'native process observer changed')
    if reuse_helper_pin is not None:
        require(_generated_pin(out/'native-generator-reuse.py')==reuse_helper_pin,'native capture helper changed before success')
    _copied_source_custody(request,out,'before-native-success')
    if seed_observation is not None:
        require(model_event_seed.observe(c,texts['run'],observed['run'],
            supplied_process=texts['process'],mgroot=mg,model_path=imported_model,process_root=process,
            process_identity=process_identity,stdout_path=out/'generate-decay-shower-reweight-stdout.log',artifacts=artifacts,**({'continuation':continuation_seed} if continuation_seed is not None else {}))==seed_observation,
            'operative seed evidence changed before native success')
    if parameter_observation is not None:
        require(bridge._hash(bridge._regular(str(process/'Cards/param_card.dat'), process)) == parameter_observation['observed_sha256'],
                'observed nominal parameter card changed after source comparison')
    reuse_info=None
    if reuse_export is not None:
        static_path=out/'reusable-static/static.json'
        if static_path.is_file(): reuse_static=generator_reuse.read_document(static_path)
        origin={'state':reuse['state'],'model_path':str(model) if reuse_origin is None else reuse_origin['model_path'],
            'observer_request':observer_request,'process_identity':process_identity,
            'process_journal_hex':authenticated_text(process_journal).encode().hex(),
            'build_hex':(out/'build.mg5').read_bytes().hex() if reuse_origin is None else reuse_origin['build_hex'],
            'prior_capsule':reuse.get('capsule_pin'),'native_export_invoked':reuse_origin is None,
            'capture_helper':reuse_helper_pin}
        reuse_info=generator_reuse.publish(out,reuse_export,reuse['compatibility'],origin,reuse_static)
    result={'status':'passed','physics_validated':False,'status_scope':SCOPE,'generated_events':population['generated_events'],
        'generation_convention':__import__('ravel.physics.generation_conventions',fromlist=['model_events_record']).model_events_record(c,texts['process'],Path(request['source_base'])),
        'quantity':{'weight_convention':'signed'},
        'source':c['source'],'intended':c,'rendered_cards':rendered,'observed_settings':checked_settings,
        **({'integration_continuation':continuation_seed,'continuation_reservation':request['checkpoint_reservation']} if continuation_seed is not None else {}),
        **({'operative_seed_observation':seed_observation} if seed_observation is not None else {}),
        'copied_source_preparation':request.get('source_preparation'),
        'generation_process_identity':process_identity,
        **({'generator_reuse':reuse_info} if reuse_info is not None else {}),
        **({'parameter_card_observation':parameter_observation} if parameter_observation is not None else {}),
        **({'pre_shower_transport':split,'original_hard_population':split['transform']['original_population']} if split is not None else {}),
        'population':population,'shower_population':shower,'variation_points':c['weights']['variation_points'],
        'lhe_check': _generated_pin(out / 'generated-lhe.lhe_check.json'),
        'commands':observations,'generated_artifacts':artifacts,
        'generated_member_commitment':generated_commitment,'model_restriction_applied':False,
        'matching_merging_validity':'unknown','eft_validity':'unknown','sampling_law_independently_qualified':False,
        'limitations':['Native source-bound generation delivery; no independent amplitude, matching-scale stability, decay-width or detector certification.',
            'Every LHE multiweight retains its literal header and original event. Point definitions and shower-name maps remain source declarations; no independent semantic, phase-space-overlap or EFT-expansion certificate is inferred.',
            'No envelope, independence, covariance or luminosity normalization is inferred.',
            'HepMC2 event census is transport evidence; full physical shower/detector lineage requires separate qualification.']}
    if seed_observation is not None:model_event_seed.ending_custody(seed_observation)
    if checkpoint is not None and checkpoint['state']=='continue':
        native_integration_checkpoint.ending(checkpoint)
        native_integration_checkpoint.verify_claim(checkpoint,request['checkpoint_reservation'],request['checkpoint_current_task'],request['source_base'],out,native=True)
    model_event_commitment.verify(generated_commitment,process)
    if split is not None:svj_preshower.ending_custody(split,process)
    if reuse_info is not None:generator_reuse.ending(result,out)
    from ravel.physics.yield_hub import delivery_checks
    result['check_results'] = delivery_checks(out, path='model-events-native.json')
    bridge._write(out/'model-events-native.json',result)
    if reuse_info is not None:generator_reuse.ending(result,out)
    model_event_commitment.verify(generated_commitment,process)
    if seed_observation is not None:model_event_seed.ending_custody(seed_observation)
    if split is not None:svj_preshower.ending_custody(split,process)
    return result


def run(task, base, output):
    rd,selected=_approved(task,output); path,c=_load(task,base)
    require(c['max_seconds']<=selected['max_seconds'],'native generator exceeds approved time')
    sources=inputs(task,base);before={str(p):bridge._hash(p) for p in sources}
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    work=rd/'work/model-events'/out.name
    require(not work.exists() and not any(p.is_symlink() for p in (work,*work.parents)),'fresh regular generator workspace required')
    work.mkdir(parents=True)
    bridge._copy(c['runtime']['madgraph_tree'],path.parent,work/'madgraph')
    bridge._copy(c['model_tree'],path.parent,work/'model_source')
    # Existing bridge content copying deliberately makes regular files. MG's
    # generated build driver also needs the original executable source modes.
    for tree,destination in ((c['runtime']['madgraph_tree'],work/'madgraph'),(c['model_tree'],work/'model_source')):
        root,_,members=bridge._tree(tree,path.parent)
        for member in members:shutil.copymode(member,destination/member.relative_to(root))
    cards={}
    for name,pin in c['cards'].items():
        if pin is not None:
            destination=work/CARD_NAMES[name];shutil.copyfile(bridge._pin(pin,path.parent),destination)
            require(bridge._hash(destination)==pin['sha256'],'copied input card differs');cards[name]=str(destination)
    absolute=deepcopy(c)
    for key,value in absolute['runtime']['options'].items():
        if value is not None: absolute['runtime']['options'][key]=str(bridge._regular(value,path.parent,directory=key.endswith('_path')))
    request={'config':absolute,'madgraph':str(work/'madgraph'),'model':str(work/'model_source'),'process':str(work/'process'),
        'python':str(bridge._pin(c['runtime']['python'],path.parent)),'card_paths':cards,'config_sha256':before[str(path)],'source_base':str(path.parent)}
    from ravel.physics import model_event_source,model_event_process,model_event_phases
    request['process_observer_sha256']=before[str(Path(model_event_process.__file__).resolve())]
    request['phase_observer_sha256']=before[str(Path(model_event_phases.__file__).resolve())]
    from ravel.validation import science_shower_guard, lhe_check
    request['delivery_helper_sha256'] = {str(Path(module.__file__).resolve()): before[str(Path(module.__file__).resolve())]
                                        for module in (science_shower_guard, lhe_check)}
    if 'pre_shower_lhe_transform' in c:
        from ravel.physics import svj_mg_reentry
        request['svj_reentry_driver_sha256']=before[str(Path(svj_mg_reentry.__file__).resolve())]
    if 'generator_reuse' in c:
        from . import generator_reuse
        texts={name:authenticated_text(pin['path'] if Path(pin['path']).is_absolute() else path.parent/pin['path'],pin['sha256'])
            for name,pin in c['cards'].items() if pin is not None}
        request['reuse_admission']=generator_reuse.probe(c,path.parent,texts)
        request['reuse_helper_sha256']=before[str(Path(generator_reuse.__file__).resolve())]
        request['reuse_dependency_roots']={'dependency:'+x['role']:str(bridge._regular(x['tree']['root'],path.parent,directory=True)) for x in c['runtime']['dependencies']}
    if 'integration_checkpoint' in c:
        from . import native_integration_checkpoint, generator_reuse
        from ravel.workflow import science
        spec=science.execution_spec(rd)
        require(spec.get('goal_binding') is not None, 'survey checkpoint requires original ordinary goal binding')
        request['checkpoint_admission']=native_integration_checkpoint.admit(c,path.parent)
        if request['checkpoint_admission']['state']=='continue':
            require(spec['goal_binding']==request['checkpoint_admission']['goal_binding'], 'continuation changes original goal/assignment')
        request['checkpoint_current_task']=deepcopy(task)
        request['checkpoint_origin']={'rundir':str(rd),'attempt':selected['attempt'],
            'config_sha256':before[str(path)],'source_base':str(path.parent),'goal_binding':spec['goal_binding']}
        request['checkpoint_helper_sha256']=before[str(Path(native_integration_checkpoint.__file__).resolve())]
        request['checkpoint_storage_sha256']=before[str(Path(generator_reuse.__file__).resolve())]
        request['checkpoint_dependency_roots']={'dependency:'+x['role']:str(bridge._regular(x['tree']['root'],path.parent,directory=True)) for x in c['runtime']['dependencies']}
    request['source_preparation']=model_event_source.prepare(request,out)
    if 'integration_checkpoint' in c and request['checkpoint_admission']['state']=='continue':
        request['checkpoint_reservation']=native_integration_checkpoint.claim(c,path.parent,task,out)
        native_integration_checkpoint.verify_claim(request['checkpoint_admission'],request['checkpoint_reservation'],task,path.parent,out)
    bridge._write(out/'native-input.json',request)
    from ravel.physics.reinterpret_db import execute_native
    receipt=execute_native([request['python'],'-I','-B',str(Path(__file__).resolve()),'--native-worker',str(out/'native-input.json'),'--out',str(out)],out,c,
        generated_event_ceiling=c['generation']['events'])
    result=bridge._read(out/'model-events-native.json')
    require(result['status_scope']==SCOPE and result['generated_events']==c['generation']['events'] and result['physics_validated'] is False,'native returned wrong delivery scope/exposure')
    require(before=={str(p):bridge._hash(p) for p in inputs(task,base)},'original generator model/runtime/cards changed during execution')
    from ravel.physics import model_event_commitment
    model_event_commitment.verify(result.get('generated_member_commitment'),request['process'])
    if 'pre_shower_lhe_transform' in c:
        from ravel.physics import svj_preshower
        svj_preshower.ending_custody(result['pre_shower_transport'],request['process'])
    if result.get('generator_reuse') is not None:generator_reuse.ending(result,out)
    if 'integration_checkpoint' in c and request['checkpoint_admission']['state']=='continue':
        require(native_integration_checkpoint.admit(c,path.parent)==request['checkpoint_admission'],'original continuation admission changed at ending')
        native_integration_checkpoint.ending(request['checkpoint_admission'])
        native_integration_checkpoint.verify_claim(request['checkpoint_admission'],request['checkpoint_reservation'],task,path.parent,out)
    result['native_execution']=receipt
    if 'composition' in task:
        from .event_inference_contract import generated_sample, file_pin
        contract = generated_sample(result, task['composition'], Path(request['process']) / c['outputs']['lhe_relative'])
        bridge._write(out / 'generated-sample-contract.json', contract)
        result['generated_sample'] = file_pin(out / 'generated-sample-contract.json')
    bridge._write(out/'model-events.json',result)
    if result.get('generator_reuse') is not None:generator_reuse.ending(result,out)
    model_event_commitment.verify(result['generated_member_commitment'],request['process'])
    if 'pre_shower_lhe_transform' in c:svj_preshower.ending_custody(result['pre_shower_transport'],request['process'])
    if 'integration_checkpoint' in c and request['checkpoint_admission']['state']=='continue':
        native_integration_checkpoint.verify_claim(request['checkpoint_admission'],request['checkpoint_reservation'],task,path.parent,out)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-worker');parser.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    require(args.native_worker is not None,'worker entry requires its prepared request; use ordinary ravel plan/run')
    native_worker(args.native_worker,args.out)


if __name__=='__main__': main()
