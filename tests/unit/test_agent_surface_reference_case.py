"""The reference check resolves a backticked name with exact case on every filesystem."""
from ravel.validation import check_agent_surface as surface


def tree(tmp_path, text):
    folder = tmp_path / 'docs' / 'notes'
    folder.mkdir(parents=True)
    (folder / 'sibling-note.md').write_text('a lower-case sibling\n')
    document = folder / 'guide.md'
    document.write_text(text)
    return str(tmp_path), [str(document)]


def test_a_differently_cased_sibling_does_not_resolve_a_bare_name(tmp_path):
    root, files = tree(tmp_path, 'A run writes `SIBLING-NOTE.md` at close.\n')
    assert surface.check_refs(root, files, 'dev') == [
        '[dev] missing: docs/notes/guide.md: `SIBLING-NOTE.md`']


def test_a_differently_cased_directory_does_not_resolve_a_path(tmp_path):
    root, files = tree(tmp_path, 'See `docs/Notes/sibling-note.md` and `DOCS/notes/sibling-note.md`.\n')
    assert surface.check_refs(root, files, 'dev') == [
        '[dev] missing: docs/notes/guide.md: `DOCS/notes/sibling-note.md`',
        '[dev] missing: docs/notes/guide.md: `docs/Notes/sibling-note.md`']


def test_a_differently_cased_literal_part_does_not_resolve_a_pattern(tmp_path):
    root, files = tree(tmp_path, 'Every `docs/Notes/sibling-*.md` applies.\n')
    assert surface.check_refs(root, files, 'dev') == [
        '[dev] missing: docs/notes/guide.md: `docs/Notes/sibling-*.md`']


def test_exact_names_resolve_from_the_root_the_document_and_its_parent(tmp_path):
    text = ('See `sibling-note.md`, `docs/notes/sibling-note.md`, `notes/sibling-note.md`, '
            '`../notes/sibling-note.md` and `docs/notes/sibling-*.md`.\n')
    root, files = tree(tmp_path, text)
    assert surface.check_refs(root, files, 'dev') == []


def test_a_file_added_between_two_checks_is_seen(tmp_path):
    root, files = tree(tmp_path, 'See `docs/notes/later-note.md`.\n')
    assert surface.check_refs(root, files, 'dev') == [
        '[dev] missing: docs/notes/guide.md: `docs/notes/later-note.md`']
    (tmp_path / 'docs' / 'notes' / 'later-note.md').write_text('added afterwards\n')
    assert surface.check_refs(root, files, 'dev') == []


def test_a_run_root_output_written_as_a_run_path_is_not_a_repository_reference(tmp_path):
    root, files = tree(tmp_path, 'Every run writes `<run>/SIBLING-NOTE.md` (run root) at close.\n')
    assert surface.check_refs(root, files, 'dev') == []


def test_a_registered_run_artifact_name_is_not_resolved_against_a_lower_case_document(tmp_path):
    # The run-root file a run writes at close shares its letters with the checklist that describes it.
    folder = tmp_path / 'docs' / 'checklists'
    folder.mkdir(parents=True)
    document = folder / 'verification-ladder.md'
    document.write_text('Every run writes `VERIFICATION-LADDER.md` (run root) at close.\n')
    assert 'VERIFICATION-LADDER.md' in surface.RUNTIME_NAMES
    assert surface.check_refs(str(tmp_path), [str(document)], 'dev') == []
