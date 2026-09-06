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
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def _write_new_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def shower_original(binary, card, output, events, *, lhe, sidecar, verification,
                    wrapper_source, run_card, encoding="plain"):
    """Own one opt-in producer and verify newly produced original-LHA content.

    Failed or partial artifacts remain in a fresh staging directory for the
    supervisor's failed-attempt evidence. Only complete verified files are
    published to declared outputs; an absent report never implies success.
    """
    from . import lhe_provenance as provenance
    require = provenance.require
    require(type(events) is int and events > 0, "Positive exact event count required")
    require(encoding in {"plain", "gzip"}, "Unsupported event encoding")
    original_paths = [Path(x).absolute() for x in (binary, card, lhe, wrapper_source, run_card)]
    binary, card, lhe, wrapper_source, run_card = original_paths
    output, sidecar, verification = (Path(x).absolute() for x in (output, sidecar, verification))
    storage_path = Path(str(output) + ".storage.json")
    destinations = [output, sidecar, verification] + ([storage_path] if encoding == "gzip" else [])
    require(len({str(p.resolve()) for p in [*original_paths, *destinations]}) ==
            len(original_paths) + len(destinations), "Shower inputs/outputs alias")
    for path in destinations:
        require(not os.path.lexists(path), f"Shower output already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
    source_paths = [*original_paths, Path(__file__).resolve(), Path(provenance.__file__).resolve()]
    source_paths = list(dict.fromkeys(source_paths))
    sources = {str(path): provenance.pin(path) for path in source_paths}
    identities = {str(path): provenance.file_identity(path) for path in source_paths}

    def unchanged_inputs():
        for path in source_paths:
            require(provenance.file_identity(path) == identities[str(path)] and
                    provenance.pin(path) == sources[str(path)],
                    f"Shower source/input changed: {path}")

    # Bound the actual card consumed by the producer, not only its source draft.
    settings = {}
    for raw in card.read_text().splitlines():
        line = raw.split("!", 1)[0].split("#", 1)[0].strip()
        if not line:
            continue
        require("=" in line, "Unsupported non-assignment shower directive")
        key, value = (part.strip() for part in line.split("=", 1))
        key = key.lower()
        require(key and key not in settings, "Duplicate shower setting")
        settings[key] = value
    require(settings.get("beams:frametype") == "4", "original-v1 requires file LHE input")
    declared_lhe = Path(settings.get("beams:lhef", ""))
    require(declared_lhe.is_absolute() and declared_lhe == lhe,
            "Actual shower card must bind the exact absolute original LHE path")
    require(settings.get("jetmatching:merge", "off").lower() in {"off", "false"},
            "original-v1 does not support jet matching")
    require(all(value.lower() in {"off", "false", "0", "0.0"}
                for key, value in settings.items() if key.startswith("merging:")),
            "original-v1 does not support merging settings")
    require(settings.get("beams:lhefheader", "void").lower() in {"void", ""},
            "Separate LHE header source is unsupported")
    require(settings.get("beams:newlhefsameinit", "off").lower() in {"off", "false"},
            "LHE source switching is unsupported")
    if "main:numberofevents" in settings:
        require(settings["main:numberofevents"] == str(events), "Shower event count differs")
    run_settings = {}
    for raw in run_card.read_text().splitlines():
        line = raw.split("!", 1)[0].split("#", 1)[0].strip()
        if not line:
            continue
        require("=" in line, "Unsupported non-assignment run-card directive")
        value, key = (part.strip().strip("'\"") for part in line.split("=", 1))
        key = key.lower()
        require(key and key not in run_settings, "Duplicate run-card setting")
        run_settings[key] = value
    require(float(run_settings.get("ickkw", "nan")) == 0 and
            float(run_settings.get("nevents", "nan")) == events and
            run_settings.get("use_syst", "").lower() in {"false", ".false."},
            "original-v1 requires declared unmerged nominal event exposure")
    # Parse all nominal LHE records before invoking even an old/incompatible binary.
    with lhe.open("rb") as stream:
        seen = set()
        count = 0
        for event in provenance.lhe_events(provenance.HashedLines(stream)):
            key = provenance.identity(event)
            require(key not in seen, "Ambiguous duplicate full original LHE event content")
            seen.add(key)
            count += 1
            require(count <= events, "Excess original LHE events")
        require(count == events, "Original LHE population differs")
    unchanged_inputs()
    temporary = Path(tempfile.mkdtemp(prefix=".original-lha-", dir=output.parent))
    plain = temporary / "events.hepmc"
    captured = temporary / "original-lhe.jsonl"
    command = [str(binary), str(card), str(plain), str(events), "--lhe-sidecar", str(captured)]
    try:
        # check=True is an actual owned child exit result, not a supplied assertion.
        subprocess.run(command, check=True)
        unchanged_inputs()
        stored = plain
        storage = None
        if encoding == "gzip":
            stored = temporary / "events.hepmc.gz"
            storage = compress_events(plain, stored)
        report = provenance.verify_new_generation(lhe, captured, stored,
            expected_events=events, encoding=encoding)
        unchanged_inputs()
        require(all(not os.path.lexists(path) for path in destinations), "Output appeared during shower")
        # Same-filesystem hard links publish exclusively, retaining exact verified bytes.
        # A failure midway leaves no complete report and no successful stage receipt.
        os.link(stored, output)
        os.link(captured, sidecar)
        report["source_files"]["hepmc"]["path"] = str(output)
        report["source_files"]["sidecar"]["path"] = str(sidecar)
        report["producer"] = {"command": command, "returncode": 0,
                              "input_sources": list(sources.values()),
                              "source_checks_before_and_after": True,
                              "binary_compilation_provenance_inferred": False}
        if storage is not None:
            storage["hepmc"] = {"events": events, "complete_listing": True,
                                "unique_event_ids": True}
            _write_new_json(storage_path, storage)
        unchanged_inputs()
        for name, path in (("hepmc", output), ("sidecar", sidecar)):
            require(provenance.pin(path) == report["source_files"][name],
                    "Published output differs from verified content")
        _write_new_json(verification, report)
    except BaseException:
        # Keep partial producer files and their path; never manufacture a success report.
        print(f"Original-LHA failure evidence retained at {temporary}", file=__import__("sys").stderr)
        raise
    else:
        shutil.rmtree(temporary)


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
    original_parser = commands.add_parser("shower-original")
    original_parser.add_argument("--events", required=True, type=int)
    original_parser.add_argument("--lhe", required=True)
    original_parser.add_argument("--sidecar", required=True)
    original_parser.add_argument("--verification", required=True)
    original_parser.add_argument("--wrapper-source", required=True)
    original_parser.add_argument("--run-card", required=True)
    original_parser.add_argument("--encoding", choices=("plain", "gzip"), required=True)
    detector_parser = commands.add_parser("delphes")
    detector_parser.add_argument("--input", required=True)
    for command in (shower_parser, original_parser, detector_parser):
        command.add_argument("--binary", required=True)
        command.add_argument("--card", required=True)
        command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.operation == "shower":
        shower(args.binary, args.card, args.output, args.events)
    elif args.operation == "shower-original":
        shower_original(args.binary, args.card, args.output, args.events,
                        lhe=args.lhe, sidecar=args.sidecar, verification=args.verification,
                        wrapper_source=args.wrapper_source, run_card=args.run_card, encoding=args.encoding)
    else:
        delphes(args.binary, args.card, args.output, args.input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
