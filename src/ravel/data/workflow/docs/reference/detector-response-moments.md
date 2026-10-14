# Complete event-group response moments

`detector_response.summarize` remains the common accumulator for the ordinary
`domain: detector-response` constructor and the released six-b retained-trace
consumer. It retains all named original weights, anchors, destination coordinates,
event identities and generator-group identities, including rejected events,
explicit zero allocations, zero weights and zero groups. Missingness is refused;
it is never converted to a zero. No new likelihood or covariance backend is used.

For each weight, event products use the existing literal floating-point arithmetic.
The coordinate marks and denominator marks in each generator group use the
existing `math.fsum` law. Signed correlated subevents therefore cancel within a
group before taking second moments. Sparse support means exactly nonzero marks
after these complete group sums; a group may cover many bins even if each event
only covers one or three bins. No per-group sparsity assumption is imposed.

The raw joint Gram uses all nonzero numerator and per-weight denominator marks,
including cross-weight and cross-anchor products. Its retained per-weight
`full_numerator_denominator_Gram` preserves the original float product/`fsum`
arithmetic. Exact zero products are skipped and all zero matrix entries are
emitted. The additional internal rational Gram uses the exact binary64 group
marks; it is not a new interpretation of the supplied physical numbers.

For a shared original-weight denominator, the conditional delta covariance is

\[
C_{wi,vj}=f_w f_v\sum_g
(m_{wgi}-r_{wi}d_{wg})(m_{vgj}-r_{vj}d_{vg}),\qquad
f_w={\rm scale}/D_w,\quad r_{wi}=N_{wi}/D_w.
\]

The factor and ratio divisions retain their binary64 meanings. Sparse raw Gram
entries are contracted in exact rational arithmetic, and each final covariance
entry is rounded once to binary64. This avoids catastrophic cancellation from
subtracting already-rounded large Gram entries. It changes covariance rounding
relative to the old per-group rounded-residual/product calculation, including
the fixed-denominator case; bitwise covariance identity is not promised.
Means, grouped marks and the separately reported float raw Gram retain their
earlier arithmetic. No covariance clipping, PSD projection or calibration is
performed. Raw product/Gram overflow, nonrepresentable ratios/factors/covariance,
or zero/negative shared denominators refuse. Per-entry final rounding can leave
small numerical residues in an exactly constant partition sum.

The two-million bound counts actual scalar nonzero event products, normalized
mean multiplications, both float and rational raw Gram products, and rational
normalization-contraction products. A returned `moment_work` census records each
component. Scalar additions/divisions, internal arbitrary-precision integer
operations, input reads and serialization are outside that count; it is not a
wall-time estimate. Complete marks are bounded by 20,000 events and 512 joint
weight/anchor/destination coordinates. Full dense group marks and full covariance
matrices remain in the result. Dense over-budget cohorts refuse.

The generic reconstructed-event constructor opts out of its selector's duplicate
per-anchor covariance. The selector returns `covariance: null` with an explicit
delegation status, and the complete joint accumulator supplies the sole moment
result. The selector's default signature behavior, results and covariance stay
unchanged; likelihood mapping refuses unavailable delegated covariance. All
selection decisions, regions, weights, yields and source checks remain.

Generic response scientific inputs retain 8 MiB per-file and 32 MiB aggregate
bounds. Its full result is streamed as lossless compact JSON under a 256 MiB
per-file bound; an oversized or nonfinite partial file is retained and the call
fails. Six-b original input/log bounds remain 64 MiB; its separately committed
compact emitted result has a measured 320 MiB ceiling and ending report checks.
These bounds and the current 512-coordinate ceiling remain real refusal paths.
The common scientific worker delegates `result.json` to these same bounded
writers for the two response modes. Other modes retain their original writer;
verification and CHECK-IN2 still bind the complete result hash, and source
delivery never supplies an expert vote or physics certification.

Conditional group-Poisson Gram and first-order shared-denominator propagation
still require their original scientific assumptions. This extension does not
establish generator independence, detector calibration, native classifier
noninterference, a finite-MC auxiliary law, likelihood coverage or exclusion.
