"""Small shared boundaries for explicitly supplied source contracts."""
import json
import os
from pathlib import Path
import tempfile


class MissingInputError(ValueError):
    reason = 'missing-input'

    def __init__(self, field, detail='Explicit supplied input required'):
        self.field = field
        super().__init__(f'{self.reason}: {field}: {detail}')


def fields(document, required):
    if type(document) is not dict:
        raise ValueError('supplied contract must be an object')
    for field in required:
        if field not in document or document[field] is None:
            raise MissingInputError(field)


def output_contract(document):
    fields(document, ('filename', 'format'))
    if set(document) != {'filename', 'format'}:
        raise ValueError('closed output filename and format required')
    name = document['filename']
    if (type(name) is not str or not name or name in ('.', '..')
            or Path(name).name != name or any(c in name for c in '\\\x00\n\r')):
        raise ValueError('safe output basename required')
    if document['format'] not in ('json', 'json-compact'):
        raise ValueError('supported JSON output representation required')
    return document


def encode(value, contract):
    output_contract(contract)
    options = {'indent': 2} if contract['format'] == 'json' else {'separators': (',', ':')}
    return (json.dumps(value, allow_nan=False, **options) + '\n').encode()


def publish(root, value, contract):
    """Check intended bytes after writing; never accept writer changes as a baseline."""
    raw = encode(value, contract)
    path = Path(root) / contract['filename']
    if path.exists() or path.is_symlink():
        raise ValueError('fresh output file required')
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink()
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if path.read_bytes() != raw:
        raise ValueError('supplied output differs from intended bytes')
    return path
