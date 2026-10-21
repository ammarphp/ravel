# Complete workspace combination

`ravel.physics.workspace_combination.combine(components, policy)` compiles two to eight complete supplied pyhf workspaces. It returns the combined workspace and a source-law report.

Each component supplies its identity, complete workspace, exact source measurement and a map for every modifier and POI. The policy supplies the common measurement and POI, an exact roster for each shared parameter, and an explicit channel-population independence statement. Channel names must be disjoint and every source channel must have exactly one complete finite nonnegative observation.

The compiler validates the original workspace before renaming, then compares the mapped original parameter contract with the transformed one. Initial values, domains, fixed states and auxiliary laws must survive mapping. The combined model must preserve the parameter-law union and count shared auxiliaries once. Scalar parameters share when their effective laws agree. Original Lumi declarations must validate before renaming.

Independence is a caller-supplied scientific assumption. Synthetic density controls test arithmetic of the compiler under their supplied laws. Official source pairs and attribution discrepancies require explicit source-bound study contracts.
