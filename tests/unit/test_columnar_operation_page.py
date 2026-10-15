"""The operation page of the supplied columnar query describes a supplied population."""
from pathlib import Path


def test_population_is_documented_as_supplied():
    text = (Path(__file__).parents[2] / 'docs/reference/dataset-query-quantities.md').read_text()
    assert 'retained source roster' not in text
    assert 'Q6' not in text and 'Q15' not in text
