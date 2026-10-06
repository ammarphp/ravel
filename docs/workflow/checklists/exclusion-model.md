# Checklist — the exclusion model (pyhf)  ·  [judgment — script-assisted: the mode table below decides from what the analysis publishes]

Goal (step 7): a real 95% CL upper limit on the signal strength µ. pyhf is the tool; pick the mode.

## Which mode
| You have | Mode | Why |
|---|---|---|
| a serialized pyhf likelihood + a signal patch | **likelihood** | the analysis's full model; strongest, ATLAS-preferred |
| only per-SR (observed, background±unc) + signal | **counting** | no likelihood published; one single-bin model per SR |

```bash
# likelihood
pyhf_exclude.py likelihood --bkg <bkgonly>.json --patch <patch>.json --out <dir>
# counting
pyhf_exclude.py counting --srs <sr_yields>.json --out <dir>
```

## Reading the output
- `exclusion.json`: `obs_limit` (observed µ₉₅), `exp_limits` = [−2σ, −1σ, median, +1σ, +2σ].
- `exclusion.png`: CLs vs µ with the 0.05 line and the limit.
- **Excluded iff observed µ₉₅ < 1.** µ₉₅ ≫ 1 means the model is far from this analysis's reach.

## Counting-mode prescription
Quote the limit from the **single most-sensitive SR** (best *expected* CLs), not a combination — the
SRs overlap and cannot be combined without their correlations. `pyhf_exclude.py` does this and prints
the per-SR table.

## The µ-grid trap (why a limit can look like ">2")
A fixed µ scan (e.g. mapyde's muscan, 0.1–2.0) stops at its ceiling. If CLs there is still ≫ 0.05,
the scan ended before the crossing — the limit is not "2", it is *beyond the grid*. `pyhf_exclude.py`
has no fixed ceiling: it brackets µ (doubling until **both the observed and the +2σ-expected** CLs fall
below 0.05) and interpolates each crossing, so the **whole band** (observed + ±1,2σ) is real even when
large (e.g. a weakly-constrained compressed point giving µ₉₅ ≈ 6) — bracketing on the observed alone
would leave the upper expected band pinned at the ceiling. Non-finite points (qtilde can return NaN at
µ≈0) are dropped from the scan. On a full likelihood each point is a many-parameter fit — expect minutes.

## Trust the limit at the source
The model under test is usually one the authors never considered, so the limit stands alone — there is
no contour to check it against. Its credibility comes from the inputs: the analysis's own likelihood
(or observed+background) paired with the matching selection; an NLO-normalised signal cross-section;
and a signal acceptance from a pipeline validated once on a published benchmark (`validation.md`).
State which mode and which approximations apply (counting-vs-likelihood, the SR/threshold mapping) so
the limit can be read for what it is.
