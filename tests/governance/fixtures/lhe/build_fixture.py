"""Deterministic builder of the content-truncated LHE fixture (DERIVED development fixture).

Standard library only; independent of the oracle it tests. See README.md beside this file.

Source: the redacted public copy of RAVEL's seed-1730 Drell-Yan control (MG5_aMC 2.9.27 LO,
100 events), SOURCE below, pinned by SOURCE_SHA256. Construction:

1. decompress the source (a complete single-member gzip);
2. cut the decompressed stream midway inside event block CUT_EVENT (42): at the start offset
   of its ``<event>`` line plus half the distance to its ``</event>`` line (byte 54,179), so
   the content holds 41 closed event blocks, then an open 42nd, and no ``</LesHouchesEvents>``;
3. compress the cut content as ONE valid gzip member: a hand-written 10-byte header (no name,
   MTIME 0, XFL 2, OS 255 "unknown"), raw deflate at level 9, memLevel 8, default strategy,
   then CRC-32 and ISIZE.

The deflate bytes can depend on the zlib build, so the stored fixture is pinned by its sha256
in fixtures.json and is never regenerated silently: ``--check`` (the default) verifies the
stored bytes and their content, and ``--write`` refuses to replace a stored fixture whose bytes
differ and leaves fixtures.json untouched when the stored fixture already matches (so a rerun
never rewrites ``built_with_zlib``). It was built with zlib 1.2.12; zlib 1.3.1 and 1.3.2 were
checked to give the same bytes (``reproduced_with_zlib``, extended by hand after such a check).
The hand-written header makes the bytes independent of the Python version: CPython 3.13's
``gzip.compress(data, mtime=0)`` writes OS 255 and gives the same bytes, while CPython 3.12's
writes zlib's own header (OS 19 on macOS) and a different sha256 over the same deflate data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
# The fixture bytes live with the harness that reads them (tasks/builder.SAMPLES; decision E-152); this record and
# builder stay with the tests.
STORED = ROOT / "benchmarks" / "governance" / "tasks" / "data"
SOURCE = "evidence/audits/2026-09-09-scoped-workflows/drell-yan-replica/events.lhe.gz"
SOURCE_SHA256 = "c8c7330fa387e5b4c864c771b6374fcbad9dbea6cffb6f104ad9275ffff4109a"
FIXTURE = "dy-1730-content-truncated.lhe.gz"
RECORD = "fixtures.json"
CUT_EVENT = 42
LICENSE = ("Apache-2.0 for the RAVEL-generated content; the header keeps MG5_aMC@NLO banner and card "
           "text under its own licence (docs/reference/third-party.md); the MG5_aMC citation request in "
           "the init block is preserved")
GZIP_HEADER = b"\x1f\x8b\x08\x00" + b"\x00\x00\x00\x00" + b"\x02\xff"   # ID, CM, FLG, MTIME, XFL, OS


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_content(root: Path = ROOT) -> bytes:
    data = (root / SOURCE).read_bytes()
    if sha256(data) != SOURCE_SHA256:
        raise SystemExit(f"source {SOURCE} does not match its pinned sha256")
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    content = decompressor.decompress(data)
    if not decompressor.eof or decompressor.unused_data:
        raise SystemExit("source is not one complete gzip member")
    return content


def cut_offset(content: bytes) -> int:
    """Offset midway inside event block CUT_EVENT (between its opening and closing lines)."""
    start = -1
    for _ in range(CUT_EVENT):
        start = content.index(b"\n<event>\n", start + 1)
    opening = start + 1
    closing = content.index(b"</event>", opening)
    return opening + (closing - opening) // 2


def truncated_content(content: bytes) -> bytes:
    return content[:cut_offset(content)]


def gzip_member(content: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS, 8, zlib.Z_DEFAULT_STRATEGY)
    body = compressor.compress(content) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(content) & 0xFFFFFFFF, len(content) & 0xFFFFFFFF)
    return GZIP_HEADER + body + trailer


def record(fixture: bytes, content: bytes, offset: int) -> dict:
    return {
        "schema_version": 1,
        "label": ("DERIVED development fixtures for the WP12 LHE census oracle tests; software-test "
                  "inputs, not physics results, agent evidence or approvals"),
        "referenced": {
            "dy-1729": {
                "path": "evidence/audits/2026-09-09-scoped-workflows/drell-yan/events.lhe.gz",
                "sha256": "875f06a5e8752ae754dddb7765ba980009ab61388ea14f653f43a07fa8519276",
                "bytes": 17571,
                "provenance": ("RAVEL scoped-workflow control 2026-09-09: MG5_aMC 2.9.27 LO pp > e+ e-, "
                               "13 TeV, seed 1729, 100 events; the exporter states that the public copy "
                               "redacts only the home-directory prefix in the header, and the recorded "
                               "event-block sha256 shows the event bytes unchanged (event-projection.json)"),
            },
            "dy-1730": {
                "path": SOURCE, "sha256": SOURCE_SHA256, "bytes": 17547,
                "provenance": ("RAVEL scoped-workflow control 2026-09-09: same recipe as dy-1729 with "
                               "seed 1730; the exporter states that the public copy redacts only the "
                               "home-directory prefix in the header, and the recorded event-block sha256 "
                               "shows the event bytes unchanged (event-projection.json)"),
            },
        },
        "stored": {
            FIXTURE: {
                "sha256": sha256(fixture), "bytes": len(fixture),
                "content_sha256": sha256(content), "content_bytes": len(content),
                "source": "dy-1730", "cut_event": CUT_EVENT, "cut_offset": offset,
                "construction": ("decompressed dy-1730 cut midway inside event block 42, recompressed "
                                 "as one gzip member (no name, MTIME 0, XFL 2, OS 255, raw deflate "
                                 "level 9, memLevel 8) by build_fixture.py"),
                "built_with_zlib": zlib.ZLIB_RUNTIME_VERSION,
                "reproduced_with_zlib": [zlib.ZLIB_RUNTIME_VERSION],
                "kind": "ravel_generated_development",
                "modifications": [
                    "decompressed content cut at byte 54,179, midway inside event block 42 (41 closed "
                    "event blocks, no </LesHouchesEvents>; the header still says 100 events)",
                    "recompressed as one gzip member; the file sha256 therefore differs from dy-1730"],
                "license": LICENSE,
            },
        },
    }


def check(root: Path = ROOT) -> dict:
    pinned = json.loads((HERE / RECORD).read_text())
    entry = pinned["stored"][FIXTURE]
    stored = (STORED / FIXTURE).read_bytes()
    content = truncated_content(source_content(root))
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    problems = []
    if sha256(stored) != entry["sha256"] or len(stored) != entry["bytes"]:
        problems.append("stored fixture bytes differ from fixtures.json")
    if decompressor.decompress(stored) != content or not decompressor.eof or decompressor.unused_data:
        problems.append("stored fixture does not decompress to the rebuilt truncated content")
    if sha256(content) != entry["content_sha256"] or len(content) != entry["content_bytes"]:
        problems.append("rebuilt truncated content differs from fixtures.json")
    if cut_offset(source_content(root)) != entry["cut_offset"]:
        problems.append("cut offset differs from fixtures.json")
    return {"problems": problems, "rebuilt_bytes_identical": gzip_member(content) == stored,
            "zlib": zlib.ZLIB_RUNTIME_VERSION}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write the fixture and fixtures.json if absent")
    args = parser.parse_args(argv)
    if args.write:
        full = source_content()
        content = truncated_content(full)
        fixture = gzip_member(content)
        target = STORED / FIXTURE
        if target.exists() and target.read_bytes() != fixture:
            print(f"refusing to replace the pinned {FIXTURE}: rebuilt bytes differ "
                  f"(zlib {zlib.ZLIB_RUNTIME_VERSION})", file=sys.stderr)
            return 1
        if target.exists() and (HERE / RECORD).exists():
            print(f"{FIXTURE} already matches; {RECORD} left unchanged", file=sys.stderr)
        else:
            target.write_bytes(fixture)
            (HERE / RECORD).write_text(json.dumps(record(fixture, content, cut_offset(full)), indent=2) + "\n")
    result = check()
    print(json.dumps(result, indent=2))
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
