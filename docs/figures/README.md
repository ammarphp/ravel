# Documentation figures

The figures in the README and in [docs/architecture](../architecture/README.md) are built from TikZ sources in this
folder. All of them share one style file, so they use the same typeface, sizes, colours, shapes and spacing.

## Layout

| Path | Contents |
|---|---|
| `ravel-figures.sty` | The shared style: typeface, type scale, light and dark palettes, shapes, connectors, canvas |
| `src/` | One TikZ source per figure |
| `svg/light/`, `svg/dark/` | SVG for the web, text converted to outlines; the README shows the variant that matches the reader's colour scheme |
| `pdf/` | PDF with embedded fonts, for print (light palette) |
| `png/` | 300 dpi PNG, for quick viewing (light palette) |
| `manifest.json` | The digest of each source and of each built file |

## Rebuilding

You need TeX Live 2024 or later (LuaLaTeX, TikZ, fontspec, the Inter font and dvisvgm) and Ghostscript.

```bash
python scripts/build_figures.py            # build every figure
python scripts/build_figures.py overview   # build one figure
python scripts/build_figures.py --check    # report figures whose source changed since the last build
```

The build is reproducible: it fixes the creation date, so an unchanged source gives unchanged files. A unit test
(`tests/unit/test_figures.py`) fails when a source or the style file changes without a rebuild, when an SVG still
contains live text, or when a figure breaks one of the rules below.

## Design rules

- **Typeface.** Inter (SIL Open Font License) in every figure: Bold for figure titles, SemiBold for node titles,
  Regular for labels.
- **Sizes.** Every figure is drawn on a 170 mm wide canvas, so all figures appear at the same scale. Text is never
  smaller than 9 pt, which is about 15.5 px across the README's width. Figure titles 13 pt, node titles 11 pt
  (also the lifecycle station names), labels 10 pt (also the lifecycle station descriptions), notes 9 pt.
- **Case.** Sentence case for titles, panel labels and chips; secondary lines and connector labels start in lower
  case. Tool names keep their official spelling (MadGraph5_aMC@NLO, Pythia 8, Delphes, SimpleAnalysis, Rivet, pyhf,
  HEPData). Human check-ins are written CHECK-IN 1, CHECK-IN 2. Step names are proper names (Analyze, Visualize);
  the prose around them uses British spelling.
- **Colour.** One hue per layer. Red covers the guardrails and the checks a step must pass; amber covers you and the
  check-ins, and connectors that return work to you are amber too. Every text colour meets the WCAG AA contrast ratio
  (4.5:1) on every fill, and every border has at least 3:1 against the background and its fill, in both palettes. Colour
  is never the only cue: each layer is also labelled.

  | Layer | Light fill / border | Dark fill / border |
  |---|---|---|
  | You and the check-ins | `#FDE8D1` / `#9D6700` | `#3A2C1B` / `#F8B452` |
  | Agent guidance | `#FFE3F7` / `#752865` | `#3C2837` / `#C775B3` |
  | Guardrails and required checks | `#FFE6DF` / `#8B190A` | `#412822` / `#E76B4F` |
  | The ravel package | `#DAEDFF` / `#0A79AC` | `#183142` / `#80C8FD` |
  | External software and public data | `#D3F2E1` / `#1E9365` | `#1A3327` / `#7CE6B3` |
  | Records and evidence | `#E5ECF2` / `#78838B` | `#292F33` / `#C8D3DC` |

  Borders vary in lightness as well as hue, so any two layers stay distinguishable for readers with
  deuteranopia or protanopia (CIEDE2000 difference of at least 12, tested). The pale fills cannot all stay
  distinct under colour-vision deficiency, which is why every layer is also labelled.

- **Shapes.** Rounded rectangles for components, actions and records, coloured by layer; the chamfered shape only
  for a check-in, always SemiBold; a stacked shape for stored records in the overview. In the lifecycle, numbered
  rings are steps and octagons are check-ins. Chip and box borders 0.8 pt, group panels 0.6 pt, lifecycle stations
  1.6 pt and check-in stations 1.4 pt. Connectors are 1.0 pt with one arrowhead style; dashed connectors only for
  loops and optional paths, and a dashed group only for alternatives of which exactly one runs. Plain 0.8 pt lines in
  the layer colour link a trigger to its checks in the guardrails table.
- **Content.** Figures name concepts and tools, never files, paths or internal identifiers. The text next to each
  figure gives the detail.

## Figures

| Figure | Used in |
|---|---|
| `overview` | README, "How RAVEL works"; architecture index |
| `lifecycle` | README, "How a calculation runs"; architecture index |
| `architecture` | README appendix; architecture index |
| `stage-1-environment` … `stage-9-verify` | The nine stage pages in docs/architecture |
| `checkins`, `guardrails`, `records`, `backends` | The cross-cutting pages in docs/architecture |
| `specimen` | Not embedded; shows the colours, the main shapes and the connectors on one canvas, for contributors |
