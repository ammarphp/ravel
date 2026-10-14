"""scripts/setup/install.sh preflight and bootstrap, with fake system commands on PATH."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "scripts/setup/install.sh"


def fake(bin_dir: Path, name: str, body: str):
    path = bin_dir / name
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(0o755)


@pytest.fixture
def system(tmp_path):
    """A fake macOS arm64 machine with plenty of disk, Command Line Tools and no Rosetta translation."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    settings = {"system": "Darwin", "machine": "arm64", "translated": "0", "clt": "0", "free_kb": str(200 * 1024 * 1024)}

    def write():
        fake(bin_dir, "python3", f'exec "{sys.executable}" "$@"' if not settings.get("old_python") else
             'case "$1" in -c) exit 1;; esac; echo "Traceback (most recent call last):" >&2; exit 1')
        fake(bin_dir, "uname", f'case "$1" in -s) echo {settings["system"]};; -m) echo {settings["machine"]};; '
                               f'*) echo {settings["system"]};; esac')
        fake(bin_dir, "sysctl", f'echo {settings["translated"]}')
        fake(bin_dir, "xcode-select", f'exit {settings["clt"]}')
        fake(bin_dir, "df", 'echo "Filesystem 1024-blocks Used Available Capacity Mounted"; '
                            f'echo "/dev/disk 999999999 1 {settings["free_kb"]} 1% /"')
        if not (bin_dir / "git").exists():
            fake(bin_dir, "git", "echo 'git version 2.39.0'")
        for name in ("tar", "awk", "head", "dirname", "mkdir", "mv", "printf", "cat", "basename"):
            real = shutil.which(name)
            if real and not (bin_dir / name).exists():
                (bin_dir / name).symlink_to(real)
        fake(bin_dir, "shasum", 'exec /usr/bin/shasum "$@"' if Path("/usr/bin/shasum").exists()
             else 'exec sha256sum "${@:3}"')
        fake(bin_dir, "curl", '[ -z "$CURL_MARK" ] || : > "$CURL_MARK"; '
                              'out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done; '
                              'printf "not the real installer" > "$out"')

    def run(*args, prefix=None, env=None):
        write()
        environment = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path / "home")}
        environment.update(env or {})
        argv = ["/bin/bash", str(SHIM), *args]
        if prefix is not None:
            argv += ["--prefix", str(prefix)]
        return subprocess.run(argv, capture_output=True, text=True, env=environment, cwd=tmp_path)

    return settings, run, tmp_path


def test_help(system):
    _, run, _ = system
    result = run("--help")
    assert result.returncode == 0 and "--profile NAME" in result.stdout and "ravel doctor" in result.stdout


def test_preflight_passes_on_a_ready_mac(system):
    _, run, tmp = system
    result = run("--preflight-only", prefix=tmp / "p")
    assert result.returncode == 0, result.stderr
    assert "macos-arm64" in result.stdout and "preflight: ok" in result.stdout
    assert not (tmp / "p").exists()


def test_rosetta_translated_terminal_is_refused(system):
    settings, run, tmp = system
    settings["translated"] = "1"
    result = run("--preflight-only", prefix=tmp / "p")
    assert result.returncode == 3 and "Rosetta" in result.stderr


def test_missing_command_line_tools_names_the_fix(system):
    settings, run, tmp = system
    settings["clt"] = "2"
    result = run("--preflight-only", prefix=tmp / "p")
    assert result.returncode == 3 and "xcode-select --install" in result.stderr


def test_low_disk_is_refused_with_alternatives(system):
    settings, run, tmp = system
    settings["free_kb"] = str(5 * 1024 * 1024)
    result = run("--preflight-only", prefix=tmp / "p")
    assert result.returncode == 4
    assert "--prefix" in result.stderr and "--adopt" in result.stderr
    assert run("--preflight-only", "--no-disk-check", prefix=tmp / "p").returncode == 0
    assert run("--preflight-only", "--profile", "site", prefix=tmp / "p").returncode == 4


def test_linux_and_unsupported_systems(system):
    settings, run, tmp = system
    settings.update(system="Linux", machine="x86_64")
    result = run("--preflight-only", prefix=tmp / "p")
    assert result.returncode == 0 and "linux-x86_64" in result.stdout
    settings.update(system="Linux", machine="riscv64")
    assert run("--preflight-only", prefix=tmp / "p").returncode == 3
    settings.update(system="FreeBSD", machine="x86_64")
    assert run("--preflight-only", prefix=tmp / "p").returncode == 3


def test_prefix_with_whitespace_is_refused(system):
    _, run, tmp = system
    result = run("--preflight-only", prefix=tmp / "has space")
    assert result.returncode == 3 and "space" in result.stderr


def test_bad_miniforge_download_is_quarantined_and_never_run(system):
    _, run, tmp = system
    result = run(prefix=tmp / "p")
    assert result.returncode == 5 and "checksum mismatch" in result.stderr
    quarantine = list((tmp / "p/downloads/quarantine").iterdir())
    assert len(quarantine) == 1 and quarantine[0].read_text() == "not the real installer"
    assert not (tmp / "p/tools/miniforge3").exists()


def test_offline_bootstrap_refuses_a_missing_miniforge_without_any_download(system):
    _, run, tmp = system
    fetched = tmp / "curl-called"
    result = run("--offline", prefix=tmp / "p", env={"CURL_MARK": str(fetched)})
    assert result.returncode == 5 and "offline" in result.stderr and "download cache" in result.stderr
    assert not fetched.exists()
    assert not (tmp / "p/tools/miniforge3").exists()


def test_cached_miniforge_installer_runs_under_a_name_ending_in_sh(system):
    """Upstream's installer refuses to run unless its own file name ends in .sh; the cache is named by checksum."""
    _, run, tmp = system
    prefix = tmp / "p"
    cache = prefix / "downloads/sha256"
    cache.mkdir(parents=True)
    sha = "0d765919d3ccfd1f89147aa1cf8133bfc55b3a3c13f5bacdcc091c33132fddd2"
    (cache / sha).write_text(
        '#!/bin/bash\necho "$0" | grep -q "\\.sh$" || { echo "refused" >&2; exit 1; }\n'
        'mkdir -p "$3/bin"; printf "#!/bin/bash\\nexit 0\\n" > "$3/bin/python"; cp "$3/bin/python" "$3/bin/conda"; '
        'chmod +x "$3/bin/python" "$3/bin/conda"\n')
    result = run(prefix=prefix)
    assert result.returncode == 0, result.stderr
    assert (prefix / "tools/miniforge3/bin/python").exists()


def test_existing_miniforge_hands_over_with_all_arguments(system):
    _, run, tmp = system
    mf = tmp / "p/tools/miniforge3/bin"
    mf.mkdir(parents=True)
    record = tmp / "args.txt"
    fake(mf, "conda", "exit 0")
    fake(mf, "python", f'printf "%s\\n" "$@" > {record}')
    result = run("--only", "madgraph", "--accept-licenses", prefix=tmp / "p")
    assert result.returncode == 0, result.stderr
    args = record.read_text().splitlines()
    assert args[:3] == ["-I", "-B", str(ROOT / "scripts/setup/install.py")]
    assert args[3:] == ["--prefix", str(tmp / "p"), "--only", "madgraph", "--accept-licenses"]
    assert not (tmp / "home").exists() or not any((tmp / "home").iterdir())


def test_shim_never_edits_shell_or_conda_configuration():
    text = SHIM.read_text()
    for forbidden in (".zshrc", ".bashrc", ".condarc", "conda init", "--agree-to-license", "sudo "):
        assert forbidden not in text


def test_dry_run_shows_the_miniforge_download_and_touches_nothing(system):
    settings, run, tmp = system
    prefix = tmp / "never-created"
    result = run("--dry-run", prefix=prefix)
    assert result.returncode == 0, result.stderr
    assert "Miniforge" in result.stdout and "https://github.com/conda-forge/miniforge" in result.stdout
    assert not prefix.exists() and not (tmp / "home").exists()


def test_dry_run_with_only_an_old_system_python_explains_instead_of_failing(system):
    """macOS ships Python 3.9 as python3. Before Miniforge exists the step list cannot be printed with it;
    the shim says so and stops cleanly instead of showing an import error."""
    settings, run, tmp = system
    settings["old_python"] = True
    for flag in ("--dry-run", "--plan"):
        result = run(flag, prefix=tmp / "p")
        assert result.returncode == 0, result.stderr
        assert "Miniforge 26.5.3-0 would be installed" in result.stdout
        assert "needs Python 3.11 or newer" in result.stdout and "Traceback" not in result.stderr
        assert not (tmp / "p").exists()
