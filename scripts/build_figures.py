#!/usr/bin/env python3
"""Build the documentation figures from their TikZ sources.

Each source in docs/figures/src is compiled twice per colour mode: DVI with the dvisvgm TikZ driver gives an SVG
with outlined text, and PDF mode (light palette) gives the print PDF, from which Ghostscript renders a 300 dpi PNG.
docs/figures/manifest.json records each source digest (style file plus source) and each output digest.

Usage: python scripts/build_figures.py [--check] [names...]
Exit codes: 0 success; 1 --check found stale or missing outputs; 2 a tool failed or is missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "figures"
SRC = FIG / "src"
STY = FIG / "ravel-figures.sty"
MANIFEST = FIG / "manifest.json"
EPOCH = "1790000000"  # fixed creation date for reproducible outputs
TOOLS = ("lualatex", "dvisvgm", "gs")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(tex: Path) -> str:
    return hashlib.sha256(STY.read_bytes() + b"\0" + tex.read_bytes()).hexdigest()


def output_paths(name: str) -> dict[str, Path]:
    return {
        f"svg/light/{name}.svg": FIG / "svg" / "light" / f"{name}.svg",
        f"svg/dark/{name}.svg": FIG / "svg" / "dark" / f"{name}.svg",
        f"pdf/{name}.pdf": FIG / "pdf" / f"{name}.pdf",
        f"png/{name}.png": FIG / "png" / f"{name}.png",
    }


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["TEXINPUTS"] = f"{FIG}{os.pathsep}{SRC}{os.pathsep}"
    env["SOURCE_DATE_EPOCH"] = EPOCH
    env["FORCE_SOURCE_DATE"] = "1"
    return env


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=cwd, env=_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-25:])
        raise RuntimeError(f"{' '.join(cmd[:2])} failed ({proc.returncode}):\n{tail}")


def overfull_labels(log: str) -> list[str]:
    """Labels wider than their box: TeX reports each as an overfull hbox, followed by the offending text."""
    problems = []
    lines = log.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"Overfull \\hbox \(([\d.]+)pt too wide\)", line)
        if match:
            text = lines[i + 1] if i + 1 < len(lines) else ""
            text = re.sub(r"\\[A-Za-z]+/[^ ]+ |\[\]", "", text).strip()
            problems.append(f"{float(match.group(1)):.1f} pt too wide: {text}")
    return problems


def build(tex: Path) -> dict[str, str]:
    name = tex.stem
    outs = output_paths(name)
    for path in outs.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"fig-{name}-") as tmp:
        work = Path(tmp)
        for mode in ("light", "dark"):
            job = f"{name}-{mode}"
            _run(["lualatex", "--output-format=dvi", "-interaction=nonstopmode", "-halt-on-error",
                  f"-jobname={job}",
                  rf"\def\pgfsysdriver{{pgfsys-dvisvgm.def}}\def\ravelmode{{{mode}}}\input{{{tex}}}"], work)
            _run(["dvisvgm", "--no-fonts", "--exact-bbox", "--precision=3", "--optimize",
                  "-o", str(outs[f"svg/{mode}/{name}.svg"]), f"{job}.dvi"], work)
        _run(["lualatex", "-interaction=nonstopmode", "-halt-on-error", f"-jobname={name}",
              rf"\def\ravelmode{{light}}\input{{{tex}}}"], work)
        overflow = overfull_labels((work / f"{name}.log").read_text(errors="replace"))
        if overflow:
            raise RuntimeError(f"{name}: labels overflow their boxes:\n  " + "\n  ".join(overflow))
        shutil.copyfile(work / f"{name}.pdf", outs[f"pdf/{name}.pdf"])
        _run(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m", "-r300",
              "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4", "-o", str(outs[f"png/{name}.png"]),
              str(outs[f"pdf/{name}.pdf"])], work)
    return {rel: sha256(path) for rel, path in outs.items()}


def stale(names: list[str]) -> list[str]:
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    problems = []
    for tex in sorted(SRC.glob("*.tex")):
        if names and tex.stem not in names:
            continue
        entry = manifest.get(tex.stem)
        if entry is None or entry.get("source_sha256") != source_digest(tex):
            problems.append(f"{tex.stem}: source changed or not built")
            continue
        for rel, digest in entry["outputs"].items():
            path = FIG / rel
            if not path.exists() or sha256(path) != digest:
                problems.append(f"{tex.stem}: {rel} missing or edited")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="figure names (default: all)")
    parser.add_argument("--check", action="store_true", help="report stale or missing outputs; build nothing")
    args = parser.parse_args(argv)
    if args.check:
        problems = stale(args.names)
        for line in problems:
            print(f"STALE {line}")
        print("figures: OK" if not problems else f"figures: {len(problems)} stale")
        return 1 if problems else 0
    missing = [tool for tool in TOOLS if shutil.which(tool) is None]
    if missing:
        print(f"missing tools: {', '.join(missing)} (TeX Live 2024 and Ghostscript are required)", file=sys.stderr)
        return 2
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    sources = [tex for tex in sorted(SRC.glob("*.tex")) if not args.names or tex.stem in args.names]
    unknown = set(args.names) - {tex.stem for tex in sources}
    if unknown:
        print(f"unknown figures: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    for tex in sources:
        try:
            outputs = build(tex)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 2
        manifest[tex.stem] = {"source_sha256": source_digest(tex), "outputs": outputs}
        print(f"built {tex.stem}")
    known = {tex.stem for tex in SRC.glob("*.tex")}
    manifest = {k: v for k, v in sorted(manifest.items()) if k in known}
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
