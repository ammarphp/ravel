# JHUGen/MELA container recipe

Builds the independent matrix-element program behind the `amplitude-crosscheck` operation, as the MCFM
recipe does for `amplitude-integration`. The image holds the toolchain only. JHUGen and MELA are fetched
from upstream at recorded commits and built on your machine; RAVEL does not redistribute them (GPL-3.0-or-later).

| File | Purpose |
|---|---|
| `Containerfile` | Fedora 41 arm64 with GNU compilers, ROOT and Python; refuses to build until the base digest is recorded |
| `base-image.json` | The base digest and the JHUGen and MELA commits, all unrecorded until the first approved fetch |
| `build-jhugen-mela.sh` | Fetches both sources at the recorded commits, builds, writes the launcher and a build receipt |
| `check-jhugen-mela.sh` | Launcher, receipt and `import Mela` check behind `ravel doctor` |

## State

Not built. Nothing here has been run: the base digest and both commits are `null`, and the build script
and image builder both refuse until they are recorded. Pulling the base image and fetching the sources need the
owner's approval (the same approval as the MCFM pull). The upstream build commands follow the JHUGen and
MELA READMEs and are confirmed by that first build. The doctor reports the `jhugen-mela` group as missing
and its qualification as not built until the launcher exists and the point oracle has passed.

## Sequence after approval

```sh
podman pull --platform linux/arm64 registry.fedoraproject.org/fedora:41
podman image inspect --format '{{.Digest}}' registry.fedoraproject.org/fedora:41   # record in base-image.json and the FROM line
ravel backend image-build --containerfile native/containers/jhugen-mela/Containerfile \
  --context native/containers/jhugen-mela --tag localhost/ravel-jhugen-mela-toolchain \
  --receipt native/build/containers/jhugen-mela-toolchain.build.json --execute
```
