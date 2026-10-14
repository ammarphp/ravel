"""The outside evaluation-term check uses the generality gate's matching and never prints a term."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('check_eval_terms', ROOT / 'scripts/maintenance/check_eval_terms.py')
terms_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(terms_check)


def test_terms_match_spacing_and_case_variants_and_report_the_term_index(tmp_path, monkeypatch, capsys):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/a.md').write_text('clean\nthe Zebra-Lantern suite\n')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/b.py').write_text('# MarmotIndex\n')
    monkeypatch.setenv('RAVEL_EVAL_TERMS', 'zebra lantern, marmot index')
    monkeypatch.delenv('RAVEL_EVAL_TERMS_FILE', raising=False)
    assert terms_check.main(['--repo', str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert 'docs/a.md:2: term #0' in out and 'src/b.py:1: term #1' in out
    assert 'zebra' not in out.lower() and 'marmot' not in out.lower()


def test_no_list_is_a_configuration_error(monkeypatch, tmp_path):
    monkeypatch.delenv('RAVEL_EVAL_TERMS', raising=False)
    monkeypatch.delenv('RAVEL_EVAL_TERMS_FILE', raising=False)
    assert terms_check.main(['--repo', str(tmp_path)]) == 2
