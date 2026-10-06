# Pipeline infrastructure (container runtime)

How to provision the container runtime that the container-based runs depend on. Tested on
macOS 15.5 / Apple Silicon (arm64); administrator rights are not required.

## Verified platform
On that platform the three verification gates below pass: the mapyde/ATLAS containers
(linux/amd64) run under emulation inside an arm64 podman machine.

## Components
| Component | Version | Source | Arch |
|---|---|---|---|
| podman (client) | 5.8.2 | **native arm64** from github.com/containers/podman release zip | arm64 |
| vfkit | 0.6.3 | github.com/crc-org/vfkit (signed) | arm64 (universal) |
| gvproxy | 0.8.9 | conda-forge | arm64 |
| podman machine image | machine-os:5.8 | quay.io | arm64 |
| mapyde | 0.5.0 | conda-forge / PyPI | noarch |

Tooling lives under the native build directory's `tools/` (`native/build/tools/`, gitignored;
`RAVEL_NATIVE_BUILD` overrides the location): `podman-native/` (the arm64 client), conda env
`pipeline` (gvproxy, vfkit, mapyde). The VM lives in podman's default machine directory,
`~/.local/share/containers/podman/machine/`.

## The key procedural gap (and fix)
- **conda-forge's `podman` package is an x86_64 binary.** Run under Rosetta it reports `amd64` and
  `podman machine init` pulled an **amd64** CoreOS image (`*-amd64.raw`). Apple Virtualization can
  only boot a native (arm64) guest, so `podman machine start` failed with
  `VZErrorDomain Code=1 "Internal Virtualization error"`.
- **Fix:** use the **native arm64 podman client** (release zip), keep arm64 `vfkit`+`gvproxy`, and
  point podman at them via `CONTAINERS_HELPER_BINARY_DIR`. Then init pulls `*-arm64.raw` and the VM
  boots.

## Reproduce the runtime
```bash
source native/scripts/paths.sh            # sets the absolute RAVEL_NATIVE_BUILD
TOOLS="$RAVEL_NATIVE_BUILD/tools"
ENVBIN="$TOOLS/miniforge3/envs/pipeline/bin"   # gvproxy, vfkit, mapyde
PODMAN="$TOOLS/podman-native/podman-5.8.2/usr/bin/podman"  # native arm64
export CONTAINERS_HELPER_BINARY_DIR="$ENVBIN"
export CONTAINERS_MACHINE_PROVIDER=applehv
export PATH="$ENVBIN:$PATH"
"$PODMAN" machine init --cpus 6 --memory 8192 --disk-size 50 mg-vm
"$PODMAN" machine start mg-vm
```

## Verification gates
| Gate | Test | Expected result |
|---|---|---|
| 1 | `podman machine init && start` (arm64) | PASS — VM "mg-vm" running |
| 2 | run native container (`alpine`) | PASS — `uname -m` → aarch64 |
| 3 | run amd64 image (`--arch amd64`) | PASS — `uname -m` → x86_64 (emulation works) |
