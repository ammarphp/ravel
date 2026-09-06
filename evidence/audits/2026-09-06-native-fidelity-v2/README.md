# Native source and IO revalidation — 2026-09-06, version 2

Four default event-IO functions remain exactly equal as Python ASTs to the source pinned in the earlier native audit. The new optional original-LHA sidecar path and its verifier have separate current source pins and targeted engineering tests. The six selection/converter engines and replica estimator retain their earlier hashes. This version does not rerun the 200,000-event eRJR loop, compressed selection, ROOT comparisons or a physics fit.

The preserved differential summary represents 200,000 original detector events. Fresh arithmetic and provenance checks reconcile its 18 region counts, 12 cutflow counts and 73 retained changed-event records, as well as the saved production-driver counts. These are checks of retained records, not a traversal of 200,000 raw event records. The original raw-input SHA-256 remains an inherited commitment; the raw file is not public and was not rehashed here. The complete earlier replay commands, runtime and scientific observations remain in the unchanged [prior audit](../2026-09-06-native-fidelity/README.md).

The original SR-low acceptance remains `95 / 200000 = 0.000475`, versus reference `0.00061805`, a relative deficit of `23.1454%`. It still fails the existing 15% tolerance. No certificate, acceptance upgrade or full physics closure was produced. The prior compressed comparison covers 141 SR branches on the retained 1,000/10,000-event inputs, with event alignment and zero-only omitted rows. That evidence is inherited with unchanged selection/converter source pins; neither the selection nor the ROOT branch comparison was repeated here. CR calibration and sparse-bin precision remain unresolved.

| Verification | Scope | Result |
|---|---|---:|
| Four default event-IO functions | Fresh exact AST comparison with byte-exact prior source | 4 equal |
| Integrated IO, original-LHA, LHAPDF and native dispatch tests | Current publication-stage code; inert/fixture tests | 316 passed, 0 skipped |
| Independent original-LHA source controls | Separate candidate and baseline review, including repaired file-descriptor binding | 86 passed |
| Retained differential/driver record checks | Inherited observations, newly checked arithmetic and hashes | 18 region cells, 12 cutflow cells, 73 changed-event records |

The independent 86 controls are a separate test run and are not added to 316 to claim a larger fresh population. They did not compile a native binary or execute a scientific sample. The ordinary source-custody defect and its repaired plain/gzip controls remain documented by their source hashes in [tests.json](tests.json). The integrated log is included with only machine prefixes translated; its original private log hash and exact path-translated argv are recorded. These are engineering checks, not coverage, detector, normalization or build/binary equivalence certificates.

[verification.json](verification.json) binds the inherited observations, all unchanged scientific engine sources and the current IO/provenance modules. [default-event-io-parity.json](default-event-io-parity.json) records the four AST identities. The byte-exact earlier IO source is retained as [prior_native_event_io.py](prior_native_event_io.py) so this comparison can be reproduced without a historical checkout. Every predecessor native-audit file is pinned and preserved. The unchanged default functions do not claim whole-module identity; the opt-in path is new behavior with its own stated scope.

Run the source and retained-record verifier from a checkout or public bundle:

```sh
python -B evidence/audits/2026-09-06-native-fidelity-v2/verify.py
python -B scripts/check_fidelity_audits.py
```

The targeted integrated recipe, with an existing Python environment containing the documented dependencies, is:

```sh
python -B -m pytest tests/unit/test_lhe_provenance.py \
  tests/unit/test_native_event_io.py tests/unit/test_native_lhapdf.py \
  tests/unit/test_native_lhapdf_linker.py tests/unit/test_native_dispatch.py -q
```

In the private source workspace, invoke pytest from the checkout's parent and prefix the test paths with the checkout directory to avoid the historical `py.py` shadow. The original executed command and environment handling are in the test record. This report makes no full-suite or remote-CI claim. It does not replace the separate current RRR evidence bundles or promote their scientific scope.
