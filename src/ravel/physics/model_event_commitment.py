"""Prospective complete Events custody; no execution or retrospective admission."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat


def _require(value, message):
    if not value: raise ValueError(message)


def _identity(st):
    return [st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def _directory(path):
    _require(path.is_absolute() and '..' not in path.parts, 'canonical recorded generated root required')
    rows = []
    for part in (*reversed(path.parents), path):
        st = part.lstat()
        _require(stat.S_ISDIR(st.st_mode), 'ordinary generated directory ancestors required')
        rows.append({'path': str(part), 'identity': [st.st_dev, st.st_ino, st.st_mode]})
    return rows


def _file(path):
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_size <= 16 * 1024**3,
             'bounded ordinary generated member required')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        _require(_identity(os.fstat(descriptor)) == _identity(before), 'generated member replaced before open')
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024**2)
            if not block: break
            digest.update(block)
        _require(_identity(os.fstat(descriptor)) == _identity(before) == _identity(path.lstat()),
                 'generated member changed during read')
        return {'path': str(path), 'sha256': digest.hexdigest(), 'size': before.st_size,
                'identity': _identity(before)}
    finally:
        os.close(descriptor)


def _structure(root):
    ancestors=_directory(root);files=[];directories=[];pending=[root];count=0
    while pending:
        directory=pending.pop()
        for path in sorted(directory.iterdir()):
            count+=1
            _require(count<=100000,'complete generated census exceeds bounded population')
            st=path.lstat()
            if stat.S_ISDIR(st.st_mode):
                directories.append({'path':str(path),'ancestors':_directory(path)})
                pending.append(path)
            else:
                _require(stat.S_ISREG(st.st_mode),'ordinary generated member required')
                files.append({'path':str(path),'identity':_identity(st)})
    _require(ancestors==_directory(root),'generated root identity changed')
    return ancestors,sorted(directories,key=lambda x:x['path']),sorted(files,key=lambda x:x['path'])


def snapshot(process):
    """Commit whole membership before AND after hashing every ordinary file."""
    process=Path(process)
    _require(process.is_absolute() and '..' not in process.parts,'canonical original native process required')
    root=process/'Events'
    structure=_structure(root);ancestors,directories,members=structure;files=[]
    for row in members:
        observed=_file(Path(row['path']))
        _require(observed['identity']==row['identity'],'generated member changed after complete census')
        files.append(observed)
    _require(_structure(root)==structure,'complete generated membership/directory identity changed during capture')
    return {'schema_version':1,'kind':'generated-events-commitment/v1',
            'process':str(process),'root':str(root),'ancestors':ancestors,
            'directories':directories,'files':files}


def verify(commitment, process):
    _require(type(commitment) is dict and commitment.get('schema_version') == 1 and
             commitment.get('kind') == 'generated-events-commitment/v1',
             'prospective generated member commitment missing; old records are not qualified')
    _require(snapshot(process) == commitment, 'complete generated Events identity/content/membership changed')
    return commitment


def member(commitment, request, result, census, relative, capture):
    """Select only an existing recorded member under the original native process."""
    name = PurePosixPath(relative)
    _require(type(relative) is str and relative and not name.is_absolute() and
             '..' not in name.parts and str(name) == relative and name.parts[0] == 'Events',
             'canonical Events-relative recorded member required')
    _require(result.get('status') == 'passed' and result.get('generated_member_commitment') == commitment and
             result.get('intended') == request['config'], 'original producer config/result commitment differs')
    verify(commitment, request['process'])
    pins = [{k: row[k] for k in ('path', 'sha256', 'size')} for row in commitment['files']]
    _require(census == {'files': pins} and result.get('generated_artifacts') == pins,
             'complete original producer census/result differ')
    path = Path(request['process']) / name
    rows = [row for row in commitment['files'] if row['path'] == str(path)]
    _require(len(rows) == 1 and rows[0]['size'] > 0, 'member absent/duplicate/empty in original producer commitment')
    for row in commitment['files']:
        capture.stream_pin({k: row[k] for k in ('path', 'sha256')}, Path(request['process']), allow_empty=True)
    pin = {k: rows[0][k] for k in ('path', 'sha256')}
    capture.finish()
    verify(commitment, request['process'])
    return pin


def finalize(result, output):
    """New producer ending boundary after the ordinary result/report writer."""
    from .ma5_saf import Capture, _json
    output=Path(output);capture=Capture()
    def document(name):
        _,raw=capture.read(str(output/name),output)
        return _json(raw)
    request=document('native-input.json');native=document('model-events-native.json')
    commitment=document('generated-member-commitment.json');census=document('generated-artifact-census.json')
    delivered=document('model-events.json');ordinary=document('result.json')
    _require(result==delivered==ordinary and all(delivered.get(k)==v for k,v in native.items()) and
             native.get('intended')==request['config'] and
             native.get('generated_member_commitment')==commitment,
             'complete published ordinary/native generation records differ')
    pins=[{k:row[k] for k in ('path','sha256','size')} for row in commitment['files']]
    _require(census=={'files':pins} and native.get('generated_artifacts')==pins,
             'complete ending generated census differs')
    if result.get('generator_reuse') is not None:
        from .generator_reuse import ending
        ending(result,output)
    verify(commitment,request['process']);capture.finish()
    verify(commitment,request['process'])
    if result.get('generator_reuse') is not None:ending(result,output)
    return commitment
