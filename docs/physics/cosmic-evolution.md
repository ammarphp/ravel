# CosmicIC and Nyx source operation

`cosmic-evolution` is an ordinary schema-2 scientific adapter. It connects supplied source/card/transfer preparation, complete retained native delivery, and synchronous site-local build → CosmicIC → Nyx phases inside an **already allocated** Slurm job. It does not submit an allocation, SSH from a Mac, install software, add a study journal, or substitute CAMB/CLASS scalar getters for the original operation. Planning and source context do not execute native commands.

The original two notes variants and transfer recipe remain separate source commitments. The CPU example has 32 MPI ranks and 1024³ ICs; 4096³ production is separate. The GPU example has two nodes, eight ranks/GPUs and 64³ ICs/mesh. A 1024→64 mismatch stays unresolved. The nine requested fields are density, xmom, ymom, zmom, rho_e, Temp, phi_grav, particle_mass_density and particle_count. All six redshifts 7,6,5,4,3,2, particle/mesh levels, checkpoints, parameters, jobInfo, comoving_a, halo and in-situ obligations survive in the declared case scope and output census. Neither a finite required-file list nor a marker matching a Header independently proves scientific completeness; whole-parent review remains authoritative.

## Prerequisites and source profiles

No actual CosmicIC source/writer profile is bundled. The original `<repo_link>`, private Perlmutter paths, PrintFormat=6 description, dirty Nyx patch and missing native/data closure are not executable evidence. Site execution requires supplied complete source trees, authentic writer evidence inside those trees, exact cards/transfers/normalization, matching ICs or a prospective generation phase, selected native tools and installed Slurm response schemas. Supplying a pinned schema/source declaration authenticates bytes; it does not certify that the private writer is physically correct, source-complete, or scientifically qualified. The synthetic test writer is never a product profile.

The supported binary reader law is source-linked AMReX BinaryMetaFile/BinaryFile at the retained Nyx/AMReX revisions: native Long + two int headers, positive particle count, dimension=3, at least mass+three velocity extras, declared byte order/float width, exact header/payload length and complete aggregate geometry. All extra values/bytes survive. Every ordered FileList entry and its terminating newline is checked; duplicate or hardlinked chunks refuse. **Relative FileList names resolve from the native working directory**, as the actual AMReX reader does. No guessed native format, silent truncation, filename correction or FileList rewrite is performed. Full numeric/units/mass/phase-space correctness still requires later native/scientific review.

## Closed configuration

The task is exactly `{"input":"configuration.json"}`. The configuration has exactly:

- `schema_version:1`, `source`, `operation` (`source-preparation`, `retained-delivery`, `site-local-execution`), `original_requests` (whole file pins), `source_trees` (`root` and complete `files` pins), `writer_contract` (a pin or null), `cases`, `runtime` (or null), and `resources`.
- Pins contain exactly `path`, lowercase SHA256 and actual byte `size`. Source trees, cards, transfer rows, writer evidence, runtime files and retained native populations are read as complete authenticated inventories with ending hash/identity/member checks. No permanent cache or digest-as-content claim is made.
- Resources declare `max_input_files`, `max_input_bytes`, `max_output_files`, `max_output_bytes`, `max_seconds`, `cleanup_seconds`, `max_controller_bytes`, `max_controller_calls`, `handshake_seconds`. These are finite admission/I/O bounds, not physics/grid coverage limits. The ordinary per-study wall ceiling is 86400 s. Configurations use the existing bounded document reader (2 MB); retained text/header parsing additionally refuses text beyond 8 MiB. Large binary leaves are streamed and retained whole, never inserted blindly into a prompt. Larger metadata populations need a separately admitted input shape, not clipping.
- Each case has `id`, `ic_card`, `nyx_card` (or null), `transfer`, `ic` (or null), `scope`, `outputs`, `retained_root`, `phases`, `data_files`. Scope explicitly records original IC/Nyx geometry, initial/final redshifts, ordered fields/output/analysis redshifts, checkpoint flag and remaining obligations. Output scope must equal the case scope. Cards retain their whole original ordered assignments, identical duplicates and explicit quoted empty values; conflicting duplicate values refuse pending a real source prescription. Active heat/cool/reionization files require exact card/path/source associations.
- Transfer declares every named column/unit, actual file, generation redshift and a pinned normalization prescription. All rows, signed species entries and zeros survive; positive ordered k is checked. These checks do not establish transfer normalization or CosmicIC rescaling equivalence. The original `cmb_CAMB.tf` versus selected `cmb.tf` discrepancy is not automatically repaired.
- A retained IC declares `file_list`, all ordered `chunks`, `shape` and actual `reader_base`. A generated IC instead declares `generated_phase`, the source-written `file_list` path within that phase's native products, and `shape`. Its actual FileList determines the chunk names; complete fresh products and counts are captured into `ic-products.json` before the next phase.
- Each phase declares `id`, `kind` (`build`, `cosmicic`, `nyx`), `payload`, literal `argv`, `copies` (`file` pin and scratch `to`), ranks/nodes/GPUs per node, wall time and `ic_handoff` (null or Nyx's `file_list_to`, complete ordered `chunks_to`). A payload is an exact executable pin or an earlier build's `build_phase` plus product `path`. Earlier full build products/configuration remain bound; changed/missing binary or receipt refuses. A CosmicIC phase selects its exact copied input.par and transfer as the first two argv entries and its source-defined output root as the third. A Nyx phase selects its exact copied native card as the first argv entry; its BinaryMetaFile association and every copied IC chunk must agree with the actual reader cwd. Physical card values and original FileList bytes are not rewritten. A needed relocation requires a prospectively supplied source-bound card, while original requests remain preserved.
- Native output contracts explicitly name required files and bounded exact raw text markers. Every actual additional regular output is retained and hashed; aliases, missing/tail fields, changed bytes and ending ABA refuse. Declared output contracts are caller scientific scope, not an automatic derivation or acceptance of the original question.

## Site-local step ownership

Runtime pins Python, srun/scontrol/scancel, all declared dependency files and the installed schema JSON; it supplies the exact `scontrol --version`, explicit environment and allocation identity (`cluster`, job/UID/submit/start/restarts/full node names). No environment override can replace Slurm allocation IDs or UID. Installed JSON schemas explicitly map all job/step identity fields and timestamps; unsupported installed representations refuse. Native compact hostlists are expanded through bounded installed `scontrol show hostnames`, with raw query outputs retained. The current local controller's ClusterName is checked. Latest online Slurm manuals are not an installed-version certificate.

A synchronous srun invokes a source-bound Python rank shim. Every unique rank must announce the same fresh nonce, actual job/step/UID/node and exact prospective payload before the controller observes the actual newly created step and releases an acknowledgement. No scientific payload runs before that acknowledgement and fresh source/build/IC checks. The parent and rank authenticate every actual copied native input against the original admitted byte commitment, including the card and transfer selected by native argv, before release and through phase ending. Both acknowledgement consumption and the final pre-payload checkpoint must remain inside the declared handshake deadline. Whole rank exits and current terminal step identity must then agree. A failed/unknown handshake is held; it cannot authorize guessed cancellation. Known cleanup targets only the observed `JOB.STEP`; reused/different incarnation, unobserved ownership or unresolved terminal state refuses. The inherited allocation is never cancelled.

Local client termination uses the exact owned Linux pidfd leader and reaps it. It does **not** assert all local descendants are gone or that remote MPI ranks are absent. The outer ordinary supervisor owns its local process envelope. Slurm completion/cleanup observations, incomplete accounting and unknown distributed memory stay separate. Site MPI/PMI inheritance, GPU affinity, native builds, loaders, dirty-source physics and remote cleanup still require actual site qualification; supplied native tools are trusted, not OS-sandboxed. No Mac/HPC/native transport was qualified by the pure controls.

Every generated JSON commitment is computed from exact intended bytes before atomic emission, checked immediately and at ending. Explicit metadata updates first authenticate their previous intended version. Rank plans/handshakes/acknowledgements, build/IC receipts, source closures, adapter/common results and review records use this law. Preparation returns are detached reconstructions of those intended serialized bytes; a writer callback that changes its document alias refuses even when the durable file remains unchanged. Externally produced native bytes are separately captured at phase return, never reclassified as an intended synthetic result.

## Ordinary preparation and review

On the selected installed source, use:

```text
python -m ravel.physics.cosmic_evolution INPUT POLICY-WRAPPER SPEC
ravel plan --rundir FRESH-RUN --spec SPEC
ravel approve --rundir FRESH-RUN --quote ACTUAL-AUTHORIZED-ASSENT
ravel run --rundir FRESH-RUN
ravel status --rundir FRESH-RUN --write
```

Run/admission/Slurm actions are future execution, requiring the real ordinary CI1 and site allocation. No study or approval is manufactured by preparation. For an existing run, use status and resume/review; never reinitialize it. A supplied goal_binding uses the existing original-parent obligation machinery. `whole_parent_accepted` and `physics_validated` remain false in this delivery; only independent ordinary review may establish its supported scientific scope.

For a bounded deterministic Graph context, `python -m ravel.physics.cosmic_evolution --context INPUT CLOSURE` emits an intended, complete input commitment document. The `cosmic-evolution-context` Host action takes exactly `request_input` and `closure_input` IDs, each a Graph pin. It authenticates the full nested closure against the actual ordinary adapter input census, including inputs too numerous to be individual Graph fields. It does not treat source hashes as model-read content, clip a population to 128, authorize execution, or serve a blinded critic/verifier role. Source bodies may be obtained through existing grounded API/paging tools. Blueprint/tool discovery uses the registered ordinary adapter and its API, with no new controller.

The report retains original cases, full input/native inventories, raw phase failures and owned-step evidence. Source-preparation with unresolved private inputs is a useful partial delivery, not successful evolution or a parent-goal completion. Actual native/scientific and comparator campaigns remain later work.


Rank authority and checkpoints
------------------------------

The local scientific worker remains the sole process admitted by the ordinary
`science.verify_worker` PID/start-identity gate. Before constructing rank plans
and again before issuing each acknowledgement, that parent performs the unchanged
live worker gate and captures the current approved plan, approval, spent attempt,
stage fingerprint, original supervisor/child/start identity and attempt output
root. The intended `rank-plan.json` binds this exact `parent_admission`; the exact
`ack.json` additionally binds its digest, nonce, payload and observed owned step.

A remote rank validates the current approved plan/attempt through the existing
call-scoped source validation and selected-stage checks, requires the unchanged
registered parent fields, and compares the token with the intended plan. It does
not claim its own PID is the local science worker. It repeats the delegated
metadata check after consuming the acknowledgement and authenticates sources,
payload and IC handoff immediately before invoking the native payload. Missing
acknowledgement, a known failed parent record, revoked approval, changed source,
stale attempt, wrong step or replaced binding refuses before that invocation.

These are finite checkpoints on trusted shared-filesystem/controller evidence.
A parent death or revocation that is not reflected in those records is not
continuously detected by a remote rank. A revocation after the last check can
race payload release; this implementation does not provide instantaneous remote
revocation. The actual srun step time/kill-on-bad-exit law and exact owned-step
cancellation remain separate. No acknowledgement before observed step identity
means ownership is held; the implementation never guesses a step to cancel.
Controller stdout/stderr and external rank metadata are authenticated as the
actual phase-return buffers and remain identity/hash-bound through final return.
