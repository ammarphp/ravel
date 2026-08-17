# Step 1 — Container runtime (one-time, macOS Apple Silicon)

The pipeline runs amd64 containers. On Apple Silicon with no admin rights, use a native arm64
podman client + Apple Virtualization. Do NOT use conda-forge's podman (it is x86 and pulls an
unbootable amd64 VM image).

**Do:**
```bash
TOOLS=stages/01-event-generation/build/tools          # any persistent location works
CONDA="$TOOLS/miniforge3/bin/conda"

# 1. helper binaries (arm64): gvproxy + mapyde + python
"$CONDA" create -y -n pipeline -c conda-forge python=3.11 podman gvproxy mapyde
ENVBIN="$TOOLS/miniforge3/envs/pipeline/bin"

# 2. native arm64 podman client (the conda one is x86 — replace it)
mkdir -p "$TOOLS/podman-native" && cd "$TOOLS/podman-native"
curl -L -o p.zip https://github.com/containers/podman/releases/download/v5.8.2/podman-remote-release-darwin_arm64.zip
unzip -oq p.zip
PODMAN="$PWD/podman-5.8.2/usr/bin/podman"; cd - >/dev/null

# 3. vfkit (Apple Virtualization helper, signed) next to gvproxy
curl -L -o "$ENVBIN/vfkit" https://github.com/crc-org/vfkit/releases/download/v0.6.3/vfkit
chmod +x "$ENVBIN/vfkit"

# 4. start an arm64 VM
export CONTAINERS_HELPER_BINARY_DIR="$ENVBIN" CONTAINERS_MACHINE_PROVIDER=applehv
export PATH="$ENVBIN:$PATH"
"$PODMAN" machine init --cpus 6 --memory 8192 --disk-size 50 mg-vm
"$PODMAN" machine start mg-vm
```

**Verify (all three must pass):**
```bash
"$PODMAN" run --rm docker.io/library/alpine uname -m          # -> aarch64
"$PODMAN" run --rm --arch amd64 docker.io/library/alpine uname -m   # -> x86_64 (emulation)
```

A ready-made env script is provided: `source trial-runs/_infrastructure/pipeline-env.sh` sets the
PATH (incl. an amd64-forcing `podman` wrapper), helper dir, and provider for all later steps.

**If `podman machine start` errors with `VZErrorDomain Code=1`:** the podman binary is x86 (check
`file "$PODMAN"`); use the native arm64 client. See `workflow/checklists/troubleshooting.md`.

**Keep the machine awake during runs:** wrap long runs in `caffeinate -i -s` (idle sleep stops the VM).

**Next:** `workflow/analysis-simpleanalysis/02-install-mapyde.md`
