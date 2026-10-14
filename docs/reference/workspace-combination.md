# Complete workspace combination

`ravel.physics.workspace_combination.combine(components, policy)` compiles two to eight complete supplied pyhf workspaces. It returns the combined workspace and a source-law report; it does not run inference or fit a model. A normal scientific-study adapter is not yet provided.

Each component supplies its identity, complete workspace, exact source measurement and a map for every modifier and POI. The policy supplies the common measurement and POI, an exact roster for each shared parameter, and an explicit channel-population independence statement. Channel names must be disjoint and every source channel must have exactly one complete finite nonnegative observation.

The compiler validates the original workspace before renaming, then compares the mapped original parameter contract with the transformed one. Initial values, domains, fixed states and auxiliary laws must survive mapping. The combined model must preserve the parameter-law union and count shared auxiliaries once. Scalar parameters may share only when their effective laws agree; shared vector parameters are refused until an explicit bin-coordinate join exists. Renaming cannot repair an invalid original Lumi declaration.

Independence is a caller-supplied scientific assumption; distinct names do not prove it. Synthetic density controls test arithmetic of the compiler under their supplied laws. They do not qualify an official combined model, its source applicability, inference or fit. Prepared official source pairs and any attribution discrepancies need their own explicit source-bound study contracts.
