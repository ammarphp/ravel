"""Declared output contracts: the paths a request names for its deliverables and what they may hold.

A request can say where its deliverables go ("write the answer to `out/answer.yaml`"), in which
format, with which top-level keys or columns, and that a location must hold nothing else. Intake
records each such declaration as a task obligation bound to exact spans of the request; the final
whole-task check observes the delivered files against those obligations and reports every
violation before delivery.

The reader is deterministic and conservative. A path is a declared deliverable only when an
output verb or an output noun links it to the request's own result. A path the request reads
from, forbids or merely mentions declares nothing, and a statement the reader does not recognise
declares nothing rather than a guess. Relative paths are relative to the workspace in which the
request was received; intake binds that workspace and, for a "create nothing else" rule, the
entries already present in the governed location.

The checker only observes. It never creates, moves or deletes a file, never follows a symbolic
link at a declared path or inside a governed location, and grants no acceptance or execution
authority. A satisfied check is mechanical conformance, not a judgment of scientific content.
"""
from copy import deepcopy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import stat

SCHEMA_VERSION = 1
KIND = 'output-contract'
CHECK_KIND = 'output-contract-check'
CRITERIA_KEY = 'output_contract'
ID_PREFIX = 'output-contract-'
ANCHORS = ('absolute', 'home', 'workspace')
EXCLUSIVE = ('only', 'no_new')
MAX_ITEMS = 32
MAX_PARSE_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 10_000
MAX_DEPTH = 32
MAX_BASELINE_BYTES = 6_000
MAX_CRITERIA_BYTES = 16_000
MAX_REPORTED = 50
# How far before a path its cue, link, negation or location lead is read. Phrasing that places
# a path sits within a few words of it; the bound keeps an unbroken pasted line linear to read.
LOOKBACK = 1000

FORMATS = {'yaml': 'YAML', 'json': 'JSON', 'csv': 'CSV', 'tsv': 'TSV', 'toml': 'TOML', 'text': 'UTF-8 text',
           'pdf': 'PDF', 'png': 'PNG', 'jpeg': 'JPEG', 'svg': 'SVG'}
_EXTENSIONS = {'yaml': 'yaml', 'yml': 'yaml', 'json': 'json', 'csv': 'csv', 'tsv': 'tsv', 'toml': 'toml',
               'txt': 'text', 'text': 'text', 'md': 'text', 'markdown': 'text', 'pdf': 'pdf', 'png': 'png',
               'jpg': 'jpeg', 'jpeg': 'jpeg', 'svg': 'svg'}
# Extensions that make a bare name (no directory part) a file. A dotted code identifier
# ("np.float64", "json.loads") or an abbreviation ("a.u.") names no deliverable.
_FILE_TYPES = frozenset(_EXTENSIONS) | frozenset((
    'gz bz2 xz zst zip tar tgz lhe hepmc hepmc2 hepmc3 root yoda slha lha dat cmnd h5 hdf5 npz npy parquet '
    'feather arrow pkl pickle onnx pt pth ckpt nc fits jsonl ndjson xml ini cfg conf log tex bib rst html htm '
    'docx odt rtf xlsx eps ps gif tif tiff bmp webp py ipynb c cc cpp cxx h hh hpp f f77 f90 inc jl sh wl wls nb so').split())
_MAPPING_FORMATS = ('yaml', 'json', 'toml')
_TABLE_FORMATS = ('csv', 'tsv')
_MAGIC = {'pdf': b'%PDF-', 'png': b'\x89PNG\r\n\x1a\n', 'jpeg': b'\xff\xd8\xff'}

# ------------------------------------------------------------------ lexical pieces of a request
_FENCE = re.compile(r'```[^\n]*\n(.*?)```', re.S)
_QUOTE_LINE = re.compile(r'^[ \t]*>.*$', re.M)
_BREAK = re.compile(r'[;!?\n]|\.(?=\s|$)')
_TOKEN = re.compile(r'`(?P<b>[^`\s]{1,512})`|"(?P<d>[^"\s]{1,512})"|“(?P<c>[^”\s]{1,512})”|'
                    r"(?<![\w])'(?P<s>[^'\s]{1,512})'(?![\w])|"
                    r'(?P<w>(?<![\w/.~:@-])(?:~/|\.{1,2}/|/)?[\w+-][\w.+-]*(?:/[\w.+-]+)*/?)')
_EXTENSION = re.compile(r'(?<=[^./])\.([A-Za-z][A-Za-z0-9]{0,7})$')
_ABBREVIATIONS = {'e.g', 'i.e', 'etc', 'vs', 'cf', 'c.f', 's.f', 'et.al', 'a.k.a', 'n.b', 'w.r.t', 'approx', 'resp'}
_DIRECTORY_NOUN = r'(?:directory|directories|folder|folders|dir|subdirectory)'
_LOCATION_NOUN = re.compile(r'\b(?:directory|directories|folder|folders|dir|subdirectory|location|workspace)\b', re.I)
# Output cues: verbs that place a result, and result nouns followed by a modal or copula.
_OUTPUT_VERBS = (r'write|writes|writing|written|wrote|save|saves|saving|saved|store|stores|storing|stored|put|puts|'
                 r'putting|place|places|placing|placed|deliver|delivers|delivering|delivered|submit|submits|'
                 r'submitting|submitted|output|outputs|produce|produces|producing|produced|create|creates|creating|'
                 r'created|generate|generates|generating|generated|export|exports|exporting|exported|emit|emits|'
                 r'emitting|emitted|dump|dumps|dumped|record|records|recording|upload|uploads|uploading|uploaded|'
                 r'provide|return|report')
_INPUT_VERBS = (r'read|reads|reading|load|loads|loading|loaded|use|uses|using|used|open|opens|opening|parse|parses|'
                r'parsing|consult|consults|consulting|import|imports|importing|download|downloads|downloading|fetch|'
                r'fetches|fetching|copy|copies|copying|given|supplied|provided|attached|located|found|available|'
                r'see|refer|compare|compares|comparing|run|runs|running|execute|executes|executing|modify|modifies|'
                r'modifying|edit|edits|editing|inspect|inspects|inspecting|follow|follows|following|consider|'
                r'considering|keep|leave|preserve|ignore|match|matches|matching|agree|agrees|reproduce|reproduces|'
                r'reproducing|cite|cites|described|defined|shown|listed|published|taken|derived|obtained|quoted|'
                r'reported|like')
_OUTPUT_NOUN = (r'(?:answers?|results?|outputs?|deliverables?|submissions?|predictions?|responses?)'
                r'(?:\s+(?:files?|directory|directories|folder|folders|dir|path|location))?'
                r'\s*(?::|\b(?:must|should|shall|will|can|is|are|goes|go|belongs?|needs?|has\s+to|have\s+to)\b)')
_CUE = re.compile(r'\b(?P<noun>' + _OUTPUT_NOUN + r')|\b(?P<out>' + _OUTPUT_VERBS + r')\b|\b(?P<in>' + _INPUT_VERBS
                  + r')\b', re.I)
_FILLER = (r'(?:the|a|an|this|that|your|our|its|their|one|single|new|separate|final|output|outputs|result|results|'
           r'answer|answers|file|files|directory|folder|dir|path|location|exactly|only|just|yaml|json|csv|tsv|toml|'
           r'text|plain|markdown|pdf|png|it|them|all|everything|be|go|written|saved|stored|placed|put|located|'
           r'delivered|submitted|out|down|back|named|called|same|current|working|following)')
_LINK = r'(?:to|into|in|at|as|under|inside|within|onto|named|called|:)'
_DIRECT = re.compile(r'^[\s,:]*(?:' + _FILLER + r'[\s,]+){0,6}[`"\'“]?$', re.I)
_LINKED = re.compile(r'(?P<link>\b(?:to|into|in|at|as|under|inside|within|onto|named|called)\b|:)[\s,]*(?:' + _FILLER
                     + r'[\s,]+){0,5}[`"\'“]?$', re.I)
_PLACE_LINK = ('in', 'at', 'under', 'inside', 'within')
_CONTRAST = re.compile(r'\b(?:not|never|nor|but|except|instead|rather|or)\b', re.I)
_NEGATION = re.compile(r"\b(?:do\s+not|don['’]t|never|must\s+not|should\s+not|shall\s+not|may\s+not|cannot|"
                       r"can['’]t|avoid|no\s+need\s+to|not)\b", re.I)
_NOT_NEGATION = re.compile(r"\b(?:do\s+not|don['’]t|never)\s+forget\b|\bnot\s+only\b", re.I)
_UNNAMED_LOCATION = re.compile(r'\b(?:in|into|inside|under|within|to)\s+(?:the|a|an|your|our|its|their|this|that)\s+'
                               r'(?!(?:current|working|present|top-level|root|same)\b)(?:[\w-]+\s+){0,2}'
                               r'(?:folder|directory|dir|subdirectory|location|repository|repo|bucket)\b', re.I)
# Exclusivity of a location: "must contain only", or "create nothing else".
_NEG = r"(?:do\s+not|don['’]t|never|must\s+not|should\s+not|shall\s+not|may\s+not|cannot|can['’]t)"
_ACTION = (r'(?:write|writes|written|create|creates|created|save|saved|put|place|placed|leave|left|add|added|'
           r'produce|produced|generate|generated|store|stored|output|emit|emitted|deliver|delivered|submit|'
           r'submitted|make|made|drop|dump)')
_OTHER = r'(?:any|other|additional|extra|further|more|auxiliary|intermediate|temporary|scratch|helper)'
_ITEMS = r'(?:files?|outputs?|artifacts?|artefacts?|documents?|entries|sidecars?|copies|logs?)'
_NO_NEW_FILES = re.compile(
    r'\b' + _NEG + r'\b[^.;\n]{0,40}?\b' + _ACTION + r'\b[^.;\n]{0,40}?\b' + _OTHER + r'\b[^.;\n]{0,25}?\b' + _ITEMS
    + r'\b|\bno\s+(?:other|additional|extra|further|more)\s+' + _ITEMS + r'\b[^.;\n]{0,40}?\b' + _ACTION + r'\b|'
    r'\b' + _ACTION + r'\b[^.;\n]{0,40}?\b(?:exactly|only)\s+one\s+(?:[\w-]+\s+)?(?:file|output)\b'
    r'(?!\s+(?:per|for\s+each|for\s+every|each)\b)|'
    r'\b(?:only\s+' + _ACTION + r'|' + _ACTION + r'\s+only)\s+(?:the\s+)?(?:file\s+)?[`"\'“]?'
    r'(?=[\w./~+-]*\.[A-Za-z][A-Za-z0-9]{0,7}\b)', re.I)
_NO_NEW_ANYTHING = re.compile(
    r'\b' + _NEG + r'\b[^.;\n]{0,40}?\b' + _ACTION + r'\b[^.;\n]{0,20}?\b(?:anything|nothing)\s+(?:else|more)\b|'
    r'\b' + _ACTION + r'\b[^.;\n]{0,80}?\b(?:and|but)\s+nothing\s+(?:else|more)\b', re.I)
_ONLY = re.compile(
    r'\b(?:contain|contains|containing|hold|holds|holding|include|includes|including|have|has|having)\s+'
    r'(?:only|exactly|nothing\s+(?:but|except|other\s+than))\b(?!\s+(?:the\s+)?(?:[\w-]+\s+)?'
    r'(?:keys?|fields?|columns?|properties|values|rows|lines))|'
    r'\bthe\s+only\s+(?:file|entry|thing|output|content|item)s?\b|'
    r'\bonly\s+(?:files?|entr(?:y|ies)|things?|contents?|outputs?|items?)\s+(?:in|inside|within|under)\b|'
    r'\bnothing\s+else\s+(?:in|inside|within|under)\b|'
    r'\bnothing\s+else\s+(?:may|must|should|can|will|shall)\s+(?:be\s+)?(?:in|inside|within|under|there|present|exist)',
    re.I)
_ALLOWED_LEAD = re.compile(r'(?:\b(?:only|except|besides|but|than|from|exactly|just)|apart\s+from|aside\s+from|'
                           r'other\s+than|:|,|\band)\s+(?:the\s+)?(?:file\s+|files\s+)?[`"\'“]?$', re.I)
_LOCATION_LEAD = re.compile(r'\b(?:in|inside|into|within|under|to|of)\s+(?:the\s+)?[`"\'“]?$', re.I)
_LOCATION_TAIL = re.compile(r'^[`"\'”]?\s*(?:' + _DIRECTORY_NOUN + r'\s*)?(?:must|should|shall|may|can|will|is|has|'
                            r'needs?)\b', re.I)
# Declared keys or columns of a single deliverable.
_KEYS = re.compile(r'\b(?:with|containing|contain|contains|include|includes|including|having|has|have|holds?|'
                   r'carry|carries|carrying|lists?|listing)\s+(?P<closed>(?:only|exactly|just)\s+)?(?:the\s+)?'
                   r'(?:(?:following|top-level|top\s+level)\s+)?(?P<noun>keys?|fields?|columns?|propert(?:y|ies))'
                   r'\b\s*(?::|named|called)?\s*', re.I)
_KEY_NOUN = re.compile(r'\b(?P<noun>keys?|fields?|columns?|propert(?:y|ies))\s+(?::\s*)?(?=[`"“\'])', re.I)
_KEY_ITEM = re.compile(r'\s*(?:`(?P<b>[^`\n]{1,128})`|"(?P<d>[^"\n]{1,128})"|“(?P<c>[^”\n]{1,128})”|'
                       r"'(?P<s>[^'\n]{1,128})'|(?P<w>[A-Za-z_][A-Za-z0-9_.-]{0,127}))")
_KEY_SEPARATOR = re.compile(r'\s*,\s*(?:and\s+|&\s+)?|\s+and\s+|\s*&\s*')
_KEY_STOPWORDS = {'the', 'a', 'an', 'following', 'below', 'above', 'described', 'listed', 'given', 'shown', 'as',
                  'each', 'every', 'all', 'any', 'some', 'other', 'these', 'those', 'this', 'that', 'for', 'in',
                  'to', 'of', 'with', 'and', 'or', 'named', 'called', 'which', 'where', 'per', 'only', 'nothing',
                  'no', 'its', 'their', 'your', 'from', 'at', 'on', 'by', 'into', 'then'}
_CLOSED_KEYS = re.compile(r'\bno\s+(?:other|additional|extra|further|more)\s+(?:keys|fields|columns|properties)\b|'
                          r'\bnothing\s+else\b', re.I)
_STATED_FORMAT = re.compile(r'\b(?:in|as|using)\s+(?:a\s+|an\s+)?(?P<f>YAML|JSON|CSV|TSV|TOML|plain[- ]text|'
                            r'Markdown|PDF|PNG)\b', re.I)
_TEMPLATE_CUE = re.compile(r'\b(?:format|structure|schema|template|layout|example|following|like\s+this|'
                           r'as\s+follows)\b', re.I)
_TEMPLATE_INFO = re.compile(r'```[ \t]*(?P<info>[A-Za-z]*)')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _span(prompt, start, end):
    while start < end and prompt[start].isspace():
        start += 1
    while end > start and prompt[end - 1].isspace():
        end -= 1
    return {'start': start, 'end': end, 'text': prompt[start:end]}


def _masked(prompt):
    """The request with fenced code and quoted lines blanked, offsets preserved."""
    chars = list(prompt)
    for pattern in (re.compile(r'```.*?(?:```|$)', re.S), _QUOTE_LINE):
        for m in pattern.finditer(prompt):
            for i in range(m.start(), m.end()):
                if chars[i] != '\n':
                    chars[i] = ' '
    return ''.join(chars)


def _back(start, position):
    """Start of the bounded look-back before `position` within a sentence beginning at `start`."""
    return max(start, position - LOOKBACK)


def _sentences(text):
    start = 0
    for m in _BREAK.finditer(text):
        if text[start:m.start()].strip():
            yield start, m.start()
        start = m.end()
    if text[start:].strip():
        yield start, len(text)


# ------------------------------------------------------------------ path tokens
def _classify(raw, quoted):
    """(token, shape) of a path-like token; shape is file, dir, path, slashed or word."""
    token = raw if quoted else raw.rstrip('.,:;!?)')
    if (not token or len(token) > 512 or '://' in token or token.startswith('//') or '@' in token
            or '\\' in token or token.lower().rstrip('.') in _ABBREVIATIONS):
        return None
    name = posixpath.basename(token.rstrip('/'))
    if not name or name in ('.', '..'):
        return None
    if token.endswith('/'):
        return token, 'dir'
    extension = _EXTENSION.search(name)
    if extension and ('/' in token or extension.group(1).lower() in _FILE_TYPES):
        return token, 'file'
    if token.startswith(('/', './', '../', '~/')) or token.count('/') >= 2:
        return token, 'path'
    if '/' in token:
        return token, 'slashed'
    return (token, 'word') if quoted else None


class _Token:
    __slots__ = ('start', 'end', 'text', 'shape')

    def __init__(self, start, end, text, shape):
        self.start, self.end, self.text, self.shape = start, end, text, shape


def _tokens(masked, start, end):
    """Path-like tokens of one sentence, with directory/file nouns applied."""
    rows = []
    for m in _TOKEN.finditer(masked, start, end):
        group = next(g for g in ('b', 'd', 'c', 's', 'w') if m.group(g) is not None)
        classified = _classify(m.group(group), group != 'w')
        if classified is None:
            continue
        text, shape = classified
        left = m.start(group)
        right = left + len(text)
        before = masked[max(start, left - 24):left]
        after = masked[right:min(end, right + 24)]
        if shape in ('path', 'slashed', 'word') and (
                re.search(r'\b' + _DIRECTORY_NOUN + r'\s+(?:named\s+|called\s+)?[`"\'“]?$', before, re.I)
                or re.match(r'^[`"\'”]?\s*' + _DIRECTORY_NOUN + r'\b', after, re.I)):
            shape = 'dir'
        elif shape in ('path', 'word') and re.search(r'\bfile\s+(?:named\s+|called\s+)?[`"\'“]?$', before, re.I):
            shape = 'file'
        rows.append(_Token(left, right, text, shape))
    return rows


def _normal(token):
    """(anchor, normalised path) of a declared token; home paths stay home-relative."""
    if token.startswith('~/'):
        anchor, path = 'home', token[2:]
    elif token.startswith('/'):
        anchor, path = 'absolute', token
    else:
        anchor, path = 'workspace', token
    path = posixpath.normpath(path)
    if anchor != 'absolute' and (path.startswith('/') or path == '.'):
        return None
    return anchor, path


def _parent(anchor, path):
    parent = posixpath.dirname(path)
    if anchor == 'absolute':
        return parent or '/'
    return parent or '.'


def _within(location, path):
    """Path of `path` relative to `location`, or None when it lies outside."""
    if location == '.':
        return None if path == '..' or path.startswith('../') else path
    if location == '/':
        return path[1:] if path.startswith('/') and path != '/' else None
    prefix = location.rstrip('/') + '/'
    return path[len(prefix):] if path.startswith(prefix) and len(path) > len(prefix) else None


# ------------------------------------------------------------------ the reader
_PARTICIPLES = {'written', 'wrote', 'saved', 'stored', 'placed', 'delivered', 'submitted', 'produced', 'created',
                'generated', 'exported', 'emitted', 'dumped', 'uploaded'}
_PASSIVE = re.compile(r'\b(?:be|been|being|is|are|was|were|get|gets|got)\s+(?:[\w-]+\s+)?$', re.I)


class _Cue:
    __slots__ = ('start', 'end', 'output')

    def __init__(self, start, end, output):
        self.start, self.end, self.output = start, end, output


def _last_cue(masked, start, end):
    """The last output or input cue in a span. A participle places a result only in the passive
    ("must be written to"); used as an adjective ("the events stored in") it names existing material."""
    last = None
    for m in _CUE.finditer(masked, start, end):
        output = m.group('in') is None
        if output and m.group('out') and m.group('out').lower() in _PARTICIPLES:
            output = bool(_PASSIVE.search(masked[max(start, m.start() - 24):m.start()]))
        last = _Cue(m.start(), m.end(), output)
    return last


def _negated(masked, start, position):
    """Whether the clause before `position` negates its action (e.g. "do not write to ...").

    A clause that runs unbroken past the look-back is treated as negated: its beginning is
    not read, so it declares nothing rather than a guess.
    """
    back = _back(start, position)
    clause = masked[back:position]
    for mark in (',', ':', ' and ', ' then '):
        clause = clause[clause.rfind(mark) + 1:] if mark in clause else clause
    if back > start and len(clause) == position - back:
        return True
    return bool(_NEGATION.search(clause)) and not _NOT_NEGATION.search(clause)


def _declared(masked, start, token):
    """A token is declared when an output cue places the request's result at it."""
    back = _back(start, token.start)
    cue = _last_cue(masked, back, token.start)
    if cue is not None and cue.output and _DIRECT.match(masked[cue.end:token.start]):
        return not _negated(masked, start, cue.start)  # "write out.json", "final answer: a.yaml"
    linked = _LINKED.search(masked, back, token.start)
    if not linked:
        return False
    link = linked.start()
    cue = _last_cue(masked, back, link)
    if cue is None or not cue.output or link - cue.end > 120:
        return False
    gap = masked[cue.end:link]
    if re.search(r'\b(?:not|never)\b', gap, re.I):
        return False
    if linked.group('link').lower() in _PLACE_LINK and re.search(r'\bfrom\b', gap, re.I):
        return False  # "from data in X": the place belongs to the source, not to the result
    return not _negated(masked, start, cue.start)


def _keys_after(masked, prompt, position, end):
    """An exact key list starting at `position`: (names, end) or None."""
    names, cursor, bare = [], position, True
    while True:
        m = _KEY_ITEM.match(masked, cursor, end)
        if not m:
            break
        group = next(g for g in ('b', 'd', 'c', 's', 'w') if m.group(g) is not None)
        name = prompt[m.start(group):m.end(group)]
        if group == 'w' and name.lower() in _KEY_STOPWORDS:
            break
        bare = bare and group == 'w'
        names.append(name)
        cursor = m.end()
        if re.match(r'\s*,?\s*or\b', masked[cursor:end], re.I):
            return None  # alternatives are not a declared key set
        separator = _KEY_SEPARATOR.match(masked, cursor, end)
        if not separator:
            break
        cursor = separator.end()
    if not names or len(names) > 64 or len(set(names)) != len(names) or (bare and len(names) < 2):
        return None
    return names, cursor


def _stated_keys(masked, prompt, start, end):
    for pattern in (_KEYS, _KEY_NOUN):
        for m in pattern.finditer(masked, start, end):
            listed = _keys_after(masked, prompt, m.end(), end)
            if listed is None:
                continue
            closed = bool(m.groupdict().get('closed')) or bool(_CLOSED_KEYS.search(masked, m.end(), end))
            container = 'columns' if m.group('noun').lower().startswith('column') else 'keys'
            return {'names': listed[0], 'closed': closed, 'container': container}, _span(prompt, m.start(), listed[1])
    return None


def _template_keys(prompt, sentence_end):
    """Top-level keys of a fenced template immediately after a format statement."""
    rest = prompt[sentence_end:sentence_end + 8]
    position = sentence_end + len(rest) - len(rest.lstrip(' \t:\n'))
    m = _FENCE.match(prompt, position)
    if not m:
        return None
    info = _TEMPLATE_INFO.match(prompt, position).group('info').lower()
    try:
        import yaml
        value = json.loads(m.group(1)) if info == 'json' else yaml.safe_load(m.group(1))
    except Exception:  # an unparsable template declares no keys
        return None
    if type(value) is not dict or not value or len(value) > 64 or not all(type(k) is str and k for k in value):
        return None
    fmt = {'yaml': 'yaml', 'yml': 'yaml', 'json': 'json', 'toml': 'toml'}.get(info)
    return {'names': list(value), 'closed': False, 'container': 'keys'}, _span(prompt, m.start(), m.end()), fmt


def _named_format(word):
    word = word.lower().replace(' ', '-')
    return {'plain-text': 'text', 'markdown': 'text'}.get(word, word)


def _evidence(row, span):
    if span['text'] and span not in row['evidence']:
        row['evidence'].append(span)


def _join_directory(masked, start, token, directories):
    """A bare file name placed in exactly one named directory of the same sentence."""
    joined = []
    for directory in directories:
        if directory.start >= token.end:
            between = masked[token.end:directory.start]
            linked = (len(between) <= LOOKBACK and not _CONTRAST.search(between)
                      and re.fullmatch(r'[`"\'”]?[\s,]+(?:[\w-]+\s+){0,3}(?:in|inside|under|within|into|to)\s+'
                                       r'(?:the\s+)?[`"\'“]?', between, re.I))
        else:
            between = masked[directory.end:token.start]
            # A file with its own destination ("... to scratch/ and the answer to a.yaml") is not joined.
            linked = (len(between) <= LOOKBACK and _LOCATION_LEAD.search(masked, _back(start, directory.start),
                                                                          directory.start)
                      and not _CONTRAST.search(between)
                      and not re.search(r'\b(?:to|into|in|at|as|under|inside|within|onto)\b', between, re.I)
                      and re.fullmatch(r'[`"\'”]?(?:\s+' + _DIRECTORY_NOUN + r')?[\s,]+(?:[\w-]+\s+){0,6}[`"\'“]?',
                                       between, re.I))
        if linked:
            joined.append(directory.text.rstrip('/') + '/')
    return joined[0] + token.text if len(joined) == 1 else None


_REFERENCE = re.compile(r'^\s*(?:it|this\s+file|that\s+file|the\s+file|this|that)\b|'
                        r'\b(?:put|place|save|store|move|write|keep|leave)\s+(?:it|this\s+file|that\s+file|the\s+file)\b',
                        re.I)


def _referent(masked, start, end, tokens, previous, files):
    """(previous file row, directory token) when a pronoun sentence places the one bare file of the
    previous sentence in exactly one named directory; otherwise None."""
    if len(previous) != 1 or '/' in previous[0]['path'] or previous[0]['anchor'] != 'workspace':
        return None
    if any(t.shape == 'file' for t in tokens) or not _REFERENCE.search(masked[start:end]):
        return None
    directories = [t for t in tokens if t.shape == 'dir'
                   and _LOCATION_LEAD.search(masked, _back(start, t.start), t.start)
                   and not _negated(masked, start, t.start)]
    if len(directories) != 1 or _normal(directories[0].text.rstrip('/')) is None:
        return None
    row = previous[0]
    target = _normal(directories[0].text.rstrip('/') + '/' + row['path'])
    if target is None or target in files or (row['anchor'], row['path']) not in files:
        return None
    return row, directories[0]


def _exclusion(masked, start, end, tokens, sentence, files):
    """The exclusivity a sentence states, with the locations and names it governs, or None."""
    text = masked[start:end]
    located = any(t.shape == 'dir' for t in tokens) or bool(_LOCATION_NOUN.search(text))
    if _ONLY.search(text) and located:
        mode = 'only'
    elif _NO_NEW_FILES.search(text) or (located and _NO_NEW_ANYTHING.search(text)):
        mode = 'no_new'
    else:
        return None
    directories = [t.text for t in tokens if t.shape == 'dir' and (
        _LOCATION_LEAD.search(masked, _back(start, t.start), t.start)
        or _LOCATION_TAIL.match(masked[t.end:min(end, t.end + LOOKBACK)]))]
    if mode == 'only' and not directories:
        # An unnamed location ("the submission directory") is not known to be the bare file's
        # parent alone; keep only what is certain: nothing new beside the deliverables.
        mode = 'no_new'
    names = [t.text for t in tokens if t.shape == 'file' and (
        _ALLOWED_LEAD.search(masked, _back(start, t.start), t.start) or _normal(t.text) in files
        or re.match(r'^[`"\'”]?\s*(?:must|should|shall|will|may)\s+be\s+the\s+only\b',
                    masked[t.end:min(end, t.end + LOOKBACK)], re.I))]
    return {'mode': mode, 'evidence': sentence, 'directories': directories, 'files': names}


def _exclusive(row, files, locations):
    """Bind one exclusivity statement to the locations it governs."""
    targets = []
    for directory in row['directories']:
        normal = _normal(directory.rstrip('/'))
        if normal is not None and normal not in targets:
            targets.append(normal)
    named_directory = bool(targets)
    if not targets:
        for token in row['files']:
            normal = _normal(token)
            if normal is not None and (normal[0], _parent(*normal)) not in targets:
                targets.append((normal[0], _parent(*normal)))
    if not targets:
        for anchor, path in files:
            if (anchor, _parent(anchor, path)) not in targets:
                targets.append((anchor, _parent(anchor, path)))
    for anchor, location in targets:
        allowed = []
        for token in row['files']:
            normal = _normal(token)
            if normal is None:
                continue
            if named_directory and '/' not in token:
                allowed.append(normal[1])
            elif normal[0] == anchor and _within(location, normal[1]) is not None:
                allowed.append(_within(location, normal[1]))
        for f_anchor, f_path in files:
            if f_anchor == anchor and _within(location, f_path) is not None:
                allowed.append(_within(location, f_path))
        target = locations.setdefault((anchor, location), {'anchor': anchor, 'path': location, 'required': False,
                                                           'exclusive': None, 'allowed': [], 'evidence': [],
                                                           'order': row['evidence']['start']})
        if target['exclusive'] != 'only':
            target['exclusive'] = row['mode']
        target['allowed'].extend(allowed)
        _evidence(target, row['evidence'])


_TOO_MANY = f'the request declares more than {MAX_ITEMS} output paths; split the request'


def read(prompt):
    """The output contract a request declares, bound to exact spans of the request.

    Every item carries its own evidence. A request that declares nothing yields an empty
    item list. The result depends only on the request text.
    """
    if type(prompt) is not str or not prompt.strip() or len(prompt.encode()) > 2_000_000:
        raise ValueError('bounded literal request text required')
    masked = _masked(prompt)
    files, locations, exclusions = {}, {}, []
    previous = []
    for start, end in _sentences(masked):
        tokens = _tokens(masked, start, end)
        sentence = _span(prompt, start, end)
        directories = [t for t in tokens if t.shape == 'dir']
        referred = _referent(masked, start, end, tokens, previous, files)
        if referred is not None:
            # "Write a.yaml. It must be the only file in `out/`": the pronoun places the previous file.
            row, directory = referred
            del files[(row['anchor'], row['path'])]
            normal = _normal(directory.text.rstrip('/') + '/' + row['path'])
            row.update(anchor=normal[0], path=normal[1])
            files[normal] = row
            _evidence(row, sentence)
        placed = []
        unnamed = _UNNAMED_LOCATION.search(masked, start, end)
        declared = [t for t in tokens if t.shape in ('file', 'dir') and _declared(masked, start, t)]
        # "Write a.json to out/a.json" names one file twice; the located name wins.
        located = {posixpath.basename(t.text) for t in declared if t.shape == 'file' and '/' in t.text}
        for token in declared:
            text = token.text
            if token.shape == 'file' and '/' not in text and text in located:
                continue
            if token.shape == 'file' and '/' not in text:
                joined = _join_directory(masked, start, token, directories)
                if joined is None and unnamed:
                    continue  # the location is named only in words; the path is not determined
                text = joined or text
            normal = _normal(text.rstrip('/') if token.shape == 'dir' else text)
            if normal is None:
                continue
            if token.shape == 'dir':
                row = locations.setdefault(normal, {'anchor': normal[0], 'path': normal[1], 'required': False,
                                                    'exclusive': None, 'allowed': [], 'evidence': [],
                                                    'order': token.start})
                row['required'] = True
                _evidence(row, sentence)
                continue
            row = files.setdefault(normal, {'anchor': normal[0], 'path': normal[1], 'format': None, 'keys': None,
                                            'evidence': [], 'order': token.start})
            extension = _EXTENSION.search(posixpath.basename(normal[1]))
            if row['format'] is None and extension:
                row['format'] = _EXTENSIONS.get(extension.group(1).lower())
            _evidence(row, sentence)
            if row not in placed:
                placed.append(row)
            if len(files) + len(locations) > MAX_ITEMS:
                raise ValueError(_TOO_MANY)  # every row found so far is emitted
        if len(placed) == 1:
            row = placed[0]
            stated = _STATED_FORMAT.search(masked, start, end)
            if stated:
                row['format'] = _named_format(stated.group('f'))
            keys = _stated_keys(masked, prompt, start, end)
            if keys is None and _TEMPLATE_CUE.search(masked, start, end):
                template = _template_keys(prompt, end)
                if template is not None:
                    keys = template[:2]
                    if row['format'] is None:
                        row['format'] = template[2]
            if keys is not None and row['keys'] is None:
                row['keys'] = keys[0]
                _evidence(row, keys[1])
        exclusion = _exclusion(masked, start, end, tokens, sentence, files)
        if exclusion is not None:
            if referred is not None:
                exclusion['files'].append(referred[0]['path'])
            exclusions.append(exclusion)
        previous = placed
    for row in exclusions:
        _exclusive(row, files, locations)
    items = []
    for row in sorted(files.values(), key=lambda r: r['order']):
        items.append({'type': 'file', 'anchor': row['anchor'], 'path': row['path'], 'format': row['format'],
                      'keys': row['keys'], 'evidence': row['evidence'][:16]})
    for row in sorted(locations.values(), key=lambda r: r['order']):
        allowed = sorted(set(row['allowed']))
        exclusive = row['exclusive'] if allowed else None
        if not row['required'] and exclusive is None:
            continue  # an exclusivity that names no deliverable cannot be checked
        items.append({'type': 'location', 'anchor': row['anchor'], 'path': row['path'], 'required': row['required'],
                      'exclusive': exclusive, 'allowed': allowed if exclusive else [],
                      'evidence': row['evidence'][:16]})
    if len(items) > MAX_ITEMS:
        raise ValueError(_TOO_MANY)
    for index, item in enumerate(items, 1):
        item['id'] = ('F' if item['type'] == 'file' else 'L') + str(index)
    return {'schema_version': SCHEMA_VERSION, 'kind': KIND,
            'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'workspace': None, 'items': items}


# ------------------------------------------------------------------ binding and obligations
def _resolve(item, workspace):
    anchor = item['anchor']
    if anchor == 'absolute':
        return Path(posixpath.normpath(item['path']))
    if anchor == 'home':
        return Path(os.path.normpath(os.path.join(str(Path.home()), item['path'])))
    if not workspace:
        return None
    return Path(os.path.normpath(os.path.join(workspace, item['path'])))


def _baseline(location, allowed):
    """The top-level entry names present now, by name or by digest when the census is large.

    A digest leaves out the top-level names of the declared entries, as the check does, so a
    deliverable already present when the request was received is not read as a change.
    """
    try:
        names = sorted(entry.name for entry in os.scandir(location))
    except FileNotFoundError:
        return {'names': []}
    except NotADirectoryError:
        return {'names': []}
    if len(json.dumps(names).encode()) <= MAX_BASELINE_BYTES:
        return {'names': names}
    declared = {a.split('/')[0] for a in allowed}
    return {'count': len(names), 'sha256': _digest([n for n in names if n not in declared])}


def bind(record, workspace=None):
    """Bind a read contract to the workspace where the request was received.

    Relative paths resolve against `workspace` (absolute). A "create nothing else" rule
    records the entries its location already holds, so supplied material is not reported as
    an extra entry. Binding observes; it creates nothing.
    """
    validate_record(record)
    bound = deepcopy(record)
    if workspace is not None:
        workspace = os.path.abspath(os.fspath(workspace))
        if not os.path.isdir(workspace):
            raise ValueError('the bound workspace must be an existing directory')
    bound['workspace'] = workspace
    for item in bound['items']:
        if item['type'] == 'location' and item['exclusive'] == 'no_new':
            location = _resolve(item, workspace)
            item['baseline'] = None if location is None else _baseline(location, item['allowed'])
    return bound


def validate_record(record):
    """Structural checks on a read or bound contract; raises ValueError."""
    if type(record) is not dict or set(record) != {'schema_version', 'kind', 'prompt_sha256', 'workspace', 'items'}:
        raise ValueError('closed output-contract record required')
    if record['schema_version'] != SCHEMA_VERSION or record['kind'] != KIND:
        raise ValueError('output contract version 1 required')
    if record['workspace'] is not None and (type(record['workspace']) is not str or not os.path.isabs(record['workspace'])):
        raise ValueError('an absolute bound workspace or null required')
    if type(record['items']) is not list or len(record['items']) > MAX_ITEMS:
        raise ValueError('bounded output-contract item list required')
    for item in record['items']:
        _validate_item(item, evidence=True)
    return record


def _validate_item(item, *, evidence):
    common = {'id', 'type', 'anchor', 'path'} | ({'evidence'} if evidence else set())
    if type(item) is not dict or item.get('type') not in ('file', 'location'):
        raise ValueError('output-contract item of type file or location required')
    if item['type'] == 'file':
        expected = common | {'format', 'keys'}
    else:
        expected = common | {'required', 'exclusive', 'allowed'} | ({'baseline'} if 'baseline' in item else set())
    if set(item) != expected:
        raise ValueError('closed output-contract item fields required')
    if type(item['id']) is not str or not re.fullmatch(r'[FL][0-9]{1,3}', item['id']):
        raise ValueError('output-contract item identity required')
    if item['anchor'] not in ANCHORS or type(item['path']) is not str or not item['path'] or '\x00' in item['path']:
        raise ValueError('anchored output path required')
    if (item['anchor'] == 'absolute') != item['path'].startswith('/'):
        raise ValueError('only absolute anchors carry absolute paths')
    if item['type'] == 'file':
        if item['format'] is not None and item['format'] not in FORMATS:
            raise ValueError('known output format or null required')
        keys = item['keys']
        if keys is not None and (type(keys) is not dict or set(keys) != {'names', 'closed', 'container'}
                                 or type(keys['names']) is not list or not keys['names']
                                 or any(type(k) is not str or not k for k in keys['names'])
                                 or type(keys['closed']) is not bool or keys['container'] not in ('keys', 'columns')):
            raise ValueError('declared keys need names, closure and container')
    else:
        if type(item['required']) is not bool or item['exclusive'] not in (None, *EXCLUSIVE):
            raise ValueError('location requirement and exclusivity required')
        if type(item['allowed']) is not list or any(type(a) is not str or not a or a.startswith('/') for a in item['allowed']):
            raise ValueError('location-relative allowed entries required')
        baseline = item.get('baseline')
        if baseline is not None and not (
                (set(baseline) == {'names'} and type(baseline['names']) is list
                 and all(type(n) is str for n in baseline['names']))
                or (set(baseline) == {'count', 'sha256'} and type(baseline['count']) is int
                    and type(baseline['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', baseline['sha256']))):
            raise ValueError('baseline by names or by digest required')
    if evidence:
        if type(item['evidence']) is not list or not 1 <= len(item['evidence']) <= 16:
            raise ValueError('bounded output-contract evidence required')
        for span in item['evidence']:
            if type(span) is not dict or set(span) != {'start', 'end', 'text'}:
                raise ValueError('exact evidence spans required')


def _statement(item):
    where = {'absolute': '', 'home': ' in the home directory',
             'workspace': ' relative to the workspace where the request was received'}[item['anchor']]
    if item['type'] == 'file':
        text = f"Deliver the declared file `{item['path']}`{where} at exactly that path as a regular, nonempty file"
        if item['format']:
            text += ' in ' + FORMATS[item['format']] + ' format'
        keys = item['keys']
        if keys:
            names = ', '.join(keys['names'])
            text += (f", whose top-level {keys['container']} are exactly {names}" if keys['closed']
                     else f", whose top-level {keys['container']} include {names}")
        return text + '.'
    allowed = ', '.join(item['allowed']) or 'nothing'
    if item['exclusive'] == 'only':
        text = f"The declared location `{item['path']}`{where} must contain only {allowed}; any other entry is a violation."
    elif item['exclusive'] == 'no_new':
        text = (f"Create nothing in the declared location `{item['path']}`{where} except {allowed}; "
                'entries present when the request was received are kept.')
    else:
        text = f"Deliver the declared output location `{item['path']}`{where} as a real directory."
    if item['required'] and item['exclusive']:
        text += ' The location must exist as a real directory.'
    elif item['required']:
        text = text[:-1] + ' holding at least one regular file.'
    return text


def obligations(record, *, room=64):
    """Task-obligation rows for a (preferably bound) output contract.

    One `deliverable` obligation per declared item while the census has room, otherwise a
    single combined obligation. Each row keeps the exact request spans as its evidence.
    """
    validate_record(record)
    items = record['items']
    if not items:
        return []
    if type(room) is not int or room < 1:
        raise ValueError('the task obligation census has no room for the declared output contract')

    def criteria(value):
        result = {CRITERIA_KEY: value}
        if len(json.dumps(result, allow_nan=False).encode()) > MAX_CRITERIA_BYTES:
            raise ValueError('declared output contract exceeds the bounded obligation criteria')
        return result

    def declared(item):
        return {'schema_version': SCHEMA_VERSION, 'workspace': record['workspace'],
                **{k: deepcopy(v) for k, v in item.items() if k != 'evidence'}}
    if len(items) <= room:
        return [{'id': ID_PREFIX + item['id'], 'kind': 'deliverable', 'statement': _statement(item),
                 'criteria': criteria(declared(item)), 'evidence': deepcopy(item['evidence'][:16])} for item in items]
    spans = []
    for item in items:
        for span in item['evidence']:
            if span not in spans:
                spans.append(deepcopy(span))
    return [{'id': ID_PREFIX + 'all', 'kind': 'deliverable',
             'statement': ' '.join(_statement(item) for item in items)[:32000],
             'criteria': criteria({'schema_version': SCHEMA_VERSION, 'type': 'set', 'workspace': record['workspace'],
                                   'items': [{k: deepcopy(v) for k, v in item.items() if k != 'evidence'}
                                             for item in items]}),
             'evidence': spans[:16]}]


def census_rows(prompt, *, room, workspace=None, retained=None):
    """The output-contract obligations intake appends to a request's obligation census.

    `retained` carries the rows of an earlier intake of the same request (a resolution).
    They must declare the same items; their workspace and intake entry records are kept, so a
    later re-reading can never admit entries created after the request was received.
    """
    record = read(prompt)
    if not retained:
        return obligations(bind(record, workspace), room=room)
    previous = _declarations(retained)
    workspaces = {bound for _, _, bound, _ in previous}
    fresh = [{k: v for k, v in item.items() if k != 'evidence'} for item in record['items']]
    if len(workspaces) != 1 or [{k: v for k, v in item.items() if k != 'baseline'}
                                for _, item, _, _ in previous] != fresh:
        raise ValueError('retained output-contract obligations differ from the declarations of the request')
    bound = deepcopy(record)
    bound['workspace'] = workspaces.pop()
    for item, (_, old, _, _) in zip(bound['items'], previous):
        if 'baseline' in old:
            item['baseline'] = deepcopy(old['baseline'])
    return obligations(bound, room=room)


def rows(contract):
    """The output-contract obligation rows of a task contract, in census order."""
    requirements = contract.get('task_requirements') if type(contract) is dict else None
    census = requirements.get('obligations') if type(requirements) is dict else None
    return [deepcopy(r) for r in census or [] if type(r) is dict and type(r.get('criteria')) is dict
            and CRITERIA_KEY in r['criteria']]


def _declarations(obligation_rows):
    """(obligation id, item, workspace, withdrawn) for every declared item; malformed rows raise."""
    result = []
    for row in obligation_rows:
        if type(row) is not dict or type(row.get('criteria')) is not dict or CRITERIA_KEY not in (row.get('criteria') or {}):
            continue
        value = row['criteria'][CRITERIA_KEY]
        withdrawn = bool(row.get('withdrawn', False))
        if type(value) is not dict or value.get('schema_version') != SCHEMA_VERSION:
            raise ValueError(f"{row.get('id')}: output contract version 1 required")
        workspace = value.get('workspace')
        if workspace is not None and (type(workspace) is not str or not os.path.isabs(workspace)):
            raise ValueError(f"{row.get('id')}: absolute bound workspace or null required")
        if value.get('type') == 'set':
            if set(value) != {'schema_version', 'type', 'workspace', 'items'} or type(value['items']) is not list:
                raise ValueError(f"{row.get('id')}: closed combined output contract required")
            members = value['items']
        else:
            members = [{k: v for k, v in value.items() if k not in ('schema_version', 'workspace')}]
        for item in members:
            _validate_item(item, evidence=False)
            result.append((row.get('id'), item, workspace, withdrawn))
    return result


# ------------------------------------------------------------------ observation
class _Report:
    def __init__(self):
        self.items = []
        self.violations = []

    def add(self, obligation, item, path, codes, observed=None, status=None):
        row = {'obligation_id': obligation, 'item_id': item['id'], 'type': item['type'],
               'declared_path': item['path'], 'path': None if path is None else str(path),
               'status': status or ('violated' if codes else 'satisfied'), 'observed': observed,
               'violations': [{'code': c, 'message': m} for c, m in codes]}
        self.items.append(row)
        for code, message in codes:
            self.violations.append({'obligation_id': obligation, 'item_id': item['id'],
                                    'path': None if path is None else str(path), 'code': code, 'message': message})


def _duplicate_free_yaml(raw):
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError:
                duplicate = False
            if duplicate:
                raise yaml.constructor.ConstructorError(None, None, f'duplicate key {key!r}', key_node.start_mark)
            try:
                seen.add(key)
            except TypeError:
                pass
        return loader.construct_mapping(node, deep=deep)
    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(raw, Loader=Loader)  # noqa: S506 - a SafeLoader subclass


def _strict_json(raw):
    def pairs(rows):
        keys = [k for k, _ in rows]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate key')
        return dict(rows)

    def constant(name):
        raise ValueError(f'non-finite constant {name}')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _parse(fmt, raw):
    """(document or header, problem). Text formats must decode as strict UTF-8."""
    if fmt in _MAGIC:
        return None, None if raw.startswith(_MAGIC[fmt]) else f'does not begin with the {FORMATS[fmt]} signature'
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return None, 'is not UTF-8 text'
    try:
        if fmt == 'yaml':
            return _duplicate_free_yaml(text), None
        if fmt == 'json':
            return _strict_json(text), None
        if fmt == 'toml':
            import tomllib
            return tomllib.loads(text), None
        if fmt in _TABLE_FORMATS:
            rows = list(csv.reader(io.StringIO(text, newline=''), delimiter='\t' if fmt == 'tsv' else ','))
            rows = [r for r in rows if r]
            if not rows or not any(cell.strip() for cell in rows[0]):
                return None, 'has no header row'
            widths = {len(r) for r in rows}
            if len(widths) != 1:
                return None, 'has rows of different widths'
            return rows[0], None
        if fmt == 'svg':
            return None, None if '<svg' in text else 'holds no <svg> element'
        return text, None
    except Exception as exc:  # every parser failure is a reported format violation
        return None, f'does not parse: {str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__}'


def _check_file(item, path):
    codes = []
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return [('missing', f'declared deliverable {path} does not exist')], None
    except OSError as exc:
        return [('unreadable', f'declared deliverable {path} cannot be observed: {exc.strerror}')], None
    if stat.S_ISLNK(before.st_mode):
        return [('symbolic_link', f'declared deliverable {path} is a symbolic link, not the delivered file')], None
    if not stat.S_ISREG(before.st_mode):
        return [('not_regular_file', f'declared deliverable {path} is not a regular file')], None
    if before.st_size == 0:
        return [('empty', f'declared deliverable {path} is empty')], {'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}
    fmt = item['format']
    keys = item['keys']
    parse = keys is not None or (fmt is not None and fmt not in _MAGIC)
    if parse and before.st_size > MAX_PARSE_BYTES:
        return [('too_large', f'declared deliverable {path} exceeds the {MAX_PARSE_BYTES}-byte bounded format check')], \
            {'size': before.st_size, 'sha256': None}
    digest = hashlib.sha256()
    raw = bytearray()
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                return [('changed', f'declared deliverable {path} changed while it was observed')], None
            while True:
                block = stream.read(1 << 20)
                if not block:
                    break
                digest.update(block)
                if parse and len(raw) <= MAX_PARSE_BYTES:
                    raw.extend(block)
                elif len(raw) < 16:
                    raw.extend(block[:16])
    except OSError as exc:
        return [('unreadable', f'declared deliverable {path} cannot be read: {exc.strerror}')], None
    raw = bytes(raw)
    observed = {'size': before.st_size, 'sha256': digest.hexdigest()}
    document = None
    if fmt is not None:
        document, problem = _parse(fmt, raw)
        if problem:
            codes.append(('format', f'declared deliverable {path} {problem}, not {FORMATS[fmt]}'))
            return codes, observed
    if keys is not None:
        if fmt is None:
            document, problem = _parse('json', raw)
            if problem:
                document, problem = _parse('yaml', raw)
            if problem:
                return [('format', f'declared deliverable {path} has declared keys but is neither JSON nor YAML')], observed
            fmt = 'yaml'
        if fmt in _TABLE_FORMATS:
            present = [cell.strip() for cell in document]
        elif fmt in _MAPPING_FORMATS:
            if type(document) is not dict:
                return [('not_mapping', f'declared deliverable {path} is not a top-level mapping of keys')], observed
            present = [str(k) for k in document]
        else:
            return [('format', f'declared deliverable {path} cannot carry declared {keys["container"]} as '
                               f'{FORMATS[fmt]}')], observed
        missing = [k for k in keys['names'] if k not in present]
        if missing:
            codes.append(('missing_keys', f'declared deliverable {path} lacks declared {keys["container"]}: '
                                          + ', '.join(missing)))
        extra = [k for k in present if k not in keys['names']]
        if keys['closed'] and extra:
            codes.append(('extra_keys', f'declared deliverable {path} carries undeclared {keys["container"]}: '
                                        + ', '.join(extra[:MAX_REPORTED])))
    return codes, observed


def _walk(root, *, skip=frozenset(), depth_limit=MAX_DEPTH):
    """Relative entries below a directory, never following links: [(relative, mode)].

    Top-level names in `skip` are listed but not entered (entries present at intake).
    """
    rows = []
    stack = [(root, '', 0)]
    while stack:
        folder, prefix, depth = stack.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                relative = prefix + entry.name
                mode = entry.stat(follow_symlinks=False).st_mode
                rows.append((relative, mode))
                if len(rows) > MAX_ENTRIES:
                    raise OverflowError
                if not stat.S_ISDIR(mode) or (depth == 0 and entry.name in skip):
                    continue
                if depth + 1 < depth_limit:
                    stack.append((entry.path, relative + '/', depth + 1))
                elif depth_limit == MAX_DEPTH:
                    raise OverflowError  # deeper than any declared layout needs
    return sorted(rows)


def _check_location(item, path):
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        if item['required']:
            return [('location_missing', f'declared output location {path} does not exist')], None
        return [], None
    except OSError as exc:
        return [('unreadable', f'declared output location {path} cannot be observed: {exc.strerror}')], None
    if stat.S_ISLNK(before.st_mode):
        return [('symbolic_link', f'declared output location {path} is a symbolic link')], None
    if not stat.S_ISDIR(before.st_mode):
        return [('not_directory', f'declared output location {path} is not a directory')], None
    baseline = item.get('baseline') if item['exclusive'] == 'no_new' else None
    by_digest = baseline is not None and 'sha256' in baseline
    preexisting = set(baseline['names']) if baseline is not None and 'names' in baseline else set()
    try:
        # A digest records only top-level names, so only the top level can be compared with it.
        entries = _walk(path, depth_limit=1) if by_digest else _walk(path, skip=preexisting)
    except OverflowError:
        return [('too_many_entries', f'declared output location {path} holds more than {MAX_ENTRIES} entries '
                                     f'or is deeper than {MAX_DEPTH} levels')], None
    except OSError as exc:
        return [('unreadable', f'declared output location {path} cannot be listed: {exc.strerror}')], None
    observed = {'entries': len(entries)}
    codes = []
    if item['required'] and not any(stat.S_ISREG(mode) for _, mode in entries):
        codes.append(('empty_location', f'declared output location {path} holds no regular file'))
    if item['exclusive'] is None:
        return codes, observed
    allowed = set(item['allowed'])
    ancestors = {'/'.join(a.split('/')[:i]) for a in allowed for i in range(1, a.count('/') + 1)}
    if by_digest:
        tops = sorted({r.split('/')[0] for r, _ in entries} - {a.split('/')[0] for a in allowed})
        if _digest(tops) != baseline['sha256']:
            codes.append(('location_changed', f'entries of {path} differ from those recorded by digest when the '
                                              'request was received'))
        return codes, observed
    if item['exclusive'] == 'no_new' and baseline is None:
        codes.append(('no_baseline', f'"create nothing else" location {path} has no entry record from intake; '
                                     'its pre-existing entries cannot be distinguished'))
    extra, special = [], []
    for relative, mode in entries:
        if relative.split('/')[0] in preexisting:
            continue
        if relative in allowed:
            if not stat.S_ISREG(mode):
                special.append(relative)
            continue
        if relative in ancestors and stat.S_ISDIR(mode):
            continue
        if any(relative.startswith(e + '/') for e in extra):
            continue  # inside an entry already reported
        extra.append(relative)
    if special:
        codes.append(('special_entry', f'declared entries of {path} are not regular files: '
                                       + ', '.join(special[:MAX_REPORTED])))
    if extra:
        shown = ', '.join(extra[:MAX_REPORTED]) + (f' and {len(extra) - MAX_REPORTED} more' if len(extra) > MAX_REPORTED else '')
        codes.append(('extra_entry', f'declared location {path} holds undeclared entries: {shown}'))
    return codes, observed


def check(obligation_rows, *, workspace=None):
    """Observe every declared output item of an obligation census (effective rows).

    Returns a report and never raises for a violation; a malformed declaration is itself
    reported. `workspace` fills only a workspace that intake did not bind. Withdrawn
    obligations are listed and not observed.
    """
    report = _Report()
    try:
        declarations = _declarations(list(obligation_rows))
    except ValueError as exc:
        return {'schema_version': SCHEMA_VERSION, 'kind': CHECK_KIND, 'declared': True, 'items': [],
                'violations': [{'obligation_id': None, 'item_id': None, 'path': None, 'code': 'invalid_declaration',
                                'message': str(exc)}],
                'satisfied': False, 'semantic_content_verified': False}
    fallback = None if workspace is None else os.path.abspath(os.fspath(workspace))
    for obligation, item, bound, withdrawn in declarations:
        if withdrawn:
            report.add(obligation, item, None, [], status='withdrawn')
            continue
        path = _resolve(item, bound or fallback)
        if path is None:
            report.add(obligation, item, None, [('no_workspace', f"relative declared path {item['path']} has no "
                                                                 'bound workspace to resolve against')])
            continue
        codes, observed = (_check_file if item['type'] == 'file' else _check_location)(item, path)
        report.add(obligation, item, path, codes, observed)
    return {'schema_version': SCHEMA_VERSION, 'kind': CHECK_KIND, 'declared': bool(declarations),
            'items': report.items, 'violations': report.violations, 'satisfied': not report.violations,
            'semantic_content_verified': False}


def require(obligation_rows, *, workspace=None):
    """The final whole-task check: the report, or ValueError naming every violation."""
    report = check(obligation_rows, workspace=workspace)
    if report['violations']:
        messages = [f"{v['obligation_id']}: {v['message']}" for v in report['violations']]
        shown = '; '.join(messages[:20]) + (f'; and {len(messages) - 20} more' if len(messages) > 20 else '')
        raise ValueError('declared output contract violated before delivery: ' + shown)
    return report


def placement_conflicts(obligation_rows, rundir, *, workspace=None):
    """Reasons a run directory would itself violate a declared output contract.

    A run directory inside a location the request declares exclusive would be an extra
    entry at delivery; one at a declared deliverable path would replace that deliverable.
    """
    # Compare real locations: one directory can be named through a linked parent.
    target = Path(os.path.realpath(os.fspath(rundir)))
    fallback = None if workspace is None else os.path.abspath(os.fspath(workspace))
    conflicts = []
    for obligation, item, bound, withdrawn in _declarations(list(obligation_rows)):
        path = None if withdrawn else _resolve(item, bound or fallback)
        if path is None:
            continue
        path = Path(os.path.realpath(path))
        if item['type'] == 'file' and (target == path or path in target.parents):
            conflicts.append(f'{obligation}: the run directory {target} would occupy the declared deliverable {path}')
        if item['type'] == 'location' and item['exclusive'] and (target == path or path in target.parents):
            relative = target.relative_to(path).as_posix() if target != path else '.'
            baseline = item.get('baseline') or {}
            preexisting = item['exclusive'] == 'no_new' and relative.split('/')[0] in baseline.get('names', ())
            if relative not in item['allowed'] and not preexisting:
                conflicts.append(f'{obligation}: the run directory {target} lies inside {path}, which the request '
                                 'declares must hold nothing but its deliverables; choose a run directory outside it')
    return conflicts


def main(argv=None):
    """Read-only projection: the declarations of a request, or a check of a run's contract."""
    import argparse
    parser = argparse.ArgumentParser(prog='ravel output-contract')
    commands = parser.add_subparsers(dest='command', required=True)
    reading = commands.add_parser('read', help='print the output contract a request declares')
    source = reading.add_mutually_exclusive_group(required=True)
    source.add_argument('--prompt')
    source.add_argument('--prompt-file', type=Path)
    checking = commands.add_parser('check', help="check a run's declared deliverables now")
    checking.add_argument('--rundir', type=Path, required=True)
    checking.add_argument('--workspace', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'read':
            prompt = args.prompt if args.prompt is not None else args.prompt_file.read_bytes().decode('utf-8')
            result = read(prompt)
        else:
            from .task_completion import _Inputs, _contract
            inputs = _Inputs(args.rundir)
            try:
                pin = inputs.capture(args.rundir.absolute() / 'inputs/task_contract.json')
                _, _, effective, _ = _contract(pin, inputs)
                inputs.finish()
            finally:
                inputs.close()
            result = check(effective.values(), workspace=args.workspace)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        parser.exit(2, f'ravel output-contract: {exc}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if args.command == 'check' and not result['satisfied'] else 0


if __name__ == '__main__':
    main()
