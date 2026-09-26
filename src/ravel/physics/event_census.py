"""Streaming structural/beam/weight census for supplied ASCII HepMC2/3 files.

This checks serialized event identities and exposure. It is not a generator
validation, truth-label classifier, or energy-conservation proof.
"""
import gzip
import math
import shlex


def census(path, metadata):
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
    if type(metadata['cross_section_pb']) not in (int, float) or not math.isfinite(metadata['cross_section_pb']) or metadata['cross_section_pb'] <= 0:
        raise ValueError('explicit positive cross section in pb required')
    if not isinstance(metadata['source'], str) or not metadata['source'].strip():
        raise ValueError('event source description required')
    version = None
    started = ended = False
    current = None
    group_ids, counts, negative = set(), 0, 0
    group_weights = {}
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
        sums = group_weights.setdefault(e['id'], [0.] * len(names))
        for i, w in enumerate(e['weights']):
            sums[i] += w
        counts += 1
        negative += int(e['weights'][0] < 0)
    previous = [None]
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
    sumw = [math.fsum(g[i] for g in group_weights.values()) for i in range(len(names))]
    if not all(math.isfinite(x) for x in sumw) or sumw[0] == 0:
        raise ValueError('invalid or zero nominal normalization weight')
    covariance = [[math.fsum(g[i] * g[j] for g in group_weights.values()) for j in range(len(names))] for i in range(len(names))]
    return {'format': f'HepMC{version}', 'events': counts, 'independent_groups': len(group_ids),
            'weight_names': names, 'sumw': sumw, 'group_weight_second_moments': covariance,
            'negative_nominal_subevents': negative, 'beams_checked': True, 'physics_validated': False}
