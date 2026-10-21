# Resonance widths and branching ratios

The `resonance-width` study computes tree-level partial widths of a spin-0 or
spin-1 resonance into fermion pairs, the total over the declared channels, the
branching ratios and Γ/M. It uses the ordinary scientific-study lifecycle with
`task: {"input": "width.json"}`.

## Input

```json
{
  "schema_version": 1,
  "source": "Sequential Z' couplings with alpha(MZ) and the MS-bar weak angle",
  "resonance": {"name": "Z'", "spin": 1, "mass_gev": 3000},
  "couplings": {"scheme": "sequential_sm", "sin2_theta_w": 0.2312, "alpha_em": 0.0078},
  "channels": [
    {"id": "ee", "fermion": "e", "mass_gev": 0.000511},
    {"id": "mumu", "fermion": "mu", "mass_gev": 0.1057},
    {"id": "tt", "fermion": "t", "mass_gev": 172.5}
  ],
  "groups": {"charged_leptons": ["ee", "mumu"]}
}
```

The interaction is L = X f̄ (gL P_L + gR P_R) f for spin 0 and
L = X_μ f̄ γ^μ (gL P_L + gR P_R) f for spin 1.

- `sequential_sm` (spin 1): gL = k (g/cos θ_W)(T3 − Q sin²θ_W) and
  gR = −k (g/cos θ_W) Q sin²θ_W with g/cos θ_W = √(4πα)/(sin θ_W cos θ_W),
  the declared `sin2_theta_w` and `alpha_em`, and an optional `scale_factor` k.
  Channels name Standard-Model fermions (`e mu tau ve vm vt u c t d s b`).
- `declared`: each channel gives `gL` and `gR`, or `gV` and `gA`
  (gL = gV + gA, gR = gV − gA). Couplings can be complex (`{"Re": .., "Im": ..}`).
  A non-Standard-Model fermion declares its `color` (1 or 3).

Every fermion mass is declared. A channel below threshold has zero width.

## Result

`resonance-width.json` lists, per channel, the couplings, partial width and
branching ratio, the formula used, the coupling convention, group sums, the
total width and Γ/M. For spin 1 the width is

Γ = N_c p/(8πM²) · (1/3) [(|gL|²+|gR|²)(2M² − m1² − m2² − (m1²−m2²)²/M²) + 12 Re(gL gR*) m1 m2],

which reduces to N_c M (|gL|²+|gR|²)/(24π) for massless fermions. For spin 0 it
is N_c p/(8πM²) [(|gL|²+|gR|²)(M² − m1² − m2²) − 4 Re(gL gR*) m1 m2].

Branching ratios are fractions of the declared channel total. Adding bosonic or
new-physics channels to the declaration changes them. The widths are tree level;
QCD and electroweak corrections are separate inputs.
