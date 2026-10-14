# Explicit SVJ hard-to-shower representation

The ordinary `model-events` configuration admits an optional `pre_shower_lhe_transform` field. The same `model-events prepare` CLI and `model-event-plan` Graph/Host action bind its complete inputs, and the existing reviewed native event runner executes the phases under its original supervisor. Without the field the original pipeline, selected shower map, and default seed checks retain their behavior.

This source-defined operation retains the genuine 2019 Athena SVJ fragment with SHA256 `4bb332d003d2f5265a5cd91b6524ec3f93e6342f827be2b30076cd11f30c0ca2`. It lowers the four actual dark-flavour UFO particles (49001011, 49001012, 49001013, 49001014) to target Pythia 4900101 between hard generation and showering. The fragment's fifth literal source ID 49001010 is absent from the authenticated model and must also be absent from events. Every changed particle token is the IDUP field of a complete NUP particle record; its sign is preserved. All mothers, colors, momentum, status, process IDs, comments, beam/PDF/cross-section metadata, source header and other event bytes remain exact. The original model/parameter/card and particle program remain scientific inputs, with all actual masses and target settings checked. The original UFO ZERO width and target Pythia width .2 are separate source settings.

The original prescription uses `event_norm=sum`; the released MG shower entry refuses this normalization. An explicit source-reviewed representation retains the raw sum cards/LHE/header and uses the complete original hard count N to multiply every nominal and detailed/compact weight by N, preserving signs and literal zeros. Only the operative derived LHE IDWTUP changes from -3 to -4. A separately retained derived Cards/run_card.dat changes the one event_norm token from sum to average. The original header/banner stays unchanged by the transformer. This implements the conditional all-weight law in the authenticated `proposed_svj_absolute_weight_representation_contract` with SHA256 `83a0490a8ec1c156def23afd92fc58c2a083f5f8853433be9692b21de31f5010`. It is not equivalence to the stock -3 named-weight bug or to Athena.

Source scalars are bounded literal decimal/D-exponent tokens (512 bytes, 256 coefficient digits, exponent magnitude ≤400), multiplied exactly as integer coefficients independently of the active Decimal precision. Nonzero scaled values must be finite and nonzero in the native binary64 range. These representation checks are not relative-error bounds or native normalization certificates. Complete decoded bytes retain the existing caller ceiling; an individual event has a separately declared ceiling ≤8 MiB and init structure ≤32 MiB. No clipping, rescaling of a subset, or accepted-event denominator is used. Standalone source transport supports compact, detailed, and exactly equal simultaneous encodings. The selected detailed-loop interface requires detailed weights in every event with nonempty declared IDs; compact-only input refuses before that native consumer.

## Configuration extension

All file pins use exact `{"path":"...","sha256":"64 lowercase hex"}` with optional literal `size`. The extension has the following exact fields:

```json
{
  "schema_version": 1,
  "mode": "svj_dark_flavour_absolute_v1",
  "source_fragment": "file pin to the exact original fragment",
  "source_particle_bindings": [
    {"pdg":49001011,"ufo_name":"gv11","mass_parameter":"Mgv11","width_parameter":"ZERO","spin":2,"color":1,"charge":"0"},
    {"pdg":49001012,"ufo_name":"gv12","mass_parameter":"Mgv12","width_parameter":"ZERO","spin":2,"color":1,"charge":"0"},
    {"pdg":49001013,"ufo_name":"gv21","mass_parameter":"Mgv21","width_parameter":"ZERO","spin":2,"color":1,"charge":"0"},
    {"pdg":49001014,"ufo_name":"gv22","mass_parameter":"Mgv22","width_parameter":"ZERO","spin":2,"color":1,"charge":"0"}
  ],
  "mapped_pdgs_absent_from_model": [49001010],
  "target_pythia_pdg": 4900101,
  "mass_gev": "10",
  "normalization": {
    "mode":"mg_sum_to_absolute_average_v1",
    "input_strategy":-3,
    "output_strategy":-4,
    "source_contract":"file pin to the exact all-weight representation contract"
  },
  "interface": {
    "source_sha256":"590c8ea4cc7643358a64e2d7e0113f17403cb72a274748dda44950fdc3e3c414",
    "archive_sha256":"1a7a62e96207701f9a8a44fec01426b7f474b580ba2c4fbb82ecd0d83fcea332",
    "build_evidence":"file pin to the full source-declared named-output build"
  },
  "shower_stream_census":"file pin to the complete native/converter stream declaration",
  "maximum_event_bytes":8388608,
  "scientific_equivalence_claim":false
}
```

This extension requires original LO MLM/PYTHIA8, native decay and ME reweight OFF, the explicit existing operative seed observation, and `Events/ravel/unweighted_events.lhe.gz`. The original full model tree, runtime/support manifests, source cards, parameter settings, scale/PDF variation definitions, original question/review policy and complete process population remain mandatory through the existing route.

The build declaration has exact keys schema_version=1, kind=`source_declared_mg_py8_named_output_build`, source/binary/build_record file pins, compile_definitions=[`HEPMC2HACK`], and a nonempty full dependency pin list. Source and binary are the actual fixed endpoints under the existing admitted MG/PY8 interface prefix; every source/binary/dependency belongs to existing complete runtime dependency manifests. Authenticated declarations do not prove actual compilation, loaded ABI, or native output behavior.

The census has exact keys schema_version=1, mode=`mg_py8_v1_3_hepmc2hack_full_streams`, `cut_values_gev` (ordered positive decimal strings), literal boolean `full_cut_variation`, and `streams`. Each stream has exact `hepmc_name`, kind (`interface_nominal`, `interface_lhe`, or `converter`), `lhe_id`, `cut_gev`, `units`, and source file pin. Every nominal cut appears; each LHE ID appears at every cut when full_cut_variation is true, or only the original central cut when false. Converter rows use null LHE ID/cut and source-declared units or explicit `unknown`. Actual returned names/vectors must equal this full ordered population. Unique names and three-decimal native cut tags prevent declared collisions; actual name transport does not prove normalization meaning or absence of converter overwrites. The existing selected nominal+LHE map remains an explicit one-cut projection into the full census.

The source Pythia card's `SysCalc:qCutList` uses the released comma-vector syntax, not Python list syntax. The original `SysCalc:fullCutVariation` and explicit cut population are preserved. The operation does not silently set true, expand a reduced cross, or guess `auto` cuts.

## Original runner phase re-entry and custody

The first existing MG launch has shower=OFF. Before any authorized replacement, the original seed observer consumes the actual hard banner, embedded LHE header, logged hard seed offset, ending mutable card, both native process cards, process-definition journal, complete parameter card and source. Full hard Events membership is committed. Raw LHE and the consumed subjects are retained separately.

Re-entry uses the original MG bin/runpy dispatch, original admitted runtime options with `--no_save`, original interactive `launch <private-process> -i`, disabled Delphes, and one `pythia8 ravel --no_default --laststep=pythia8` command. The authenticated adapter imports the original `MadEventCmd` only in that future native child. The released check first selects ravel and loads the original sum banner; its same-name `set_run_name(..., level='pythia8', reload_card=True)` then reads the derived operative Cards file before configuration and the unit/average guard. All loaded fields and original argument mutations/return are observed. Only event_norm and the source-supported hard ending iseed reset (19→0 for a seed-19 example) differ. The run tag, full N and every other field remain equal. A fresh unselected session and one intended check are required; the wrapper is restored afterward. No new generator/shower engine, optimizer or supervisor is added.

The native shower may add its actual MGPythiaCard and the source-supported matched integrated-weight line to the final banner. Every original banner component remains exact. Raw hard, derived LHE, card token change, every changed lexical span, both populations, actual reload journal and complete final C31 Events commitment stay separate and are checked around delivery. Historical hard seed evidence is explicitly labeled consumed before operative replacement; it is not presented as custody of the now-derived native endpoint.

The result retains `original_hard_population` and `pre_shower_transport` separately from the derived operative `population` and full `shower_population`. It explicitly reports unknown physical hard-to-shower association and false scientific/build/ABI/numerical/matching/Athena acceptance. The released accepted-only HepMC event stream does not supply a complete per-hard-event cut/disposition join. No caller assertion manufactures one.

## Later qualification obligations

After full buildout/integration and independent source clearance, native qualification must establish the actual named-output build/HEPMC2HACK mode, Pythia8.312 versus reviewed 8.317 source/ABI compatibility, all nominal/named/compact normalization and converter stream semantics, full-cut output/collision/convergence behavior, and real cost. Final paper card/mass/width/tune/BR/MLM compatibility, matching/acceptance and any scientific use requiring hard-event/cut association remain separate questions. The cached 2019 fragment is not established equivalence to the final ATLAS2305.18037 study. All previous failures, 130 strands,16 families,18 comparators,full52 RS1 points and standing scientific questions remain in scope.

Pure software controls check exact byte replay, signed/zero/all-weight arithmetic, late failures without accepted transform publication, complete source API/ordinary staging, and released method ordering under inert boundaries. They execute no MG/UFO/native/shower/provider/model/fit operation and confer no physics acceptance.
