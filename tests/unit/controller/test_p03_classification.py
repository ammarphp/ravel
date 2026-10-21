"""Conservative duty and exact citation resolution regression controls."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ravel.controller import instructions as ins
from ravel.controller.instructions import catalogue, compiler


@pytest.mark.parametrize('text', [
    'The result is ready. Record the verdict in `RESULT.md`.',
    'Every quoted number gets traced to its artifact; an untraceable claim is an automatic failure.',
    '- Final report: record the verdict and its evidence.',
    'Background material with an unreviewed classification.',
])
def test_unreviewed_prose_is_always_duty(text):
    assert compiler.is_duty(text)
    assert compiler.is_duty('Never skip approval.')  # positive control


@pytest.mark.parametrize('source,needle', [
    ('docs/workflow/steps/09-verify.md', 'automatic'),
    ('.claude/skills/certify/SKILL.md', 'Record the verdict'),
])
def test_actual_embedded_duties_cannot_be_deferred(monkeypatch, source, needle):
    cat = catalogue.installed()
    selected = [u for u in cat.by_source[source] if needle.lower() in u['text'].lower()]
    assert selected
    step = {'id': 's1', 'instruction_sources': [source]}
    manifest = ins.manifest(step, None)
    monkeypatch.setitem(cat.manifests['packet'], 'inline_tokens', 1)
    packet = ins.packet(manifest, None, step, [])
    for unit in selected:
        assert unit['kind'] == 'duty'
        assert unit['id'] in packet['units'] and unit['id'] not in packet['deferred']
        record = {'instruction_ack': {'manifest_sha256': manifest['sha256']},
                  'checklist': [{'unit': e['id'], 'status': 'not_applicable', 'note': 'Outside this operation.'}
                                for e in manifest['units'] if e['kind'] == 'duty' and e['id'] != unit['id']]}
        assert any(e.startswith('missing: ' + unit['id']) for e in ins.check_ack(manifest, record, []))


@pytest.mark.parametrize('replacement', [
    '# Guide\n\nUnrelated background.\n', '# Guide\n',
    '# Guide\n\nNever skip approval.\n\nNever skip approval.\n',
])
def test_stale_citation_never_rebinds_by_line(replacement):
    original = '# Guide\n\nNever skip approval.\n'
    row = {'id': 'D1', 'source': 'guide.md', 'line': 3, 'decision': True,
           'source_sha256': hashlib.sha256(original.encode()).hexdigest(), 'evidence': 'Never skip approval.'}
    units = compiler.compile_markdown('guide.md', original)
    compiler.attach_census(units, [row], {'guide.md': original})
    assert any('D1' in u.get('census', []) for u in units)
    with pytest.raises(ValueError, match='citation'):
        compiler.attach_census(compiler.compile_markdown('guide.md', replacement), [row], {'guide.md': replacement})


def test_unique_quote_resolves_a_moved_citation():
    text = '# Guide\n\nBackground.\n\nNever skip approval.\n'
    units = compiler.compile_markdown('guide.md', text)
    compiler.attach_census(units, [{'id': 'D1', 'source': 'guide.md', 'line': 3,
        'source_sha256': 'old', 'evidence': 'Never skip approval.', 'decision': True}], {'guide.md': text})
    attached = [u for u in units if 'D1' in u.get('census', [])]
    assert len(attached) == 1 and attached[0]['text'] == 'Never skip approval.'


def test_no_second_family_acceptance_has_no_allowlist():
    assert catalogue.family_mandates(catalogue.installed()) == []


def test_only_digest_bound_reviewed_context_may_be_deferred(tmp_path):
    source = tmp_path / 'guide.md'
    source.write_text('# Guide\n\nLayout background.\n')
    sources = {'schema_version': 1, 'kind': 'instruction-sources', 'discover': ['*.md'],
               'canonical': [{'path': 'guide.md', 'kind': 'workflow-doc', 'nodes': ['worker']}],
               'mirrors': [], 'reviewed_context': [
                   {'id': 'guide.md#guide/1', 'sha256': compiler.digest_text('Layout background.'),
                    'kind': 'context', 'reviewed_by': 'package-review', 'reason': 'Description without a duty.'}]}
    built = compiler.build(tmp_path, sources, cards=[])
    assert built['units'][1]['kind'] == 'context'
    source.write_text('# Guide\n\nRecord every result.\n')
    with pytest.raises(ValueError, match='context'):
        compiler.build(tmp_path, sources, cards=[])


def test_whole_file_citation_requires_the_source_pin():
    text = '# Unrelated\n\nReplacement instructions.\n'
    with pytest.raises(ValueError, match='citation'):
        compiler.attach_census(compiler.compile_markdown('guide.md', text),
                              [{'id': 'D1', 'source': 'guide.md', 'line': 1, 'source_sha256': 'old'}],
                              {'guide.md': text})


@pytest.mark.parametrize('damage', ['missing-review', 'stale-pin', 'blank-reviewer', 'blank-reason', 'changed-text'])
def test_loaded_context_requires_reviewed_data(damage):
    cat = catalogue.installed()
    document, manifests = deepcopy(cat.document), deepcopy(cat.manifests)
    unit = document['units'][0]
    unit['kind'] = 'context'
    review = {'id': unit['id'], 'sha256': unit['sha256'], 'kind': 'context',
              'reviewed_by': 'fixture-review', 'reason': 'Fixture context decision.'}
    unit['context_review'] = review
    if damage == 'missing-review':
        del unit['context_review']
    elif damage == 'stale-pin':
        review['sha256'] = '0' * 64
    elif damage == 'blank-reviewer':
        review['reviewed_by'] = ' '
    elif damage == 'changed-text':
        unit['text'].append('Record approval before every operation.')
    else:
        review['reason'] = ''
    with pytest.raises(ValueError, match='context'):
        catalogue.Catalogue(document, manifests)


def test_reviewed_citation_migration_is_pinned_to_its_replacement():
    original = '# Guide\n\nNever skip approval.\n'
    current = '# Guide\n\nRecord approval before any operation.\n'
    units = compiler.compile_markdown('guide.md', current)
    target = units[1]
    row = {'id': 'D1', 'source': 'guide.md', 'line': 3,
           'source_sha256': hashlib.sha256(original.encode()).hexdigest(), 'evidence': 'Never skip approval.',
           'migration': {'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
                         'units': {target['id']: compiler.digest_text(target['text'])},
                         'reviewed_by': 'fixture-review', 'reason': 'Same prerequisite with explicit recording.'}}
    compiler.attach_census(units, [row], {'guide.md': current})
    assert 'D1' in units[1]['census']
    changed = current.replace('Record approval before any operation.', 'Background only.')
    with pytest.raises(ValueError, match='citation'):
        compiler.attach_census(compiler.compile_markdown('guide.md', changed), [row], {'guide.md': changed})
