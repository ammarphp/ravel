"""Literal Pythia singleton settings plus ordered explicit decay-table commands.

The pinned ParticleDataScheme manual defines oneChannel as a table reset and
addChannel as an append. This parser never normalizes branching fractions or
executes Pythia. Inherited/default tables and other table-edit commands are not
reconstructed. Source-defined masses, visibility and lifetime settings remain
literal inputs; native interpretation and physical decay qualification are separate.
"""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import math
import re

from ravel.physics.model_event_weights import require

INTEGER = re.compile(r'[+-]?\d+')
BR = re.compile(r'[+]?((\d+(\.\d*)?)|(\.\d+))([eE][+-]?\d+)?')
# Every returned integer is at most 617 decimal digits, below the minimum
# configurable Python3.11+ conversion limit640 (3.10 has no such limit).
MAX_RATIONAL_BITS = 2048
MAX_BR_LITERAL = 512
PARTICLE_PROPERTIES = {'name','antiname','names','spintype','chargetype','coltype',
                       'm0','mwidth','mmin','mmax','tau0','taucalc','isresonance',
                       'maydecay','doexternaldecay','isvisible','doforcewidth','all','new'}


def _int(token, label):
    require(INTEGER.fullmatch(token) is not None, 'literal integer required for ' + label)
    value = int(token)
    require(abs(value) <= 2147483647, 'Pythia integer outside admitted signed-int range: ' + label)
    return value


def _ratio(value):
    require(value.numerator.bit_length() <= MAX_RATIONAL_BITS and
            value.denominator.bit_length() <= MAX_RATIONAL_BITS,
            'exact branching-ratio rational exceeds portable JSON bound')
    return {'numerator':value.numerator,'denominator':value.denominator}


def _channel(value):
    tokens = value.replace(',', ' ').split()
    require(4 <= len(tokens) <= 11, 'Pythia channel requires three fields and one to eight products')
    on = _int(tokens[0], 'onMode'); mode = _int(tokens[2], 'meMode')
    require(on in (0,1,2,3), 'unsupported Pythia channel onMode')
    require(0 <= mode <= 103, 'unsupported Pythia channel meMode')
    require(len(tokens[1]) <= MAX_BR_LITERAL and BR.fullmatch(tokens[1]) is not None,
            'bounded finite nonnegative literal branching ratio required')
    exponent = re.search(r'[eE]([+-]?\d+)$', tokens[1])
    require(exponent is None or abs(_int(exponent[1], 'branching exponent')) <= 400,
            'branching-ratio exponent outside bounded exact representation')
    try:
        branch = Decimal(tokens[1])
        native = float(branch)
    except (InvalidOperation, OverflowError, ValueError):
        raise ValueError('finite representable branching ratio required') from None
    require(branch.is_finite() and branch >= 0 and math.isfinite(native), 'finite nonnegative branching ratio required')
    require(branch == 0 or native > 0, 'branching ratio underflows the admitted native double representation')
    products = [_int(x, 'decay product') for x in tokens[3:]]
    require(all(x != 0 for x in products), 'zero decay-product identity is unsupported')
    ratio = Fraction(branch)
    return {'on_mode':on, 'branching_ratio_literal':tokens[1],
            'branching_ratio_rational':_ratio(ratio),
            'me_mode':mode, 'products':products, 'tokens':tokens}


def parse(raw):
    """Return all singleton literals and ordered commands without last-value wins."""
    require(type(raw) is str and len(raw.encode('utf-8')) <= 2*1024**2, 'bounded literal Pythia card required')
    settings = {}; commands = []; tables = {}; properties = {}; scalar_rows = []
    for line_number, source in enumerate(raw.splitlines(),1):
        line = source.split('#',1)[0].split('!',1)[0].strip()
        if not line:
            continue
        require(line.count('=') == 1, 'unparsed Pythia card assignment: ' + line)
        left,value = map(str.strip,line.split('=',1));key = left.lower()
        require(re.fullmatch(r'[a-zA-Z0-9_:]+',key) and value, 'malformed Pythia card setting')
        numeric = re.match(r'([0-9]+):',key)
        if key[0].isdigit():
            require(numeric is not None, 'canonical positive Pythia particle identity required')
            parent = _int(numeric[1], 'particle identity')
            require(parent > 0 and numeric[1] == str(parent), 'canonical positive Pythia particle identity required')
        channel = re.fullmatch(r'([1-9]\d*):(onechannel|addchannel)',key)
        if channel:
            parent = _int(channel[1], 'parent identity'); operation = channel[2]
            row = {'parent_pdg':parent,'operation':operation,**_channel(value),'line':line_number}
            if operation == 'onechannel':
                tables[parent] = []
            else:
                require(parent in tables, 'addChannel requires an explicit preceding oneChannel; inherited table is unresolved')
            tables[parent].append(len(commands));commands.append(row)
            continue
        require(not key.endswith((':onechannel',':addchannel')), 'canonical positive Pythia channel parent required')
        require(key not in settings, 'duplicate Pythia singleton setting: ' + key)
        settings[key] = value
        particle = re.fullmatch(r'([1-9]\d*):(.+)',key)
        if particle:
            parent = _int(particle[1], 'particle identity'); name = particle[2]
            require(name in PARTICLE_PROPERTIES, 'unsupported Pythia particle/table command: ' + key)
            require(name != 'new' or parent not in tables, 'particle new after decay-table construction would erase the retained table')
            properties[key] = value
        scalar_rows.append({'key':key,'literal':value,'line':line_number})
    population = []
    for parent,indices in tables.items():
        total = sum((Fraction(commands[i]['branching_ratio_rational']['numerator'],
                              commands[i]['branching_ratio_rational']['denominator']) for i in indices),Fraction())
        population.append({'parent_pdg':parent,'command_indices':indices,
                           'branching_ratio_sum_rational':_ratio(total),
                           'normalization_applied':False})
    return {'schema_version':1,'settings':settings,'singleton_commands':scalar_rows,
            'particle_settings':properties,'channel_commands':commands,'final_explicit_tables':population,
            'table_scope':'explicit oneChannel reset followed by ordered additions; inherited tables unresolved',
            'physical_shower_qualified':False,'branching_normalization_applied':False}


def _identity(parsed):
    # Comments/whitespace/numerically equal BR spellings may change in a rendered
    # card. Complete command order, reset operations, modes and products cannot.
    def channel(row):
        return {k:row[k] for k in ('parent_pdg','operation','on_mode',
                                 'branching_ratio_rational','me_mode','products')}
    program = [(row['line'], {'kind':'particle_setting','key':row['key'],
                             'literal':' '.join(row['literal'].split())})
               for row in parsed['singleton_commands'] if row['key'] in parsed['particle_settings']]
    program += [(row['line'], {'kind':'decay_channel', **channel(row)}) for row in parsed['channel_commands']]
    return {'settings':{k:' '.join(v.split()) for k,v in parsed['settings'].items()},
            'particle_settings':{k:' '.join(v.split()) for k,v in parsed['particle_settings'].items()},
            'channel_commands':[channel(row) for row in parsed['channel_commands']],
            'ordered_particle_program':[row for _,row in sorted(program,key=lambda x:x[0])]}


def compare(intended, observed, *, hepmc_filename=None):
    """Typed card observation only; callers retain report before enforcing match."""
    source, actual = parse(intended), parse(observed)
    left,right = _identity(source),_identity(actual)
    if hepmc_filename is not None:
        require(type(hepmc_filename) is str and re.fullmatch(r'[A-Za-z0-9_.+\-]+',hepmc_filename)
                and hepmc_filename not in ('.','..','auto'), 'explicit task-bound HEPMC basename required')
        if (left['settings'].get('hepmcoutput:file') == 'auto' and
                right['settings'].get('hepmcoutput:file') == hepmc_filename):
            right['settings']['hepmcoutput:file'] = 'auto'
    return {'schema_version':1,'intended':source,'observed':actual,
            'matched':left == right,'mismatches':[k for k in left if left[k] != right[k]],
            'comparison_scope':'all singleton settings, ordered explicit decay commands and particle program',
            'allowed_output_rewrite':{'source':'auto','destination':hepmc_filename} if hepmc_filename is not None else None,
            'physical_shower_qualified':False,'scientific_acceptance':False}
