# Native cumulant source bundle

Released primary source and format evidence for the CMS two-particle cumulant/flow routine,
with the `native-cumulant/v1` mapping that binds it (`mapping.json`). These are source bytes,
not native output and not a qualified runtime.

`ravel.physics.shipped_assets.cumulant_mapping()` returns the complete mapping with pins to
these files; `native_cumulant.requests_for(mapping)` builds the ten output requests. The mapping
holds 10 finalized Scatter2D outputs and 117 RAW Profile1D operands (13 correlators x 9 cyclic
subsamples), every pin a sha256. See [the contract reference](../../../../docs/reference/native-cumulants.md).

Provenance (`source-map.json`): the routine source and its reference YODA are the released
Rivet 4.1.4 bytes; the correlator header and projection are the Rivet 4.1.3 release-tag files;
the YODA headers are the 2.1.3 release; `WriterYODA.cc` is the public `yoda-2.1.3` tag file.
`LICENSE.Rivet.txt` and `LICENSE.YODA.txt` preserve the upstream GPL-3 licences; these
third-party files keep their upstream copyrights, and RAVEL's transport code is licensed by
its repository. The reference values bind source geometry and output counts only; they are
never substituted for event-derived native values.

The source routine's labels and comments do not override its finalize calls: it calls
`cnTwoInt` for the first and third tables, and `vnTwoDiff` discards computed bootstrap errors.
These behaviours are preserved and are listed in the mapping's `semantic_notes`.
