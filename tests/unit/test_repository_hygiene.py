"""Public navigation checks must resolve exact paths without basename guessing."""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('repository_hygiene', REPO / 'scripts/check_repository.py')
hygiene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hygiene)


def write(root, relative, text='fixture'):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def fixture_registry():
    """The real registry in its exported form: without undistributed declarations, whose files a
    fixture tree does not carry."""
    registry = json.loads((REPO / 'distribution.json').read_text())
    return json.dumps(hygiene.evidence_layout.public_registry(registry), indent=2) + '\n'


@pytest.fixture
def repo(tmp_path):
    write(tmp_path, 'distribution.json', fixture_registry())
    return tmp_path


def test_relative_link_does_not_search_for_the_same_basename_elsewhere(repo):
    write(repo, 'docs/topic.md', '# Topic\n')
    write(repo, 'docs/reference/guide.md', '# Guide\n')
    assert hygiene.check_link(repo, 'docs/topic.md', 'guide.md')
    assert hygiene.check_link(repo, 'docs/topic.md', 'reference/guide.md') is None


def test_wrong_filename_case_fails_on_case_sensitive_and_insensitive_filesystems(repo):
    write(repo, 'docs/reference/guide.md', '# Guide\n')
    assert hygiene.check_link(repo, 'README.md', 'docs/reference/Guide.md')
    assert hygiene.check_link(repo, 'README.md', 'Docs/reference/guide.md')
    assert hygiene.check_link(repo, 'README.md', 'docs/reference/guide.md') is None


def test_decoded_local_paths_and_heading_anchors(repo):
    write(repo, 'docs/reference/a guide.md', '# Setup\n\n## Setup\n\n<a id="explicit"></a>\n')
    for fragment in ('setup', 'setup-1', 'explicit'):
        assert hygiene.check_link(repo, 'README.md', 'docs/reference/a%20guide.md#' + fragment) is None
    assert 'heading' in hygiene.check_link(repo, 'README.md', 'docs/reference/a%20guide.md#missing')
    assert hygiene.check_link(repo, 'README.md', '../outside.md')


def test_public_root_is_explicit_and_does_not_include_private_archives(repo):
    (repo / 'notes').mkdir()
    assert not hygiene.check(repo, public=False)[0]
    assert any('notes: forbidden public root' in e for e in hygiene.check(repo, public=True)[0])
    registry = json.loads((repo / 'distribution.json').read_text())
    registry['distribution']['trees'].append('notes')
    (repo / 'distribution.json').write_text(json.dumps(registry))
    assert any('notes: forbidden public root' in e for e in hygiene.check(repo, public=True)[0])
    (repo / 'notes').rmdir()
    (repo / '.venv-replay').mkdir()
    (repo / 'dist').mkdir()
    (repo / 'build').mkdir()
    write(repo, 'local-runs/replay-example/results.json', '{}')
    write(repo, 'logs/hook-probe.log', 'local hook output')
    assert not hygiene.check(repo, public=True)[0]
    (repo / 'trial-runs').mkdir()
    write(repo, 'export-provenance.json', '{}')
    assert any('trial-runs: forbidden public root' in e for e in hygiene.check(repo)[0])


def test_links_resolve_exactly_with_no_alias_layout(repo):
    write(repo, 'docs/records/summary.md', '# Summary\n')
    write(repo, 'docs/guide.md', '[Summary](records/summary.md)\n')
    assert hygiene.check_link(repo, 'docs/guide.md', 'records/summary.md') is None
    assert hygiene.check_link(repo, 'docs/guide.md', 'records/summary.md', public=True) is None
    assert not hygiene.check(repo)[0]
    # A nearby invented path is not a valid alternative.
    assert hygiene.check_link(repo, 'docs/guide.md', 'records/another-summary.md')


def test_source_navigation_cannot_depend_on_unshipped_files(repo):
    write(repo, 'private.md', '# Not part of this repository\n')
    write(repo, 'README.md', '[Private](private.md)\n')
    errors, _ = hygiene.check(repo)
    assert any('absent from the public selection' in error for error in errors)


def test_backticked_labels_are_still_checked():
    assert hygiene.markdown_links('[`named-file`](missing-file.md)') == [(1, 'missing-file.md')]


def test_source_and_document_naming_rules_keep_recognized_entrypoints(repo):
    write(repo, 'src/ravel/physics/BadName.py')
    write(repo, 'native/scripts/build_native.sh')
    write(repo, 'docs/old_style.md')
    write(repo, 'docs/README.md')
    errors, _ = hygiene.check(repo)
    assert len(errors) == 3
    assert any('snake_case' in e for e in errors)
    assert not any('README.md' in e for e in errors)


def test_markdown_parser_ignores_examples_but_checks_real_reference_and_image_links():
    text = '''# Guide
`[not a link](example.md)`
```markdown
[also an example](missing.md)
```
<!-- [commented out](comment.md) -->
[real](real.md#section)
![figure](<a%20figure.png>)
[reference]: destination.md "Title"
'''
    assert {target for _, target in hygiene.markdown_links(text)} == {
        'real.md#section', 'a%20figure.png', 'destination.md'}
    assert 'setext-title' in hygiene.heading_ids('Setext title\n============\n')
    assert 'hidden' not in hygiene.heading_ids('<!--\n# Hidden\n-->\n# Visible\n')


def instruction_pair(repo, text='[Guide](research/guide.md)\n'):
    logical = 'docs/cli.md'
    mirror = 'src/ravel/data/workflow/' + logical
    write(repo, logical, text)
    write(repo, mirror, text)
    write(repo, 'docs/research/guide.md', '# Guide\n')
    return logical, mirror


def test_declared_byte_exact_instruction_mirror_uses_logical_navigation(repo):
    logical, mirror = instruction_pair(repo)
    assert hygiene.navigation_document(repo, mirror) == logical
    errors, counts = hygiene.check(repo)
    assert not errors
    assert counts['canonical_workflow_mirrors'] == 1
    # Logical-source navigation is not installed-wheel browser-link closure.
    assert hygiene.check_link(repo, mirror, 'research/guide.md')
    assert hygiene.check_link(repo, logical, 'research/guide.md') is None


@pytest.mark.parametrize('changed', ['canonical', 'mirror'])
def test_instruction_mirror_requires_exact_canonical_bytes(repo, changed):
    logical, mirror = instruction_pair(repo)
    write(repo, logical if changed == 'canonical' else mirror, '# Different\n')
    errors, _ = hygiene.check(repo)
    assert any('differs from canonical source' in error for error in errors)


@pytest.mark.parametrize('missing', ['canonical', 'mirror'])
def test_instruction_mirror_requires_both_regular_files(repo, missing):
    logical, mirror = instruction_pair(repo)
    (repo / (logical if missing == 'canonical' else mirror)).unlink()
    with pytest.raises(FileNotFoundError):
        hygiene.navigation_document(repo, mirror)


def test_undeclared_packaged_document_is_not_exempt(repo):
    write(repo, 'src/ravel/data/workflow/docs/invented.md', '[Missing](missing.md)\n')
    errors, _ = hygiene.check(repo)
    assert any('undeclared packaged workflow instruction' in error for error in errors)


def test_canonical_instruction_itself_must_be_selected(repo, monkeypatch):
    logical, mirror = instruction_pair(repo)
    monkeypatch.setattr(hygiene.evidence_layout, 'selected_files',
                        lambda _root, include_internal=False: [(mirror, mirror)])
    errors, _ = hygiene.check(repo)
    assert any('canonical instruction is absent from the public selection' in error for error in errors)


@pytest.mark.parametrize('defect', ['missing', 'private', 'case', 'fragment'])
def test_authenticated_mirror_keeps_destination_and_heading_guards(repo, defect):
    target = {'missing': 'research/missing.md', 'private': '../private.md',
              'case': 'research/Guide.md', 'fragment': 'research/guide.md#missing'}[defect]
    instruction_pair(repo, f'[Guide]({target})\n')
    if defect == 'private':
        write(repo, 'private.md', '# Private\n')
    errors, _ = hygiene.check(repo)
    assert errors
    if defect == 'private':
        assert any('absent from the public selection' in error for error in errors)


def test_symlinked_mirror_cannot_gain_logical_projection(repo):
    logical, mirror = instruction_pair(repo)
    (repo / mirror).unlink()
    (repo / mirror).symlink_to(repo / logical)
    with pytest.raises(FileNotFoundError):
        hygiene.navigation_document(repo, mirror)


SHIPPED_ROOTS = ('.codex', '.gemini', '.opencode', '.antigravity', '.ravel', 'addons', 'GEMINI.md')
SHIPPED_NAMES = ('GEMINI.md', 'THIRD-PARTY-NOTICES.md', '.antigravity/RAVEL.md', '.opencode/RAVEL.md',
                 'addons/gpl/mcfm-amplitudes/ATTRIBUTION.md', 'scripts/live/ordinary-review-cell.sh')


def test_every_shipped_root_is_a_public_root_in_the_registry_selection(repo):
    registry = json.loads((REPO / 'distribution.json').read_text())['distribution']
    declared = {Path(p).parts[0] for p in registry['trees'] + registry['files'] + registry.get('extra_files', [])}
    assert set(SHIPPED_ROOTS) <= declared
    assert declared <= set(hygiene.PUBLIC_ROOTS)


def test_shipped_roots_and_conventional_names_pass_the_public_check(repo):
    for relative in SHIPPED_NAMES:
        write(repo, relative)
    for root in SHIPPED_ROOTS:
        if not (repo / root).exists():
            write(repo, root, '') if root.endswith('.md') else (repo / root).mkdir()
    errors, _ = hygiene.check(repo, public=True)
    assert not [e for e in errors if 'forbidden public root' in e or 'kebab-case' in e], errors


def test_upper_case_names_stay_refused_outside_the_conventional_set(repo):
    write(repo, 'docs/RAVEL.md')
    write(repo, 'scripts/live/ordinary_review_cell.sh')
    write(repo, 'tests/RAVEL.md')
    errors, _ = hygiene.check(repo, public=True)
    refused = {e.split(':')[0] for e in errors if 'kebab-case' in e}
    assert {'docs/RAVEL.md', 'scripts/live/ordinary_review_cell.sh', 'tests/RAVEL.md'} <= refused


def test_every_shipped_file_name_follows_the_naming_rules():
    # The source tree also checks internal files, which have their own names; the shipped selection must be clean.
    shipped = {destination for _source, destination in hygiene.evidence_layout.selected_files(REPO)}
    errors, _ = hygiene.check(REPO)
    naming = [e for e in errors if 'must use' in e and e.split(':', 1)[0] in shipped]
    assert not naming
