# Container runtime

The installer provisions the container client and platform helpers declared in
the toolchain manifest. On macOS it uses a native Podman client, a matching
virtual-machine image and the configured helper binaries. On Linux the selected
runtime executes containers directly. The installation prefix keeps managed
tools together.

```sh
bash scripts/setup/install.sh --only container-runtime
.venv/bin/ravel doctor --group container-runtime
```

The installed image architecture and the guest architecture are separate facts.
An arm64 host requires an arm64 guest for native virtualization; an amd64 tool
inside that guest additionally requires the configured emulation route. A
successful guest boot establishes the guest runtime. Each scientific tool still
requires its pinned image, output checks and operation-specific qualification.

The doctor reports installation readiness and a repair command. It leaves
virtual-machine startup to an explicit execution or operator action. Retain
runtime versions, image digests, execution settings and output evidence with
the run.

See [installation](../installation.md), [execution backends](execution-backends.md)
and the [environment reference](environment.md) for supported setup and dispatch.
The [component inventory](component-inventory.md) identifies declared
installation boundaries and licences.
