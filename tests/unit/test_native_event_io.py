"""Compressed storage preserves bytes and never hides producer/consumer failure."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.physics import native_event_io as io


def executable(tmp_path, body):
    path = tmp_path / "executable"
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o755)
    return path


def test_compression_is_lossless_and_deterministic(tmp_path):
    payload = bytes(range(256)) * 100
    source = tmp_path / "source"
    source.write_bytes(payload)
    first, second = tmp_path / "one.gz", tmp_path / "two.gz"
    evidence = io.compress_events(source, first)
    io.compress_events(source, second)
    assert gzip.decompress(first.read_bytes()) == payload
    assert first.read_bytes() == second.read_bytes()
    assert evidence["uncompressed_sha256"] == hashlib.sha256(payload).hexdigest()
    assert evidence["round_trip_verified"] is True
    assert source.read_bytes() == payload
    with pytest.raises(ValueError, match="already exists"):
        io.compress_events(source, first)


def test_shower_storage_receipt_and_cleanup(tmp_path):
    payload=b'HepMC::Asciiv3-START_EVENT_LISTING\n'+b''.join(f'E {i} 0 0\n'.encode() for i in range(5))+b'HepMC::Asciiv3-END_EVENT_LISTING\n'
    binary = executable(tmp_path, f"from pathlib import Path\nimport sys\nPath(sys.argv[2]).write_bytes({payload!r})\n")
    output = tmp_path / "events.gz"
    io.shower(binary, "card", output, 5)
    assert gzip.decompress(output.read_bytes()) == payload
    receipt = json.loads(Path(str(output) + ".storage.json").read_text())
    assert receipt["uncompressed_bytes"] == len(payload)
    assert receipt["hepmc"]["events"] == 5
    assert not list(tmp_path.glob(".shower-*"))


@pytest.mark.parametrize("body", ["raise SystemExit(3)\n", "pass\n"])
def test_failed_or_empty_shower_has_no_success_receipt(tmp_path, body):
    binary = executable(tmp_path, body)
    output = tmp_path / "events.gz"
    with pytest.raises((subprocess.CalledProcessError, ValueError, FileNotFoundError)):
        io.shower(binary, "card", output, 5)
    assert not Path(str(output) + ".storage.json").exists()
    assert not list(tmp_path.glob(".shower-*"))


@pytest.mark.parametrize('body,count',[
    ('E 0 0 0\n',1),
    ('HepMC::Asciiv3-START_EVENT_LISTING\nE 0 0 0\n',1),
    ('HepMC::Asciiv3-START_EVENT_LISTING\nE 0 0 0\nHepMC::Asciiv3-END_EVENT_LISTING\n',2),
    ('HepMC::Asciiv3-START_EVENT_LISTING\nE 0 0 0\nE 0 0 0\nHepMC::Asciiv3-END_EVENT_LISTING\n',2)])
def test_incomplete_or_duplicate_event_exposure_fails(tmp_path,body,count):
    path=tmp_path/'events';path.write_text(body)
    with pytest.raises(ValueError):io.validate_hepmc(path,count)


def test_detector_gets_exact_decompressed_stream(tmp_path):
    binary = executable(tmp_path, "from pathlib import Path\nimport sys\nassert sys.argv[3]=='-'\nPath(sys.argv[2]).write_bytes(sys.stdin.buffer.read())\n")
    source, output = tmp_path / "events.gz", tmp_path / "detector"
    payload = b"HepMC data\n" * 1000
    source.write_bytes(gzip.compress(payload))
    io.delphes(binary, "card", output, source)
    assert output.read_bytes() == payload
    with pytest.raises(ValueError, match="already exists"):
        io.delphes(binary, "card", output, source)


def test_corrupt_gzip_is_not_success_when_detector_exits_zero(tmp_path):
    binary = executable(tmp_path, "import sys\nsys.stdin.buffer.read()\n")
    source = tmp_path / "events.gz"
    source.write_bytes(gzip.compress(b"events")[:-5])
    with pytest.raises(EOFError):
        io.delphes(binary, "card", tmp_path / "detector", source)


def test_detector_failure_is_not_hidden_by_valid_gzip(tmp_path):
    binary = executable(tmp_path, "import sys\nsys.stdin.buffer.read()\nraise SystemExit(4)\n")
    source = tmp_path / "events.gz"
    source.write_bytes(gzip.compress(b"events"))
    with pytest.raises(subprocess.CalledProcessError) as caught:
        io.delphes(binary, "card", tmp_path / "detector", source)
    assert caught.value.returncode == 4
