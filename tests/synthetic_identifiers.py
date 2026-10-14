"""Identifier-shaped inputs for tests of readers, parsers and routers.

A reader that recognises a literature number or an analysis code needs an input of that shape, and
no test may name a real publication, analysis or routine. Each value here is therefore synthetic and
is assembled at run time, so no test file carries an identifier as text:

- ``arxiv(n)``: a literature number whose year-month field is zero, which no real number has;
- ``analysis(n)``: an analysis-code-shaped label with the group ``ANA`` and a number above 9000.

A data file writes ``{{arxiv:n}}``, ``{{analysis:n}}`` or ``{{analysis:n:m}}`` and is read through
``expand``. A test that needs only a name for a routine or a package uses a plainly fictional one.
These values stand for no source: product data, documents and code cite real sources or none (the
generality gate refuses these shapes in every file).
"""
import json
import re

_FIELD = re.compile(r'\{\{(arxiv|analysis):(\d+)(?::(\d+))?\}\}')


def arxiv(number):
    """A literature number of the synthetic form: four zeros, a dot and five digits."""
    return '0' * 4 + '.' + format(number, '05d')


def analysis(number, serial=1):
    """An analysis-code-shaped label of the synthetic group."""
    return '-'.join(['ANA', str(9000 + number), format(serial, '02d')])


def expand(text):
    """``text`` with every ``{{kind:n}}`` field replaced by its synthetic identifier."""
    def value(match):
        kind, number, serial = match.group(1), int(match.group(2)), match.group(3)
        if kind == 'arxiv':
            return arxiv(number)
        return analysis(number, int(serial) if serial else 1)
    return _FIELD.sub(value, text)


def load_json(path):
    """A JSON data file with its synthetic-identifier fields expanded."""
    return json.loads(expand(path.read_text(encoding='utf-8')))
