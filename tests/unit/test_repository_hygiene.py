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


@pytest.fixture
def repo(tmp_path):
    write(tmp_path, 'evidence/collections.json', (REPO / 'evidence/collections.json').read_text())
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
    (repo / 'framework').mkdir()
    assert not hygiene.check(repo, public=False)[0]
    assert any('framework: forbidden public root' in e for e in hygiene.check(repo, public=True)[0])
    registry = json.loads((repo / 'evidence/collections.json').read_text())
    registry['distribution']['trees'].append('framework')
    (repo / 'evidence/collections.json').write_text(json.dumps(registry))
    assert any('framework: forbidden public root' in e for e in hygiene.check(repo, public=True)[0])
    (repo / 'framework').rmdir()
    (repo / '.venv-replay').mkdir()
    (repo / 'dist').mkdir()
    (repo / 'build').mkdir()
    write(repo, 'local-runs/replay-example/results.json', '{}')
    write(repo, 'logs/hook-probe.log', 'local hook output')
    assert not hygiene.check(repo, public=True)[0]
    (repo / 'trial-runs').mkdir()
    write(repo, 'evidence/export-provenance.json', '{}')
    assert any('trial-runs: forbidden public root' in e for e in hygiene.check(repo)[0])


def test_explicit_mapping_resolves_source_provenance_and_exempts_archival_text(repo):
    original = 'trial-runs/sleptonscan_fig3_SCAN/RESULT.md'
    public = 'evidence/scans/slepton-bino-figure-3/RESULT.md'
    write(repo, original, '# Original record\n\n[Recorded old path](nonexistent-ancient-path.md)\n')
    write(repo, 'docs/guide.md', f'[Historical scan](../{public})\n')
    assert hygiene.check_link(repo, 'docs/guide.md', '../' + public) is None
    assert not hygiene.check(repo)[0]
    # Mapping is exact; a nearby invented collection is not a valid alternative.
    assert hygiene.check_link(repo, 'docs/guide.md', '../evidence/scans/another-scan/RESULT.md')


def test_public_browser_links_cannot_use_source_aliases(repo):
    public = 'evidence/scans/slepton-bino-figure-3/RESULT.md'
    original = 'trial-runs/sleptonscan_fig3_SCAN/RESULT.md'
    write(repo, public, '# Public record\n')
    assert hygiene.evidence_layout.resolve(repo, original) == repo / public
    # Runtime compatibility is not browser URL compatibility.
    assert hygiene.check_link(repo, 'README.md', original, public=True)
    assert hygiene.check_link(repo, 'README.md', public, public=True) is None
    assert hygiene.check_link(repo, 'README.md', original, public=False)


def test_source_navigation_cannot_depend_on_unshipped_files(repo):
    write(repo, 'private.md', '# Present only in the development workspace\n')
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
