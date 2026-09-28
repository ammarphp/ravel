# LHE census fixtures (DERIVED development fixtures)

These are software-test inputs for the independent LHE census oracle
(`benchmarks/governance/oracle/lhe_census.py`, WP12 task bank). They are not physics results,
agent evidence or approvals. No event was generated for them.

`fixtures.json` pins every LHE input the tests use, by sha256 and byte count:

| Label | Where | What |
|---|---|---|
| `dy-1729` | referenced: `evidence/audits/2026-09-09-scoped-workflows/drell-yan/events.lhe.gz` | Complete public file, 17,571 bytes |
| `dy-1730` | referenced: `evidence/audits/2026-09-09-scoped-workflows/drell-yan-replica/events.lhe.gz` | Complete public file, 17,547 bytes |
| `dy-1730-content-truncated.lhe.gz` | stored in `benchmarks/governance/tasks/data/` | Content-truncated fixture, 10,462 bytes |

The two complete files are referenced rather than copied. Both come from RAVEL's 2026-09-09
scoped-workflow Drell–Yan controls. They are MG5_aMC 2.9.27 LO parton events for pp → e⁺e⁻ at
13 TeV (sm-no_b_mass, cteq6l1), 100 events each, with seeds 1729 and 1730. What the public
copies show:

- The event bytes are unchanged. The `event_blocks_sha256` recorded in `event-projection.json`
  recomputes from the public files (`test_referenced_public_files_match_their_pins`).
- That hash does not cover the init block, which carries XSECUP, the cross section the tasks
  score. σ is corroborated separately: the run-time `result.json` of each control recorded
  760.535 and 761.52 pb, `verify.py` checks them against the init block, and every event weight
  equals XSECUP.
- That the redaction changed only the home-directory prefix in the header is the exporter's
  statement. The original files are not in the public tree, so their hashes cannot be checked
  here.

Licence: Apache-2.0 for the RAVEL-generated content. The header keeps MG5_aMC@NLO banner and
card text, which is under its own licence (`docs/reference/third-party.md`). The MG5_aMC
citation request in each file's init block is kept.

## The content-truncated fixture

The fixture's bytes are stored with the harness that reads them, in
`benchmarks/governance/tasks/data/` (the task-bank builder builds the whole bank for every
campaign, so the production path must not read a file from `tests/`; decision E-152). This
directory keeps its record (`fixtures.json`) and its builder.

`build_fixture.py` (standard library only) builds it from `dy-1730`:

1. It decompresses the source.
2. It cuts the stream midway inside event block 42, at byte 54,179. The content then holds 41
   closed event blocks and an open 42nd. It has no `</LesHouchesEvents>`, and its header still
   says 100 events.
3. It recompresses the cut content as one valid gzip member. The header is written by hand
   (no name, MTIME 0, XFL 2, OS 255); the body is raw deflate at level 9, memLevel 8.

Because the gzip stream itself is complete, every byte-level decompressor tested gives the same
content: zlib streaming, `gzip.decompress`, line iteration and `gzip -dc` (which exits 0). That
content has 41 closed event blocks. Other counting rules on it give other answers: counting
opening tags (`gzip -dc … | grep -c '<event>'`) gives 42, a whole-document ElementTree parse and
both kernel readers raise, and an incremental `iterparse` yields 41 events and then raises. The
oracle's count is the closed blocks; the opening-tag count is exposed only as a fault-value
diagnostic.

A cut in the compressed bytes would not even give one content: how much a reader salvages
depends on the reader. Such a cut is used only in a documentation test and is never scored.

Deflate output can depend on the zlib build. The stored bytes are therefore pinned, not
regenerated. The fixture was built with zlib 1.2.12, and zlib 1.3.1 and 1.3.2 were checked to
give identical bytes (`reproduced_with_zlib` in `fixtures.json`). `python build_fixture.py`
(the default `--check`) verifies the stored bytes and their decompressed content (sha256
`5cdb5f85…`). `--write` refuses to replace a stored fixture whose rebuilt bytes differ, and it
leaves `fixtures.json` untouched when the stored fixture already matches.

The fixture's source kind is `ravel_generated_development`, with the truncation and
recompression listed under `modifications`, as the task-bank design's source vocabulary
expects.

The hand-written header makes the bytes independent of the Python version. CPython 3.13's
`gzip.compress(data, mtime=0)` produces the same bytes. CPython 3.12's writes zlib's own header
(OS 19 on macOS), which gives a different sha256 over the same deflate data. The design's
recorded prefix `c45eea92cf78` is the OS 255 form.
