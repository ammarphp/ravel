"""Documentation figures: present, current, outlined, safe, on one canvas, and free of file labels."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIG = ROOT / "docs" / "figures"
SRC = FIG / "src"
STY = FIG / "ravel-figures.sty"
MANIFEST = FIG / "manifest.json"
OUTPUTS = ("svg/light/{n}.svg", "svg/dark/{n}.svg", "pdf/{n}.pdf", "png/{n}.png")
FILE_LABEL = re.compile(
    r"[\w.-]+\.(?:py|md|json|sh|tex|sty|ya?ml|toml|lhe|hepmc|root|yoda|dat|csv|cc|cpp|h)\b"
    r"|(?:\b[\w.-]+/){1,}[\w.-]+"
)
CANVAS_MM = 170.0
PT_PER_MM = 72.0 / 25.4


def _sources() -> list[Path]:
    return sorted(SRC.glob("*.tex"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_digest(tex: Path) -> str:
    return hashlib.sha256(STY.read_bytes() + b"\0" + tex.read_bytes()).hexdigest()


def _node_texts(tex: Path) -> list[str]:
    text = re.sub(r"(?<!\\)%.*", "", tex.read_text(encoding="utf-8"))
    return re.findall(r"\\node(?:\[[^\]]*\])?(?:\s*\([^)]*\))?(?:\s*at\s*\([^)]*\))?\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text)


def test_sources_exist():
    assert STY.is_file()
    assert _sources(), "no figure sources"


@pytest.mark.parametrize("tex", _sources(), ids=lambda p: p.stem)
def test_every_source_has_all_outputs(tex: Path):
    for pattern in OUTPUTS:
        out = FIG / pattern.format(n=tex.stem)
        assert out.is_file() and out.stat().st_size > 0, f"missing {out.relative_to(ROOT)}"


def test_manifest_matches_sources():
    manifest = json.loads(MANIFEST.read_text())
    names = {p.stem for p in _sources()}
    assert set(manifest) == names, "manifest and sources differ; rebuild with scripts/build_figures.py"
    for tex in _sources():
        entry = manifest[tex.stem]
        assert entry["source_sha256"] == _source_digest(tex), f"{tex.stem} is stale; rebuild it"
        for rel, digest in entry["outputs"].items():
            assert _sha(FIG / rel) == digest, f"{rel} differs from the manifest; rebuild"


@pytest.mark.parametrize("tex", _sources(), ids=lambda p: p.stem)
def test_svgs_are_outlined_and_safe(tex: Path):
    for mode in ("light", "dark"):
        svg = (FIG / "svg" / mode / f"{tex.stem}.svg").read_text(encoding="utf-8")
        assert "<text" not in svg, "text must be outlined"
        assert "<script" not in svg and "<foreignObject" not in svg
        assert not re.search(r"(?:href|src)=['\"]https?:", svg), "no external references"
        assert "viewBox=" in svg


@pytest.mark.parametrize("tex", _sources(), ids=lambda p: p.stem)
def test_figures_share_canvas_width(tex: Path):
    svg = (FIG / "svg" / "light" / f"{tex.stem}.svg").read_text(encoding="utf-8")
    width_pt = float(re.search(r"width='([\d.]+)pt'", svg).group(1))
    assert abs(width_pt - CANVAS_MM * PT_PER_MM) < 1.0, f"{tex.stem} is {width_pt:.1f} pt wide"


@pytest.mark.parametrize("tex", _sources(), ids=lambda p: p.stem)
def test_no_file_labels_in_figures(tex: Path):
    for label in _node_texts(tex):
        plain = re.sub(r"\\[a-zA-Z]+\*?(\{[^}]*\})?", " ", label)
        assert not FILE_LABEL.search(plain), f"{tex.stem}: file label in node text {label!r}"


@pytest.mark.parametrize("tex", _sources(), ids=lambda p: p.stem)
def test_sources_use_only_the_style(tex: Path):
    text = re.sub(r"(?<!\\)%.*", "", tex.read_text(encoding="utf-8"))
    forbidden = [r"\\definecolor", r"\\fontsize", r"\\setmainfont", r"\\setsansfont", r"\\usepackage\{fontspec\}",
                 r"#[0-9A-Fa-f]{6}", r"\b(?:red|blue|green|black|gray|orange|purple)!\d"]
    for pattern in forbidden:
        assert not re.search(pattern, text), f"{tex.stem}: {pattern} belongs in ravel-figures.sty"
    assert r"\usepackage{ravel-figures}" in text


def test_no_text_below_minimum():
    sty = STY.read_text(encoding="utf-8")
    sizes = [float(s) for s in re.findall(r"\\fontsize\{([\d.]+)\}", sty)]
    assert sizes and min(sizes) >= 9.0


def _hex_to_lum(hexcode: str) -> float:
    rgb = [int(hexcode[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_hex_to_lum(a), _hex_to_lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_figure_contrast_meets_aa():
    sty = STY.read_text(encoding="utf-8")
    for mode in ("light", "dark"):
        block = re.search(rf"%% palette:{mode}(.*?)%% end palette:{mode}", sty, re.S).group(1)
        colours = dict(re.findall(r"\\definecolor\{(\w+)\}\{HTML\}\{([0-9A-Fa-f]{6})\}", block))
        text = colours["rvtext"]
        fills = {k: v for k, v in colours.items() if k.endswith("fill")} | {"rvbackground": colours["rvbackground"]}
        for name, fill in fills.items():
            assert _contrast(text, fill) >= 4.5, f"{mode}: rvtext on {name} is {_contrast(text, fill):.2f}:1"
        assert _contrast(colours["rvmuted"], colours["rvbackground"]) >= 4.5


LAYERS = ("people", "agent", "guard", "ravel", "hep", "records")
# Machado, Oliveira & Fernandes (2009), severity 1.0, applied in linear RGB.
VISION = {
    "normal": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
}


def _palette(mode: str) -> dict[str, str]:
    sty = STY.read_text(encoding="utf-8")
    block = re.search(rf"%% palette:{mode}(.*?)%% end palette:{mode}", sty, re.S).group(1)
    return dict(re.findall(r"\\definecolor\{(\w+)\}\{HTML\}\{([0-9A-Fa-f]{6})\}", block))


def _linear(hexcode: str) -> list[float]:
    rgb = [int(hexcode[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]


def _lab(lin_rgb: list[float]) -> tuple[float, float, float]:
    r, g, b = (min(1.0, max(0.0, c)) for c in lin_rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = [t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116 for t in (x, y, z)]
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


def _de2000(lab1, lab2) -> float:
    import math
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    cbar = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p, h2p = math.degrees(math.atan2(b1, a1p)) % 360, math.degrees(math.atan2(b2, a2p)) % 360
    dlp, dcp = L2 - L1, c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    else:
        dhp = h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    lbp, cbp = (L1 + L2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    else:
        hbp = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    sl = 1 + 0.015 * (lbp - 50) ** 2 / math.sqrt(20 + (lbp - 50) ** 2)
    sc, sh = 1 + 0.045 * cbp, 1 + 0.015 * cbp * t
    rt = -2 * math.sqrt(cbp ** 7 / (cbp ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-(((hbp - 275) / 25) ** 2))))
    return math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2 + rt * (dcp / sc) * (dHp / sh))


def _seen(hexcode: str, vision: str) -> tuple[float, float, float]:
    lin_rgb = _linear(hexcode)
    m = VISION[vision]
    return _lab([sum(m[i][j] * lin_rgb[j] for j in range(3)) for i in range(3)])


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("vision", list(VISION))
def test_layer_borders_distinct_for_every_reader(mode: str, vision: str):
    colours = _palette(mode)
    seen = {layer: _seen(colours[f"rv{layer}line"], vision) for layer in LAYERS}
    for a, b in __import__("itertools").combinations(LAYERS, 2):
        assert _de2000(seen[a], seen[b]) >= 12.0, f"{mode}/{vision}: {a} and {b} borders too similar"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_layer_fills_distinct_for_normal_vision(mode: str):
    colours = _palette(mode)
    seen = {layer: _seen(colours[f"rv{layer}fill"], "normal") for layer in LAYERS}
    for a, b in __import__("itertools").combinations(LAYERS, 2):
        assert _de2000(seen[a], seen[b]) >= 5.0, f"{mode}: {a} and {b} fills too similar"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_borders_meet_non_text_contrast(mode: str):
    colours = _palette(mode)
    for layer in LAYERS:
        line = colours[f"rv{layer}line"]
        assert _contrast(line, colours["rvbackground"]) >= 3.0, f"{mode}: {layer} border on background"
        assert _contrast(line, colours[f"rv{layer}fill"]) >= 3.0, f"{mode}: {layer} border on its fill"


def test_build_rejects_overflowing_labels():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_figures", ROOT / "scripts" / "build_figures.py")
    build_figures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_figures)
    log = ("(./overview.tex\n"
           "Overfull \\hbox (6.29074pt too wide) in paragraph at lines 35--35\n"
           "[]\\TU/Inter(1)/b/n/10.95 MadGraph5_aMC@NLO\n"
           "Underfull \\hbox (badness 10000) in paragraph at lines 9--9\n")
    problems = build_figures.overfull_labels(log)
    assert problems == ["6.3 pt too wide: MadGraph5_aMC@NLO"]
    assert build_figures.overfull_labels("Underfull \\hbox (badness 10000)\n") == []


def _chipgate_labels(tex: Path) -> list[str]:
    text = re.sub(r"(?<!\\)%.*", "", tex.read_text(encoding="utf-8"))
    labels = re.findall(r"\\node\[chipgate[^\]]*\][^{;]*\{((?:[^{}]|\{[^{}]*\})*)\}", text)
    for groups in re.findall(r"\\(?:chips|ravelchips|ravelrow)(?:\[[^\]]*\])?\{chipgate\}((?:\{[^{}]*\})+)", text):
        labels += [part.strip() for part in re.findall(r"\{([^{}]*)\}", groups)[-1].split(",")]
    # A bare macro is a \foreach variable (the check-ins table); its rows are the check-ins themselves.
    return [label for label in labels if not re.fullmatch(r"\\[A-Za-z]+", label.strip())]


@pytest.mark.parametrize("tex", _sources(), ids=lambda p: p.stem)
def test_chamfered_shape_marks_only_checkins(tex: Path):
    """The chamfered shape means 'the work stops for you'; approved inputs and other chips stay rounded."""
    for label in _chipgate_labels(tex):
        assert re.search(r"CHECK-IN|check-in", label), f"{tex.stem}: chamfered chip {label!r} is not a check-in"
        assert r"\textbf" not in label, f"{tex.stem}: check-in weight belongs in the chipgate style"


def test_checkin_weight_is_set_once_in_the_style():
    sty = STY.read_text(encoding="utf-8")
    assert re.search(r"chipgate/\.style=\{[^}]*\\bfseries", sty)
    for tex in _sources():
        text = re.sub(r"(?<!\\)%.*", "", tex.read_text(encoding="utf-8"))
        assert not re.search(r"\\node\[chipgate[^\]]*font=", text), f"{tex.stem}: chipgate font override"


def test_checkin_2_is_not_a_station_on_the_line():
    """CHECK-IN 2 is held once, at the agreed waypoint; on the line, the scan loop would pass it every point."""
    text = (SRC / "lifecycle.tex").read_text(encoding="utf-8")
    on_line = re.findall(r"\\node\[stationgate\][^;]*at \(\\lx,", text)
    assert len(on_line) == 2, f"{len(on_line)} check-in stations on the line; expected CHECK-IN 1 and the final one"
