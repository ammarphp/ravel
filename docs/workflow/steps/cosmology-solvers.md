# Finite supplied cosmology solver studies

The `cosmology-solver` mode uses the ordinary version2 scientific-study lifecycle, one attempt, fresh approval and Check-In2 review. Preparation imports no cosmology engine. The operation uses the existing bounded native subprocess transport; it creates no sampler, installer or separate runner.

`ravel.physics.cosmology_solver.prepare(input_path, policy_path, output, approval_mode)` prepares a specification. Its task is exactly `{"input": "/absolute/solver-input.json"}`. Use the existing commands:

```sh
ravel plan --rundir /absolute/fresh-run --spec /absolute/science-spec.json
ravel approve --rundir /absolute/fresh-run --quote '<actual assent>'
ravel run --rundir /absolute/fresh-run
ravel status --rundir /absolute/fresh-run --write
```

The approval mode must match the caller's actual policy. Scripted assent is machine approval. A prepared specification grants no execution authority. All runtime/input files are bound by the normal plan. Native entry refuses without a live, source-matched ordinary worker and current attempt/approval. A source review is separate from native API/ABI and scientific qualification.

## Closed input and output

The schema1 document requires exactly `schema_version`, `engine`, `source`, `profile`, `points`, `grid`, `model`, `components`, `runtime`, `trusted_runtime`, `operation_resources`, `max_ram_mib`, and `measurement`. Every point is `{id, parameters}` with a distinct bounded ID. Pins are `{path, sha256}`. `operation_resources` is the existing closed schema1 solver declaration: kind `solver`, generated_events `0`, solver_evaluations equal to the complete point count, and a positive max_seconds at most900. At most64 points and4096 cells are admitted. The outer study reserves30 extra seconds and has one attempt. The count describes explicit parameter-point API solves; internal cached calls are not a hard operating-system evaluation quota.

The finite runtime manifest is `{schema_version:1, engine, version, files:[pins], site_roots:[ordinary absolute paths], environment:{...}}`. Only PATH/LD_LIBRARY_PATH/DYLD_LIBRARY_PATH selected environment values are allowed; they must match the actual startup environment. `runtime` pins the resolved ordinary executable and manifest. Every observed nonstdlib Python module origin must be in the finite bound file set before and after evaluation. This is not a full OS/shared-library/data-read closure or sandbox. Engines and their data/configuration are trusted and must be independently qualified. No engine dependency is installed automatically.

CAMB1.6.5 and CLASS3.4.1 accept only profile `flat-massless-lcdm-linear`: explicit H0, physical omega_b and omega_cdm, A_s, n_s, tau, T_CMB, YHe and N_eff; flat curvature and zero massive neutrinos. `grid` contains complete strictly ordered `k_h_mpc`, `redshifts` and `background_redshifts`. `model` and `components` are null. CAMB uses `get_results`, explicitly linear total-matter interpolation, k/h and `(Mpc/h)^3`. CLASS uses `compute(['fourier'])`, `pk_lin(k=h*k_h,z)` and P*h^3, `Hubble(z)*299792.458` in km/s/Mpc, and angular_distance in Mpc. Both retain every power rectangle cell and Hubble/distance cell. Finite real NumPy scalars and zero-dimensional real numeric arrays are admitted only at native getter boundaries; booleans, vectors, object/complex arrays and nonfinite values refuse. Closed JSON inputs remain literal finite numbers. CAMB sets extrap_kmax=None, records returned kmin/kmax in h/Mpc and zmin/zmax for every point, and requires the complete requested power grid to lie inclusively inside that actual support before any observable getter. Single-redshift support with zmin==zmax is valid. Delivery revalidates all retained support rows and their exact requested grids/units; no arbitrary extrapolation or tolerance is added. This support check describes matter-power interpolation, not an independent qualification of background or model domains. CMB spectra, massive neutrinos and engine comparisons use the lensed CMB profile below.

Cobaya3.6.2 accepts profile `logposterior`, a pinned explicit model JSON, complete sampled parameter values, and null grid/measurement. `components` explicitly declares `priors`, `likelihoods`, `derived`, and complete `derived_units`. Named log-density outputs have unit1. `get_model` and `logposterior(...as_dict=True,make_finite=False,return_derived=True,cached=False)` preserve raw results. Outside-prior negative infinity remains negative infinity; the complete likelihood/derived population receives explicit `not_computed:outside_prior` markers when the engine skips it. No posterior sampler, evidence, CLs or model-ranking interpretation is created. Dynamic external functions, lambda expressions, installation and sampling options are refused; trusted native components remain runtime-qualified dependencies.

Raw call starts/returns/failures and the complete uncompleted point denominator are written progressively. The first failure stops the task without retry. Successful delivery checks the full operation/cell census and each cell's correspondence to the retained raw return. Physics validity always remains false pending actual review and qualification.

## Lensed CMB spectra and engine comparison

Profile `lensed-cmb-cl` delivers lensed CMB power spectra C_ell in muK^2 for ell = 2 to `ell_max`. `engine` is `camb`, `class` or `camb+class`. `grid` is `{ell_max, spectra}` with `ell_max` up to 5000 and spectra chosen from `TT`, `EE`, `BB` and `TE`. Point parameters are the linear-profile set plus `mnu_ev` (summed neutrino mass in eV) and `num_massive_nu` (0, or 1 for one massive species carrying the full mass). `N_eff` is the total effective number. `solver_evaluations` equals points times engines; `model`, `components` and `measurement` are null.

CAMB runs `set_for_lmax(ell_max, lens_potential_accuracy=1)`, `get_results` and `get_cmb_power_spectra(CMB_unit='muK', raw_cl=True)`. CLASS runs with `output='tCl,pCl,lCl'`, `lensing='yes'`, `l_max_scalars=ell_max+500`, `N_ncdm=num_massive_nu`, `m_ncdm=mnu_ev` and `N_ur = N_eff - 1.0132*num_massive_nu` (the CLASS correspondence for T_ncdm = 0.71611); its dimensionless `lensed_cl` values are multiplied by (T_CMB*1e6)^2. Each spectrum cell carries the full multipole vector and is checked against the retained raw engine return.

With `camb+class`, the result adds `comparison` per point and spectrum: the maximum and root-mean-square of |C_ell(CAMB) - C_ell(CLASS)| divided by the CLASS C_ell (by sqrt(C_TT C_EE) of CLASS for TE), and the multipole of the maximum. At default accuracy settings the two engines agree at the few-per-mille level for Planck-like parameters; the comparison quantifies the difference at the requested point.

Write the runtime manifest from an installed environment:

```sh
python -m ravel.physics.cosmology_solver manifest --engine camb+class \
  --site "$(python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" --out runtime.json
```

The manifest lists every file of the installed dependency closure of the selected engines.

## Supplied measurement connection

An optional pinned bridge declares `{model, point_id, quantity, cell_ids, bin_ids, role:'sm', task}`. The complete quantity cells, explicit bin mapping and units must match the supplied existing measurement model. It preserves experimental covariance, theory covariance, overlap/constraint policy, signal and data, and replaces only its declared SM values. The caller's ordinary measurement task retains its inference and signal-strength settings; only its input path is replaced with the new full model. Output files `measurement-model.json` and `measurement-task.json` are ready for a separate existing `measurement` study. No inference, approval, physical applicability or covariance is manufactured.

References: [CAMB1.6.5 result API](https://github.com/cmbant/CAMB/blob/1.6.5/camb/results.py), [CLASS3.4.1 source](https://github.com/lesgourg/class_public/blob/814ce59c380a5cccd0bed1747a384ff7bfc1f9cf/python/classy.pyx), [Cobaya3.6.2 model source](https://github.com/CobayaSampler/cobaya/blob/899f30a49f85de610dac321e91a1af50018e56aa/cobaya/model.py).
