# Analysis option B (container backend) — SimpleAnalysis routine

> **LEGACY / general fallback.** This is the **container backend** of step-4 Option B. For
> **EwkCompressed2018 / slepton-bino the default is the native, VM-free backend**
> (`../reference/native-pipeline.md`; `../steps/04-analyze.md` Option B) — no podman, no VM, no x86
> emulation, points run in parallel. Use this container path **only when the chosen analysis has no
> native backend yet** (the native SimpleAnalysis is EwkCompressed2018-specific today).

The SimpleAnalysis branch of step 4. SimpleAnalysis is the SR-yield framework that many ATLAS/CMS
SUSY analyses publish a routine for; it produces per-SR yields that map directly onto a published
pyhf likelihood — the route to the strongest limit when one exists. It runs in the ATLAS container
(linux/amd64), orchestrated by `mapyde`:

```
MadGraph → Pythia8 → Delphes → SimpleAnalysis → sa2json → pyhf
```

Use this branch when the target analysis ships a SimpleAnalysis routine and/or a serialized pyhf
likelihood. (When it ships a Rivet routine instead, use Option A in `../steps/04-analyze.md`.) The
two options are co-equal; pick by what the analysis provides (`../checklists/choosing-routine.md`).

| File | What |
|---|---|
| `01-container-runtime.md` | native arm64 podman + machine (the conda podman is x86 and won't boot) |
| `02-install-mapyde.md`    | install mapyde + pull the pipeline images |
| `03-configure.md`         | write the mapyde TOML for the model + target analysis |
| `04-run.md`               | run the six stages |
| `05-read-results.md`      | extract the per-SR yields + signal patch (consumed by steps 6–7) |
| `config-decisions.md`     | TOML field choices |

It needs a container runtime (these images are linux/amd64) and is slow on Apple Silicon (amd64 under
emulation). The yields/patch land in `<rundir>/outputs/`; the limit itself is computed in
`../steps/07-exclude.md` (pyhf). Worked example: `../reference/example-simpleanalysis-path.md`.
