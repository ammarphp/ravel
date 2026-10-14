"""Streaming structural/beam/weight census for supplied ASCII HepMC2/3 files.

This checks serialized event identities and exposure. It is not a generator
validation, truth-label classifier, or energy-conservation proof.
"""
import gzip
import math
import shlex
import re


def nominal_version(selection):
    """Decode only the two source-reviewed full named-stream protocols."""
    protocols = {'rivet-4.1.3-full-named-streams': '4.1.3',
                 'rivet-4.1.4-full-named-streams': '4.1.4'}
    if type(selection) is not dict or type(selection.get('source_protocol')) is not str or selection['source_protocol'] not in protocols:
        raise ValueError('explicit source-bound Rivet 4.1.3 or 4.1.4 naming protocol required')
    return protocols[selection['source_protocol']]


def nominal_selection(weight_names, name, *, rivet_version='4.1.4'):
    """Source-reviewed Rivet 4.1.3/4.1.4 naming, preserving original order.

    This describes dispatched naming and native normalization semantics. It
    does not observe a process or select a generator normalization convention.
    """
    if type(rivet_version) is not str or rivet_version not in ('4.1.3', '4.1.4'):
        raise ValueError('explicit source-bound Rivet 4.1.3 or 4.1.4 naming protocol required')
    if (type(weight_names) is not list or not weight_names
            or any(type(n) is not str or not n for n in weight_names)
            or len(set(weight_names)) != len(weight_names)):
        raise ValueError('explicit unique original weight names required')
    if any(not n.isascii() for n in weight_names):
        raise ValueError('explicit nominal selection supports ASCII original weight names only')
    if type(name) is not str or not name or name not in weight_names:
        raise ValueError('nominal_weight must exactly name an original event weight')
    if any(any(c in n for c in '[]\n\r\x00') for n in weight_names):
        raise ValueError('ambiguous native named-weight suffix')
    selected = weight_names.index(name)
    candidates = [i for i, n in enumerate(weight_names)
                  if n.upper() in ('WEIGHT', '0', 'DEFAULT', 'NOMINAL')]
    # Exact all-named/no-match/no-skip AnalysisHandler::setWeightNames order:
    # an auto-detected nominal controls normalization; a custom label can be
    # distinct and is renamed empty without moving its original vector entry.
    normalization = (selected if selected in candidates else candidates[0]) if candidates else selected
    if any(re.fullmatch('IRREG.*', n, re.IGNORECASE) and i not in (selected, normalization)
           for i, n in enumerate(weight_names)):
        raise ValueError('native default filtering would omit an original weight stream')
    native = ['' if i == selected else n for i, n in enumerate(weight_names)]
    return {'schema_version': 1, 'source_protocol': 'rivet-' + rivet_version + '-full-named-streams',
            'original_weight_names': list(weight_names), 'nominal_weight': name,
            'nominal_weight_index': selected, 'native_weight_names': native,
            'native_raw_suffixes': ['' if n == '' else '[' + n + ']' for n in native],
            'native_normalization_weight': weight_names[normalization],
            'native_normalization_weight_index': normalization,
            'original_order_preserved': True, 'native_effective_weights_observed': False}


def census(path, metadata, *, nominal_weight=None, rivet_version='4.1.4'):
    required = {'schema_version', 'event_level', 'beam_pdg', 'beam_energy_gev', 'weight_names',
                'events', 'groups', 'cross_section_pb', 'source'}
    if not isinstance(metadata, dict) or set(metadata) != required or metadata['schema_version'] != 1:
        raise ValueError('invalid frozen-event metadata fields')
    if metadata['event_level'] != 'hadron' or metadata['groups'] not in ('independent', 'correlated_event_number'):
        raise ValueError('Rivet input needs explicit hadron level and event-group semantics')
    if type(metadata['events']) is not int or metadata['events'] <= 0:
        raise ValueError('positive event census required')
    if len(metadata['beam_pdg']) != 2 or any(type(x) is not int for x in metadata['beam_pdg']):
        raise ValueError('two signed PDG beam identifiers required')
    if len(metadata['beam_energy_gev']) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0 for x in metadata['beam_energy_gev']):
        raise ValueError('two positive beam energies required')
    names = metadata['weight_names']
    if not names or len(set(names)) != len(names) or any(not isinstance(n, str) or not n for n in names):
        raise ValueError('explicit unique weight names required')
    selection = nominal_selection(names, nominal_weight, rivet_version=rivet_version) if nominal_weight is not None else None
    nominal_index = selection['nominal_weight_index'] if selection else 0
    if type(metadata['cross_section_pb']) not in (int, float) or not math.isfinite(metadata['cross_section_pb']) or metadata['cross_section_pb'] <= 0:
        raise ValueError('explicit positive cross section in pb required')
    if not isinstance(metadata['source'], str) or not metadata['source'].strip():
        raise ValueError('event source description required')
    version = None
    started = ended = False
    current = None
    group_ids, counts, negative = set(), 0, 0
    group_weights = {}
    pending_group = [None]
    pending_columns = [[] for _ in names]
    declared_names = None
    opener = gzip.open if str(path).endswith('.gz') else open

    def finish(e):
        nonlocal counts, negative
        if e is None:
            return
        if e['units'] not in (('GEV', 'MM'), ('GEV', 'CM'), ('MEV', 'MM'), ('MEV', 'CM')):
            raise ValueError('missing or unsupported explicit HepMC units')
        if len(e['weights']) != len(names) or any(not math.isfinite(w) for w in e['weights']):
            raise ValueError('event weight dimension or finiteness mismatch')
        if e['expected_particles'] is not None and len(e['particles']) != e['expected_particles']:
            raise ValueError('truncated HepMC3 particle inventory')
        if not e['particles']:
            raise ValueError('event contains no particles')
        particles = e['particles']
        beams = ([particles.get(b) for b in e['beam_barcodes']] if version == 2 else
                 [p for p in particles.values() if p['status'] == 4])
        if len(beams) != 2 or any(p is None for p in beams):
            raise ValueError('exactly two identified beam particles required')
        # Positive-z beam first; symmetric beams remain stable under serialization order.
        beams.sort(key=lambda p: -p['pz'])
        scale = .001 if e['units'][0] == 'MEV' else 1.
        for i, beam in enumerate(beams):
            if beam['pz'] * (1 if i == 0 else -1) <= 0 or abs(beam['px']) > 1e-8 or abs(beam['py']) > 1e-8:
                raise ValueError('adapter requires opposing collinear beams in the declared laboratory frame')
            if beam['pdg'] != metadata['beam_pdg'][i] or not math.isclose(beam['energy'] * scale, metadata['beam_energy_gev'][i], rel_tol=1e-7, abs_tol=1e-6):
                raise ValueError('serialized beams disagree with the declared beam identity or energy')
        if e['id'] in group_ids and e['id'] != previous[0]:
            raise ValueError('event number repeated non-contiguously; group semantics ambiguous')
        if e['id'] in group_ids and metadata['groups'] == 'independent':
            raise ValueError('duplicate independent event identifier')
        group_ids.add(e['id'])
        previous[0] = e['id']
        if pending_group[0] != e['id']:
            finish_group()
            pending_group[0] = e['id']
        for i, w in enumerate(e['weights']):
            pending_columns[i].append(w)
        counts += 1
        negative += int(e['weights'][nominal_index] < 0)
    previous = [None]
    def finish_group():
        if pending_group[0] is None:
            return
        values = [math.fsum(column) for column in pending_columns]
        if not all(math.isfinite(value) for value in values):
            raise ValueError('nonfinite compensated event-group weight')
        group_weights[pending_group[0]] = values
        for column in pending_columns:
            column.clear()
    with opener(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            if 'START_EVENT_LISTING' in line:
                if started:
                    raise ValueError('multiple HepMC streams must be separate inputs')
                version = 3 if 'Asciiv3' in line else 2 if 'IO_GenEvent' in line else None
                if version is None:
                    raise ValueError('unsupported HepMC serialization')
                started = True
                continue
            if 'END_EVENT_LISTING' in line:
                if not started or ended:
                    raise ValueError('invalid HepMC end marker')
                finish(current)
                current = None
                ended = True
                continue
            if ended:
                raise ValueError('content after the HepMC end marker')
            if line.startswith('HepMC::Version'):
                continue
            fields = line.split()
            tag = fields[0]
            if tag == 'E':
                if not started:
                    raise ValueError('event before HepMC stream header')
                finish(current)
                current = {'id': int(fields[1]), 'weights': [], 'units': None, 'particles': {},
                           'expected_particles': int(fields[3]) if version == 3 else None}
                if version == 2:
                    nrandom = int(fields[11])
                    offset = 12 + nrandom
                    nweights = int(fields[offset])
                    current['weights'] = [float(x) for x in fields[offset+1:]]
                    if len(current['weights']) != nweights:
                        raise ValueError('truncated HepMC2 event weights')
                    current['beam_barcodes'] = [int(fields[9]), int(fields[10])]
            elif tag == 'N' and version == 2:
                quoted = shlex.split(line)
                this_names = quoted[2:]
                if int(quoted[1]) != len(this_names) or this_names != names:
                    raise ValueError('HepMC2 weight names differ from metadata')
                declared_names = this_names
            elif tag == 'W' and version == 3:
                if current is None:
                    declared_names = line[2:].split('\\|')
                    if declared_names != names:
                        raise ValueError('HepMC3 weight names differ from metadata')
                else:
                    if current['weights']:
                        raise ValueError('duplicate event weight line')
                    current['weights'] = [float(x) for x in fields[1:]]
            elif tag == 'U' and current is not None:
                if current['units'] is not None:
                    raise ValueError('duplicate event units')
                current['units'] = tuple(fields[1:])
            elif tag == 'P' and current is not None:
                offset = 1 if version == 2 else 2
                pid = int(fields[1])
                if pid in current['particles']:
                    raise ValueError('duplicate HepMC particle identifier')
                vals = [float(x) for x in fields[offset+2:offset+7]]
                if len(vals) != 5 or not all(math.isfinite(x) for x in vals):
                    raise ValueError('nonfinite or truncated particle kinematics')
                current['particles'][pid] = {'pdg': int(fields[offset+1]), 'px': vals[0], 'py': vals[1], 'pz': vals[2],
                                            'energy': vals[3], 'status': int(fields[offset+7])}
    if not started or not ended or counts != metadata['events'] or declared_names != names:
        raise ValueError('incomplete stream, missing weight names or event census differs from declaration')
    finish_group()
    sumw = [math.fsum(g[i] for g in group_weights.values()) for i in range(len(names))]
    if not all(math.isfinite(x) for x in sumw) or sumw[nominal_index] == 0:
        raise ValueError('invalid or zero nominal normalization weight')
    if selection and sumw[selection['native_normalization_weight_index']] == 0:
        raise ValueError('zero source-defined native normalization weight')
    covariance = [[math.fsum(g[i] * g[j] for g in group_weights.values()) for j in range(len(names))] for i in range(len(names))]
    if not all(math.isfinite(value) for row in covariance for value in row):
        raise ValueError('nonfinite full event-group weight second moment')
    result = {'format': f'HepMC{version}', 'events': counts, 'independent_groups': len(group_ids),
            'weight_names': names, 'sumw': sumw, 'group_weight_second_moments': covariance,
            'negative_nominal_subevents': negative, 'beams_checked': True, 'physics_validated': False}
    if selection:
        result.update(nominal_weight_selection=selection, nominal_sumw=sumw[nominal_index],
                      nominal_group_second_moment=covariance[nominal_index][nominal_index],
                      native_normalization_sumw=sumw[selection['native_normalization_weight_index']])
    return result
