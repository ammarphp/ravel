# MCFM in an arm64 Linux container

MCFM 10.2.1 requires GNU C, C++ and Fortran and its QCDLoop needs quad
precision, which Apple Silicon compilers do not provide. RAVEL therefore builds
and runs it in an arm64 Linux container. The image only holds the toolchain;
the MCFM source, the RAVEL overlay and the build live on the host and are
mounted at identical paths, so the build receipt is valid on the host. The
overlay files come from the GPL program in `addons/gpl/mcfm-amplitudes/`.

## Steps

1. Record the base digest (owner approval: network and disk). Pull
   `registry.fedoraproject.org/fedora:41` for `linux/arm64`, read its digest with
   `podman image inspect --format '{{.Digest}}'`, and put it in the `FROM` line of
   `Containerfile` and in `base-image.json`. Until then `image-build` refuses.
2. Build the toolchain image:
   ```sh
   ravel backend image-build --containerfile native/containers/mcfm/Containerfile \
     --context native/containers/mcfm --tag localhost/ravel-mcfm-toolchain \
     --receipt "$RAVEL_NATIVE_BUILD/containers/mcfm-toolchain.build.json" --execute
   ```
3. Prepare the source and overlay trees on the host with the `mcfm-amplitudes`
   commands in `native/setup/toolchain-manifest.json` (clone at commit
   `0adaa4ed4079de1b17c84417a0a428a468f57e69`, export the overlay, apply the patch,
   append the CMake include). Stop before the `cmake` lines.
4. Write a launcher record from the image id in the build receipt:
   ```sh
   ravel backend launcher --image-id sha256:<id from the build receipt> --cpus 4 \
     --memory-mib 8192 --out "$RAVEL_NATIVE_BUILD/containers/mcfm-launcher.json"
   ```
5. Build MCFM in the container (the build directory must be new and empty):
   ```sh
   mkdir "$RAVEL_MCFM_BUILD"
   RAVEL_BUILD_JOBS=4 ravel backend launch --launcher "$RAVEL_NATIVE_BUILD/containers/mcfm-launcher.json" \
     --readonly "$RAVEL_MCFM_SOURCE" --readonly "$RAVEL_MCFM_OVERLAY" --writable "$RAVEL_MCFM_BUILD" \
     --workdir "$RAVEL_MCFM_BUILD" --execute -- \
     /opt/ravel/bin/build-mcfm.sh "$RAVEL_MCFM_SOURCE" "$RAVEL_MCFM_OVERLAY" "$RAVEL_MCFM_BUILD"
   ```
   To pass `RAVEL_BUILD_JOBS` into the container, add `--env RAVEL_BUILD_JOBS=4`
   when writing the launcher record.
6. Check the installation (no physics inputs): the same `launch` with
   `/opt/ravel/bin/check-mcfm.sh "$RAVEL_MCFM_BUILD"` prints `"status":"passed"`
   when the binary is an ELF for this machine, every shared library resolves in
   the image and the binary matches its build receipt.
7. Run the point oracle, the physics-level installation check: prepare an
   `amplitude-integration` study with operation `point-oracle` (see
   [amplitude reweighting](../../../docs/reference/amplitude-reweighting.md)) whose
   backend declares the toolchain image and the source, overlay, build and PDF
   directories as read-only trees. The stage runs the binary through the execution
   backend and checks the oracle points against their numerical band.

`build-receipt.json` records the source commit, overlay and binary hashes. Compilers and
system libraries come from the image: `toolchain.json` and
`linked-libraries.json` in the build directory record them, and the image digest
in the launcher record identifies the image that ran.
