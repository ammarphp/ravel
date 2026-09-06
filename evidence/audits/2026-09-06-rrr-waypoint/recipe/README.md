# Reconstruct the completed anchor recipe

This folder contains byte-exact copies of the completed 20k anchor's five physics cards and a configuration template. The template changes **only** `statistics_python` and `likelihood` paths. The original configuration SHA256 and unchanged settings are recorded in [recipe.json](recipe.json). Masses, process composition, beam energy, exposure, seeds, K factor, luminosity, detector response and full signal-MC policy are retained. This is a recipe, not authorization to generate events.

First install Ravel and prepare the native toolchain using [environment setup](../../../../environment/README.md), [native portability](../../../../docs/reference/native-portability.md), and the [native execution reference](../../../../docs/workflow/reference/native-pipeline.md). The recorded host used Apple Silicon, MG5 2.9.27, Pythia 8.312, Delphes 3.5.1, mapyde 0.5.0 and pyhf 0.7.6. Its guarded JAX fit used a separate Python 3.14 environment with iminuit 2.32.0. See the [environment inventory](../../../../docs/reference/environment.md) for that recorded setup and its limitations. These version notes do not lock shared libraries, packages or compiler behavior.

From the repository root, copy into a **new** run directory:

```sh
export RAVEL_EXAMPLE_RUN="/absolute/new-run"
mkdir "$RAVEL_EXAMPLE_RUN"
cp -R evidence/audits/2026-09-06-rrr-waypoint/recipe/inputs "$RAVEL_EXAMPLE_RUN/inputs"
cp evidence/audits/2026-09-06-rrr-waypoint/recipe/config.toml.template "$RAVEL_EXAMPLE_RUN/config.toml"
python -c 'import gzip,pathlib,sys; pathlib.Path(sys.argv[2]).open("xb").write(gzip.decompress(pathlib.Path(sys.argv[1]).read_bytes()))' \
  evidence/audits/2026-09-06-rrr-waypoint/likelihood/background.json.gz \
  "$RAVEL_EXAMPLE_RUN/inputs/background-official.json"
```

Edit `statistics_python` in the copied `config.toml` to the explicit absolute path of your configured guarded JAX interpreter. The likelihood path already points to the decompressed file in this new run. Use the Ravel-installed Python to inspect a plan:

```sh
python -m ravel.physics.native_pipeline plan \
  --rundir "$RAVEL_EXAMPLE_RUN" --config config.toml
```

This validates a proposed recipe. It neither starts generation nor approves compute. A run needs its own bound task contract, check-in, resource estimate, saved plan and actual approval under the native execution workflow. The shipped template uses the historical seeds to describe this recipe; it must not be represented as an independent new replica of the anchor.

The exact frozen production binary is not distributed. The anchor used the original six-decimal RISR CSV serializer; current native source uses the separately tested round-trip serializer. That candidate had no anchor high/low selection migrations, but remains a source/binary difference. Reconstructing the cards and likelihood inputs therefore does not promise bitwise execution or complete public raw-event custody. Approximate b-tag response, unresolved truth acceptance and the precision limitations in the [waypoint report](../README.md) still apply.
