"""hepdata-retrieval block on a synthetic record JSON; no network."""
import pytest

SKILL = "hepdata-retrieval"


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ["record-table-urls"]


def test_table_urls(handbook):
    urls = handbook.load(SKILL, "record-table-urls")["table_urls"]
    record = {"recid": 123, "version": 2, "data_tables": [{"id": 7, "name": "Cutflow SR1"}, {"id": 8, "name": "Yields"}]}
    assert urls(record) == {"Cutflow SR1": "https://www.hepdata.net/record/data/123/7/2",
                            "Yields": "https://www.hepdata.net/record/data/123/8/2"}
    with pytest.raises(ValueError):
        urls({"recid": 123, "data_tables": []})
