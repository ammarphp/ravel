"""Pythia 8 shower stage for scoped generation.

The host side launches this file under the declared Python that provides the
pythia8 bindings. The child uses only the standard library, pythia8 and the
sibling final_state_observables module, so it runs without RAVEL installed.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

RESERVED = re.compile(r'^\s*(Beams|Random|Main|Next|Init):', re.I)
SETTING = re.compile(r'^[A-Za-z][A-Za-z0-9:_]*\s*=\s*[A-Za-z0-9_.+\-]+$')


def check(shower):
    """Errors for a shower declaration (engine, python, seed, settings)."""
    if not isinstance(shower, dict) or set(shower) != {'engine', 'python', 'seed', 'settings'}:
        return ['shower requires exactly engine, python, seed and settings']
    errors = []
    if shower['engine'] != 'pythia8':
        errors.append('the supported shower engine is pythia8')
    if not isinstance(shower['python'], str) or not shower['python']:
        errors.append('shower python must name the interpreter with pythia8 bindings')
    if type(shower['seed']) is not int or not 1 <= shower['seed'] <= 900000000:
        errors.append('shower seed must be an integer from 1 to 900000000')
    settings = shower['settings']
    if not isinstance(settings, list) or len(settings) > 64:
        errors.append('shower settings must be a list of at most 64 Key = value strings')
    else:
        for line in settings:
            if not isinstance(line, str) or not SETTING.match(line) or RESERVED.match(line):
                errors.append('invalid or reserved shower setting: %r' % (line,))
    return errors


def probe(python):
    """Locate the pythia8 binding files under the declared interpreter (no shower)."""
    code = 'import pythia8,sys;print(pythia8.__file__)'
    done = subprocess.run([str(python), '-I', '-B', '-c', code], capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise ValueError('the declared shower python cannot import pythia8: ' + done.stderr.strip()[-300:])
    module = Path(done.stdout.strip().splitlines()[-1]).resolve()
    files = [module] + sorted(p.resolve() for p in module.parent.glob('_pythia8*') if p.is_file())
    return files


def run_shower(lhe_path, shower, observables, out_dir):
    """Shower a plain-text LHE file and evaluate particle-level observables."""
    errors = check(shower)
    if errors:
        raise ValueError('; '.join(errors))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    from ravel.validation.lhe_check import check_science
    check_science(lhe_path, output=out / 'shower-input.lhe_check.json')
    request = out / 'shower-request.json'
    request.write_text(json.dumps({'lhe': str(Path(lhe_path).absolute()), 'seed': shower['seed'],
                                   'settings': shower['settings'], 'observables': observables,
                                   'output': str(out / 'shower-result.json')}))
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'TMPDIR', 'LANG')}
    env.update(OMP_NUM_THREADS='1')
    with (out / 'shower.log').open('w') as log:
        done = subprocess.run([shower['python'], '-I', '-B', str(Path(__file__).resolve()), str(request)],
                              stdout=log, stderr=subprocess.STDOUT, env=env)
    if done.returncode:
        raise ValueError('Pythia shower failed (%d); inspect %s' % (done.returncode, out / 'shower.log'))
    return json.loads((out / 'shower-result.json').read_text())


def main(path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import final_state_observables as fso
    import pythia8
    request = json.loads(Path(path).read_text())
    pythia = pythia8.Pythia('', False)
    for line in ['Beams:frameType = 4', 'Beams:LHEF = ' + request['lhe'], 'Random:setSeed = on',
                 'Random:seed = %d' % request['seed'], 'Next:numberCount = 0'] + request['settings']:
        if not pythia.readString(line):
            raise ValueError('Pythia rejected setting: ' + line)
    if not pythia.init():
        raise ValueError('Pythia initialization failed')
    # Pythia 8.2 bindings expose pythia.info; 8.3 bindings return a fresh
    # snapshot from infoPython(), so read it again after every event.
    def info():
        return pythia.infoPython() if hasattr(pythia, 'infoPython') else pythia.info
    values = {row['id']: [] for row in request['observables']}
    read = showered = failed = 0
    while True:
        ok = pythia.next()
        if not ok:
            if info().atEndOfFile():
                break
            read += 1
            failed += 1
            if failed > 100:
                raise ValueError('more than 100 failed shower events')
            continue
        read += 1
        showered += 1
        event = pythia.event
        final = []
        for i in range(event.size()):
            p = event[i]
            if p.isFinal():
                final.append((p.id(), p.px(), p.py(), p.pz(), p.e()))
        for key, vals in fso.evaluate(final, request['observables']).items():
            values[key].extend(vals)
    version = pythia.parm('Pythia:versionNumber')
    result = {'engine': 'pythia8', 'version': version, 'events_read': read, 'events_showered': showered,
              'events_failed': failed, 'seed': request['seed'], 'settings': request['settings'],
              'observables': values, 'sigma_generated_mb': info().sigmaGen()}
    Path(request['output']).write_text(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
