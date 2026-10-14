---
name: hepdata-retrieval
description: Use when fetching a search's HEPData record - data tables, cut flows, acceptance and efficiency maps, covariance matrices, published likelihood archives - finding a record from a Rivet routine name, and verifying that every table landed, for RAVEL's source-tables and published-model modes.
license: Apache-2.0
compatibility: hepdata-cli 0.3.1 as pinned in RAVEL's Python dependencies, and the open HEPData JSON endpoints as tested on 2026-08-28.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "source-tables published-model"
  upstream-version: "pypi:hepdata-cli=0.3.1"
  last-reviewed: "2026-10-11"
---

# HEPData retrieval

## Routes

RAVEL's fetcher (`src/ravel/workflow/hepdata_fetch.py`) records what was
reachable when it was tested on 2026-08-28; access rules can change:

- the record JSON (`/record/ins<id>?format=json`) lists the tables and the
  record resources, including published likelihoods;
- the per-table download endpoints were blocked for scripts;
- the internal data endpoint `/record/data/<recid>/<table_id>/<version>`
  served every table as JSON;
- likelihood archives downloaded through the resource endpoint.

A Rivet routine name ending in `_I<digits>` carries the INSPIRE id. Build the
table URLs from the record JSON, never by guessing ids:

```python ravel-block=record-table-urls
from ravel.workflow import hepdata_fetch

def table_urls(record_json, base="https://www.hepdata.net"):
    """One data URL per table listed by an open record JSON."""
    recid, version, tables = hepdata_fetch.record_data_index(record_json)
    return {name: f"{base}/record/data/{recid}/{table_id}/{version}" for table_id, name in tables}
```

## Pitfalls

- A fetch that lands only some tables, or empty ones, and exits 0. Caught by
  `ravel.workflow.hepdata_fetch.fetch_tables_via_record_data`, which checks
  every listed table parses and has values.
- A record JSON without a record id or without tables. Caught by
  `ravel.workflow.hepdata_fetch.record_data_index`.
- Advisory: HEPData records are versioned; pin the version and the table
  hashes in the run, as `source-tables` does for literal primary tables.
- Advisory: a table's units, basis (per bin or cumulative, fb or events) and
  any covariance must be read from its header; `source-tables` requires the
  declared basis and covariance join.

More: `references/review.md`. Upstream: https://www.hepdata.net/ (submission
format and API notes) and https://github.com/HEPData/hepdata-cli.
