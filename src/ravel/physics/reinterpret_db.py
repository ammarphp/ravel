"""Source-complete SModelS model portfolio through the supervised science seam.

An unchanged supplied SLHA/LHE, an explicitly trusted pinned database, the
qualified native runtime, and the decomposition protocol form one transaction.
No production process is replaced. Statistical combinations are only native
within-analysis combinations from the bound database.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import configparser
from copy import deepcopy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import signal
import shutil
import threading

if not __package__:  # Support the bound native interpreter without installing Ravel.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = 'ravel.physics'

SCOPE = 'complete supplied-model simplified-topology map interpretation within the pinned database domain'
SETTINGS = {
    'analyses': ['all'], 'txnames': ['all'], 'data_types': 'all',
    'combine_srs': True, 'sigmacut_fb': .005, 'minmassgap_gev': 5.,
    'minmassgap_isr_gev': 1., 'maxcond': .2,
    'prompt_width_gev': 1e-11, 'stable_width_gev': 1e-25,
}


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _pin(path):
    path = Path(path).expanduser().resolve(strict=True)
    return {'path': str(path), 'sha256': _hash(path)}


_XSECTION_HEADER = re.compile(r'^XSECTION\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\d+)((?:\s+-?\d+)*)', re.I)


def _pdg_list(value, label):
    tokens = value.split() if isinstance(value, str) else list(value)
    try:
        pdgs = [int(token) for token in tokens]
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be integer PDG codes') from exc
    if not pdgs or any(isinstance(t, bool) or (not isinstance(t, str) and type(t) is not int) for t in tokens):
        raise ValueError(f'{label} must name at least one integer PDG code')
    return pdgs


def add_xsection(slha, sigma_pb, proc, *, sqrts_gev, qcd_order, code, output,
                 initial=(2212, 2212), ew_order=0, scale_scheme=0, kappa_f=1.0, kappa_r=1.0, pdf_id=0):
    """Write a copy of a supplied SLHA file with one XSECTION block for a production process.

    SModelS reads production rates only from SLHA ``XSECTION`` blocks. The cross section,
    the collision energy, the QCD order and the code or table that produced the value are
    the caller's inputs and are never defaulted. ``proc`` names the final-state PDG codes
    (space-separated text or a sequence). The supplied file is not changed: the block is
    appended to a new file at ``output``. Existing blocks are kept; a second block for the
    same energy, initial state and final state is refused. Returns the output pin."""
    source = Path(slha).expanduser().resolve(strict=True)
    target = Path(output).expanduser().resolve()
    if target == source or target.exists():
        raise ValueError('add_xsection writes a new output file; the supplied SLHA is preserved')
    values = {'sigma_pb': sigma_pb, 'sqrts_gev': sqrts_gev, 'kappa_f': kappa_f, 'kappa_r': kappa_r}
    for name, value in values.items():
        if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be a positive finite number')
    for name, value in (('qcd_order', qcd_order), ('ew_order', ew_order), ('scale_scheme', scale_scheme),
                        ('pdf_id', pdf_id)):
        if type(value) is not int or value < 0:
            raise ValueError(f'{name} must be a nonnegative integer')
    if not isinstance(code, str) or not code or any(c.isspace() for c in code):
        raise ValueError('code must name the producer of the cross section as one token')
    final = _pdg_list(proc, 'proc')
    beams = _pdg_list(initial, 'initial')
    if len(beams) != 2:
        raise ValueError('initial must name the two colliding particles')
    text = source.read_text(errors='replace')
    for line in text.splitlines():
        match = _XSECTION_HEADER.match(line.strip())
        if match and math.isclose(float(match[1].replace('D', 'E').replace('d', 'e')), sqrts_gev, rel_tol=1e-9) \
                and [int(match[2]), int(match[3])] == beams and sorted(map(int, match[5].split())) == sorted(final):
            raise ValueError('the supplied SLHA already carries an XSECTION block for this process and energy')
    block = (f'XSECTION  {sqrts_gev:.6E}  {beams[0]} {beams[1]}  {len(final)}  {" ".join(map(str, final))}\n'
             f'  {scale_scheme}  {qcd_order}  {ew_order}  {kappa_f:.6E}  {kappa_r:.6E}  {pdf_id}  {sigma_pb:.8E}  {code}\n')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x') as stream:
        stream.write(text.rstrip('\n') + '\n' + block)
    return _pin(target)


def _keys(value, required, label):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError(label + ' requires exactly ' + ', '.join(required))


def _read(path):
    from ravel.workflow.state_io import read_json
    return read_json(path)


def _bound(pin, base, *, verify=True):
    from ravel.workflow.science import regular
    _keys(pin, ('path', 'sha256'), 'file binding')
    if not isinstance(pin['sha256'], str) or len(pin['sha256']) != 64 or any(c not in '0123456789abcdef' for c in pin['sha256']):
        raise ValueError('invalid SHA256')
    path = regular(pin['path'], base)
    if verify and _hash(path) != pin['sha256']:
        raise ValueError('bound file changed: ' + str(path))
    return path


def validate(task):
    _keys(task, ('input',), 'model-portfolio task')
    if not isinstance(task['input'], str) or not task['input'].strip():
        raise ValueError('model-portfolio requires its input document')
    return deepcopy(task)


def validate_document(document):
    _keys(document, ('schema_version', 'source', 'model_input', 'database', 'runtime', 'model', 'settings', 'max_seconds', 'max_ram_mib'), 'portfolio input')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ValueError('unsupported portfolio schema')
    if not isinstance(document['source'], str) or not document['source'].strip():
        raise ValueError('scientific input attribution required')
    _keys(document['model_input'], ('file', 'format'), 'supplied model')
    if document['model_input']['format'] not in ('slha', 'lhe'):
        raise ValueError('supported input formats are SLHA and LHE')
    _keys(document['database'], ('file', 'version', 'source_url', 'trusted_pickle'), 'database')
    if document['database']['version'] != '3.1.1' or document['database']['trusted_pickle'] is not True:
        raise ValueError('only explicitly trusted source-bound 3.1.1 pickle database is qualified')
    if not isinstance(document['database']['source_url'], str) or not document['database']['source_url'].startswith('https://'):
        raise ValueError('database needs its trusted HTTPS source attribution')
    _keys(document['runtime'], ('python', 'manifest', 'smodels_version'), 'runtime')
    if document['runtime']['smodels_version'] != '3.1.1':
        raise ValueError('only installed SModelS 3.1.1 API is qualified')
    _keys(document['model'], ('kind', 'file'), 'particle model')
    if document['model']['kind'] not in ('mssm', 'qnumbers', 'python'):
        raise ValueError('particle model must be MSSM, input QNUMBERS, or supplied Python model')
    if (document['model']['kind'] == 'python') != (document['model']['file'] is not None):
        raise ValueError('only Python particle model takes an extra source file')
    settings = document['settings']
    _keys(settings, SETTINGS, 'decomposition protocol')
    for key in ('analyses', 'txnames'):
        if not isinstance(settings[key], list) or not settings[key] or any(not isinstance(v, str) or not v or ',' in v or '\n' in v for v in settings[key]):
            raise ValueError(key + ' must be a nonempty list of native selectors')
    if settings['data_types'] not in ('all', 'efficiencyMap', 'upperLimit') or type(settings['combine_srs']) is not bool:
        raise ValueError('invalid database/result combination protocol')
    for key in ('sigmacut_fb', 'minmassgap_gev', 'minmassgap_isr_gev', 'maxcond', 'prompt_width_gev', 'stable_width_gev'):
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(key + ' must be finite and nonnegative')
    if not 0 < settings['maxcond'] <= 1 or not 0 < settings['stable_width_gev'] < settings['prompt_width_gev']:
        raise ValueError('invalid condition/lifetime boundaries')
    if type(document['max_seconds']) is not int or not 1 <= document['max_seconds'] <= 3600:
        raise ValueError('native worker budget must be an integer from 1 to 3600')
    if type(document['max_ram_mib']) is not int or not 512 <= document['max_ram_mib'] <= 8192:
        raise ValueError('RAM ceiling must be an integer from 512 to 8192 MiB')
    return deepcopy(document)


def _load(task, base):
    from ravel.workflow.science import regular
    path = regular(validate(task)['input'], base)
    return path, validate_document(_read(path))


def inputs(task, base):
    path, doc = _load(task, base)
    pins = [doc['model_input']['file'], doc['database']['file'], doc['runtime']['python'], doc['runtime']['manifest']]
    if doc['model']['file']:
        pins.append(doc['model']['file'])
    files = [_bound(pin, path.parent) for pin in pins]
    capsule = _read(files[3])
    if capsule.get('smodels_version') != doc['runtime']['smodels_version'] or not isinstance(capsule.get('files'), list) or not capsule['files']:
        raise ValueError('runtime capsule does not describe the qualified installed API')
    files += [_bound(pin, path.parent) for pin in capsule['files']]
    return [path, *files, Path(__file__).resolve()]


def _ini(document, model_path, db_path, model_file):
    s = document['settings']
    cp = configparser.ConfigParser()
    cp['options'] = {'checkInput': 'True', 'doInvisible': 'True', 'doCompress': 'True',
        'testCoverage': 'True', 'computeStatistics': 'True', 'combineSRs': str(s['combine_srs']),
        'reportAllSRs': 'True', 'pyhfbackend': 'numpy'}
    cp['particles'] = {'promptWidth': str(s['prompt_width_gev']), 'stableWidth': str(s['stable_width_gev'])}
    if document['model']['kind'] == 'mssm':
        cp['particles']['model'] = 'share.models.mssm'
    elif document['model']['kind'] == 'python':
        cp['particles']['model'] = str(model_file)
    # Omission is upstream's input-file QNUMBERS model route.
    cp['parameters'] = {'sigmacut': str(s['sigmacut_fb']), 'minmassgap': str(s['minmassgap_gev']),
        'minmassgapISR': str(s['minmassgap_isr_gev']), 'maxcond': str(s['maxcond']), 'ncpus': '1'}
    cp['database'] = {'path': str(db_path), 'analyses': ','.join(s['analyses']),
        'txnames': ','.join(s['txnames']), 'dataselector': s['data_types'], 'useNonValidated': 'False'}
    cp['printer'] = {'outputType': 'python,summary', 'outputFormat': 'version3'}
    cp['python-printer'] = {'addSMSList': 'True', 'addTxWeights': 'True', 'addNodesMap': 'True', 'typeOfExpectedValues': 'apriori'}
    cp['summary-printer'] = {'expandedSummary': 'True'}
    return cp


def select_expected(records):
    """Predeclared apriori choice, retaining unavailable expectations separately."""
    groups = defaultdict(list)
    for index, record in enumerate(records):
        expected = record.get('r_expected')
        if type(expected) in (int, float) and math.isfinite(expected) and expected > 0:
            groups[record['AnalysisID']].append((index, record))
    choices = []
    for analysis, predictions in sorted(groups.items()):
        native_combined = [p for p in predictions if p[1]['dataType'] == 'combined']
        pool = native_combined or predictions
        # Stable source identities break ties without depending on observed-r
        # printer ordering or whether an observed fit happens to succeed.
        chosen = min(pool, key=lambda p: (-p[1]['r_expected'], -p[1]['theory prediction (fb)'],
            str(p[1]['DataSetID']), json.dumps(p[1].get('TxNames',[]),sort_keys=True),
            json.dumps({key: p[1].get(key) for key in ('Mass (GeV)', 'Width (GeV)',
                'native_sms_ids', 'dataType', 'AnalysisSqrts (TeV)',
                'native_dataset_path', 'native_analysis_path')}, sort_keys=True)))
        choices.append({'analysis_id': analysis, 'record_index': chosen[0],
            'result_identity': {key: chosen[1].get(key) for key in ('AnalysisID', 'DataSetID',
                'dataType', 'AnalysisSqrts (TeV)', 'TxNames', 'Mass (GeV)', 'Width (GeV)',
                'native_sms_ids', 'native_dataset_path', 'native_analysis_path')},
            'basis': 'native_within_analysis_combination' if native_combined else 'largest_apriori_expected_r'})
    selected = min(choices, key=lambda c: (-records[c['record_index']]['r_expected'],
        c['analysis_id'])) if choices else None
    return {'evaluation_mode': 'apriori', 'per_analysis': choices, 'selected': selected,
        'cross_analysis_combination': None, 'selection_uses_observed_r': False}


def _source_decay_headers(path):
    """Retain literal declarations independently of the consumer's effective rows."""
    headers = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        fields = line.split('#', 1)[0].split()
        if fields and fields[0].upper() == 'DECAY':
            headers.append({'pdg': int(fields[1]), 'width_token': fields[2],
                'width_gev': None if fields[2].upper() == 'NAN' else float(fields[2].replace('D', 'E').replace('d', 'e')),
                'source_line': number, 'recognized_header': not line[0].isspace() and bool(
                    re.match(r'DECAY\s+(-?\d+)\s+([\d\.E+-]+|NAN).*', line.upper()))})
    return headers


def _physical_input(path, format, settings):
    if format == 'lhe':
        from smodels.base import lheReader
        from smodels.base.physicsUnits import fb, TeV
        reader = lheReader.LheReader(str(path))
        return {'format': 'lhe', 'event_count': reader.metainfo['nevents'],
            'total_xsec_fb': reader.metainfo['totalxsec'].asNumber(fb),
            'sqrts_tev': reader.metainfo['sqrts'].asNumber(TeV),
            'spectrum_and_decay_source': 'upstream LHE-derived particle model; original LHE preserved'}
    import pyslha
    slha = pyslha.readSLHAFile(str(path))
    processes = []
    for process in slha.xsections.values():
        for xsec in process.xsecs:
            processes.append({'initial_pdgs': list(process.pidsinitial), 'final_pdgs': list(process.pidsfinal),
                'sqrts_gev': xsec.sqrts, 'scale_scheme': xsec.scale_scheme, 'qcd_order': xsec.qcd_order,
                'ew_order': xsec.ew_order, 'kappa_f': xsec.kappa_f, 'kappa_r': xsec.kappa_r,
                'pdf_id': xsec.pdf_id, 'xsec_pb': xsec.value, 'code': xsec.code})
    headers = _source_decay_headers(path)
    declared = defaultdict(list)
    for header in headers:
        if header['recognized_header']:
            declared[header['pdg']].append(header['source_line'])
    decays, defaults = [], []
    for pdg, particle in sorted(slha.decays.items()):
        width = particle.totalwidth
        category = 'stable' if width is not None and width < settings['stable_width_gev'] else 'prompt' if width is not None and width > settings['prompt_width_gev'] else 'intermediate_width'
        row = {'pdg': pdg, 'width_gev': width, 'width_category': category,
            'branching_fraction_sum': sum(d.br for d in particle.decays),
            'channels': [{'branching_fraction': d.br, 'daughter_pdgs': list(d.ids)} for d in particle.decays]}
        if pdg in declared:
            row.update(source_header_lines=declared[pdg], representation='effective pyslha row for explicit source declarations')
            decays.append(row)
        else:
            row.update(provenance='pyslha default for a mass entry without a recognized DECAY header', source_header_lines=[])
            defaults.append(row)
    return {'format': 'slha', 'production_processes': processes,
        'masses_gev': [{'pdg': p, 'mass': m} for p,m in sorted(slha.blocks['MASS'].items())],
        'decays': decays, 'literal_decay_headers': headers, 'parser_added_decay_defaults': defaults,
        'all_original_cross_sections_preserved': True,
        'decay_consumer_note': 'decays contains effective pyslha rows with explicit source headers; every literal header is retained separately, including duplicate declarations. Consumer duplicate-header semantics are unchanged, not repaired or independently resolved by RAVEL.',
        'lifetime_note': 'Literal width tokens are retained in literal_decay_headers. Parser-added defaults are separate and are not supplied widths. Native prompt/displaced/stable probability reweighting governs applicability; labels are only threshold diagnostics.'}


def _number(value, unit=None):
    if value is None:
        return None
    if unit is not None and hasattr(value, 'asNumber'):
        value = value.asNumber(unit)
    value = float(value)
    return value if math.isfinite(value) else None


def _node_quantity(value, unit):
    """Keep exact native node values and explicitly encode infinity sentinels."""
    if value is None:
        return None
    if hasattr(value, 'asNumber'):
        value = value.asNumber(unit)
    if isinstance(value, (list, tuple)):
        return [_node_quantity(item, None) for item in value]
    number = float(value)
    if math.isnan(number):
        raise ValueError('native node physics contains NaN')
    return number if math.isfinite(number) else {'native_sentinel': 'positive_infinity' if number > 0 else 'negative_infinity'}


def _combined_regions(tp, fb):
    if tp.dataType() != 'combined':
        return []
    matched = {p.dataset.getID(): p for p in tp.datasetPredictions}
    return [{'dataset_id': ds.getID(),
        'signal_xsec_fb': _number(matched[ds.getID()].xsection, fb) if ds.getID() in matched else 0.0,
        'signal_yield': _number(matched[ds.getID()].xsection * ds.getLumi()) if ds.getID() in matched else 0.0,
        'matched_prediction': ds.getID() in matched}
        for ds in tp.dataset.origdatasets]


def execute_native(command, out, document, *, generated_event_ceiling=None, environment=None):
    """Bound the owned native process group and sample actual aggregate RSS."""
    out = Path(out)
    if generated_event_ceiling is not None and (type(generated_event_ceiling) is not int or generated_event_ceiling <= 0):
        raise ValueError('explicit positive generated-event ceiling required')
    event_fields = ({'new_events_generated': 0} if generated_event_ceiling is None else
                    {'new_events_generated': None, 'generated_event_ceiling': generated_event_ceiling,
                     'event_observation': 'pending adapter population census'})
    if environment is not None and (type(environment) is not dict or len(environment)>64 or
            any(type(k) is not str or type(v) is not str or not k or len(k)>128 or len(v.encode())>16384 or
                '\x00' in k+v or k in {'HOME','home','CODEX_HOME'} for k,v in environment.items())):
        raise ValueError('finite explicit native environment required; protected home variables cannot be overridden')
    env = dict(os.environ if environment is None else environment,
        OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')
    explicit_environment = ({'environment_mode':'explicit', 'effective_environment':dict(env)}
        if environment is not None else {})
    start, peak, samples, violation = time.monotonic(), 0, 0, None
    previous_handlers, received_signals = {}, []
    def interrupted(signum, frame):
        received_signals.append(signal.Signals(signum).name)
        raise KeyboardInterrupt('native worker interrupted by ' + signal.Signals(signum).name)
    with (out/'native-stdout.log').open('w') as stdout, (out/'native-stderr.log').open('w') as stderr:
        stdout.write('Native worker stdout follows.\n'); stdout.flush()
        stderr.write('Native worker stderr follows.\n'); stderr.flush()
        process = subprocess.Popen(command,cwd=out,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        if environment is not None:
            explicit_environment.update({'pid':process.pid,'working_directory':str(out.absolute())})
        try:
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGTERM, signal.SIGINT):
                    previous_handlers[sig] = signal.signal(sig, interrupted)
            _write(out/'native-process.json', {'pid':process.pid, 'process_group':process.pid,
                'owner_pid':os.getpid(), 'command':command, **event_fields, **explicit_environment})
            while process.poll() is None:
                census = subprocess.run(['ps','-axo','pid=,pgid=,rss=,stat='],capture_output=True,text=True,check=True,timeout=5)
                table = [line.split() for line in census.stdout.splitlines() if len(line.split()) == 4]
                rss_kib = sum(int(rss) for pid,pgid,rss,state in table
                    if int(pgid) == process.pid and not state.startswith('Z'))
                peak = max(peak,rss_kib); samples += 1
                if rss_kib > document['max_ram_mib'] * 1024:
                    violation = 'aggregate native RSS exceeded RAM ceiling'; break
                if time.monotonic()-start > document['max_seconds']:
                    violation = 'native execution exceeded time ceiling'; break
                time.sleep(.25)
        except (Exception, KeyboardInterrupt) as exc:
            violation = 'native resource supervision failed: ' + str(exc)
        finally:
            # A terminated leader does not establish that its owned children stopped.
            try:
                os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                try:
                    # The outer scientific supervisor allows two seconds of grace.
                    process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL); process.wait(timeout=.5)
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            for sig,handler in previous_handlers.items():
                signal.signal(sig,handler)
    receipt = {'command':command,'returncode':process.returncode,'wall_seconds':time.monotonic()-start,
        'max_seconds':document['max_seconds'],'max_ram_mib':document['max_ram_mib'],
        'peak_sampled_aggregate_rss_mib':peak/1024,'rss_samples':samples,'rss_sampling_seconds':.25,
        'resource_violation':violation, 'received_signals':received_signals,
        'thread_limits':{key:env[key] for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')},
        **event_fields, **explicit_environment}
    _write(out/'native-execution.json',receipt)
    if violation or process.returncode:
        raise ValueError(violation or 'native process failed; see retained native-stdout.log and native-stderr.log')
    return receipt


def native_worker(document_path, output):
    """Unmodified upstream decomposition/matching/likelihood pipeline, plus evidence."""
    import smodels
    import importlib.metadata as metadata
    from smodels.matching import modelTester
    from smodels.matching.theoryPrediction import TheoryPredictionList
    from smodels.tools.coverage import Uncovered
    from smodels.decomposition.topologyDict import TopologyDict
    from smodels.tools.ioObjects import OutputStatus
    from smodels.base.physicsUnits import fb, TeV, GeV
    from smodels.statistics.basicStats import apriori, observed
    document = json.loads(Path(document_path).read_text())
    if metadata.version('smodels') != document['runtime']['smodels_version']:
        raise ValueError('executed SModelS differs from qualified version')
    out = Path(output)
    model_path = Path(document['model_input']['file']['path'])
    database_path = Path(document['database']['file']['path'])
    model_file = document['model']['file']['path'] if document['model']['file'] else None
    cp = _ini(document, model_path, database_path, model_file)
    parameter_file = out / 'parameters.ini'
    with parameter_file.open('w') as stream:
        cp.write(stream)
    parser = modelTester.getParameters(str(parameter_file))
    db = modelTester.loadDatabase(parser, None)
    if db.databaseVersion != document['database']['version']:
        raise ValueError('loaded database version differs from bound version')
    modelTester.loadDatabaseResults(parser, db)
    census = []
    for exp in db.expResultList:
        census.append({'analysis_id': exp.globalInfo.id,
            'sqrts_tev': exp.globalInfo.sqrts.asNumber(TeV),
            'datasets': [{'dataset_id': ds.getID(), 'data_type': ds.getType(),
                          'txnames': [tx.txName for tx in ds.txnameList]} for ds in exp.datasets],
            'has_covariance': exp.hasCovarianceMatrix(), 'has_json_likelihood': exp.hasJsonFile()})
    _write(out / 'loaded-database-census.json', census)
    master = next(iter(modelTester.testPoint(str(model_path), str(out), parser, db).values()))
    printer = master.Printers['python']
    objects = list(printer.toPrint)
    coverage, decomposition, exact_predictions = [], [], []
    for obj in objects:
        if isinstance(obj, TheoryPredictionList):
            for tp in obj:
                native = printer._formatTheoryPredictionList(TheoryPredictionList([tp]))['ExptRes'][0]
                native.update({'r': _number(tp.getRValue(evaluationType=observed)),
                    'r_expected': _number(tp.getRValue(evaluationType=apriori)),
                    'theory prediction (fb)': _number(tp.xsection, fb),
                    'upper limit (fb)': _number(tp.getUpperLimit(), fb),
                    'expected upper limit (fb)': _number(tp.getUpperLimit(evaluationType=apriori), fb),
                    'native_sms_ids': sorted(set(sms.smsID for sms in tp.smsList)),
                    'native_dataset_path': str(tp.dataset.path),
                    'native_analysis_path': str(tp.expResult.path),
                    'statistical_model': 'native_covariance' if hasattr(tp.dataset.globalInfo,'covariance') and tp.dataType() == 'combined' else 'native_pyhf' if hasattr(tp.dataset.globalInfo,'jsonFiles') and tp.dataType() == 'combined' else tp.dataType(),
                    'native_region_mapping': getattr(tp.dataset.globalInfo,'jsonFiles', None),
                    'native_dataset_order': getattr(tp.dataset.globalInfo,'datasetOrder', None),
                    'region_signal_predictions': [{'dataset_id': p.dataId(), 'signal_xsec_fb': _number(p.xsection,fb)} for p in getattr(tp,'datasetPredictions',[])],
                    'native_combined_region_inputs': _combined_regions(tp, fb),
                    'likelihood_status': 'available' if tp.likelihood(return_nll=True) is not None else 'unavailable'})
                exact_predictions.append(native)
        elif isinstance(obj, Uncovered):
            for group in obj.groups:
                coverage.append({'label': group.label, 'description': group.description,
                    'sqrts_tev': group.sqrts.asNumber(TeV), 'total_xsec_fb': group.getTotalXSec(),
                    'signatures': [{'sms': str(sms), 'weight_fb': sms.missingX,
                                    'native_sms_ids': [s.smsID for s in sms._contributingSMS]} for sms in group.finalStateSMS]})
        elif isinstance(obj, TopologyDict):
            for sms in obj.getSMSList():
                item = printer._formatSMS(sms)
                item.update({'covered_by': sorted(sms.coveredBy), 'tested_by': sorted(sms.testedBy),
                    'native_nodes': [{'node_index': index, 'particle': str(node),
                        'parent_index': sms.parentIndex(index) if index != sms.rootIndex else None,
                        'daughter_indices': list(sms.daughterIndices(index)),
                        'mass_gev': _node_quantity(getattr(node,'mass',None), GeV),
                        'width_gev': _node_quantity(getattr(node,'totalwidth',None), GeV)}
                        for index,node in sorted(sms._nodesMapping.items())],
                    'compression_ancestor_sms_ids': sorted(set(parent.smsID for parent in sms.getAncestors())),
                    'full_weights': [{'sqrts_tev': x.info.sqrts.asNumber(TeV), 'order': x.info.order,
                                      'value_fb': x.value.asNumber(fb), 'pdgs': list(x.pid)} for x in sms.weightList]})
                decomposition.append(item)
    upstream = master.flush()['python']
    _write(out / 'upstream-structured.json', upstream)
    _write(out / 'portfolio-native.json', {'output_status': upstream['OutputStatus'],
        'predictions': exact_predictions, 'decomposition': decomposition, 'coverage': coverage,
        'supplied_physics': _physical_input(model_path,document['model_input']['format'],document['settings']),
        'loaded_database_census': 'loaded-database-census.json'})


def summarize(native):
    status = native['output_status']
    records = native['predictions']
    choice = select_expected(records)
    ds = status['decomposition status']
    if ds < 0:
        conclusion = {'status': 'invalid_or_no_decomposition', 'excluded': None,
            'reason': 'upstream status ' + str(ds)}
    elif not records:
        conclusion = {'status': 'no_applicable_prediction', 'excluded': None,
            'reason': 'no admitted matching predictions in selected database'}
    elif choice['selected'] is None:
        conclusion = {'status': 'no_expected_sensitive_prediction', 'excluded': None,
            'reason': 'observed-only map constraints retained without post-data selection'}
    else:
        selected = records[choice['selected']['record_index']]
        observed = selected.get('r')
        usable = type(observed) in (int,float) and math.isfinite(observed) and observed >= 0
        conclusion = {'status': 'excluded' if usable and observed >= 1 else 'not_excluded' if usable else 'selected_prediction_inference_unavailable',
            'excluded': observed >= 1 if usable else None, 'analysis_id': selected['AnalysisID'],
            'dataset_id': selected['DataSetID'], 'r_observed': selected['r'],
            'r_expected': selected['r_expected'], 'data_type': selected['dataType'],
            'confidence_convention': 'native database 95 percent upper-limit comparison'}
    nonzero = [g for g in native['coverage'] if g['total_xsec_fb'] > 0]
    return {'conclusion': conclusion, 'selection': choice,
        'coverage': {'groups': native['coverage'], 'groups_overlap': True,
            'groups_must_not_be_summed': True, 'omitted_below_sigmacut_not_zero': True},
        'follow_up': [{'group':g['label'], 'source_signature':g['signatures'][0]['sms'] if g['signatures'] else None,
            'required_calculation': 'Identify a published response/likelihood for this exact final state and lifetime, or use a native event-level analysis with validated response. Supply new events only in a separately approved study.',
            'reason': 'outside map support' if g['label'].startswith('outsideGrid') else 'uncovered topology/lifetime'} for g in nonzero]}


def run(task, base, output):
    path, doc = _load(task, base)
    files = inputs(task, base)
    for container,key in ((doc['model_input'],'file'),(doc['database'],'file'),(doc['runtime'],'python'),(doc['runtime'],'manifest')):
        container[key]['path'] = str(_bound(container[key], path.parent))
    if doc['model']['file']:
        doc['model']['file']['path'] = str(_bound(doc['model']['file'],path.parent))
    out = Path(output)
    out.mkdir(parents=True,exist_ok=True)
    native_input = out / 'native-input.json'
    _write(native_input,doc)
    command = [doc['runtime']['python']['path'], str(Path(__file__).resolve()), '--native-worker',str(native_input),'--out',str(out)]
    execute_native(command,out,doc)
    native = _read(out/'portfolio-native.json')
    report = summarize(native)
    passed = native['output_status']['decomposition status'] >= 0
    result = {'status':'passed' if passed else 'failed','physics_validated':False,
        'scope':SCOPE, **report, 'source':doc['source'], 'database':doc['database'],
        'runtime':doc['runtime'],'protocol':doc['settings'], 'output_status':native['output_status'],
        'predictions':native['predictions'],'supplied_physics':native['supplied_physics'],
        'native_artifacts':['portfolio-native.json','upstream-structured.json','loaded-database-census.json','parameters.ini','native-execution.json'],
        'limitations':['Simplified topology maps apply only to their source assumptions and mass/lifetime domain.',
            'Widths, branching fractions and all production cross sections are supplied physics, not recalculated predictions.',
            'Coverage groups overlap and use upstream lifetime reweighting at the largest available energy; their weights must not be added.',
            'Native coverage additionally removes each lifetime-reweighted SMS contribution at or below sigmacut, removes common ancestors and merges inclusive final states.',
            'Original cross-section records remain available; upstream may select highest orders, remove duplicates or omit unsupported particle/decay definitions.',
            'Contributions below the declared decomposition cut are omitted; missing expected limits cannot determine the selected answer.',
            'No global cross-analysis combination or full model exclusion outside the map domain is established.']}
    _write(out/'portfolio.json',result)
    (out/'PORTFOLIO.md').write_text('# Supplied-model portfolio\n\n' + json.dumps(report['conclusion'],indent=2) + '\n\n'
        + str(len(native['predictions'])) + ' retained predictions. Selection uses apriori expected sensitivity.\n\n'
        + ''.join('- '+g['label']+': '+str(g['total_xsec_fb'])+' fb at '+str(g['sqrts_tev'])+' TeV\n' for g in native['coverage'])
        + '\nCoverage groups overlap. Full signatures, source physics, all predictions and limitations are in portfolio.json and portfolio-native.json.\n')
    return result


def runtime_inventory(output):
    """Installed metadata/source census only; no database loading or calculation."""
    import importlib.metadata as metadata
    import sysconfig
    files, versions = set(), {}
    for dist in metadata.distributions():
        versions[dist.metadata['Name']] = dist.version
        for name in dist.files or []:
            path = Path(dist.locate_file(name))
            if path.is_file() and (path.suffix in ('.py','.so','.dylib','.ini','.json','.yaml','.yml') or path.name in ('METADATA','VERSION','version')):
                files.add(path.resolve())
    for path in Path(sysconfig.get_path('stdlib')).rglob('*'):
        if 'site-packages' in path.parts or '__pycache__' in path.parts:
            continue
        if path.is_file() and path.suffix in ('.py','.so','.dylib'):
            files.add(path.resolve())
    cli = Path(sys.executable).resolve().parent/'runSModelS.py'
    files.add(cli)
    _write(output,{'schema_version':1,'smodels_version':metadata.version('smodels'),
        'python_version':sys.version,'distributions':versions,'files':[_pin(p) for p in sorted(files)],
        'scope':'Installed Python/runtime source and distributed binary assets; host OS libraries are outside this finite capsule.'})


def prepare(args):
    """Normal supplied-model request -> automatic custody -> existing CHECK-IN 1."""
    if not args.trust_database_pickle:
        raise ValueError('the chosen native pickle must be explicitly trusted with --trust-database-pickle')
    rd = Path(args.rundir).expanduser().absolute()
    if rd.exists():
        raise ValueError('existing studies are resumed through ravel status/run --resume, never reinitialized')
    proposal = rd.with_name(rd.name+'-proposal')
    proposal.mkdir(parents=True,exist_ok=False)
    python = Path(args.python).expanduser().resolve(strict=True)
    capsule = proposal/'runtime-capsule.json'
    subprocess.run([str(python),str(Path(__file__).resolve()),'--runtime-inventory',str(capsule)],check=True,timeout=120)
    settings = deepcopy(SETTINGS)
    settings['analyses'] = args.analyses.split(',')
    settings['data_types'] = args.data_types
    settings['combine_srs'] = not args.no_combine_srs
    settings['sigmacut_fb'] = args.sigmacut_fb
    particle_model = {'kind':args.model,'file':_pin(args.model_file) if args.model_file else None}
    doc = {'schema_version':1,'source':args.source,
        'model_input':{'file':_pin(args.input),'format':args.format},
        'database':{'file':_pin(args.database),'version':'3.1.1',
            'source_url':args.database_source,'trusted_pickle':True},
        'runtime':{'python':_pin(python),'manifest':_pin(capsule),'smodels_version':'3.1.1'},
        'model':particle_model,'settings':settings,'max_seconds':args.max_seconds,'max_ram_mib':args.max_ram_mib}
    validate_document(doc)
    document = proposal/'model-portfolio.json';_write(document,doc)
    request = {'question':args.question,'model_source':args.source,
        'model_input':doc['model_input'],'requested_outputs':['expected-sensitive map-domain constraint',
            'all available per-analysis and per-region constraints','complete missing/outside-grid topology and lifetime report'],
        'scientific_boundary':'Supplied spectrum/production/decays interpreted within source database map assumptions.'}
    _write(proposal/'request.json',request)
    review_policy = _read(args.review_policy)
    specification = {'schema_version':2,'mode':'model-portfolio','source':args.source,
        'assumptions':['Complete supplied spectrum, widths, branching fractions and production cross sections are accepted as source physics.',
            'Apriori expected sensitivity chooses the reported constraint; no cross-analysis combination is assumed.',
            'Only the pinned topology/mass/lifetime map domain is interpreted; uncovered contributions remain visible.'],
        'max_seconds':args.max_seconds+240,'approval_mode':args.approval_mode,
        'max_attempts':1 + review_policy['policy']['max_redos'], 'review_policy':review_policy,
        'task':{'input':str(document)}}
    spec_path=proposal/'science.json';_write(spec_path,specification)
    from ravel.workflow.science import plan
    plan(rd,spec_path)
    print('Prepared source-complete model portfolio. Review '+str(rd/'CHECKIN1.md')+' and use ravel approve/run.')
    return 0


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == 'plan':
        ap=argparse.ArgumentParser(prog='ravel model-portfolio plan',description='Plan a complete supplied SLHA/LHE interpretation and coverage report; no physics computation.')
        ap.add_argument('--input',required=True);ap.add_argument('--source',required=True)
        ap.add_argument('--question',default='Which published simplified-model maps constrain this complete supplied model, which expected-sensitive result determines the answer, and what is uncovered?')
        ap.add_argument('--python',required=True,help='qualified native SModelS 3.1.1 Python executable')
        ap.add_argument('--database',required=True,help='exact local database pickle, never a download shorthand')
        ap.add_argument('--database-source',required=True,help='trusted original upstream HTTPS source URL')
        ap.add_argument('--trust-database-pickle',action='store_true')
        ap.add_argument('--rundir',required=True);ap.add_argument('--format',choices=('slha','lhe'),default='slha')
        ap.add_argument('--model',choices=('mssm','qnumbers','python'),default='mssm');ap.add_argument('--model-file')
        ap.add_argument('--analyses',default='all');ap.add_argument('--data-types',choices=('all','efficiencyMap','upperLimit'),default='all')
        ap.add_argument('--no-combine-srs',action='store_true');ap.add_argument('--sigmacut-fb',type=float,default=.005)
        ap.add_argument('--max-seconds',type=int,default=900);ap.add_argument('--max-ram-mib',type=int,default=8192)
        ap.add_argument('--approval-mode',choices=('physicist','scripted_yes'),default='physicist',
            help='scripted_yes requires actual prior authorization and records no expert review')
        ap.add_argument('--review-policy',required=True,
            help='prospective version 2 review-policy wrapper with actual separated actor identities')
        return prepare(ap.parse_args(arguments[1:]))
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--native-worker',help=argparse.SUPPRESS)
    ap.add_argument('--runtime-inventory',help=argparse.SUPPRESS)
    ap.add_argument('--out')
    args=ap.parse_args(arguments)
    if args.runtime_inventory:
        runtime_inventory(args.runtime_inventory);return 0
    if not args.native_worker:
        ap.error('Use ravel model-portfolio plan with the supplied model, runtime and exact local database')
    if not args.out:
        ap.error('--out required for native worker')
    native_worker(args.native_worker,args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
