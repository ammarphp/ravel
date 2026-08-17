# Step 3 — Configure the run (TOML) · CHECK-IN

mapyde is driven by one TOML file. Start from a bundled template and override the few fields the
request needs. See `workflow/analysis-simpleanalysis/config-decisions.md` for what each field means.

**Do:**
1. Create a run folder under `trial-runs/` (naming per `trial-runs/README.md`):
   ```bash
   RUN="trial-runs/$(date +%F)_<model>_<point>_<Nevents>"
   mkdir -p "$RUN/config" "$RUN/logs" "$RUN/inputs"
   ```
2. Copy a template and edit it (the slepton example template is the bundled `sleptons.toml`):
   ```bash
   CARDS=$(stages/01-event-generation/build/tools/miniforge3/bin/conda run -n pipeline mapyde --prefix templates)
   cp "$CARDS/sleptons.toml" "$RUN/config/run.toml"
   ```
   Then edit `$RUN/config/run.toml`:
   - `[base] engine = "podman"`  (the **container backend** only — the native default does not use mapyde/podman)
   - `[madgraph.masses]` — the parameter point (e.g. `MSLEP = 200`, `MN1 = 150`)
   - `[madgraph.run] nevents = <N>`
   - `[simpleanalysis] name = "<selection>"` and `[pyhf] likelihood = "<file>.json"` for the target analysis
   - leave the rest as the template (faithful to the paper)
3. Validate it resolves:
   ```bash
   source trial-runs/_infrastructure/pipeline-env.sh
   CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda
   ( cd "$RUN" && PWD="$PWD" "$CONDA" run -n pipeline mapyde config parse config/run.toml >/dev/null && echo "config OK" )
   ```

**CHECK-IN (required):** show the scientist the resolved model, point, analysis, and nevents.

**Next:** `workflow/analysis-simpleanalysis/04-run.md`
