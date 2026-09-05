#!/usr/bin/env python
"""Give a Rivet routine's cryptic plot files standardized, parseable names + a legend.

rivet-mkhtml writes plots keyed by the routine's internal object names -- HEPData
table IDs like `d04-x01-y01`, or terse SR tags like `2jl` / `CF-2jl`. A scientist
cannot tell from `d04-x01-y01.png` what physical quantity it shows. This step makes
a `named/` copy of every plot under a standard scheme and writes an INDEX.md legend.

NAMING CONVENTION (standardized; the same for every run):
    <routine>__<origID>__<label>.<ext>
  - <routine> : the Rivet routine (provenance)
  - <origID>  : the routine's original object id (kept verbatim, so every plot is
                still traceable to its HEPData table / routine object)
  - <label>   : a slugified physical descriptor (what the plot shows + region)
  e.g.  ATLAS_2016_I1458270__d04-x01-y01__meff-incl_SR-2jl.png

Label source, in priority order:
  1) an explicit --labels JSON  ({origID: {label, shows, definition, source}})
     -- the [Opus] physics map (read from the routine .cc / the paper);
  2) the routine .plot file's per-id Title;  3) the plot .py file's title=...;
  4) fallback: the origID itself (flagged "unlabeled" in the legend).

Usage:
  name_plots.py --plots-dir DIR --routine NAME [--labels labels.json]
                [--plot-file ROUTINE.plot] [--out-dir DIR/named]
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.plotting"

import argparse, json, os, re, shutil, glob, sys


def slug(s):
    s = re.sub(r"\$|\\mathrm|\\,|\{|\}|\\", "", s)
    s = re.sub(r"[^A-Za-z0-9.+-]+", "-", s).strip("-")
    return s[:60] or "plot"


def labels_from_plotfile(path, routine):
    """Parse `# BEGIN PLOT /routine/<id>` ... `Title=...` blocks."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    cur, title = None, None
    for line in open(path):
        m = re.match(rf"#\s*BEGIN PLOT\s+/{re.escape(routine)}/(\S+)", line)
        if m:
            cur, title = m.group(1), None
        elif line.startswith("Title=") and cur:
            title = line.split("=", 1)[1].strip()
        elif re.match(r"#\s*END PLOT", line) and cur and title:
            if "*" not in cur and "." not in cur.replace("-", "").replace("x", "").replace("y", ""):
                out[cur] = title
            cur = None
    return out


def title_from_pyfile(py):
    if not os.path.exists(py):
        return None
    for line in open(py):
        m = re.search(r"['\"]Title['\"]\s*[:=]\s*['\"](.+?)['\"]", line)
        if m:
            return m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plots-dir", required=True, help="rivet-mkhtml output dir (the per-routine folder)")
    ap.add_argument("--routine", required=True)
    ap.add_argument("--labels", help="JSON: {origID: {label, shows, definition, source}}")
    ap.add_argument("--plot-file", help="ROUTINE.plot (for Title fallback)")
    ap.add_argument("--out-dir", help="default: <plots-dir>/named")
    args = ap.parse_args()

    # --- input validation: a silent no-op here means a run ships with unnamed plots ---
    if not os.path.isdir(args.plots_dir):
        print(f"ERROR: --plots-dir does not exist (or is not a directory): {args.plots_dir}\n"
              f"       (expected the rivet-mkhtml per-routine output folder)", file=sys.stderr)
        sys.exit(1)
    if args.labels and not os.path.exists(args.labels):
        print(f"ERROR: --labels file not found: {args.labels}\n"
              f"       (pass the run's inputs/plot_labels.json, or omit --labels to fall back "
              f"to .plot/.py titles)", file=sys.stderr)
        sys.exit(1)
    if args.plot_file and not os.path.exists(args.plot_file):
        print(f"WARNING: --plot-file not found: {args.plot_file} (Title fallback disabled)",
              file=sys.stderr)

    out_dir = args.out_dir or os.path.join(args.plots_dir, "named")
    os.makedirs(out_dir, exist_ok=True)
    labels = json.load(open(args.labels)) if args.labels else {}
    plot_titles = labels_from_plotfile(args.plot_file, args.routine)

    pngs = sorted(glob.glob(os.path.join(args.plots_dir, "*.png")))
    if not pngs:
        print(f"ERROR: no .png plots found in {args.plots_dir} -- nothing to name.\n"
              f"       Did rivet-mkhtml run into this directory? (it writes "
              f"<out>/<ROUTINE>/*.png)", file=sys.stderr)
        sys.exit(1)
    rows = []
    for png in pngs:
        oid = os.path.basename(png)[:-4]
        meta = labels.get(oid, {})
        if meta.get("label"):
            label, src = meta["label"], "labels"
        elif oid in plot_titles:
            label, src = slug(plot_titles[oid]), ".plot"
        elif title_from_pyfile(png[:-4] + ".py"):
            label, src = slug(title_from_pyfile(png[:-4] + ".py")), ".py"
        else:
            label, src = slug(oid), "unlabeled"
        newname = f"{args.routine}__{oid}__{label}"
        for ext in (".png", ".pdf"):
            srcf = png[:-4] + ext
            if os.path.exists(srcf):
                shutil.copy2(srcf, os.path.join(out_dir, newname + ext))
        rows.append((newname + ".png", oid, src, meta.get("shows", ""),
                     meta.get("definition", ""), meta.get("source", "")))

    # INDEX.md legend
    idx = os.path.join(out_dir, "INDEX.md")
    with open(idx, "w") as f:
        f.write(f"# Plot index -- {args.routine}\n\n")
        f.write("Naming convention: `<routine>__<origID>__<label>`. The original routine object id "
                "is kept (middle field) so each plot stays traceable to its HEPData table.\n\n")
        f.write("| File | orig id | shows | region / definition | source |\n")
        f.write("|---|---|---|---|---|\n")
        for name, oid, src, shows, defn, source in rows:
            f.write(f"| `{name}` | `{oid}` | {shows or '_(label from '+src+')_'} | {defn} | {source or src} |\n")
    print(f"named {len(rows)} plots -> {out_dir}")
    print(f"legend -> {idx}")
    unl = [r[1] for r in rows if r[2] == "unlabeled"]
    if unl:
        print(f"WARNING: {len(unl)} plots had no physical label (kept origID): {unl}")


if __name__ == "__main__":
    main()
