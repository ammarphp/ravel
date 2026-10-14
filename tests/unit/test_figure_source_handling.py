"""Published-figure acquisition: safe archive extraction, main-file choice, figure ids, and
figure-contract paths relative to the run directory."""
import synthetic_identifiers as syn
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

from ravel.plotting import fetch_figures

REPO = Path(__file__).resolve().parents[2]
FT_PY = REPO / "src" / "ravel" / "plotting" / "figure_target.py"

PAPER = r"""\documentclass{article}
\usepackage{graphicx}
\graphicspath{{figs/}}
\begin{document}
\input{sections/results}
\end{document}
"""
RESULTS = r"""
\begin{figure}
\includegraphics{mass_spectrum}
\caption{Invariant mass spectrum in the signal region. Second sentence.}
\end{figure}
% \begin{figure}\includegraphics{commented_out}\end{figure}
\begin{figure*}
\includegraphics[width=0.4\textwidth]{limit_obs}
\includegraphics[width=0.4\textwidth]{limit_exp.png}
\caption{Observed and expected limits.}
\end{figure*}
"""
AUTHORS = r"""\documentclass{article}
\begin{document}
\section*{The Collaboration}
A.~Author$^{1}$, B.~Author$^{2}$
\end{document}
"""


def _add(tf, name, data, mode=0o644, kind=tarfile.REGTYPE, linkname=""):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.mode = mode
    info.linkname = linkname
    payload = data.encode() if isinstance(data, str) else data
    info.size = len(payload) if kind == tarfile.REGTYPE else 0
    tf.addfile(info, io.BytesIO(payload) if kind == tarfile.REGTYPE else None)


def _source_tarball(path):
    with tarfile.open(path, "w:gz") as tf:
        _add(tf, "authors.tex", AUTHORS)            # first in archive order
        _add(tf, "paper.tex", PAPER)
        _add(tf, "sections/results.tex", RESULTS)
        _add(tf, "figs/mass_spectrum.pdf", b"%PDF-1.4 a", mode=0o4777)
        _add(tf, "figs/limit_obs.pdf", b"%PDF-1.4 b")
        _add(tf, "figs/limit_exp.png", b"\x89PNG c")
        _add(tf, "figs/escape.png", b"", kind=tarfile.SYMTYPE, linkname="/etc/passwd")
    return path


def test_extraction_flattens_and_sanitizes_members(tmp_path):
    tarpath = _source_tarball(tmp_path / "src.tar.gz")
    figdir = tmp_path / "figures"
    extracted = fetch_figures.extract_figure_files(str(tarpath), str(figdir))
    assert extracted == {"mass_spectrum.pdf": "figs/mass_spectrum.pdf",
                         "limit_obs.pdf": "figs/limit_obs.pdf",
                         "limit_exp.png": "figs/limit_exp.png"}
    assert sorted(os.listdir(figdir)) == ["limit_exp.png", "limit_obs.pdf", "mass_spectrum.pdf"]
    mode = (figdir / "mass_spectrum.pdf").stat().st_mode
    assert not mode & (stat.S_ISUID | stat.S_IWOTH)
    assert not (figdir / "escape.png").exists()


def test_main_file_is_the_document_with_figures_not_the_author_list(tmp_path):
    tarpath = _source_tarball(tmp_path / "src.tar.gz")
    extracted = fetch_figures.extract_figure_files(str(tarpath), str(tmp_path / "figures"))
    fmap = fetch_figures.build_figure_map(str(tarpath), extracted, (syn.arxiv(680)))
    assert fmap["main_tex"] == "paper.tex"
    assert sorted(fmap["figures"]) == ["1", "2"]


def test_figure_map_entries_carry_figure_ids(tmp_path):
    tarpath = _source_tarball(tmp_path / "src.tar.gz")
    extracted = fetch_figures.extract_figure_files(str(tarpath), str(tmp_path / "figures"))
    fmap = fetch_figures.build_figure_map(str(tarpath), extracted, (syn.arxiv(680)))
    one, two = fmap["figures"]["1"], fmap["figures"]["2"]
    assert one["figure_id"] == "Figure 1"
    assert one["graphics"]["_"]["figure_id"] == "Figure 1"
    assert one["graphics"]["_"]["file"] == "mass_spectrum.pdf"
    assert two["figure_id"] == "Figure 2"
    assert two["graphics"]["a"]["figure_id"] == "Figure 2a"
    assert two["graphics"]["b"] == {"arg": "limit_exp.png", "member": "figs/limit_exp.png",
                                    "file": "limit_exp.png", "figure_id": "Figure 2b"}


def test_choose_main_tex_prefers_documentclass_and_figures():
    texs = {"notes.tex": "\\begin{document}text\\end{document}",
            "main.tex": PAPER, "sections/results.tex": RESULTS,
            "authors.tex": AUTHORS}
    assert fetch_figures.choose_main_tex(texs) == "main.tex"
    assert fetch_figures.choose_main_tex({"a.tex": "no document here"}) is None


# ------------------------------------------------------------------- figure contract paths
def _ft(*args, cwd):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(FT_PY), *args], capture_output=True, text=True,
                          cwd=cwd, env=env)


def _contract(rd):
    return json.loads((rd / "inputs" / "figure_target.json").read_text())


def test_attached_paths_resolve_against_the_run_directory(tmp_path):
    rd = tmp_path / "run"
    (rd / "published" / "figures").mkdir(parents=True)
    (rd / "published" / "figures" / "limit_obs.pdf").write_bytes(b"%PDF")
    (rd / "plots").mkdir()
    (rd / "plots" / "contour.png").write_bytes(b"png")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    r = _ft("declare", "--rundir", str(rd), "--role", "summary", "--figure-id", "Fig. 2(a)",
            "--source", "paper-inspection", "--arxiv", (syn.arxiv(680)), "--no-checkin", cwd=elsewhere)
    assert r.returncode == 0, r.stderr
    r = _ft("attach-image", "--rundir", str(rd), "--figure-id", "2a", "--route", "arxiv-tex-map",
            "--path", "published/figures/limit_obs.pdf", cwd=elsewhere)
    assert r.returncode == 0, r.stderr
    r = _ft("attach-generated", "--rundir", str(rd), "--figure-id", "2a",
            "--path", "plots/contour.png", "--step", "08-scan", cwd=elsewhere)
    assert r.returncode == 0, r.stderr
    tgt = _contract(rd)["targets"][0]
    assert tgt["extracted_image"]["path"] == str(rd / "published" / "figures" / "limit_obs.pdf")
    assert tgt["generated_counterpart"]["path"] == str(rd / "plots" / "contour.png")


def test_attach_image_infers_the_route(tmp_path):
    rd = tmp_path / "run"
    (rd / "paper").mkdir(parents=True)
    (rd / "paper" / "p.pdf").write_bytes(b"%PDF")
    assert _ft("declare", "--rundir", str(rd), "--role", "summary", "--figure-id", "4",
               "--caption", "Expected limits.", "--source", "paper-inspection",
               "--arxiv", (syn.arxiv(680)), "--no-checkin", cwd=tmp_path).returncode == 0
    r = _ft("attach-image", "--rundir", str(rd), "--figure-id", "4", "--path", "paper/p.pdf",
            "--pdf-page", "7", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert _contract(rd)["targets"][0]["extracted_image"]["route"] == "pdf-page"
    r = _ft("attach-image", "--rundir", str(rd), "--figure-id", "4", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert _contract(rd)["targets"][0]["extracted_image"]["route"] == "none"


def test_description_only_target_needs_no_paper_id(tmp_path):
    rd = tmp_path / "run"
    r = _ft("declare", "--rundir", str(rd), "--role", "summary", "--source", "description-only",
            "--caption", "Combined exclusion reach of the listed searches in the mass plane.",
            "--no-checkin", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    tgt = _contract(rd)["targets"][0]
    assert tgt["figure_id"] is None and tgt["source"] == "description-only"
    assert tgt["reference_comparison"]["deliverable"] == "non-comparison"
    (rd / "plots").mkdir()
    (rd / "plots" / "reach.png").write_bytes(b"png")
    r = _ft("attach-generated", "--rundir", str(rd), "--role", "summary",
            "--path", "plots/reach.png", "--step", "05-visualize", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert _contract(rd)["targets"][0]["generated_counterpart"]["path"] == str(rd / "plots" / "reach.png")


def test_a_named_figure_still_requires_a_paper_id(tmp_path):
    r = _ft("declare", "--rundir", str(tmp_path / "run"), "--role", "summary", "--figure-id", "3",
            "--source", "paper-inspection", "--no-checkin", cwd=tmp_path)
    assert r.returncode != 0 and "paper id" in r.stderr
