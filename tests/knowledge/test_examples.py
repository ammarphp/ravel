"""Operation-card curation: every science mode has use_when, do_not_use_when and a parseable example.

Examples are parsed against the ravel command-line parser and validated by their adapter; nothing runs.
Curation text is held out from the tool-selection battery: a digest check refuses any copied battery phrase.
"""
import copy
import hashlib
import json
import re
import shlex
from pathlib import Path

import pytest

from ravel.cli import parser
from ravel.setup import manifest as mf
from ravel.validation.check_knowledge import validate
from ravel.workflow import knowledge_atlas as ka
from ravel.workflow.science import MODES, adapter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CURATION = ROOT / 'src/ravel/data/knowledge/curation'
BATTERY_DIRS = (HERE / 'tool_selection',)
EXCLUSIONS = HERE / 'curation_exclusions.json'
SHINGLE = 8
FIELDS = ('use_when', 'do_not_use_when', 'examples')


@pytest.fixture(scope='module')
def atlas():
    return ka.generate(ROOT)


def science_modes(atlas):
    return [r for r in atlas['entries'] if r['kind'] == 'op' and r['catalogue']['kind'] == 'science-mode']


def _words(text):
    return re.findall(r'[a-z0-9][a-z0-9\-+.]*', text.casefold())


def shingle_digests(text, size=SHINGLE):
    words = _words(text)
    return {hashlib.sha256(' '.join(words[i:i + size]).encode()).hexdigest() for i in range(len(words) - size + 1)}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def battery_files():
    return sorted(p for d in BATTERY_DIRS for p in d.rglob('*.json'))


def battery_digests():
    """Shingle digests of every string in the battery plans, from disk and from the committed list."""
    digests = set(json.loads(EXCLUSIONS.read_text())['shingle_sha256']) if EXCLUSIONS.is_file() else set()
    for path in battery_files():
        digests |= shingle_digests('\n'.join(_strings(json.loads(path.read_text()))))
    return digests


def curation_hits(texts, digests):
    return sorted(name for name, text in texts.items() if shingle_digests(text) & digests)


def curation_texts():
    return {p.name: p.read_text() for p in sorted(CURATION.glob('*.json'))}


# 1. every mode carries all three curated fields -------------------------------------------------
def test_every_mode_has_curated_fields(atlas):
    modes = science_modes(atlas)
    # The agent-visible atlas withholds the operations of unqualified tools (d8b96be); their
    # curation stays in the source tree and is checked below against the full MODES list.
    assert {r['id'] for r in modes} == {'op:' + m for m in MODES if m not in mf.unreleased_operations(mf.load(ROOT)[0])}
    for row in modes:
        op = row['op']
        assert op['use_when'] and op['do_not_use_when'], row['id']
        assert op['examples'], row['id']
        assert row['curation_source']['path'].startswith('src/ravel/data/knowledge/curation/'), row['id']
    assert validate(ROOT, atlas) == []


@pytest.mark.parametrize('field', FIELDS)
def test_missing_field_fails_check_knowledge(atlas, field, monkeypatch):
    monkeypatch.setattr('ravel.validation.check_knowledge.generate', lambda root: atlas)
    broken = copy.deepcopy(atlas)
    victim = science_modes(broken)[0]
    victim['op'][field] = []
    errors = validate(ROOT, broken)
    assert any(victim['id'] in e and ('curation requires' in e) for e in errors), errors


def test_do_not_use_when_is_named_in_the_error(atlas, monkeypatch):
    monkeypatch.setattr('ravel.validation.check_knowledge.generate', lambda root: atlas)
    broken = copy.deepcopy(atlas)
    victim = science_modes(broken)[0]
    victim['op']['do_not_use_when'] = []
    assert any('do_not_use_when' in e for e in validate(ROOT, broken))


# 2. each example is a valid ravel command line and a valid adapter task -------------------------
def _parse(command):
    argv = shlex.split(command)
    assert argv[0] == 'ravel', command
    return parser().parse_args(argv[1:])


def test_every_example_parses_as_a_ravel_command(atlas):
    for row in science_modes(atlas):
        mode = row['id'][3:]
        for example in row['op']['examples']:
            assert example.get('command'), row['id']
            args = _parse(example['command'])
            assert args.command == 'plan', row['id']
            assert Path(args.spec).stem == mode, row['id']
            assert example['spec']['mode'] == mode
            adapter(example['spec']).validate(example['spec']['task'])


@pytest.mark.parametrize('command', ['ravel plan --rundir runs/x', 'ravel absent-subcommand --spec s.json', 'ravel plan --spec s.json',
                                     'ravel plan --rundir runs/x --spec s.json --unknown-flag'])
def test_an_unparseable_command_is_refused(command):
    with pytest.raises(SystemExit):
        _parse(command)


# 3. cross-references name registered modes ------------------------------------------------------
def test_pointers_to_other_modes_resolve(atlas):
    pointer = re.compile(r'\buse ([a-z0-9]+(?:-[a-z0-9]+)+)')
    for row in science_modes(atlas):
        for text in row['op']['do_not_use_when']:
            for name in pointer.findall(text):
                assert name in MODES, (row['id'], name)
                assert name != row['id'][3:], row['id']


def test_a_released_mode_points_to_no_withheld_mode(atlas):
    """A release withholds some modes; the curation of a mode it ships never sends the reader to one."""
    held = mf.unreleased_operations(mf.load(ROOT)[0])
    pointer = re.compile(r'\buse ([a-z0-9]+(?:-[a-z0-9]+)+)')
    for row in science_modes(atlas):
        if row['id'][3:] in held:
            continue
        for text in row['op']['do_not_use_when']:
            assert not set(pointer.findall(text)) & held, (row['id'], text)


# 4. battery plans were not used ------------------------------------------------------------------
def test_curation_sources_exclude_the_battery(atlas):
    battery = {p.relative_to(ROOT).as_posix() for p in battery_files()}
    assert battery
    for row in science_modes(atlas):
        source = row['curation_source']['path']
        assert source not in battery and 'tool_selection' not in source, row['id']
    assert {p.name for p in CURATION.glob('*.json')} == {m + '.json' for m in MODES}


def test_no_battery_phrase_in_curation():
    digests = battery_digests()
    assert digests
    assert curation_hits(curation_texts(), digests) == []


def test_exclusion_list_records_the_battery_files():
    listing = json.loads(EXCLUSIONS.read_text())
    assert listing['battery_files'], 'the exclusion list names the battery files'
    for item in listing['battery_files']:
        assert item['path'].startswith('tests/knowledge/tool_selection/') and re.fullmatch('[0-9a-f]{64}', item['sha256'])
    assert listing['shingle_size'] == SHINGLE
    assert all(re.fullmatch('[0-9a-f]{64}', d) for d in listing['shingle_sha256'])


def test_a_planted_battery_phrase_fails_the_check():
    plans = json.loads((HERE / 'tool_selection/siblings.json').read_text())['plans']
    phrase = ' '.join(_words(plans[0]['request'])[:SHINGLE + 2])
    texts = curation_texts()
    name = sorted(texts)[0]
    texts[name] = texts[name].replace('"use_when": [', '"use_when": [\n  "' + phrase + '",', 1)
    assert phrase in texts[name]
    assert curation_hits(texts, battery_digests()) == [name]


# 5. the committed atlas carries the curated fields ------------------------------------------------
def test_committed_atlas_matches_regeneration(atlas):
    assert ka.encode(atlas) == (ROOT / ka.ATLAS).read_bytes()
