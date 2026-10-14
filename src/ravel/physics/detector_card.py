"""Delphes detector cards: parsing, the invisible-particle gate, derived cards and skimmed output.

A Delphes card is a Tcl script. ``parse_card`` reads the parts that decide what the
detector sees: the ``ExecutionPath``, every ``module Class Name {...}`` with its
``set`` and ``add`` commands and their line spans, and ``source`` directives (followed
relative to the card's directory).

``check_invisibles`` takes the set of stable invisible states of a model and refuses a
card that would reconstruct any of them:

* every calorimeter module on the execution path (``SimpleCalorimeter``,
  ``Calorimeter``, ``DualReadoutCalorimeter``) must give the state a zero energy
  fraction, either explicitly or through its ``{0}`` default (Delphes compares
  ``|PID|``; a calorimeter without a ``{0}`` entry deposits unlisted particles fully);
* every generator-level jet finder or momentum merger (a ``FastJetFinder`` or
  ``Merger`` whose inputs reach ``Delphes/...`` through filters, mergers and jet finders
  only, without a detector-simulation module)
  must have the state removed by a ``PdgCodeFilter`` on that path, for both signs of
  the PDG code.

``derive_card`` writes a managed copy that adds the missing zero fractions and filter
codes, applies declared module overrides, keeps only the declared output branches and
rewrites ``source`` paths to absolute paths. Every changed line is recorded with its
reason, and the unified diff contains only those lines.

``invisible_census`` builds the invisible set from the model: declared invisible and
visible stable states, cross-checked against an SLHA spectrum (a stable BSM state that
is neither declared invisible nor declared visible is refused) or against a
decay-closure report. ``hepmc_census`` lists the stable BSM states seen in showered
events, so a sample that contains an undeclared stable state stops before Delphes.
"""
from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys

CALORIMETERS = ('SimpleCalorimeter', 'Calorimeter', 'DualReadoutCalorimeter')
GENERATOR_CONSUMERS = ('FastJetFinder', 'Merger')
# Modules that pass generator particles on without simulating the detector.
GENERATOR_PASS = ('PdgCodeFilter', 'Merger', 'FastJetFinder', 'StatusPidFilter')
# Delphes calorimeter defaults for particles without an entry and without a {0} entry.
DEFAULT_FRACTIONS = {'SimpleCalorimeter': (1.0,), 'Calorimeter': (0.0, 1.0), 'DualReadoutCalorimeter': (0.0, 1.0)}
SM_FUNDAMENTAL = frozenset({1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 16, 21, 22, 23, 24, 25})


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def is_bsm(pdg, declared=()):
    """A PDG code outside the Standard Model fundamental and hadron numbering, or declared BSM."""
    a = abs(int(pdg))
    if a in {abs(int(p)) for p in declared}:
        return True
    if a < 100:
        return a not in SM_FUNDAMENTAL and a not in (7, 8, 17, 18, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99)
    return 1000000 <= a < 9000000


# ---------------------------------------------------------------- Tcl reading
class Command:
    __slots__ = ('words', 'line', 'end_line', 'source')

    def __init__(self, words, line, end_line, source):
        self.words, self.line, self.end_line, self.source = words, line, end_line, source

    @property
    def verb(self):
        return self.words[0] if self.words else ''

    def __repr__(self):
        return f'Command({self.words!r}, {self.line})'


def _words(text, first_line=1):
    """Split Tcl text into commands of words; brace groups stay raw. Yields (words, line, end_line)."""
    i, n, line = 0, len(text), first_line
    words, start = [], None
    while i < n:
        c = text[i]
        if c == '\n':
            if words:
                yield words, start, line
                words, start = [], None
            line += 1
            i += 1
        elif c in ' \t\r':
            i += 1
        elif c == ';':
            if words:
                yield words, start, line
                words, start = [], None
            i += 1
        elif c == '\\' and i + 1 < n and text[i + 1] == '\n':
            line += 1
            i += 2
        elif c == '#' and not words:
            while i < n and text[i] != '\n':
                i += 1
        elif c == '{':
            depth, j, begin = 1, i + 1, line
            while j < n and depth:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                elif text[j] == '\n':
                    line += 1
                j += 1
            if depth:
                raise ValueError(f'unbalanced braces starting at line {begin}')
            if start is None:
                start = begin
            words.append(('{', text[i + 1:j - 1], begin))
            i = j
        elif c == '"':
            j, begin = i + 1, line
            while j < n and text[j] != '"':
                if text[j] == '\\':
                    j += 1
                elif text[j] == '\n':
                    line += 1
                j += 1
            if start is None:
                start = begin
            words.append(('"', text[i + 1:j], begin))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n;':
                j += 1
            if start is None:
                start = line
            words.append(('w', text[i:j], line))
            i = j
    if words:
        yield words, start, line


def _value(word):
    return word[1]


class Module:
    def __init__(self, cls, name, line, end_line, source):
        self.cls, self.name, self.line, self.end_line, self.source = cls, name, line, end_line, source
        self.commands = []

    def sets(self, key):
        rows = [c for c in self.commands if c.verb == 'set' and len(c.words) >= 3 and c.words[1] == key]
        return rows[-1].words[2] if rows else None

    def adds(self, key):
        return [c for c in self.commands if c.verb == 'add' and len(c.words) >= 2 and c.words[1] == key]

    def inputs(self):
        names = []
        for c in self.commands:
            if len(c.words) >= 3 and c.words[1] in ('InputArray', 'ParticleInputArray', 'TrackInputArray',
                                                   'CandidateInputArray', 'JetInputArray', 'PartonInputArray'):
                if c.verb in ('set', 'add'):
                    names.append(c.words[2])
        return names


class Card:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.text = self.path.read_text()
        self.lines = self.text.splitlines(keepends=True)
        self.execution_path = []
        self.modules = {}
        self.sources = []
        self.top = []


def _resolve_source(name, card_dir):
    candidate = Path(name)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    for root in (card_dir, card_dir.parent, card_dir.parent.parent):
        if (root / candidate).is_file():
            return (root / candidate).resolve()
    return None


def _read_commands(card, text, first_line, source, module, depth):
    if depth > 8:
        raise ValueError('source directives nest too deeply')
    for raw, line, end_line in _words(text, first_line):
        words = [_value(w) for w in raw]
        if not words:
            continue
        if words[0] == 'module' and module is None:
            if len(words) < 4 or raw[3][0] != '{':
                raise ValueError(f'malformed module declaration at line {line}')
            mod = Module(words[1], words[2], line, end_line, source)
            if words[2] in card.modules:
                raise ValueError(f'module {words[2]} is declared twice')
            card.modules[words[2]] = mod
            _read_commands(card, raw[3][1], raw[3][2], source, mod, depth)
            continue
        if words[0] == 'source':
            if len(words) != 2:
                raise ValueError(f'malformed source directive at line {line}')
            target = _resolve_source(words[1], card.path.parent)
            if target is None:
                raise ValueError(f'card sources {words[1]}, which is not found next to the card')
            card.sources.append({'directive': words[1], 'path': str(target), 'sha256': sha256(target),
                                 'line': line, 'in': source, 'module': module.name if module else None})
            _read_commands(card, target.read_text(), 1, str(target), module, depth + 1)
            continue
        command = Command(words, line, end_line, source)
        if module is not None:
            module.commands.append(command)
        else:
            card.top.append(command)
            if words[0] == 'set' and len(words) >= 3 and words[1] == 'ExecutionPath':
                card.execution_path = words[2].split()


def parse_card(path):
    card = Card(path)
    _read_commands(card, card.text, 1, None, None, 0)
    if not card.execution_path:
        raise ValueError(f'{card.path.name} has no ExecutionPath')
    missing = [m for m in card.execution_path if m not in card.modules]
    if missing:
        raise ValueError(f'ExecutionPath names undeclared modules: {", ".join(missing)}')
    return card


def _numbers(text):
    out = []
    for token in text.split():
        try:
            value = float(token)
        except ValueError as exc:
            raise ValueError(f'non-numeric energy fraction {token!r}') from exc
        if not math.isfinite(value):
            raise ValueError('energy fractions must be finite')
        out.append(value)
    return tuple(out)


def energy_fractions(module):
    table = {}
    for c in module.adds('EnergyFraction'):
        if len(c.words) < 4:
            raise ValueError(f'malformed EnergyFraction in {module.name} at line {c.line}')
        try:
            pdg = int(c.words[2].strip())
        except ValueError as exc:
            raise ValueError(f'EnergyFraction PDG code must be an integer in {module.name} line {c.line}') from exc
        table[abs(pdg)] = (_numbers(c.words[3]), c)
    return table


def effective_fraction(module, pdg):
    table = energy_fractions(module)
    a = abs(int(pdg))
    if a in table:
        return table[a][0], 'explicit', table[a][1]
    if 0 in table:
        return table[0][0], 'default {0} entry', table[0][1]
    return DEFAULT_FRACTIONS[module.cls], 'Delphes built-in default', None


def filter_codes(module):
    codes = []
    for c in module.adds('PdgCode'):
        try:
            codes.append(int(c.words[2].strip()))
        except (IndexError, ValueError) as exc:
            raise ValueError(f'malformed PdgCode in {module.name} at line {c.line}') from exc
    invert = (module.sets('Invert') or 'false').strip().lower() in ('true', '1', 'yes', 'on')
    return set(codes), invert


def _producer(array):
    if '/' not in array:
        raise ValueError(f'input array {array!r} must be Module/array')
    return array.split('/', 1)[0]


def generator_paths(card, name, _trail=()):
    """Every input path from a module back to Delphes/... through generator-level modules only."""
    if name in _trail:
        return []
    module = card.modules[name]
    paths = []
    for array in module.inputs():
        producer = _producer(array)
        if producer == 'Delphes':
            paths.append((name,))
            continue
        if producer not in card.modules:
            raise ValueError(f'{name} reads {array}, whose module is not declared')
        if card.modules[producer].cls not in GENERATOR_PASS:
            continue
        for path in generator_paths(card, producer, _trail + (name,)):
            paths.append((name,) + path)
    return paths


def _removed(card, path, pdg):
    for name in path:
        module = card.modules[name]
        if module.cls == 'PdgCodeFilter':
            codes, invert = filter_codes(module)
            listed = pdg in codes
            if listed != invert:
                return True
    return False


def check_invisibles(card, invisible):
    """Findings for every invisible state the card would reconstruct; empty when the card is consistent."""
    invisible = sorted({abs(int(p)) for p in invisible})
    findings = []
    path_set = set(card.execution_path)
    for name in card.execution_path:
        module = card.modules[name]
        if module.cls in CALORIMETERS:
            for pdg in invisible:
                fractions, origin, command = effective_fraction(module, pdg)
                if any(f != 0 for f in fractions):
                    findings.append({'code': 'calorimeter_deposit', 'module': name, 'pdg': pdg,
                                     'fractions': list(fractions), 'origin': origin,
                                     'line': command.line if command else None,
                                     'message': f'{name} deposits {list(fractions)} of the energy of invisible state '
                                                f'{pdg} ({origin}); it would appear as visible energy'})
        elif module.cls in GENERATOR_CONSUMERS:
            for path in generator_paths(card, name):
                if not all(p in path_set or card.modules[p].cls == 'PdgCodeFilter' for p in path):
                    continue
                for pdg in invisible:
                    for signed in (pdg, -pdg):
                        if not _removed(card, path, signed):
                            findings.append({'code': 'generator_level_includes_invisible', 'module': name, 'pdg': signed,
                                             'path': list(path),
                                             'message': f'{name} clusters generator particles through {" <- ".join(path)} '
                                                        f'without removing {signed}'})
    unique, seen = [], set()
    for f in findings:
        key = (f['code'], f['module'], f['pdg'], tuple(f.get('path', ())))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


# ---------------------------------------------------------------- derived card
def _indent(card, command):
    text = card.lines[command.line - 1]
    return text[:len(text) - len(text.lstrip())] or '  '


def derive_card(source, destination, *, invisible=(), overrides=(), keep_branches=None, reason=None):
    """Write a managed card copy and return its record (edits, diff, remaining findings)."""
    card = parse_card(source)
    destination = Path(destination)
    if destination.exists():
        raise ValueError(f'derived card already exists: {destination}')
    invisible = sorted({abs(int(p)) for p in invisible})
    edits = []        # {'line', 'action': insert-after|replace|delete, 'text', 'reason', 'module'}

    def own(command_or_module, what):
        if command_or_module.source is not None:
            raise ValueError(f'{what} is defined in sourced file {command_or_module.source}; '
                             'copy that file into the card before deriving it')

    for finding in check_invisibles(card, invisible):
        module = card.modules[finding['module']]
        if finding['code'] == 'calorimeter_deposit':
            zero = ' '.join(['0.0'] * len(finding['fractions']))
            text = f'add EnergyFraction {{{finding["pdg"]}}} {{{zero}}}'
            why = f'invisible state {finding["pdg"]} deposits no calorimeter energy'
            if finding['origin'] == 'explicit':
                command = next(c for c in module.adds('EnergyFraction') if abs(int(c.words[2])) == finding['pdg'])
                own(command, f'EnergyFraction {finding["pdg"]} in {module.name}')
                edits.append({'module': module.name, 'line': command.line, 'end_line': command.end_line,
                              'action': 'replace', 'text': _indent(card, command) + text, 'reason': why})
            else:
                anchor = (module.adds('EnergyFraction') or module.commands)
                anchor = anchor[-1] if anchor else None
                own(anchor or module, f'module {module.name}')
                line = anchor.end_line if anchor else module.line
                edits.append({'module': module.name, 'line': line, 'action': 'insert-after',
                              'text': (_indent(card, anchor) if anchor else '  ') + text, 'reason': why})
        else:
            filters = [card.modules[n] for n in finding['path'] if card.modules[n].cls == 'PdgCodeFilter']
            if not filters:
                raise ValueError(f'{finding["module"]} reads generator particles with no PdgCodeFilter on the path; '
                                 'add a filter module to the card before deriving it')
            target = filters[-1]
            if filter_codes(target)[1]:
                raise ValueError(f'{target.name} uses Invert true; edit its list by hand and declare the change')
            anchor = (target.adds('PdgCode') or target.commands)[-1]
            own(anchor, f'module {target.name}')
            edits.append({'module': target.name, 'line': anchor.end_line, 'action': 'insert-after',
                          'text': _indent(card, anchor) + f'add PdgCode {{{finding["pdg"]}}}',
                          'reason': f'generator-level jets and missing momentum exclude invisible state {finding["pdg"]}'})

    for override in overrides:
        if not isinstance(override, dict) or set(override) - {'module', 'set', 'value', 'reason'} \
                or not all(isinstance(override.get(k), str) and override[k].strip() for k in ('module', 'set', 'value', 'reason')):
            raise ValueError('an override needs module, set, value and reason')
        module = card.modules.get(override['module'])
        if module is None:
            raise ValueError(f'override names unknown module {override["module"]}')
        rows = [c for c in module.commands if c.verb == 'set' and len(c.words) >= 3 and c.words[1] == override['set']]
        value = override['value'] if override['value'].startswith('{') or ' ' not in override['value'] else '{' + override['value'] + '}'
        if rows:
            own(rows[-1], f'{override["set"]} in {module.name}')
            edits.append({'module': module.name, 'line': rows[-1].line, 'end_line': rows[-1].end_line, 'action': 'replace',
                          'text': _indent(card, rows[-1]) + f'set {override["set"]} {value}', 'reason': override['reason']})
        else:
            anchor = module.commands[-1]
            own(anchor, f'module {module.name}')
            edits.append({'module': module.name, 'line': anchor.end_line, 'action': 'insert-after',
                          'text': _indent(card, anchor) + f'set {override["set"]} {value}', 'reason': override['reason']})

    if keep_branches is not None:
        keep = set(keep_branches)
        writers = [card.modules[n] for n in card.execution_path if card.modules[n].cls == 'TreeWriter']
        if not writers:
            raise ValueError('the card has no TreeWriter module')
        present = set()
        for writer in writers:
            for c in writer.adds('Branch'):
                if len(c.words) < 5:
                    raise ValueError(f'malformed Branch in {writer.name} at line {c.line}')
                present.add(c.words[3])
                if c.words[3] not in keep:
                    own(c, f'Branch {c.words[3]}')
                    edits.append({'module': writer.name, 'line': c.line, 'end_line': c.end_line, 'action': 'delete',
                                  'text': '', 'reason': f'branch {c.words[3]} is not read by the declared analysis'})
        unknown = sorted(keep - present - {'Event', 'Weight'})
        if unknown:
            raise ValueError('kept branches are not written by the card: ' + ', '.join(unknown))

    for entry in card.sources:
        if entry['in'] is None and entry['directive'] != entry['path']:
            raw = card.lines[entry['line'] - 1]
            edits.append({'module': entry['module'], 'line': entry['line'], 'end_line': entry['line'], 'action': 'replace',
                          'text': raw[:len(raw) - len(raw.lstrip())] + f'source {entry["path"]}',
                          'reason': 'sourced file pinned by absolute path so the card runs from any directory'})

    for module in card.modules.values():
        for c in module.commands:
            if (c.source is None and c.verb == 'set' and len(c.words) == 3 and c.words[1].endswith('File')
                    and not Path(c.words[2]).is_absolute()):
                target = _resolve_source(c.words[2], card.path.parent)
                if target is not None:
                    edits.append({'module': module.name, 'line': c.line, 'end_line': c.end_line, 'action': 'replace',
                                  'text': _indent(card, c) + f'set {c.words[1]} {target}',
                                  'reason': f'{c.words[1]} pinned by absolute path so the card runs from any directory'})

    unique, seen = [], set()
    for e in edits:
        key = (e['action'], e['line'], e['text'])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    edits = unique
    for e in edits:
        if e['action'] != 'insert-after':
            e['original'] = [l.rstrip('\n') for l in card.lines[e['line'] - 1:e.get('end_line', e['line'])]]
    lines = [l.rstrip('\n') for l in card.lines]
    output = []
    replaced = {}
    inserted = {}
    for e in edits:
        if e['action'] == 'insert-after':
            inserted.setdefault(e['line'], []).append(e['text'])
        else:
            for k in range(e['line'], e.get('end_line', e['line']) + 1):
                replaced[k] = None
            replaced[e['line']] = e['text'] if e['action'] == 'replace' else None
    for number, text in enumerate(lines, 1):
        if number in replaced:
            if replaced[number] is not None:
                output.append(replaced[number])
        else:
            output.append(text)
        output.extend(inserted.get(number, []))
    body = '\n'.join(output) + ('\n' if card.text.endswith('\n') else '')
    header = f'# Derived by RAVEL from {card.path.name} (sha256 {sha256(card.path)}).\n'
    if reason:
        header += f'# Reason: {reason}\n'
    header += '# Every change is recorded in the accompanying derived-card record.\n'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x') as stream:
        stream.write(header + body)
    diff = unified_diff(card.text, header + body, str(card.path), str(destination))
    derived = parse_card(destination)
    remaining = check_invisibles(derived, invisible)
    undeclared = undeclared_changes({'diff': diff, 'edits': edits, 'header': header})
    if undeclared:
        raise ValueError('derived card differs from its source outside the recorded edits: ' + '; '.join(undeclared[:5]))
    return {'schema_version': 1, 'kind': 'ravel-derived-delphes-card',
            'source_card': {'path': str(card.path), 'sha256': sha256(card.path)},
            'derived_card': {'path': str(destination.resolve()), 'sha256': sha256(destination)},
            'invisible': invisible, 'edits': edits, 'diff': diff, 'header': header,
            'sources': card.sources, 'remaining_findings': remaining, 'consistent': not remaining}


def unified_diff(before, after, fromfile, tofile, context=3):
    """A unified diff without difflib's popular-line heuristic, so repeated lines such as '}' align."""
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = [f'--- {fromfile}\n', f'+++ {tofile}\n']
    for group in matcher.get_grouped_opcodes(context):
        i1, i2, j1, j2 = group[0][1], group[-1][2], group[0][3], group[-1][4]
        out.append(f'@@ -{i1 + 1},{i2 - i1} +{j1 + 1},{j2 - j1} @@\n')
        for tag, a1, a2, b1, b2 in group:
            if tag == 'equal':
                out += [' ' + line for line in a[a1:a2]]
                continue
            out += ['-' + line for line in a[a1:a2]]
            out += ['+' + line for line in b[b1:b2]]
    return ''.join(line if line.endswith('\n') else line + '\n' for line in out)


def diff_lines(diff):
    """Added and removed content lines of a unified diff (headers excluded)."""
    added, removed = [], []
    for line in diff.splitlines():
        if line.startswith(('+++', '---', '@@')):
            continue
        if line.startswith('+'):
            added.append(line[1:])
        elif line.startswith('-'):
            removed.append(line[1:])
    return added, removed


def undeclared_changes(record):
    """Nonblank diff lines that no recorded edit (or the provenance header) accounts for."""
    diff, edits, header = record['diff'], record['edits'], record.get('header', '')
    added, removed = diff_lines(diff)
    allowed_added = {e['text'].strip() for e in edits if e['text'].strip()} | {l.strip() for l in header.splitlines()}
    allowed_removed = {l.strip() for e in edits for l in e.get('original', [])}
    return ([f'added {l.strip()!r}' for l in added if l.strip() and l.strip() not in allowed_added]
            + [f'removed {l.strip()!r}' for l in removed if l.strip() and l.strip() not in allowed_removed])


def tree_branches(card):
    out = []
    for name in card.execution_path:
        module = card.modules[name]
        if module.cls == 'TreeWriter':
            out += [c.words[3] for c in module.adds('Branch') if len(c.words) >= 5]
    return out


# ---------------------------------------------------------------- invisible census
def _parse_slha(text):
    try:
        from ravel.physics.simplified_spectrum import parse_slha
        return parse_slha(text)
    except ImportError:
        pass
    blocks, decays, current = {}, {}, None
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        tokens = line.split()
        head = tokens[0].upper()
        if head == 'BLOCK':
            current = ('block', tokens[1].upper())
            blocks[current[1]] = {'entries': {}}
        elif head == 'DECAY':
            current = ('decay', int(tokens[1]))
            decays[current[1]] = {'width': float(tokens[2].replace('d', 'e').replace('D', 'E')), 'channels': []}
        elif current is None:
            continue
        elif current[0] == 'block':
            if current[1] == 'MASS' and len(tokens) >= 2:
                blocks['MASS']['entries'][(int(tokens[0]),)] = float(tokens[1].replace('d', 'e').replace('D', 'E'))
        else:
            nda = int(tokens[1])
            decays[current[1]]['channels'].append((float(tokens[0]), tuple(int(t) for t in tokens[2:2 + nda])))
    return {'blocks': blocks, 'decays': decays}


def invisible_census(model, base=None):
    """The invisible set of a model and the evidence for it.

    ``model`` declares ``invisible`` (PDG codes of stable states that leave no signal) and
    may declare ``visible_stable`` (stable states the detector does see), ``slha`` (a
    spectrum whose decay tables are checked), ``produced`` (hard-process states, to limit
    the census to the decay chains they start) and ``closure_report`` (the JSON written by
    the simplified-spectrum decay-closure check, whose ``invisible_census`` must be declared).
    """
    if not isinstance(model, dict):
        raise ValueError('model must be an object')
    base = Path(base) if base is not None else Path.cwd()
    invisible = model.get('invisible')
    if not isinstance(invisible, list) or any(type(p) is not int for p in invisible):
        raise ValueError('model.invisible must list the PDG codes of the stable invisible states (it may be empty)')
    visible = model.get('visible_stable', [])
    if not isinstance(visible, list) or any(type(p) is not int for p in visible):
        raise ValueError('model.visible_stable must be a list of PDG codes')
    invisible_set = {abs(p) for p in invisible}
    visible_set = {abs(p) for p in visible}
    if invisible_set & visible_set:
        raise ValueError(f'states declared both invisible and visible: {sorted(invisible_set & visible_set)}')
    evidence = {'declared_invisible': sorted(invisible_set), 'declared_visible_stable': sorted(visible_set)}
    errors = []
    if model.get('slha'):
        path = Path(model['slha'])
        path = path if path.is_absolute() else base / path
        doc = _parse_slha(path.read_text())
        decays = doc['decays']
        masses = {k[0] for k in doc['blocks'].get('MASS', {}).get('entries', {}) if len(k) == 1}
        bsm_declared = model.get('bsm_pdgs', [])
        produced = [abs(int(p)) for p in model.get('produced', [])]
        if produced:
            stable, seen, queue = set(), set(), list(produced)
            while queue:
                pdg = abs(queue.pop(0))
                if pdg in seen:
                    continue
                seen.add(pdg)
                table = decays.get(pdg)
                if table is None or (table['width'] == 0 and not table['channels']):
                    if is_bsm(pdg, bsm_declared):
                        stable.add(pdg)
                    continue
                for br, daughters in table['channels']:
                    if br > 0:
                        queue.extend(daughters)
        else:
            stable = {abs(p) for p in masses if is_bsm(p, bsm_declared)
                      and (abs(p) not in decays or (decays[abs(p)]['width'] == 0 and not decays[abs(p)]['channels']))}
        for pdg in sorted(invisible_set):
            table = decays.get(pdg)
            if table is not None and (table['width'] > 0 or table['channels']):
                errors.append(f'declared invisible state {pdg} decays in the SLHA card (width {table["width"]:g})')
        undeclared = sorted(stable - invisible_set - visible_set)
        if undeclared:
            errors.append('stable BSM states are neither declared invisible nor declared visible: '
                          + ', '.join(map(str, undeclared)))
        evidence['slha'] = {'path': str(path.resolve()), 'sha256': sha256(path), 'stable_bsm': sorted(stable),
                            'census_from': 'decay chains of the produced states' if produced else 'every BSM state in MASS'}
    if model.get('closure_report'):
        path = Path(model['closure_report'])
        path = path if path.is_absolute() else base / path
        report = json.loads(path.read_text())
        closure = report.get('closure', report)
        if closure.get('passed') is False:
            errors.append('the decay-closure report did not pass')
        census = {abs(int(p)) for p in closure.get('invisible_census', [])}
        stable = {abs(int(p)) for p in closure.get('stable_census', [])}
        missing = sorted(census - invisible_set)
        if missing:
            errors.append('the decay-closure report lists invisible states that are not declared: ' + ', '.join(map(str, missing)))
        undeclared = sorted({p for p in stable if is_bsm(p)} - invisible_set - visible_set)
        if undeclared:
            errors.append('stable BSM states in the closure report are not declared: ' + ', '.join(map(str, undeclared)))
        evidence['closure_report'] = {'path': str(path.resolve()), 'sha256': sha256(path),
                                      'invisible_census': sorted(census), 'stable_census': sorted(stable)}
    if errors:
        raise ValueError('invisible-state census refused: ' + '; '.join(errors))
    return {'invisible': sorted(invisible_set), 'visible_stable': sorted(visible_set), 'evidence': evidence}


def hepmc_census(path, *, max_events=None, bsm_pdgs=()):
    """Stable (status 1) BSM PDG codes and their counts in a HepMC2/3 ASCII file (plain or gzip)."""
    opener = gzip.open if str(path).endswith('.gz') else open
    counts, events = {}, 0
    with opener(path, 'rt') as stream:
        for raw in stream:
            if raw.startswith('E '):
                events += 1
                if max_events is not None and events > max_events:
                    events -= 1
                    break
            elif raw.startswith('P '):
                fields = raw.split()
                # HepMC3: P id parent pdg px py pz e m status ; HepMC2: P barcode pdg px py pz e m status ...
                if len(fields) >= 10 and fields[1].isdigit() and len(fields) == 10:
                    pdg, status = int(fields[3]), int(fields[9])
                else:
                    pdg, status = int(fields[2]), int(fields[8])
                if status == 1 and is_bsm(pdg, bsm_pdgs):
                    counts[abs(pdg)] = counts.get(abs(pdg), 0) + 1
    return {'events_read': events, 'stable_bsm': {str(k): v for k, v in sorted(counts.items())}}


def gate(card_path, census):
    """Consistency of one card with an invisible census (no files written)."""
    card = parse_card(card_path)
    findings = check_invisibles(card, census['invisible'])
    return {'card': {'path': str(card.path), 'sha256': sha256(card.path)}, 'invisible': census['invisible'],
            'consistent': not findings, 'findings': findings}


# ---------------------------------------------------------------- command line
def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel detector-card', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check', help='refuse a card that would reconstruct a declared invisible state')
    check.add_argument('card')
    check.add_argument('--invisible', type=int, action='append', default=[])
    check.add_argument('--model', help='model JSON with invisible, visible_stable, slha, produced, closure_report')
    derive = sub.add_parser('derive', help='write a managed derived card with every change recorded')
    derive.add_argument('card')
    derive.add_argument('--output', required=True)
    derive.add_argument('--record', required=True)
    derive.add_argument('--invisible', type=int, action='append', default=[])
    derive.add_argument('--model')
    derive.add_argument('--keep-branch', action='append')
    derive.add_argument('--overrides', help='JSON list of {module, set, value, reason}')
    branches = sub.add_parser('branches', help='list the branches the card writes')
    branches.add_argument('card')
    census_parser = sub.add_parser('hepmc-census', help='stable BSM states in showered events')
    census_parser.add_argument('events')
    census_parser.add_argument('--max-events', type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == 'branches':
            print(json.dumps(tree_branches(parse_card(args.card)), indent=2))
            return 0
        if args.command == 'hepmc-census':
            print(json.dumps(hepmc_census(args.events, max_events=args.max_events), indent=2))
            return 0
        if args.model:
            path = Path(args.model)
            census = invisible_census(json.loads(path.read_text()), path.parent)
        else:
            census = invisible_census({'invisible': args.invisible})
        if args.command == 'check':
            report = gate(args.card, census)
            print(json.dumps(report, indent=2))
            return 0 if report['consistent'] else 1
        overrides = json.loads(Path(args.overrides).read_text()) if args.overrides else []
        record = derive_card(args.card, args.output, invisible=census['invisible'], overrides=overrides,
                             keep_branches=args.keep_branch)
        record['census'] = census
        Path(args.record).write_text(json.dumps(record, indent=2) + '\n')
        print(record['diff'])
        return 0 if record['consistent'] else 1
    except (OSError, ValueError) as exc:
        print(f'detector-card: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
