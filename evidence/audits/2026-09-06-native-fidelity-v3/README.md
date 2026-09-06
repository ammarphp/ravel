# Native source diagnostic bridge — 2026-09-06, version 3

A refused LHAPDF preparation now names the offending environment fields in
sorted order. It still refuses every nonempty value in the same fixed set of
19 forbidden fields, before filesystem or linker probes. The message contains
field names only, never their values. Empty fields remain ignored and the
inherited bytecode-suppression check keeps precedence. No successful generation
decision, PDF selection, compiler flag, event selection or inference calculation
changes in this version.

This audit is needed because the production module and its test module have new
bytes. The earlier [v2 audit](../2026-09-06-native-fidelity-v2/README.md) correctly
rejects those changed current-source pins. Its records remain intact: its 316
integrated tests and separate 86 independent source controls still describe
their original source versions, not the new diagnostic. V3 does not make the old
current-source verifier pretend to pass against changed files.

| Evidence | Scope | Result |
|---|---|---:|
| Current LHAPDF and linker unit modules | Current engineering source, inert fixtures | 180 passed, 0 skipped |
| Independent refusal/privacy cases | Early guard code only; no filesystem or linker probes | 295 cases |
| Prior integrated engineering run | Inherited at exact v2 source/test hashes | 316 passed |
| Prior independent original-LHA controls | Separate inherited source review | 86 passed |
| Unchanged default event-IO functions | Rechecked AST identity to the original IO source | 4 equal |
| Retained differential/driver arithmetic | Earlier observations, checked small records | 18 region cells, 12 cutflow cells, 73 changed-event records |

The four test populations are separate and are not summed. The current 180-test
log is included byte-for-byte. Its path-translated command and original log
commitment are in [tests.json](tests.json). The independent 295-case result is
also included byte-for-byte. It covers all 19 fields with absent, empty and
nonempty values, all 171 two-field combinations, bytecode-priority controls,
the complete field set, and unchanged unknown-prefix refusals.

The portable [guard checker](check_override_guards.py) repeats those 295 cases.
It parses the exact old and current source, verifies that only the declared
message block changed, then compiles only the function prefix ending at its
first filesystem operation. That operation is a tripwire. It never imports the
full historical module, runs a linker probe or starts MadGraph. All 15 other
module-level functions remain AST-identical. The old test functions are also
unchanged; two new test functions cover the 19 fields and a multiple-field case.
The byte-exact prior module and prior test are retained as
[prior_native_lhapdf.py](prior_native_lhapdf.py) and
[prior_test_native_lhapdf.py](prior_test_native_lhapdf.py).

## Earlier scientific observations are inherited

The six scientific selection/converter pins and mandatory event-IO, replica
estimator and original-LHA provenance pins remain enforced. All 33 files across
the three predecessor audit directories are preserved with fixed expected
paths and hashes. The predecessor population is not inferred from a potentially
narrowed live directory. Missing, added or rebound historical roles fail.
All prior integrated engineering/test source pins remain checked; only the two
explicitly bridged files use their preserved prior copies plus exact current
source checks. The prior 316-test log remains linked to those prior bytes.

The retained eRJR summary represents 200,000 original events. This verifier
checks its count arithmetic, 73 retained changed-event records and production-
driver summary; it does not reread 200,000 raw events. The earlier raw-input
hash remains an inherited commitment and the payload is not supplied publicly.
The prior compressed 1,000/10,000-event SR comparison is also inherited with
unchanged selection/converter source. No new ROOT branch comparison is claimed.

The original SR-low acceptance is still `95 / 200000 = 0.000475`, versus
`0.00061805`, a **23.1454% deficit**. It still fails the existing 15% tolerance.
No acceptance promotion, detector calibration, statistical coverage or full RRR
closure follows from this diagnostic or its tests. No generation, shower,
detector simulation, fit, fresh scientific replay or figure rendering occurred
for this audit. The separate current RRR evidence bundles retain their own scope.

## Verify

From a source checkout or its public export, with Python 3.10 or later:

```sh
python -B -S evidence/audits/2026-09-06-native-fidelity-v3/verify.py
python -B scripts/check_fidelity_audits.py
python -B -m pytest evidence/audits/2026-09-06-native-fidelity-v3/test_verify.py -q
```

The last command runs constructed admission controls in addition to the
positive verifier. CI invokes it explicitly because these tests live outside
the ordinary `tests/` collection root. The current LHAPDF test recipe is:

```sh
python -B -m pytest tests/unit/test_native_lhapdf.py \
  tests/unit/test_native_lhapdf_linker.py -q
```

The recorded local invocation used the checkout's parent as working directory
and prefixed the test paths, avoiding the historical `py.py` shadow. This is a
source-byte and bounded engineering bridge, not evidence that legacy absolute-
path execution validators remain valid after changing a working checkout.
