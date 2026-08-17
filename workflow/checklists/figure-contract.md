# Checklist — the FIGURE CONTRACT  ·  [judgment] declares · [agent] extracts/composes

A reproduction is only checkable if the run states, **up front**, the specific published figure it is
reproducing ("Figure N of arXiv:XXXX.XXXXX") — echoes it to the physicist at the step-2 check-in —
and, at the end, emits the generated counterpart **side-by-side** with it. The contract lives at
`<rundir>/inputs/figure_target.json` and is owned by `trial-runs/_infrastructure/figure_target.py`.
It is fully general: nothing in the protocol is tied to any one analysis — the figure↔data linkage
is the paper-agnostic fact that HEPData table names very often literally carry the figure id
("Figure 7 Observed …"), which `hepdata_fetch.py` indexes as `figure_index` on every discovery pass.

## The contract file (schema_version 1)
`targets[]`, one per figure the run reproduces (typically one `summary` + optionally one `overlay`):

| field | meaning |
|---|---|
| `primary` | the headline target (one per run) |
| `role` | `summary` (exclusion contour/limit figure) or `overlay` (yield/distribution figure) |
| `paper` | `{arxiv, inspire, code}` — at least one id, so the reference is precise |
| `figure_id` | normalized `"Figure 16a"` form (declare accepts `fig 16a` / `Fig. 16(a)` / …), or null |
| `caption_snippet` | first sentence of the published caption (the textual anchor) |
| `source` | how the id was resolved: `user-prompt \| registry-hint \| hepdata-table-name \| paper-inspection \| description-only` |
| `hepdata_tables` | the HEPData table name(s) backing the figure (from `figure_index`) |
| `extracted_image` | `{path, route: arxiv-tex-map\|pdf-page\|none, pdf_page}` — the published pixels |
| `generated_counterpart` | `{path, step: 05-visualize\|08-scan}` — this pipeline's figure |
| `side_by_side` | the composed published-vs-generated PNG (from `compose`) |
| `declared_at_checkin` / `verified_by_physicist` | the echo + confirmation audit trail |

## Resolution precedence (how `figure_id` gets decided — [judgment], never auto)
| rank | source | mechanism |
|---|---|---|
| 1 | **user-prompt** | the requester named the figure ("reproduce Fig 3 of arXiv:…") → `declare` directly, no resolve |
| 2 | **registry-hint** | `figure_manifest.py` `FIGURE_HINTS` (optional curated accelerator; confirm, don't trust blindly) |
| 3 | **hepdata-table-name** | `figure_target.py resolve` ranks the manifest's `figure_index` by role + model keywords; **it prints candidates and exits — [judgment] reads the descriptions and chooses**, then calls `declare` |
| 4 | **paper-inspection** | read the paper (`fetch_figures.py`, the PDF) and identify the figure by eye |
| 5 | **description-only** | no figure id resolvable — declare a caption/description and raise it at the CHECK-IN |

## Extraction routes + the degradation ladder (`fetch_figures.py --figure <id>`)
1. **arxiv-tex-map** — parse the saved source tarball's `.tex` (main file → `\input` order → figure
   envs in document order, `\includegraphics` + caption, `\graphicspath`), match the figure to its
   extracted file; the whole map persists as `<out>/figure_map.json` (`--map-captions` builds it
   standalone). Numbering follows document order — any inconsistency WARNs and falls through.
2. **pdf-page** — pypdf text-scan for the "Figure N:" caption; rasterize that page via
   `gs -r200` to `figures/figN_pageP.png` (if gs fails, the page number alone is recorded).
3. **textual reference (route `none`)** — no pixels. **A VALID terminal state** provided
   `figure_id` + `caption_snippet` are populated: the physicist verifies against the precise
   reference instead of an echoed image. Never block a run on figure extraction.

## Emission contract (what the run owes at the end)
- Step 5 (`05-visualize`) or step 8 (`08-scan`) attaches the generated figure:
  `figure_target.py attach-generated --figure-id <ID> --path <plot> --step <05-visualize|08-scan>`.
- `figure_target.py compose --figure-id <ID>` emits the side-by-side PNG — published left
  (labelled "published (arXiv:X, Figure N)"), generated right ("this pipeline"); a PDF source is
  rasterized via gs. With no extracted image it emits the generated figure under a
  **textual-reference banner** (the degraded-but-valid form) and exits 0.
- `figure_target.py show` prints the check-in block (paper ids, figure id, caption, image path or
  "NOT EXTRACTED — verify via figure id + caption") — echo it at the step-2 and step-8 CHECK-INs.
- `result_pack.py` embeds the contract top-level in `figures.json` and **WARNs on any declared
  target whose `generated_counterpart` is null** — a declared-but-unfulfilled contract is loud.
- `validate_run_state.py` is **PRIMARY-aware and hard-FAILs** (not WARNs) once generation is
  complete, in **every** task_mode (scan/reinterpret included, where the figure_contract STAGE is
  only level O and does not gate on `side_by_side`): the single target marked `primary` — once it
  carries `declared_at_checkin` — must have BOTH a non-null `generated_counterpart` AND a non-null
  `side_by_side` (run `figure_target.py compose`), or the `figure-contract-fulfilled` invariant
  fails the run. A contract with **more than one target marked `primary`** also FAILs here — the
  single-primary invariant is enforced at validate time, not only on the write path via
  `figure_target.py primary`. Non-primary declared-but-unrendered targets stay advisory (the
  `result_pack.py` WARN above), not a hard fail.

## Figure-SPEC block + the critique loop (M4b — BUILT 2026-07-07, CR-026)
Beyond `axes`, the contract carries a `style` block read off the EXTRACTED published figure at
declaration (protocol P1 look-first): `{binning, error_band_style, marker_conventions,
color_encoding, annotation_set (experiment label, lumi, √s, region labels), hatching,
legend_order, panel_structure}` — each a FACT from looking, never a default (scales live in
`axes`). Declare it with `figure_target.py declare --style-json '{...}'` (inline JSON or `@file`);
`show` prints the recorded facts; `read_style()` is the consumption API (mirrors `read_axes`).

Then the **bounded structural-critique loop**:
```
figure_target.py compose  --rundir R --figure-id ID              # build the side-by-side first
figure_target.py critique --rundir R --figure-id ID              # EMIT the task (composite + style facts + rubric)
#   -> hand the printed task to a FRESH-CONTEXT agent that sees ONLY the composite; it returns
#      {"iterations":N,"mismatches":[...],"surviving_mismatches":[...]}
figure_target.py critique --rundir R --figure-id ID --record @findings.json
```
The critic lists STRUCTURAL mismatches only (never aesthetics), distinguishing **defects**
(→ `mismatches`, drive ≤2 fix iterations) from **stated-subset / deliberate deviations**
(→ `surviving_mismatches`, become caption'd deviations in the deck). The loop is bounded at 2
iterations (a warning fires past it). The CR-016 lint gate owns the LAYOUT half of R6; this loop
owns the CONTENT half — together they close the KNOWN-LIMITATIONS R6 two-tier entry.
**Worked precedents:** the fig3 loop (form-verification caught the blocky-lattice form + a
provenance-hazard ATLAS stamp) and the live CMS-EXO-22-026 Figure 5 run (a fresh-context critic
scored the real published-vs-generated composite: 0 defects, 3 caption'd deviations — subset
scope + deliberate non-CMS labelling correctly classified as legitimate, not defects).

## Generality note
The protocol logic carries **no analysis-specific knowledge**: `figure_index` is a regex over table
names on any HEPData record; `resolve` ranks by *role* vocabulary (exclusion/contour/limit vs
yield/distribution/events) plus whatever model keywords the caller supplies; `compose` is
renderer-agnostic (any published image vs any generated PNG/PDF — contour, bars, distribution).
Analysis-specific figure ids exist in exactly one place — the optional curated `FIGURE_HINTS`
registry — and even a hit there is only a hint [judgment] confirms against the resolve candidates.

- **compose stamps provenance** (`composed_by {tool, utc}`): the run-state gate hard-FAILs a PRIMARY whose `side_by_side` is hand-populated (path not on disk, or no stamp) — only `figure_target.py compose` output satisfies the primary contract (A2, trial QI.2).
