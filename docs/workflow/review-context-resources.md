# Complete reviewer inventories and bounded presentation

A review context binds the entire copied artifact inventory and the omission list.
Authentication of these bytes is separate from the content initially presented to a
reviewer. A catalogue row, hash, binary header or omitted source is not a content read
or a scientific judgment. The original stage, approval, source and journal gates
remain authoritative; a larger resource declaration grants no execution permission.

Legacy packets keep a 10,000-copy index and 256 MiB aggregate authentication bound.
A larger packet must explicitly declare `index_limits` in its digest-bound manifest:

```python
limits = {"max_artifacts": 20000, "max_total_bytes": 512 * 1024**2}
manifest = review_context.create(rundir, "critic", new_packet, index_limits=limits)
```

These are finite maxima, including manifest bytes in the aggregate. The manifest
remains bounded at 16 MiB; individual copies remain bounded at 64 MiB. The omission
list has a separate finite 20,000-row ceiling and retains its original projection
semantics. No rows are clipped to make a packet fit. Overbound packets refuse.

The ordinary scientific-role preparation accepts `context_index_limits=limits`.
Its Host request `arguments` accepts that same optional closed field. Public
`ravel judgment prepare-role` and `advance`, and `ravel review-context create`,
expose `--max-index-artifacts 20000 --max-index-bytes 536870912`. Omit these flags to
retain the existing defaults. Existing role, cycle, source, policy and freshness
checks still run. Exact retained SOURCE inputs can be empty at generated IDs above
`a9999`; empty controls or unbound source copies remain refused.

The Host retains its existing 2,000,000-byte request default and quarter-request
initial text budget. On-demand artifacts and omissions have complete digest-bound
catalogues and explicit paging actions. Artifact pages remain at most 64 KiB and
authenticate the selected complete copy. Index pages authenticate every copied
artifact and retain a complete-index digest, while returning at most 64 KiB of rows.
They do not scan the original scientific input corpus or claim its content was read
by a model. Repeated index pages repeat retained-copy authentication.

For multiple selected content reads, use one ordinary `read_artifacts` call. It
reconstructs the complete role projection and checks current original source bytes
once within an ending-checked session. Its existing defaults remain 10,000 selected
IDs, 64 MiB returned content, 256 MiB source projection and 512 MiB session-managed
I/O. An explicit larger observation can declare up to 20,000 selected IDs, 256 MiB
returned content, 512 MiB source projection and 4 GiB session-managed I/O. A 64 MiB
individual-copy maximum is unchanged. The requested-content bound remains separate
from the complete index/authentication bound; reading all copies can require more
than one content batch. Every new call starts a fresh observation, with no persistent
cache. Direct proof/runtime-helper I/O is not included in session accounting; the
receipt reports that cost as unknown, so an external deadline remains necessary.

The original generator stage contains 12,107 individual input commitments totalling
1,147,464,304 declared bytes. Its 12,035 inputs at most 1 MiB sum to 290,510,704 bytes;
118 are empty, and 72 larger inputs retain their original commitments. These are
metadata observations, not a payload rehash or a completed reviewer context. The
input-only metadata model is 6,639,068 bytes, below the manifest limit. The final
context still needs an actual bound projection and root-admitted read allocation;
its genuine count/bytes depend on the existing content and disclosure rules.
