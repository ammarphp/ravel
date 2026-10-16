# Per-point helicity amplitudes in a Linux container

The default installer builds the MCFM-based program for per-point helicity
amplitudes of interfering resonances, checks it, and records its runtime:

```sh
bash scripts/setup/install.sh --only mcfm-amplitudes --prefix <prefix> --jobs 4 --accept-licenses
ravel doctor --group mcfm-amplitudes --prefix <prefix>
```

MCFM needs libquadmath. The image uses `Containerfile.amd64` and `linux/amd64`
on every supported host: Linux x86_64, macOS x86_64, and macOS arm64 with
Rosetta enabled in the Podman machine. Start a stopped machine with
`ravel-podman machine start ravel`. Linux aarch64 is unsupported by this
installer route. The pinned base digest is in `base-image.json`.

The install budget is 8 GB and 210 minutes for image, source, overlay, and build.
Compilation under emulation takes 1–3 hours. These are planning estimates;
the native qualification run records measured time and disk.

## Linux x86_64: native build

On Linux x86_64 the installer skips the image and compiles on the host instead:
`native_compile` runs `build-mcfm.sh SOURCE OVERLAY BUILD` with the compiler-bootstrap
group's GNU 13 compilers and CMake first on `PATH`, and runs
`check-mcfm.sh` with the same toolchain. The installation record names a `native`
launcher, pins the toolchain executables and MCFM's runtime files (`process.DAT`,
`br.sm1`, `br.sm2`, copied next to the program), and the `native` backend runs the
program. The route was first built on AMD EPYC Linux cluster nodes (CMake 4.4, so the build
sets `CMAKE_POLICY_VERSION_MINIMUM=3.5` for the bundled QCDLoop).

## What the installer runs

These commands describe the install steps. The installer performs them itself;
there are no manual container steps.

1. Build or adopt the toolchain image. The installer calls
   `ravel.workflow.backends.oci_local.build_image` with the pinned client,
   `execute=True`, amd64 recipe and context. Its CLI equivalent is:
   ```sh
   ravel backend image-build --containerfile native/containers/mcfm/Containerfile.amd64 \
     --context native/containers/mcfm --tag localhost/ravel-mcfm-toolchain \
     --platform linux/amd64 --execute \
     --receipt <prefix>/containers/mcfm-amplitudes-toolchain.build.json
   ```
   A saved receipt is adopted when its Containerfile hash, context hash, base
   digest and platform match and the engine still reports its image present.
   The context hash covers copied scripts. Old receipts are retained under the
   prefix's trash directory before rebuilding. Package installation precedes
   script COPY in the Containerfile, so script changes reuse the package layer.
2. Clone `https://gitlab.com/mcfm-team/releases.git` at
   `0adaa4ed4079de1b17c84417a0a428a468f57e69` into the prefix's `tools/mcfm-src`
   (about 230 MB of source).
3. Run `native/setup/recipes/mcfm_overlay.py`. It verifies the hash of every member
   of the separately licensed component, exports source without Git metadata, applies the capture patch, copies
   the declared overlay members, and appends the CMake include. Its ownership
   receipt detects altered outputs and refuses foreign non-empty destinations.
   It also installs the verified component metadata and members under the prefix.
4. Run `/opt/ravel/bin/build-mcfm.sh SOURCE OVERLAY BUILD` through
   `oci_local.launcher_command`. Source and overlay are read-only; the new empty
   build directory is the only writable tree. The launcher enforces no network,
   CPU and memory limits, and amd64 emulation when needed. `RAVEL_BUILD_JOBS`
   comes from `--jobs`. The installer's prefix lock serializes the build like every other
   installer build; the machine lease admits approved study stages only and is not taken.
5. Run `/opt/ravel/bin/check-mcfm.sh BUILD` in the image. It checks ELF format,
   linked libraries and the binary hash against its build receipt. Only one
   JSON line with `"status":"passed"` succeeds. The generated
   `ravel-mcfm-amplitudes-check` wrapper repeats that check for doctor.
6. Save the launcher and installation record. A failed build is moved to the
   prefix's trash directory; it is never deleted. Resume verifies image
   presence, overlay bytes, build pins and the installation check.

The install command authorizes compilation. Its record includes the invocation,
licence acceptance by flag or prompt (or reuse of recorded acceptance), and
build receipt hashes. It grants no study approval or human review.
`ravel backend launch --execute` still requires an approved supervised stage.

## Runtime and scientific checks

The installation record is at
`<prefix>/installations/mcfm-amplitudes.json`. It pins the image id, amd64
platform and emulation flag, program path, build receipt, and read-only build,
source, overlay and LHAPDF trees. The launcher additionally pins the client,
connection, CPUs and memory. Compilers and linked libraries are recorded in
`toolchain.json` and `linked-libraries.json` inside the build directory.

An `amplitude-integration` document supplies backend kind and resource limits;
image, program, trees and runtime environment default from the installation
record found through `ravel.paths.native_build_root()`. Explicit backend fields
keep their values. The installation record becomes a pinned study and stage
input. A changed record invalidates prepared work.

Prepare a `point-oracle` study with approved oracle points to qualify numerical
consistency. See [amplitude reweighting](../../../docs/reference/amplitude-reweighting.md).
Doctor establishes installation readiness. Qualification remains
`built-unqualified` until the native numerical check is recorded. Independent
matrix-element comparison remains a separate operation.
