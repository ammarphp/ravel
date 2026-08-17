# Benchmark validation pages

One page per known-answer benchmark case, generated from the gate's own
`framework/benchmark/{cases.json,results.json}` by `scripts/gen_validation_pages.py`
(regenerate after any `--full` gate re-run; CI checks freshness indirectly via the
claims gate). Δ% = |1 − s95_obs(ours)/s95_obs(published)|.

| Case | Analysis | Δ% (obs) | Tier | Page |
|---|---|---|---|---|
| `ins1458270_squark_800_100` | ATLAS_2016_I1458270 | 0.2 | Ideal | [ins1458270_squark_800_100.md](ins1458270_squark_800_100.md) |
| `ins1458270_gluino_1000_100` | ATLAS_2016_I1458270 | 5.4 | Ideal | [ins1458270_gluino_1000_100.md](ins1458270_gluino_1000_100.md) |
| `ins1458270_squark_merged_800_100` | ATLAS_2016_I1458270 | 0.2 | Ideal | [ins1458270_squark_merged_800_100.md](ins1458270_squark_merged_800_100.md) |
| `ins1458270_gluino_merged_1000_100` | ATLAS_2016_I1458270 | 5.9 | Ideal | [ins1458270_gluino_merged_1000_100.md](ins1458270_gluino_merged_1000_100.md) |
| `conf2016054_gluino_onestep_1500_60` | ATLAS_2016_CONF_2016_054 | 8.6 | Ideal | [conf2016054_gluino_onestep_1500_60.md](conf2016054_gluino_onestep_1500_60.md) |
| `ins1452559_dm_axial_850_1` | ATLAS_2016_I1452559 | 2.3 | Ideal | [ins1452559_dm_axial_850_1.md](ins1452559_dm_axial_850_1.md) |
| `conf2016037_gluino_2step_sleptons_1400_60` | ATLAS_2016_CONF_2016_037 (run-local PATCHED copy) | 8.2 | Ideal | [conf2016037_gluino_2step_sleptons_1400_60.md](conf2016037_gluino_2step_sleptons_1400_60.md) |
