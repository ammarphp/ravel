"""Lossless compressed event storage for supervised native stages.

The shower's plain output is temporary within its producing stage. The durable
output is gzip from birth; downstream Delphes consumes its verified byte stream.
This does not delete or replace an artifact named in an earlier stage receipt.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def validate_hepmc(path, expected_events):
    """Check complete native HepMC3 framing and event IDs before storage succeeds."""
    started = ended = False
    seen = set()
    with Path(path).open("rt", encoding="ascii") as stream:
        for raw in stream:
            line = raw.strip()
            if line == "HepMC::Asciiv3-START_EVENT_LISTING":
                if started:
                    raise ValueError("duplicate HepMC start marker")
                started = True
            elif line == "HepMC::Asciiv3-END_EVENT_LISTING":
                if not started or ended:
                    raise ValueError("invalid HepMC end marker")
                ended = True
            elif line.startswith("E "):
                if not started or ended:
                    raise ValueError("HepMC event outside complete listing")
                fields = line.split()
                if len(fields) < 4:
                    raise ValueError("malformed HepMC event header")
                event_id, vertices, particles = map(int, fields[1:4])
                if event_id in seen or vertices < 0 or particles < 0:
                    raise ValueError("duplicate event ID or invalid HepMC counts")
                seen.add(event_id)
            elif ended and line:
                raise ValueError("unexpected content after HepMC end marker")
    if not started or not ended or len(seen) != expected_events:
        raise ValueError("HepMC framing/count differs from requested event exposure")
    return {"events": len(seen), "complete_listing": True, "unique_event_ids": True}


def compress_events(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError("compressed output already exists")
    if not source.is_file() or not source.stat().st_size:
        raise ValueError("shower produced no event file")
    digest = hashlib.sha256()
    size = 0
    # gzip mtime=0 and an empty original filename keep the transform deterministic.
    with destination.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as target:
            with source.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
                    target.write(block)
    check = hashlib.sha256()
    with gzip.open(destination, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            check.update(block)
    if check.digest() != digest.digest():
        raise ValueError("compressed event round-trip changed bytes")
    compressed_digest = hashlib.sha256()
    with destination.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            compressed_digest.update(block)
    return {"schema_version": 1, "encoding": "gzip", "uncompressed_bytes": size,
            "uncompressed_sha256": digest.hexdigest(),
            "compressed_bytes": destination.stat().st_size,
            "compressed_sha256": compressed_digest.hexdigest(),
            "round_trip_verified": True}


def shower(binary, card, output, events):
    output = Path(output)
    if output.exists() or Path(str(output) + ".storage.json").exists():
        raise ValueError("shower output already exists")
    if events < 1:
        raise ValueError("event count must be positive")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".shower-", dir=output.parent) as temporary:
        plain = Path(temporary) / "events.hepmc"
        subprocess.run([str(binary), str(card), str(plain), str(events)], check=True)
        exposure = validate_hepmc(plain, events)
        record = compress_events(plain, output)
        record["hepmc"] = exposure
    Path(str(output) + ".storage.json").write_text(json.dumps(record, indent=2) + "\n")


def delphes(binary, card, output, events):
    """Feed gzip into Delphes' documented stdin interface; propagate both failures."""
    if Path(output).exists():
        raise ValueError("detector output already exists")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen([str(binary), str(card), str(output), "-"], stdin=subprocess.PIPE)
    try:
        with gzip.open(events, "rb") as stream:
            shutil.copyfileobj(stream, child.stdin, length=1024 * 1024)
        child.stdin.close()
        code = child.wait()
        if code:
            raise subprocess.CalledProcessError(code, child.args)
    except BaseException:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    shower_parser = commands.add_parser("shower")
    shower_parser.add_argument("--events", required=True, type=int)
    detector_parser = commands.add_parser("delphes")
    detector_parser.add_argument("--input", required=True)
    for command in (shower_parser, detector_parser):
        command.add_argument("--binary", required=True)
        command.add_argument("--card", required=True)
        command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.operation == "shower":
        shower(args.binary, args.card, args.output, args.events)
    else:
        delphes(args.binary, args.card, args.output, args.input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
