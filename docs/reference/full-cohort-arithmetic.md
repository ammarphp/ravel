# Complete-group arithmetic

The supplied-group normalization and composition adapters accept an optional closed
`arithmetic_policy` in their pinned input contracts. The opt-in method is
`vectorized_products_compensated_sum_v1`, with integer `maximum_groups` at most
20000 and `maximum_pair_group_products` at most 100000000. The latter bounds logical
coordinate-squared times group products. Gradient-bound propagation uses additional
explicit product streams; this is not a CPU, RSS or universal runtime guarantee.

The absent policy retains the original 4096-group and 25000000-product limits and
output shape. Null, unknown keys and noninteger or excessive limits are refused
before worker execution. Each complete nested normalization, rebin and same-event
composition contract is source-pinned through ordinary scientific schema2 planning.
A larger policy never authorizes a missing group, an unobserved native weight or an
unmatched event population. Original coordinate reconciliation, RAW/flow provenance,
shared event counters and exact measurement component slices remain mandatory.

The implementation computes separate binary64 products and ordered compensated
reductions, retaining all original groups and explicit emitted-operand forward-error
bounds. It does not center, compress, repair or infer covariance. Native acquisition,
source-law applicability, prediction uncertainty and physics inference need their own
scientific checks. The supplied 20000-group fixture and timing are engineering evidence,
not a physical Rmiss prediction or a portable memory bound.
