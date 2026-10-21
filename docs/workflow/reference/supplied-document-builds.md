# Supplied classes, requirements and slides

Use the authenticated manuscript authoring route and its existing
`manuscript_production.prepare_build` for a note. Compilation is an ordinary
science stage of the document-build operation with a method-decision record,
admission, CHECK-IN 1 approval, one attempt and delivery-only
`manuscript_pdf_delivery` review scope. A release that withholds that operation
or its toolchain group prepares sources only. A machine approval is not human approval.

## Supplied class custody

Pin the complete user folder before authoring:

```bash
ravel manuscript bundle --folder /supplied/class-folder --out /work/class-bundle.json
```

Put the resulting object in the formatting contract's `template_assets` list:
`{"kind":"user-supplied-class","redistributable":false,"files":[{"path":...,"sha256":...,"size":...}]}`.
Paths are absolute source paths. Every regular file is pinned; aliases and
special files are refused. The common parent of the listed file parents is the
bundle's compilation root. Place the entry class at that root; nested includes
retain their relative directories. No file is obtained from the network.

Select `render.class="source-template"` and supply the full LaTeX entry template
through the existing production request's `template` pin. It must name the
supplied class, include `\usepackage{zref-user,zref-abspage}`, and contain the
`%RAVEL_BODY%` insertion marker. The existing author must classify the complete
template into `template_units`. Template prose remains subject to the complete
authoring and independent integrity requirements.

Authoring, conformance and the built result retain the grouped bundle's kind and
redistribution flag. Private packages retain the files and provenance. Public
submission export refuses any staged bytes matching a non-redistributable
bundle leaf, including renamed copies. Metadata alone can be exported; it does
not grant rights to distribute the files. Preserve the bundle record in the
declared formatting/package/build metadata when exporting products. The guard
follows declared JSON pin references and inspects staged JSON, without searching
unrelated folders.

## Requester requirements

No note rule pack ships with the product. Supply the pack pin to
`manuscript_format.build_note_contract`. Its sections, page ceiling, counting
exclusions and limits remain supplied data. A pack can include
`required_sentences:["exact requester sentence", ...]`. Each sentence becomes a
`required_text` rule with `scope="document"`; absence is a mechanical finding.
Literal text presence does not verify the scientific truth of the sentence.
Do not put a universal pseudo-data sentence or a study-specific section list in
product code. Main pages use physical section boundaries; appendices are
excluded through the existing section-placement/counting contract.

## Slide preparation

Supply an authenticated note-build binding JSON with `rundir`, `receipt` and
`result` pins, and a content JSON carrying the requested presentation layout:

```bash
ravel manuscript slides --from /work/note-build-binding.json \
  --content /supplied/slide-content.json --minutes 5 --out /work/deck-source
```

The content contract has `schema_version:1`, `kind:"supplied-slide-content"`,
`title`, `quantities`, `slides`, `audit` and `theme`. Each quantity has an `id`,
`label`, `artifact` pin and JSON `pointer`. Each slide has a `title` and lists of
`sections` (authored section IDs), `quantities` (declared IDs) and `figures`
(exact authored figure pin paths). The layout and the comparison population
come from this input. For a reference comparison, explicitly supply its result
quantity and include it in the layout; no previous study is assumed.

Quantity artifacts must belong to the reverified note's inputs, and their
selected scalar rendering must occur in its authenticated prose or LaTeX.
Supply source-rendered strings when decimal spelling matters. Figures are the
same authored images, using the note's recorded PDF conversion where needed.
The `audit` pin supplies a JSON record with its full scalar `totals` object.
Every total is displayed verbatim. A priced cost is displayed when the record
supplies one; token counts alone do not establish a currency cost.

Use `theme:null` for standard beamer. A supplied theme is
`{"name":...,"bundle":<supplied class bundle record>}` and must contain the
corresponding `beamertheme<name>.sty`. Its provenance and nested files survive
both preparation and build. All identities, duration, quantities and layout
remain supplied inputs.

This command writes `slides.tex`, figures, `slides.json` and
`slides-build-config.json`. It reports **did not compile**, and also reports
missing `pdflatex` when applicable. Source preparation launches no compiler.

## Supervised slide build and workflow reruns

`manuscript-slides-build` is a registered operation specialization of the
existing document-build mode. Its task is
`{"config":"/work/deck-source/slides-build-config.json"}`; the config kind
selects the slide adapter. Supply the ordinary version-2 science specification,
original goal binding, delivery-only policy and recorded resource bounds.
Use the existing `ravel plan`, method-decision, approval and `ravel wms` route.
There is no compiler subcommand or separate launch path. The authenticated note
runtime must contain beamer and its complete recorder-observed dependencies.
Installation and native qualification remain prerequisites.

The generic workflow-manager task rule already dispatches both note and slide
tasks through guarded `site-workflow run-step`. Changed results require a fresh
authenticated authored note/build and a fresh admitted task/export, which
rebuilds the document. A spent completion marker must not authorize another
compile; unchanged authenticated output is retained rather than relabelled as
a fresh build. Do not bypass admission to force a scheduler rerun.

The registration fragment in `src/ravel/data/manuscript/registration/` hands
the new operation signature to the shared registry owner. It grants neither
launch authority nor native qualification and changes no installation group.
Native qualification jobs belong in the development completion record, with
supplied inputs and resource/platform bounds. Fake compiler tests establish
custody and guard behavior; they establish no actual TeX or visual fidelity.
