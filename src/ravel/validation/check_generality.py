#!/usr/bin/env python3
"""Generality gate: the repository names no specific analysis, challenge, person or showcase point.

One scan, run by the pre-commit hook, the public-scope export check and the development
snapshot push. It reports four classes of finding:

(a) named challenges, benchmark or evaluation suites and compared agent systems;
(b) specific analysis identifiers: experiment analysis codes and notes, Rivet routine ids,
    search-specific routine names, experiment-year slugs, arXiv, INSPIRE and HEPData record ids
    and physics-journal DOIs;
(c) person names;
(d) benchmark points tied to one study.

The (b) shapes are structural patterns. Names, which no pattern can recognise, come from a
maintained denylist that stores only keyed digests of each term's letters and digits, so the
list itself names nothing. A text matches an entry when a run of its words, joined without
separators and lower-cased, has the entry's digest: "Fable Quarry", "FableQuarry",
"fable_quarry" and "FABLE-QUARRY" are one entry. Two outside lists join the denylist at run
time: the term list in RAVEL_EVAL_TERMS_FILE / RAVEL_EVAL_TERMS, and the fingerprints and
document hashes of the owner's restricted-source list in RAVEL_RESTRICTED_SOURCES.

(e) placeholder identifiers: an arXiv-shaped number whose year-month field no real number has,
    an analysis label of the form ANA-9<nnn>-<nn>, a routine label of the form Routine00<n>, and
    any DOI, link or report number built from them. A placeholder that stands where a source
    should be cited is a fabricated citation, so these are refused in every file.

Upstream sources are cited, not named: the citation list (data/generality/citations.json) gives,
for each file that cites the source of shipped data, a method, a convention or a tool, the exact
identifiers that file may carry. Those strings are removed from the file's text before the scan,
so any other identifier in the same file is a finding, the same identifier in a file that is not
listed is a finding, and a listed identifier that its file no longer carries is a finding too
(stale-citation). The list never applies to the placeholder rules.

The allowlist is empty. A supplied allowlist ({path: [rule, ...]}) must match exactly; a stale
entry is itself a finding. Output names the path, line and rule. --show adds the matched text
for pattern rules only; a denylist match is never echoed.

Usage:
  check_generality.py                     scan the tracked files of the repository
  check_generality.py --tree DIR          scan every file under DIR (an export stage, a snapshot)
  check_generality.py --staged            scan the staged content (the pre-commit hook)
  check_generality.py PATH ...            scan these files or directories
  check_generality.py --summary           counts by rule and by file instead of every line
  check_generality.py --citations FILE    use this citation list instead of the shipped one
  check_generality.py --add-term CATEGORY read terms from stdin, add their digests to the denylist
Exit 0 when clean, 1 on any finding, 2 on a configuration error.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

GIT = '/usr/bin/git' if Path('/usr/bin/git').exists() else 'git'
DENYLIST = Path(__file__).resolve().parents[1] / 'data' / 'generality' / 'denylist.json'
CITATIONS = DENYLIST.with_name('citations.json')
CITATION_LIST = 'src/ravel/data/generality/citations.json'
KEY = b'ravel-generality-v1'
CATEGORIES = ('challenge', 'benchmark', 'comparator', 'study', 'routine', 'person', 'benchmark-point',
              'external', 'restricted-document')
MAX_WORDS = 6
MAX_BYTES = 64 << 20
SKIP_DIRS = {'.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'node_modules', '.venv'}

# (b) Structural identifier shapes. Each rule is general: no list of groups, years or papers.
PATTERNS = (
    # <EXPERIMENT>-<GROUP>-<YY|YYYY>-<NN>, CONF/PUB/PAS notes, upper or lower case.
    ('analysis-code', re.compile(
        r'(?i)(?:(?<![A-Za-z0-9])|(?<=\\[nrt]))(?:atlas|cms|lhcb|alice)[-_ ](?:pas[-_ ])?[a-z][a-z0-9]{1,5}[-_ ]'
        r'(?:\d{2}|(?:19|20)\d\d)[-_ ]\d{2,3}(?![0-9])'), ('atlas', 'cms', 'lhcb', 'alice')),
    # <GROUP>-<YYYY>-<NN> or <GROUP>-<YY>-<NNN> without the experiment prefix.
    # (also after another prefix, as in a source file name ANA-<GROUP>-<YYYY>-<NN>).
    ('analysis-code', re.compile(
        r'(?:(?<![A-Za-z0-9])|(?<=\\[nrt]))(?:[A-Za-z][A-Za-z0-9]*-)?[A-Z][A-Z0-9]{1,5}-(?:(?:19|20)\d\d-\d{2,3}|\d{2}-\d{3})(?![0-9])'),
     None),
    # Rivet ids: <EXP>_<YYYY>_I<inspire> or _S<spires>.
    ('routine-id', re.compile(r'(?:(?<![A-Za-z0-9])|(?<=\\[nrt]))[A-Z][A-Z0-9]{1,9}_(?:19|20)\d\d_[IS]\d{4,8}(?![0-9])'), ('_',)),
    # Search-specific routine names: a capitalised word of four or more characters, with a
    # lower-case letter or a digit before the final year (an all-capitals set name such as a PDF
    # set is a tool name).
    ('routine-name', re.compile(
        r'(?<![A-Za-z0-9_])(?=[A-Z][A-Za-z0-9]*?[a-z0-9][A-Za-z0-9]*?(?:19[89]\d|20[0-3]\d)(?![0-9]))'
        r'[A-Z][A-Za-z0-9]{2,}?[A-Za-z](?:19[89]\d|20[0-3]\d)(?![0-9])'), None),
    # The same names folded to lower case, as module and file names: ten or more letters and a year.
    ('routine-name', re.compile(r'(?<![A-Za-z0-9_])[a-z]{10,}(?:19[89]\d|20[0-3]\d)(?![0-9])'), None),
    # Experiment-year slugs naming one publication: atlas-2016-..., cms_2019_...
    ('experiment-year-slug', re.compile(r'(?i)(?:(?<![a-z0-9])|(?<=\\[nrt]))(?:atlas|cms|lhcb|alice)[-_](?:19|20)\d\d[-_][a-z]'), ('atlas', 'cms', 'lhcb', 'alice')),
    ('arxiv-id', re.compile(
        r'(?i)arxiv(?:\.org/[a-z-]+/|\s*:?\s*)(?:(?:0[7-9]|1\d|2\d)(?:0[1-9]|1[0-2])\.\d{4,5}|[a-z-]+/\d{7})'),
     ('arxiv',)),
    ('arxiv-id', re.compile(
        r'(?<![\w.\-])(?:0[7-9]|1\d|2[0-9])(?:0[1-9]|1[0-2])\.\d{5}(?:v\d+)?(?![\w.])'), ('.',)),
    ('arxiv-id', re.compile(r'(?<![A-Za-z])(?:hep-(?:ph|ex|th|lat)|astro-ph|nucl-(?:ex|th)|gr-qc)/\d{7}(?![0-9])'), ('/',)),
    # Analysis names that embed an arXiv id: <experiment>_<YYMM>_<NNNNN>.
    ('arxiv-id', re.compile(r'(?i)(?:(?<![a-z0-9])|(?<=\\[nrt]))(?:atlas|cms|lhcb|alice)_(?:0[7-9]|1\d|2\d)(?:0[1-9]|1[0-2])_\d{4,5}(?![0-9])'),
     ('atlas', 'cms', 'lhcb', 'alice')),
    # Real record numbers never start with 0; a zero-padded number is synthetic (a schema may need its width).
    ('inspire-id', re.compile(r'(?i)inspirehep\.net/(?:api/)?(?:literature|record)s?/[1-9]\d{4,}'), ('inspirehep',)),
    ('inspire-id', re.compile(r'(?i)inspire[a-z_-]*["\']?\s*[:=#]\s*["\']?[1-9]\d{4,7}'), ('inspire',)),
    ('inspire-id', re.compile(r'(?i)inspire\s+(?:id\s+|record\s+)?[1-9]\d{5,7}(?![0-9])'), ('inspire',)),
    ('inspire-id', re.compile(r'(?:(?<![A-Za-z0-9])|(?<=\\[nrt]))ins[1-9]\d{4,7}(?![0-9])'), ('ins',)),
    ('inspire-id', re.compile(r'(?:(?<![A-Za-z0-9])|(?<=\\[nrt]))i[1-9]\d{5,7}(?![0-9])'), None),
    ('hepdata-record', re.compile(r'(?i)hepdata\.net/record/(?:(?:ins|resource/|data/)?[1-9]\d{4,})'), ('hepdata',)),
    ('hepdata-record', re.compile(r'(?i)10\.17182/hepdata\.\d{4,}'), ('hepdata',)),
    ('hepdata-record', re.compile(r'(?i)hepdata\s*(?:record\s*|entry\s*|#\s*)?[1-9]\d{4,}'), ('hepdata',)),
    ('journal-doi', re.compile(r'(?i)10\.(?:1103/phys|1007/jhep|1140/epjc|1016/j\.physletb|1088/1126-6708)'), ('10.',)),
    # (e) Placeholder identifiers. No real arXiv number has a year-month field outside 0704 to 2912.
    ('placeholder-arxiv-id', re.compile(
        r'(?i)arxiv(?:\.org/[a-z-]+/|\s*:?\s*)(?!(?:0[7-9]|1\d|2\d)(?:0[1-9]|1[0-2])\.)\d{4}\.\d{4,5}'), ('arxiv',)),
    ('placeholder-arxiv-id', re.compile(r'(?<![\w.\-])0000\.\d{5}(?:v\d+)?(?!\w|\.\d)'), ('0000.',)),
    ('placeholder-analysis-id', re.compile(r'(?<![A-Za-z0-9])ANA-9\d{3}-\d{2}(?![0-9])'), ('ana-9',)),
    ('placeholder-routine-name', re.compile(r'(?<![A-Za-z0-9])Routine00\d(?![0-9])'), ('routine00',)),
)
PLACEHOLDER_RULES = ('placeholder-arxiv-id', 'placeholder-analysis-id', 'placeholder-routine-name')
# Words for the denylist: camel-case humps, upper-case runs and digit runs, in text order.
WORD = re.compile(r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+')
SHA = re.compile(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])')


def _digest(compact):
    return hashlib.blake2b(compact.encode(), digest_size=10, key=KEY).hexdigest()


def _compact(term):
    return ''.join(w.lower() for w in WORD.findall(term))


def entry_for(term, category):
    """A denylist entry for ``term``: its digest, its category and its compact length."""
    if category not in CATEGORIES:
        raise ValueError(f'unknown category {category!r}; expected one of {CATEGORIES}')
    compact = _compact(term)
    if len(compact) < 3:
        raise ValueError('a term needs at least three letters or digits')
    return {'digest': _digest(compact), 'category': category, 'length': len(compact)}


def denylist_document(entries):
    return {'schema_version': 1, 'kind': 'generality-denylist',
            'purpose': 'Keyed digests of named challenges, benchmark suites, compared systems, studies, '
                       'search-specific routines, people and showcase points that no tracked file may '
                       'name. Maintained with check_generality.py --add-term; the terms are not stored.',
            'entries': sorted(entries, key=lambda e: (e['category'], e['digest']))}


class Denylist:
    def __init__(self, entries, documents=()):
        self.entries = [dict(e) for e in entries]
        self.by_digest = {e['digest']: e['category'] for e in entries}
        self.lengths = {e['length'] for e in entries}
        self.maxlen = max(self.lengths, default=0)
        self.documents = [d.lower() for d in documents]

    def __getstate__(self):
        return {'entries': self.entries, 'documents': self.documents}

    def __setstate__(self, state):
        self.__init__(state['entries'], state['documents'])

    def match(self, term):
        """The category ``term`` matches as a whole, or None."""
        compact = _compact(term)
        return self.by_digest.get(_digest(compact)) if compact else None

    def hits(self, text):
        """(offset, category) for every word run of ``text`` that matches an entry."""
        found = []
        if self.by_digest:
            matches = list(WORD.finditer(text))
            lengths, table = self.lengths, self.by_digest
            words = [m.group().lower() for m in matches]
            # A run of two or more words never includes a one-character word, so separated
            # letters ("r", "r", "r") never spell an entry.
            short = [len(w) < 2 for w in words]
            window = words
            for size in range(1, MAX_WORDS + 1):
                if size > 1:
                    window = list(map(str.__add__, window, words[size - 1:]))
                    blocked = list(map(bool.__or__, blocked if size > 2 else short, short[size - 1:]))
                for i, compact in enumerate(window):
                    if size > 1 and (blocked[i] or short[i]):
                        continue
                    if len(compact) in lengths:
                        category = table.get(_digest(compact))
                        if category is not None:
                            found.append((matches[i].start(), category))
        if self.documents:
            lower = text.lower()
            for digest in self.documents:
                at = lower.find(digest)
                if at >= 0:
                    found.append((at, 'restricted-document'))
        return found


def _external_entries(env):
    """Entries from the outside term list and the owner's restricted-source list."""
    terms, documents = [], []
    if env.get('RAVEL_EVAL_TERMS_FILE'):
        terms += Path(env['RAVEL_EVAL_TERMS_FILE']).read_text(encoding='utf-8').splitlines()
    if env.get('RAVEL_EVAL_TERMS'):
        terms += env['RAVEL_EVAL_TERMS'].replace(',', '\n').splitlines()
    if env.get('RAVEL_RESTRICTED_SOURCES'):
        document = json.loads(Path(env['RAVEL_RESTRICTED_SOURCES']).read_text())
        if not isinstance(document, dict) or document.get('kind') != 'restricted-sources':
            raise ValueError('RAVEL_RESTRICTED_SOURCES is not a restricted-sources list')
        terms += [f for f in document.get('fingerprints', []) if isinstance(f, str)]
        documents += [d['sha256'] for d in document.get('documents', []) if isinstance(d, dict)
                      and isinstance(d.get('sha256'), str) and SHA.fullmatch(d['sha256'].lower())]
    entries = []
    for term in terms:
        term = term.strip()
        if term and not term.startswith('#') and len(_compact(term)) >= 3:
            entries.append(entry_for(term, 'external'))
    return entries, documents


def load_denylist(path, env=None):
    """The maintained denylist (``path`` or the shipped one) plus the outside lists in ``env``."""
    path = Path(path) if path else DENYLIST
    document = json.loads(path.read_text()) if path.is_file() else denylist_document([])
    if (not isinstance(document, dict) or document.get('schema_version') != 1
            or document.get('kind') != 'generality-denylist' or not isinstance(document.get('entries'), list)):
        raise ValueError(f'{path}: not a version-1 generality denylist')
    for entry in document['entries']:
        if (not isinstance(entry, dict) or set(entry) != {'digest', 'category', 'length'}
                or entry['category'] not in CATEGORIES or not re.fullmatch(r'[0-9a-f]{20}', str(entry['digest']))
                or type(entry['length']) is not int or entry['length'] < 3):
            raise ValueError(f'{path}: invalid denylist entry {entry!r}')
    extra, documents = _external_entries(os.environ if env is None else env)
    return Denylist(document['entries'] + extra, documents)


def citations_document(files, withheld=None):
    """The citation list. ``withheld`` holds the entries of files that a public export leaves out; they
    are the last key, one block, which the export removes with those files."""
    document = {'schema_version': 1, 'kind': 'generality-citations',
                'purpose': 'Identifiers of upstream sources that the named files cite: the source of shipped data, '
                           'a method, a convention or a tool. A file may carry exactly the identifiers listed for '
                           'it; the generality gate refuses every other identifier, the same identifier in a file '
                           'that is not listed, and a listed identifier that its file no longer carries.',
                'files': {path: sorted(set(strings)) for path, strings in sorted(files.items())}}
    if withheld:
        document['withheld_files'] = {path: sorted(set(strings)) for path, strings in sorted(withheld.items())}
    return document


def _pattern_rules(text):
    return {rule for rule, pattern, _ in PATTERNS if pattern.search(text)}


def load_citations(path=None):
    """{file: [identifier, ...]} from the citation list (``path`` or the shipped one).

    Every entry is an identifier the pattern rules recognise, and none is a placeholder: the list
    cannot admit free text or a fabricated identifier."""
    path = Path(path) if path else CITATIONS
    if not path.is_file():
        return {}
    document = json.loads(path.read_text())
    files = document.get('files') if isinstance(document, dict) else None
    withheld = document.get('withheld_files', {}) if isinstance(document, dict) else None
    if (not isinstance(document, dict) or document.get('schema_version') != 1
            or document.get('kind') != 'generality-citations' or not isinstance(files, dict)
            or not isinstance(withheld, dict) or set(files) & set(withheld)):
        raise ValueError(f'{path}: not a version-1 generality citation list')
    files = {**files, **withheld}
    for name, strings in files.items():
        if (not isinstance(name, str) or not name or name.startswith('/') or '..' in name.split('/')
                or any(c in name for c in '*?[') or not isinstance(strings, list) or not strings
                or len(set(strings)) != len(strings)):
            raise ValueError(f'{path}: a citation entry is one exact file path with a list of distinct identifiers: {name!r}')
        for string in strings:
            # An arXiv number of the four-digit form is recognised only behind its prefix.
            rules = _pattern_rules(string) | _pattern_rules('arXiv:' + string) if isinstance(string, str) else set()
            if not rules or rules & set(PLACEHOLDER_RULES):
                raise ValueError(f'{path}: {name}: not a citable identifier: {string!r}')
    return {name: list(strings) for name, strings in files.items()}


_CITATIONS = None


def shipped_citations():
    global _CITATIONS
    if _CITATIONS is None:
        _CITATIONS = load_citations()
    return _CITATIONS


def _cited(relative, citations):
    """The identifiers ``relative`` may carry. The list itself carries all of them and its file names."""
    if relative == CITATION_LIST:
        return sorted({s for strings in citations.values() for s in strings} | set(citations))
    return citations.get(relative, ())


def _without(text, strings):
    """``text`` with each cited identifier blanked; offsets and line numbers are unchanged."""
    for string in sorted(strings, key=len, reverse=True):
        text = text.replace(string, ' ' * len(string))
    return text


def load_allowlist(path):
    """{path: [rule, ...]}; empty unless a file is supplied."""
    if not path:
        return {}
    document = json.loads(Path(path).read_text())
    allow = document.get('allow') if isinstance(document, dict) else None
    if not isinstance(allow, dict) or any(not isinstance(v, list) for v in allow.values()):
        raise ValueError(f'{path}: an allowlist is {{"allow": {{path: [rule, ...]}}}}')
    return allow


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    rule: str
    text: str = ''


def scan_text(text, denylist, path=''):
    """Findings in ``text``. Line 0 marks a finding in the path itself."""
    starts = None
    found = []

    def line_of(offset):
        nonlocal starts
        if starts is None:
            starts = [0] + [m.end() for m in re.finditer('\n', text)]
        return bisect_right(starts, offset)

    lower = text.lower()
    seen = set()
    for rule, pattern, needles in PATTERNS:
        if needles and not any(n in lower for n in needles):
            continue
        for match in pattern.finditer(text):
            if (rule, match.start()) not in seen:
                seen.add((rule, match.start()))
                found.append(Hit(path, line_of(match.start()), rule, match.group()))
    for offset, category in denylist.hits(text):
        found.append(Hit(path, line_of(offset), 'denylist:' + category))
    return found


PRINTABLE = re.compile(rb'[\t\n\r\x20-\x7e]{16,}')


def _decode(data):
    """Text, or for a binary file its printable runs of sixteen or more characters, one per line
    (compressed bytes never spell a term, but embedded text and metadata are kept)."""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return '\n'.join(m.group().decode('ascii') for m in PRINTABLE.finditer(data))


def scan_bytes(relative, data, denylist, citations=None):
    """Findings in a file's path and content; gzip and zip members are opened. The identifiers the
    citation list gives for this file are not findings in it or in its members; a listed one that
    neither the file nor its name carries is."""
    cited = _cited(relative, shipped_citations() if citations is None else citations)
    found = [Hit(relative, 0, h.rule, h.text) for h in scan_text(_without(relative, cited), denylist, relative)]
    if len(data) > MAX_BYTES:
        return found + [Hit(relative, 0, 'unscanned-large-file')]
    carried = {s for s in cited if s in relative}

    def content(text, path):
        carried.update(s for s in cited if s in text)
        return scan_text(_without(text, cited), denylist, path)

    if relative.endswith('.gz'):
        try:
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_BYTES + 1)
        except (OSError, EOFError):
            pass
        found += content(_decode(data), relative)
    elif relative.endswith('.zip') and zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                member = f'{relative}!{info.filename}'
                found += [Hit(member, 0, h.rule, h.text) for h in content(info.filename, '')]
                if not info.is_dir() and info.file_size <= MAX_BYTES:
                    found += content(_decode(archive.read(info)), member)
    else:
        found += content(_decode(data), relative)
    if relative != CITATION_LIST:
        found += [Hit(relative, 0, 'stale-citation', s) for s in cited if s not in carried]
    return found


def _walk(root):
    for parent, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not Path(parent, d).is_symlink())
        for name in sorted(names):
            path = Path(parent, name)
            if path.is_file() and not path.is_symlink():
                yield path


_WORKER_DENYLIST = None


def _worker_start(denylist):
    global _WORKER_DENYLIST
    _WORKER_DENYLIST = denylist


def _scan_files(batch):
    return [h for relative, path in batch for h in scan_bytes(relative, Path(path).read_bytes(), _WORKER_DENYLIST)]


def _scan_many(files, denylist):
    """Findings for [(relative, path)]; a large set is split over worker processes."""
    workers = min(4, os.cpu_count() or 1)
    # Forked workers inherit the loaded denylist and never re-import the caller's main module.
    fork = 'fork' in multiprocessing.get_all_start_methods()
    if len(files) < 64 or workers < 2 or not fork:
        return [h for relative, path in files for h in scan_bytes(relative, Path(path).read_bytes(), denylist)]
    # Interleaved batches spread the few very large files over the workers.
    batches = [files[i::workers * 4] for i in range(workers * 4)]
    found = []
    with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context('fork'),
                             initializer=_worker_start, initargs=(denylist,)) as pool:
        for hits in pool.map(_scan_files, batches):
            found += hits
    return found


def scan_tree(root, denylist):
    root = Path(root)
    return _scan_many([(p.relative_to(root).as_posix(), str(p)) for p in _walk(root)], denylist)


def _git(root, *args):
    return subprocess.run([GIT, '-C', str(root), *args], check=True, capture_output=True).stdout


def tracked_files(root):
    """Tracked paths present in the working tree (a deleted tracked file is not scanned)."""
    names = [n for n in _git(root, 'ls-files', '-z').decode().split('\0') if n]
    return [n for n in names if (Path(root, n).is_file() and not Path(root, n).is_symlink())]


def scan_repository(root, denylist, staged=False):
    root = Path(root)
    found, scanned = [], set()
    if staged:
        names = [n for n in _git(root, 'diff', '--cached', '--name-only', '-z', '--diff-filter=ACMR').decode()
                 .split('\0') if n]
        for name in names:
            scanned.add(name)
            found += scan_bytes(name, _git(root, 'show', f':{name}'), denylist)
        return found, scanned
    names = tracked_files(root)
    return _scan_many([(n, str(Path(root, n))) for n in names], denylist), set(names)


def scan_paths(paths, denylist, root='.'):
    found, scanned = [], set()
    for given in paths:
        given = Path(given)
        for path in ([given] if given.is_file() else _walk(given)):
            try:
                relative = path.resolve().relative_to(Path(root).resolve()).as_posix()
            except ValueError:
                relative = path.as_posix()
            scanned.add(relative)
            found += scan_bytes(relative, path.read_bytes(), denylist)
    return found, scanned


def apply_allowlist(hits, allow, scanned):
    """(remaining findings, stale-entry messages). An allowed rule must occur in its file."""
    if not allow:
        return list(hits), []
    seen = {}
    for hit in hits:
        seen.setdefault(hit.path.split('!')[0], set()).add(hit.rule)
    kept = [h for h in hits if h.rule not in allow.get(h.path.split('!')[0], ())]
    stale = []
    for path, rules in sorted(allow.items()):
        if path not in scanned:
            stale.append(f'{path}: allowlist names a file not scanned')
            continue
        stale += [f'{path}: stale allowlist rule {r}' for r in sorted(set(rules) - seen.get(path, set()))]
    return kept, stale


def summary(hits):
    """Counts by rule and by file; it never carries matched text."""
    return {'total': len(hits), 'by_rule': dict(sorted(Counter(h.rule for h in hits).items())),
            'by_file': dict(sorted(Counter(h.path.split('!')[0] for h in hits).items()))}


def _repository_root(start):
    try:
        return Path(_git(start, 'rev-parse', '--show-toplevel').decode().strip())
    except (subprocess.CalledProcessError, OSError):
        return Path(start)


def _add_terms(path, category, lines):
    path = Path(path) if path else DENYLIST
    document = json.loads(path.read_text()) if path.is_file() else denylist_document([])
    entries = {e['digest']: e for e in document['entries']}
    added = 0
    for line in lines:
        term = line.strip()
        if term and not term.startswith('#'):
            entry = entry_for(term, category)
            added += entry['digest'] not in entries
            entries[entry['digest']] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(denylist_document(list(entries.values())), indent=1) + '\n')
    return added


def main(argv=None):
    global _CITATIONS
    parser = argparse.ArgumentParser(description='Generality gate: ' + __doc__.splitlines()[0].split(': ', 1)[1])
    parser.add_argument('paths', nargs='*', help='files or directories to scan instead of the tracked files')
    parser.add_argument('--root', help='repository root (default: the checkout containing the working directory)')
    parser.add_argument('--tree', help='scan every file under this directory')
    parser.add_argument('--staged', action='store_true', help='scan the staged content only')
    parser.add_argument('--denylist', help='denylist file (default: the shipped one)')
    parser.add_argument('--allowlist', help='exact {"allow": {path: [rule]}} exceptions (default: none)')
    parser.add_argument('--citations', help='citation list (default: the shipped one)')
    parser.add_argument('--show', action='store_true', help='print the matched text of pattern findings')
    parser.add_argument('--summary', action='store_true', help='print counts by rule and file')
    parser.add_argument('--json', action='store_true', help='print the summary as JSON')
    parser.add_argument('--add-term', metavar='CATEGORY', choices=CATEGORIES,
                        help='read terms from stdin and add their digests to the denylist')
    args = parser.parse_args(argv)
    try:
        if args.add_term:
            added = _add_terms(args.denylist, args.add_term, sys.stdin.read().splitlines())
            print(f'check_generality: added {added} entr{"y" if added == 1 else "ies"}', file=sys.stderr)
            return 0
        denylist = load_denylist(args.denylist)
        allow = load_allowlist(args.allowlist)
        _CITATIONS = load_citations(args.citations)
    except (OSError, ValueError) as error:
        print(f'check_generality: {error}', file=sys.stderr)
        return 2
    root = Path(args.root) if args.root else _repository_root(Path.cwd())
    if args.tree:
        hits = scan_tree(args.tree, denylist)
        scanned = {p.relative_to(args.tree).as_posix() for p in _walk(Path(args.tree))}
    elif args.paths:
        hits, scanned = scan_paths(args.paths, denylist, root)
    else:
        hits, scanned = scan_repository(root, denylist, staged=args.staged)
    hits, stale = apply_allowlist(hits, allow, scanned)
    if args.summary or args.json:
        report = summary(hits)
        report['stale_allowlist'] = stale
        print(json.dumps(report, indent=1) if args.json else
              '\n'.join([f'{n:6d}  {r}' for r, n in report['by_rule'].items()]
                        + [f'{n:6d}  {p}' for p, n in sorted(report['by_file'].items(), key=lambda kv: -kv[1])]))
    else:
        for hit in sorted(hits, key=lambda h: (h.path, h.line, h.rule)):
            shown = f' {hit.text!r}' if args.show and hit.text and not hit.rule.startswith('denylist:') else ''
            print(f'{hit.path}:{hit.line}: {hit.rule}{shown}')
        for message in stale:
            print(message)
    print(f'check_generality: {len(hits)} finding(s) in {len({h.path.split("!")[0] for h in hits})} file(s)'
          + (f', {len(stale)} stale allowlist entr{"y" if len(stale) == 1 else "ies"}' if stale else ''),
          file=sys.stderr)
    return 1 if hits or stale else 0


if __name__ == '__main__':
    sys.exit(main())
