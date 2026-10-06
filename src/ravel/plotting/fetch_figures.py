#!/usr/bin/env python
r"""Acquire an analysis's PUBLISHED figures so the model overlay can be checked against them.

The visual-fidelity test (workflow step 5) needs the experiment's own figure (e.g. the m_eff
distribution per signal region) to judge whether our overlay reproduces it. Routes, in order:
  1. arXiv source tarball (`/e-print/<id>`) -> the figure files exactly as published (PDF/EPS/PNG);
  2. arXiv PDF (`/pdf/<id>`) -> the whole paper, readable page-by-page (the Read tool renders PDF pages);
  3. HEPData per-table thumbnail images, when present.
The arXiv id is taken from the HEPData record JSON (its bibtex `eprint`) or given with --arxiv.

FIGURE-DIRECTED mode (--figure, repeatable; the figure-contract extraction ladder): given a figure id
("16a", "3"), resolve the specific published image through three routes, degrading gracefully:
  i.  arxiv-tex-map -- parse the saved source tarball's .tex (resolve \input order from the main
      file, walk figure envs in document order, collect \includegraphics + the caption, honor
      \graphicspath), match the figure to its extracted file; the map is written to
      <out>/figure_map.json (also produced standalone by --map-captions);
  ii. pdf-page -- pypdf text-scan the paper PDF for the "Figure N:" caption, rasterize that whole
      page via gs (-r200) to <out>/figures/figN_pageP.png (if gs fails, record the page only);
  iii. textual reference -- no pixels, print {extracted:false, figure_id, caption, arxiv} and exit 0
      (a VALID terminal state: the figure-contract check-in then verifies via figure id + caption).
Tex-map figure numbering follows document order of the figure envs -- a WARNING is printed and the
route falls through to ii on any inconsistency (missing member, unmatched graphic, no main file).

Usage:
  fetch_figures.py (--routine NAME | --inspire insNNNN | --arxiv 1605.03814) --out DIR
                   [--figure 16a ...] [--map-captions]
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.plotting"

import argparse, json, os, re, ssl, subprocess, sys, tarfile, urllib.request, urllib.error

GS = "/usr/local/bin/gs"

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def _open(url, timeout=60):
    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    req = urllib.request.Request(url, headers=UA)
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except urllib.error.URLError as e:
        # CR-021 SSL policy (mining #8): NEVER an unverified fallback. Retry with the
        # certifi bundle (conda envs ship it); if that is unavailable, fail with instructions.
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            if _VERIFIED_CTX is not None:
                return urllib.request.urlopen(req, timeout=timeout, context=_VERIFIED_CTX)
            raise RuntimeError(
                "TLS verification failed and certifi is unavailable under this python. "
                "Re-run inside a conda env (e.g. `<conda> run -n rivet ...`). "
                "Verification is never bypassed (CR-021).") from e
        raise


def arxiv_from_inspire(inspire):
    """Pull the arXiv id from the HEPData record's bibtex eprint."""
    import json
    url = f"https://www.hepdata.net/record/{inspire}?format=json"
    try:
        rec = json.load(_open(url, 30))
    except Exception:
        return None
    blob = json.dumps(rec)
    m = re.search(r'(?:eprint["\s:=]+|arxiv[:/])\s*"?(\d{4}\.\d{4,5})', blob, re.I)
    return m.group(1) if m else None


# --------------------------------------------------------------------- route i: arXiv tex map
def _strip_tex_comments(tex):
    """Drop % to end-of-line (not \\%) so commented-out figures don't get numbered."""
    return re.sub(r"(?<!\\)%.*", "", tex)


def _read_tex_members(tarpath):
    texs = {}
    with tarfile.open(tarpath) as tf:
        for m in tf.getmembers():
            if m.isfile() and m.name.lower().endswith(".tex"):
                texs[m.name] = tf.extractfile(m).read().decode("utf-8", errors="replace")
    return texs


def _resolve_tex_name(name, texs):
    name = name.strip().lstrip("./")
    for cand in (name, name + ".tex"):
        if cand in texs:
            return cand
        for k in texs:                       # tolerate a leading source-dir prefix
            if k.endswith("/" + cand):
                return k
    return None


def _inline_inputs(member, texs, seen):
    """Recursively inline \\input/\\include so figure envs appear in true document order."""
    if member in seen:
        return ""
    seen.add(member)
    txt = _strip_tex_comments(texs[member])

    def repl(m):
        child = _resolve_tex_name(m.group(1), texs)
        return _inline_inputs(child, texs, seen) if child else m.group(0)

    return re.sub(r"\\(?:input|include)\s*\{([^}]+)\}", repl, txt)


def _balanced_braces(s, i):
    """s[i] == '{'; return (content, index just past the matching '}') or (None, i)."""
    if i >= len(s) or s[i] != "{":
        return None, i
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return None, i


def _first_caption(body):
    """First brace-balanced \\caption content, reduced to its first sentence."""
    m = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", body)
    if not m:
        return None
    cap, _ = _balanced_braces(body, m.end() - 1)
    if cap is None:
        return None
    cap = re.sub(r"\\label\s*\{[^}]*\}", "", cap)
    cap = re.sub(r"\s+", " ", cap).strip()
    m = re.search(r"\.(\s|$)", cap)          # first sentence
    return cap[: m.start() + 1] if m else cap


def _match_graphic(arg, gpaths, extracted):
    """Match an \\includegraphics arg (possibly extensionless, possibly in a subdir) to an
    extracted file. `extracted` maps extracted-basename -> original member path. Returns
    (extracted_basename, member_path) or (None, None)."""
    arg = arg.strip().lstrip("./")
    exts = ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps")
    for gp in gpaths:
        for ext in exts:
            cand = (gp.rstrip("/") + "/" + arg + ext).lstrip("/") if gp else arg + ext
            for base, member in extracted.items():
                if member == cand or member.endswith("/" + cand):
                    return base, member
    return None, None


def build_figure_map(tarpath, extracted, arxiv):
    """Walk the paper's figure environments in document order -> {fig_no: {caption, graphics}}.
    Returns the map dict, or None (with a WARN) on any structural inconsistency -- the caller
    falls through to the pdf-page route."""
    try:
        texs = _read_tex_members(tarpath)
    except (tarfile.ReadError, OSError) as e:
        print(f"WARN: tex map unavailable ({e!r}); falling through", file=sys.stderr)
        return None
    mains = [n for n, t in texs.items() if r"\begin{document}" in t]
    if not mains:
        print("WARN: no .tex member holds \\begin{document}; tex map unavailable", file=sys.stderr)
        return None
    if len(mains) > 1:
        print(f"WARN: multiple main-file candidates {mains}; using {mains[0]}", file=sys.stderr)
    doc = _inline_inputs(mains[0], texs, set())

    gpaths = [""]
    m = re.search(r"\\graphicspath\s*\{((?:\s*\{[^}]*\}\s*)+)\}", doc)
    if m:
        gpaths += re.findall(r"\{([^}]*)\}", m.group(1))

    figures = {}
    for num, env in enumerate(
            re.finditer(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", doc, re.S), 1):
        body = env.group(1)
        graphics = [g.strip() for g in
                    re.findall(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", body)]
        entry = {"caption": _first_caption(body), "graphics": {}}
        for i, g in enumerate(graphics):
            letter = chr(ord("a") + i) if len(graphics) > 1 else ""
            base, member = _match_graphic(g, gpaths, extracted)
            entry["graphics"][letter or "_"] = {"arg": g, "member": member, "file": base}
        figures[str(num)] = entry
    if not figures:
        print("WARN: no figure environments found in the tex source", file=sys.stderr)
        return None
    return {"arxiv": arxiv, "main_tex": mains[0], "figures": figures,
            "extracted_files": extracted,
            "note": "figure numbers follow document order of the figure envs; subfigure letters "
                    "are the \\includegraphics ordinal -- verify against the paper if in doubt"}


# --------------------------------------------------------------- routes ii/iii + the ladder
def _parse_figure_id(fid):
    m = re.match(r"(?i)^\s*(?:fig(?:ure)?\.?\s*)?(\d+)\s*\(?([a-z]?)\)?\s*$", fid.strip())
    if not m:
        sys.exit(f"unparseable --figure id {fid!r} (expected e.g. '16a' or '3')")
    return m.group(1), m.group(2).lower()


def pdf_page_route(pdfpath, num, out):
    """pypdf text scan for the 'Figure N:'/'Figure N.' caption -> rasterize that page via gs.
    Returns a result dict, or None when the caption is not found in the PDF text."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdfpath)
    except Exception as e:
        print(f"WARN: pypdf unavailable/unreadable ({e!r})", file=sys.stderr)
        return None
    pat = re.compile(rf"Figure\s+{num}\s*[:.]")
    for pno, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        if not pat.search(text):
            continue
        png = os.path.join(out, "figures", f"fig{num}_page{pno}.png")
        os.makedirs(os.path.dirname(png), exist_ok=True)
        r = subprocess.run([GS, "-dSAFER", "-dBATCH", "-dNOPAUSE", f"-dFirstPage={pno}",
                            f"-dLastPage={pno}", "-sDEVICE=png16m", "-r200",
                            f"-sOutputFile={png}", pdfpath], capture_output=True, text=True)
        if r.returncode == 0 and os.path.isfile(png):
            return {"extracted": True, "route": "pdf-page", "path": png, "pdf_page": pno}
        print(f"WARN: gs failed on page {pno} ({r.stderr.strip()[:120]}); "
              f"recording the page number only", file=sys.stderr)
        return {"extracted": False, "route": "pdf-page", "path": None, "pdf_page": pno}
    return None


def resolve_figure(fid, figure_map, figdir, pdfpath, out, arxiv):
    """The extraction ladder for one requested figure id: tex map -> pdf page -> textual ref."""
    num, letter = _parse_figure_id(fid)
    caption = None
    # route i: the tex map
    if figure_map:
        entry = figure_map["figures"].get(num)
        if entry:
            caption = entry.get("caption")
            g = entry["graphics"].get(letter or "_") or (
                entry["graphics"].get("a") if not letter else None)
            if g and g.get("file") and os.path.isfile(os.path.join(figdir, g["file"])):
                return {"extracted": True, "route": "arxiv-tex-map", "figure_id": f"Figure {num}{letter}",
                        "path": os.path.join(figdir, g["file"]), "caption": caption, "arxiv": arxiv}
            print(f"WARN: tex map has Figure {num} but no matched file for subfigure "
                  f"{letter or '(none)'}; falling through to the pdf-page route", file=sys.stderr)
        else:
            print(f"WARN: Figure {num} not in the tex map (numbering drift?); falling through",
                  file=sys.stderr)
    # route ii: the PDF page
    if pdfpath and os.path.isfile(pdfpath):
        r = pdf_page_route(pdfpath, num, out)
        if r:
            r.update({"figure_id": f"Figure {num}{letter}", "caption": caption, "arxiv": arxiv})
            return r
    # route iii: textual reference (valid terminal state -- exit 0 at the caller)
    return {"extracted": False, "route": "none", "figure_id": f"Figure {num}{letter}",
            "path": None, "caption": caption, "arxiv": arxiv}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--routine"); g.add_argument("--inspire"); g.add_argument("--arxiv")
    ap.add_argument("--out", required=True)
    ap.add_argument("--figure", action="append",
                    help="figure id to resolve through the extraction ladder (repeatable), e.g. 16a")
    ap.add_argument("--map-captions", action="store_true",
                    help="write <out>/figure_map.json (figure -> files + captions) from the tex source")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    arxiv = args.arxiv
    if not arxiv:
        inspire = args.inspire
        if not inspire and args.routine:
            m = re.search(r"_I(\d+)$", args.routine)
            inspire = f"ins{m.group(1)}" if m else None
        if inspire:
            arxiv = arxiv_from_inspire(inspire)
    if not arxiv:
        sys.exit("could not resolve an arXiv id; pass --arxiv explicitly")
    print(f"arXiv: {arxiv}")

    # route 1: source tarball -> figure files. Basenames are FLATTENED into figures/; a name
    # collision is suffixed __2, __3, ... (never silently overwritten) and the original member
    # paths are recorded in figure_map.json. A failed download falls back to a previously saved
    # tarball, which the figure-map route also reads.
    figdir = os.path.join(args.out, "figures")
    os.makedirs(figdir, exist_ok=True)
    extracted = {}                        # extracted basename -> original member path
    tarpath = os.path.join(args.out, f"{arxiv}.tar.gz")
    try:
        with _open(f"https://arxiv.org/e-print/{arxiv}") as r, open(tarpath + ".part", "wb") as f:
            f.write(r.read())
        os.replace(tarpath + ".part", tarpath)
    except Exception as e:
        if os.path.isfile(tarpath) and os.path.getsize(tarpath) > 0:
            print(f"arXiv source fetch failed ({e!r}); reusing the saved tarball {tarpath}")
        else:
            print(f"arXiv source fetch failed: {e!r}")
    if os.path.isfile(tarpath) and os.path.getsize(tarpath) > 0:
        try:
            with tarfile.open(tarpath) as tf:
                for m in tf.getmembers():
                    if m.isfile() and m.name.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".eps")):
                        orig, base = m.name, os.path.basename(m.name)
                        stem, ext = os.path.splitext(base)
                        k = 2
                        while base in extracted:     # collision: suffix, never overwrite
                            base = f"{stem}__{k}{ext}"
                            k += 1
                        m.name = base
                        tf.extract(m, figdir)
                        extracted[base] = orig
            print(f"extracted {len(extracted)} figure files -> {figdir}")
        except tarfile.ReadError:
            print("source is not a tarball (single-file submission); keeping the raw download")
    got = sorted(extracted)

    # route 2: the PDF (readable page-by-page with the Read tool)
    pdfpath = os.path.join(args.out, f"{arxiv}.pdf")
    try:
        with _open(f"https://arxiv.org/pdf/{arxiv}") as r, open(pdfpath + ".part", "wb") as f:
            f.write(r.read())
        os.replace(pdfpath + ".part", pdfpath)
        print(f"paper PDF -> {pdfpath}  (Read it page-by-page to view a specific figure)")
    except Exception as e:
        if os.path.isfile(pdfpath) and os.path.getsize(pdfpath) > 0:
            print(f"arXiv PDF fetch failed ({e!r}); reusing the saved PDF {pdfpath}")
        else:
            print(f"arXiv PDF fetch failed: {e!r}")

    print(f"\nfigure files: {len(got)} in {figdir}")
    if got:
        print("  e.g. " + ", ".join(sorted(got)[:8]))

    # ------------------- figure-directed mode: the tex map + the extraction ladder -------------------
    figure_map = None
    if args.figure or args.map_captions:
        if os.path.isfile(tarpath) and os.path.getsize(tarpath) > 0:
            figure_map = build_figure_map(tarpath, extracted, arxiv)
        else:
            print("WARN: no source tarball on disk -- tex map unavailable", file=sys.stderr)
        if figure_map:
            mpath = os.path.join(args.out, "figure_map.json")
            with open(mpath, "w") as f:
                json.dump(figure_map, f, indent=2)
                f.write("\n")
            print(f"figure map ({len(figure_map['figures'])} figure env(s)) -> {mpath}")

    if args.figure:
        print("\n=== figure-directed extraction (ladder: tex map -> pdf page -> textual ref) ===")
        for fid in args.figure:
            res = resolve_figure(fid, figure_map, figdir, pdfpath, args.out, arxiv)
            print(json.dumps(res))
            if res.get("extracted"):
                print(f"  -> {res['figure_id']}: {res['path']}  [route: {res['route']}]")
            elif res.get("pdf_page"):
                print(f"  -> {res['figure_id']}: caption found on PDF page {res['pdf_page']} but "
                      f"not rasterized; Read the PDF page, or verify via the textual reference")
            else:
                print(f"  -> {res['figure_id']}: NOT extracted; a textual reference "
                      f"(figure id + caption) is the valid degraded state -- declare it and "
                      f"verify at the check-in")


if __name__ == "__main__":
    main()
