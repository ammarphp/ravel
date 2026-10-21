"""Exact P04 input-copy handoff, with composed cards and inert copied-byte custody."""
import ast
import hashlib
from pathlib import Path
import re
import subprocess

import pytest

from ravel.workflow import role_registry

ROOT = Path(__file__).resolve().parents[3]
PATCH = ROOT / 'tests/fixtures/peer_contracts/input-screen.patch'
CARDS = sorted(role_registry.all_cards(), key=lambda card: card['id'])


def _existing_canaries():
    """Use the named path canaries already declared by the P13 screening controls."""
    source = (Path(__file__).with_name('test_p13_review_independence.py')).read_text()
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'test_ROLE_sees_every_card_is_screenable_on_the_classes_it_forbids')
    assignment = next(node for node in function.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'planted' for target in node.targets))
    return ast.literal_eval(assignment.value)


CANARIES = _existing_canaries()
FORBIDDENS = [(card['id'], kind, CANARIES[kind]) for card in CARDS
              for kind in card['sees'].get('forbidden_inputs', []) if kind in CANARIES]


@pytest.fixture
def copier(tmp_path):
    """Rebuild the exact preimage hunks, apply the handoff, then load only its function."""
    lines = PATCH.read_text().splitlines(keepends=True)
    hunks = []
    for line in lines:
        match = re.match(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', line)
        if match:
            hunks.append((tuple(map(int, match.groups())), []))
        elif hunks and line[:1] in (' ', '+', '-') and not line.startswith(('--- ', '+++ ')):
            hunks[-1][1].append(line)
    source = []
    for (old_start, old_count, _, _), body in hunks:
        before = [line[1:] for line in body if line[:1] in (' ', '-')]
        assert len(before) == old_count
        source.extend(['\n'] * (old_start - 1 - len(source)))
        source.extend(before)
    copied = tmp_path / 'peer'
    path = copied / 'src/ravel/controller/step/graph.py'
    path.parent.mkdir(parents=True)
    path.write_text(''.join(source))
    applied = subprocess.run(['patch', '--batch', '-p1', '-d', str(copied), '-i', str(PATCH)],
                             capture_output=True, text=True, check=False)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert 'fuzz' not in applied.stdout
    (_, _, start, count), _ = hunks[0]
    function = ''.join(path.read_text().splitlines(keepends=True)[start - 1:start - 1 + count])
    writes = []
    class StepHold(ValueError):
        def __init__(self, code, message, *, evidence=None):
            super().__init__(message)
            self.code, self.evidence = code, evidence
    namespace = {'Path': Path, 'hashlib': hashlib, 'StepHold': StepHold,
                 '_write_once': lambda path, raw: writes.append((path, raw))}
    exec(compile(function, str(path), 'exec'), namespace)
    # The second exact hunk passes the actual card identity into this function.
    changed = [line[1:].strip() for line in hunks[1][1] if line.startswith('+')]
    assert any("_copy_inputs(run_dir, folder, rows, role=card['id'])" in line for line in changed)
    return namespace['_copy_inputs'], StepHold, writes


def row(root, artifact, raw=b'{"value": 17}\n', *, destination=None):
    source = artifact if destination is None else destination
    path = root / source
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    value = {'artifact': artifact, 'sha256': hashlib.sha256(raw).hexdigest(), 'kind': 'run-input'}
    if destination is not None:
        value.update(kind='custody', custody={'destination': destination})
    return value


@pytest.mark.parametrize('card', CARDS, ids=lambda card: card['id'])
def test_CF09_ROLE_sees_every_card_copies_safe_bytes_without_changing_their_pin(copier, tmp_path, card):
    copy, _, writes = copier
    original = row(tmp_path, 'inputs/model.json')
    pins = copy(tmp_path, Path('worker-inputs'), [original], role=card['id'])
    target = Path('worker-inputs/artifacts/000/model.json')
    assert writes == [(tmp_path / target, b'{"value": 17}\n')]
    assert pins == [{'pin': {'path': target.as_posix(), 'sha256': original['sha256']},
                     'as': 'inputs/artifacts/000/model.json'}]


@pytest.mark.parametrize('role,kind,path', FORBIDDENS, ids=[f'{r}:{k}' for r, k, _ in FORBIDDENS])
def test_CF09_ROLE_sees_forbidden_canary_never_copies_any_part_of_the_batch(copier, tmp_path, role, kind, path):
    copy, StepHold, writes = copier
    rows = [row(tmp_path, 'inputs/model.json'), row(tmp_path, path)]
    with pytest.raises(StepHold) as held:
        copy(tmp_path, Path('worker-inputs'), rows, role=role)
    assert held.value.code == 'forbidden_input'
    # This role forbids outputs through two classes; the classifier reports
    # the earlier first_method match for the producer_numbers path canary.
    expected = 'first_method' if (role, kind) == ('second-method-deriver', 'producer_numbers') else kind
    assert any(item['path'] == path and item['class'] == expected for item in held.value.evidence['removed'])
    assert writes == []


@pytest.mark.parametrize('artifact,destination', [
    ('producer:inputs/first_derivation.json', 'inputs/renamed.json'),
    ('producer:inputs/model.json', 'steps/producer/outputs/first_derivation.json'),
])
def test_CF09_first_method_custody_renaming_cannot_hide_the_original_or_source_path(
        copier, tmp_path, artifact, destination):
    copy, StepHold, writes = copier
    rows = [row(tmp_path, 'inputs/model.json'), row(tmp_path, artifact, destination=destination)]
    with pytest.raises(StepHold) as held:
        copy(tmp_path, Path('worker-inputs'), rows, role='second-method-deriver')
    assert held.value.code == 'forbidden_input'
    assert any(item['class'] == 'first_method' for item in held.value.evidence['removed'])
    assert writes == []


def test_CF09_workspace_trainer_embedded_truth_refuses_without_rewriting_its_digest(copier, tmp_path):
    copy, StepHold, writes = copier
    rows = [row(tmp_path, 'inputs/model.json'),
            row(tmp_path, 'producer:inputs/train.json', b'{"features": [1], "metadata": {"truth": [0]}}\n',
                destination='steps/producer/train.json')]
    with pytest.raises(StepHold) as held:
        copy(tmp_path, Path('worker-inputs'), rows, role='ml-trainer')
    assert held.value.code == 'forbidden_input'
    assert held.value.evidence['path'] == 'inputs/train.json'
    assert held.value.evidence['removed']
    assert writes == []


def test_CF09_last_row_digest_failure_leaves_the_entire_batch_uncopied(copier, tmp_path):
    copy, StepHold, writes = copier
    rows = [row(tmp_path, 'inputs/model.json'), row(tmp_path, 'inputs/train.json')]
    rows[-1]['sha256'] = '0' * 64
    with pytest.raises(StepHold) as held:
        copy(tmp_path, Path('worker-inputs'), rows, role='ml-trainer')
    assert held.value.code == 'input_changed'
    assert writes == []
