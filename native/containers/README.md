# Container recipes

RAVEL runs Linux-only engines in containers through its execution backends
(see [execution backends](../../docs/reference/execution-backends.md)). Images are
always referenced by digest, run without network, and get CPU, memory and PID
limits. Podman keeps its machine and image state inside the RAVEL container home
(`RAVEL_CONTAINER_HOME`, default `<native build>/containers`), never in your
global configuration.

| Recipe or image | Use | How RAVEL runs it |
|---|---|---|
| [`mcfm/`](mcfm/README.md) | MCFM 10.2.1 with the RAVEL four-lepton overlay, arm64 Linux | Toolchain image built here; MCFM built and run through the container launcher |
| [`jhugen-mela/`](jhugen-mela/README.md) | JHUGen and MELA matrix elements for the independent amplitude cross-check, arm64 Linux | Toolchain image built here; sources fetched at recorded commits and built through the container launcher. Not built until the owner approves the pull |
| AnalysisBase (SimpleAnalysis) | ATLAS SimpleAnalysis routines, `linux/amd64` | The qualified SimpleAnalysis transport in `physics/simpleanalysis_container.py` (image pinned by manifest and config digest, emulated on Apple silicon) |
| `gitlab-registry.cern.ch/cms-cloud/combine-standalone:v9.2.1` | CMS Combine with ROOT 6.22 | Pull once, record `podman image inspect --format '{{.Digest}}'`, then reference `name@sha256:<digest>` in an `oci-local` plan or launcher |

## Typical sequence

```sh
ravel backend doctor --backend oci-local
ravel backend machine init --cpus 4 --memory-mib 8192 --disk-gib 40            # prints the command
ravel backend machine init --cpus 4 --memory-mib 8192 --disk-gib 40 --execute  # after approval
ravel backend machine start --execute
ravel backend image-build --containerfile native/containers/mcfm/Containerfile \
  --context native/containers/mcfm --tag localhost/ravel-mcfm-toolchain \
  --receipt native/build/containers/mcfm-toolchain.build.json --execute
```

Building or pulling an image, creating a machine and the first run of a new
image need the owner's approval: they download data and use disk. Each step is
a dry run until `--execute` is given.
