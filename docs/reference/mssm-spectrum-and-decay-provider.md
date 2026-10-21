# Consistent MSSM spectrum and decay source operations

`ravel model-spectrum prepare` accepts the closed schema3 profile `MSSM-SPheno-4.0.5` and operation `spheno-4.0.5-mssm-spectrum-decays`. It uses the existing generated-spectrum planner, admitted native executor, single-worker compile/solver phases and scientific review. It builds the complete official55-file SPheno4.0.5 source capsule and obtains one new full SLHA spectrum/decay origin.

Required configuration fields are `schema_version`, `operation`, `profile`, nonempty `source`, `trusted_generated_source:true`, pinned `source_capsule` and `input_card`, pinned `tools`, complete explicit finite `runtime_inputs`, selected absolute-directory `native_path`, and `max_ram_mib`. Tools are fc(gfortran),make,ar,uname,rm,mv; all are ordinary regular pinned files at their first exact PATH resolution. Symlink aliases need separately authenticated regularization. Each source file's exact released hash/mode is in `data/spectrum/mssm-spheno-4.0.5.json`. Runtime/compiler/system dependency completeness is a separate admitted-capsule obligation.

The supplied full real weak-scale card has unique ordered MODSEL,SMINPUTS,VCKMIN,MINPAR,EXTPAR,SPHENOINPUT blocks, no alternate/output/scaled blocks, and every source-consumed scalar listed in the profile's adapter. MODSEL selects weak-scale MSSM, no RPV, no complex/generation-mixing branch. VCKMIN's CP phase is explicitly zero. The admitted neutrino branch explicitly sets all neutrino masses to zero; no ambiguous nonzero native neutrino unit is assumed. The μ/m_A² branch fixes every gaugino,third-generation trilinear and soft input; released first/second-generation zero initialization is disclosed. Conventions outside the declared profile are refused rather than transformed.

EXTPAR0 on the card is **Q in GeV**; SPheno stores Q² internally. EXTPAR31–49 on the card are **masses in GeV**, squared internally; EXTPAR24 directly holds m_A² in GeV². Signed gaugino/μ/trilinear values and all literal card tokens remain intact. Explicit settings bind errors, thresholds, loop/RGE/Yukawa choices, decay output and numerical precision/iterations; disabled external-spectrum and fallback branches must not silently change the input model. The external card is passed byte-for-byte, without squaring/conversion.

The released solver's120-character filename buffers are accommodated with exact isolated-cwd basenames `selected-input.slha` and `spectrum-output.slha`. The executable itself has an authenticated absolute pathname. The adapter refuses collisions and ambient `LesHouches.in`; no supplied filename is truncated. Exact source and selected card are checked around both phases. The1200s compile/60s solver ceilings are inside the existing1440s adapter stage and do not constitute permission to run. Fresh ordinary CHECK-IN1 and machine lease remain required.

All source/native workspace files and directories, phase receipts and ordinary outputs are retained and checked. `MSSM.slha` is a byte-identical copy of the authenticated native return. The result retains all blocks, scale occurrences, signed masses,mixing/coupling rows,DECAY channels and diagnostic/error rows. Process success is transport success; `physics_validated:false` and `channel_completeness_declared:false` remain explicit. Known emitted result bytes and complete output membership are checked before returning.

`ravel model-spectrum grid` prepares arbitrary finite supplied parameter axes
through operation `parameter-grid`. A pinned grid specifies card-address
bindings, explicit affine or constant relations, source evidence, dataset
population and JSON or TSV delivery. No mass equality, coupling ratio, range or
spacing is implicit. Only selected scalar tokens change; every other byte and
source remains intact. All points receive separate unapproved ordinary
specifications, with an aggregate proposed budget derived from their actual
count. See [input preparation](../workflow/steps/02-inputs.md).

An actual accepted SPheno return can use existing named-spectrum point handoff to join an independently accepted UFO through a complete explicit identity map of *all* external addresses. Every width must come from the returned same-provider DECAY header; absence does not permit a default. Source/target units must agree. The generated MSSM map accepts `accepted_spheno_mssm_spectrum` only with the exact executed config,source version,input and full returned SLHA. This is source custody, not physical equivalence or normalization certification.

Near-degenerate applicability remains limited. The released quark three-body gate is Δm>0.3GeV; the pion branch can replace the first nine quark widths, and its single-zero-coupling expression has a source inconsistency relative to the general branch. No complete mixed-state multihadron/current matching law or lifetime accuracy is asserted. Emitted zero/missing widths do not establish stability or channel completeness. Source constants/default numerical settings are retained explicitly. A supplied LLP research goal remains open pending its physical prescription and a separately reviewed complete applicable decay law/native qualification.

## Separate exact-row pure-limit table

`ravel model-spectrum decay-table` prepares mode `chargino-decay-table`; `ravel chargino-decay-table --request ... --review-policy ... --rundir ...` prepares its ordinary unapproved study directly. Input schema1 requires exact string mass, a documented basis enum, complete distinct accessible daughter IDs/splittings, `complete_accessible_neutralino_population:true`, explicit exclusion of other modes within the declared pure-limit scope, and pinned source evidence for those assumptions.

Supported bases are `pure_higgsino_single_neutralino_normalization`(one or two accessible pure-Higgsino daughters) and `pure_wino_four_times_normalization`(one neutral partner, factor4). The author table for [2312.08087](https://arxiv.org/abs/2312.08087) is obtained from its [released data](https://member.ipmu.jp/satoshi.shirai/Chargino_Decay/chargino_decay.dat). All3794 rows,13 literal columns,3654 unique coordinates and140 equal duplicate lineages are retained with original tokens/source lines. Both mass and splitting must match actual released rows exactly; there is no interpolation/extrapolation.

The published total(column3 in1-based numbering) is used. Inclusive nonstrange multihadron(column7) overlaps the separately displayed exclusive subchannels(columns8–10); they are never added twice. Higgsino normalization is to one neutralino; widths are summed over the explicitly supplied complete accessible population. Wino normalization is4×, as declared by the author. Arithmetic uses exact decimal/integer factors and rational totals; no numerical error enclosure or physical uncertainty is invented from table precision.

The complete original table and selected result are independently committed and retained through ordinary output custody. The table result retains its original spectrum assumptions. A generic M1=M2 mixed state requires its own model calculation. Public redistribution requires source-table licence review.
