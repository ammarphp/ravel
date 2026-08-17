# Step 2 — Install mapyde + pull pipeline images (one-time)

`mapyde` is installed into the `pipeline` conda env in **step 1 (§5)** — this step confirms it and
pre-pulls the amd64 images, which are needed ONLY for the **container backend** (`--backend container`;
the default native backend needs no images — see `reference/native-pipeline.md`). It ships the cards,
templates, and the slepton likelihood. Confirm + pre-pull the amd64 images.

**Do:**
```bash
source trial-runs/_infrastructure/pipeline-env.sh   # PATH (incl. amd64 podman wrapper), helpers
CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda

# confirm mapyde + see where its bundled assets live
"$CONDA" run -n pipeline mapyde --prefix cards
"$CONDA" run -n pipeline mapyde --prefix likelihoods
"$CONDA" run -n pipeline mapyde --prefix templates   # defaults.toml, sleptons.toml, ewkinos.toml

# pre-pull the four images (amd64), so runs don't stall on first use
for img in \
  ghcr.io/scipp-atlas/mapyde/madgraph:2.9.3 \
  ghcr.io/scipp-atlas/mapyde/delphes:latest \
  ghcr.io/scipp-atlas/mapyde/pyplotting:latest \
  gitlab-registry.cern.ch/atlas-sa/simple-analysis:master ; do
  "$PIPE_PODMAN_REAL" pull --arch amd64 "$img"
done
```

**Verify:**
```bash
"$PIPE_PODMAN_REAL" images | grep -E "mapyde|simple-analysis"   # 4 images present
```
All four registries are public (no CERN/GitHub auth required).

**Next:** `workflow/analysis-simpleanalysis/03-configure.md`
