#!/usr/bin/env python
"""Compute a 95% CL upper limit on the signal strength mu with pyhf.

Two model-building modes, matching what a search actually publishes:

  likelihood : a full serialized statistical model (background-only workspace +
               a JSON-Patch that adds the signal). This is the ATLAS-preferred
               reinterpretation input. Used as-is -- no hand-rolled model.
  counting   : no serialized likelihood available, so build a simple
               single-bin-per-SR counting model from each signal region's
               (observed, background, background-uncertainty, signal) numbers.
               The limit is quoted from the single most-sensitive SR (best
               EXPECTED CLs), which is the standard prescription when the SRs
               overlap and cannot be statistically combined.

Both modes invert pyhf's asymptotic CLs with a shared scan and bracketed root
refinement. Observed and expected (+/-1,2 sigma) limits have separate resolved /
above-scan / below-scan statuses. A scan endpoint is a bound, not a measured limit.
This computes the supplied statistical model; it does not establish asymptotic
coverage, detector fidelity, or the validity of missing background correlations.

Every minimization runs through `robust_optimizer`: scipy/SLSQP plus bounded
multistart profiling and a NaN-guarded iminuit-MIGRAD fallback. Scalar fits retain
sticky per-model escalation. Analytic fits require a finite original
objective and projected gradient; transient invalid line-search trials are only
recoverable inside the multistart, objective-nesting and fresh-root checks.
Published histosys workspaces can carry NaN pockets and competing local minima,
so a successful optimizer flag alone is insufficient. `exclusion.json` records the guard's activity under
"optimizer", and flags `median_at_cap` and `band_degenerate` mark
a ceiling-pinned median and an unusable expected band. Regressions: `selftest`.

Usage:
  pyhf_exclude.py likelihood --bkg BKG.json --patch PATCH.json --out OUTDIR [--label TXT]
  pyhf_exclude.py counting   --srs SRS.json                     --out OUTDIR [--label TXT]
      where SRS.json = [{"name": "...", "n": <obs>, "b": <bkg>, "db": <bkg_unc>, "s": <signal>}, ...]
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse, hashlib, importlib.metadata, inspect, json, os, sys, time, uuid
from pathlib import Path
import numpy as np
from ..paths import package_data_path
from ..limits import attach_limits, read_limits, rescale_artifact

try:
    import pyhf
    from pyhf.infer import hypotest
    from pyhf.optimize.opt_scipy import scipy_optimizer
except ImportError as exc:
    raise ImportError("pyhf is required; install the complete RAVEL Python toolchain.") from exc


PROFILE_START_RULE = {
    "selection": "nominal plus two best distinct retained starts ranked on the current objective",
    "maximum_starts": 3, "distinct_max_abs_atol": 1e-5,
    "admissibility": "clip bounds then restore this fit's fixed coordinates",
    "pool_capacity": 256, "pool_overflow": "first 32 plus most recent 224",
    "scope": "one model; frozen without updates during each two-order fresh check",
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _json_value(value):
    """Keep invalid numerical values explicit and JSON-safe in failed witnesses."""
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else {"nonfinite": str(float(value))}
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, dict):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(child) for child in value]
    return value


class ProfileWitnessBudgetError(Exception):
    """Recording exhaustion is fatal and must never become a numerical fallback."""


class _ProfileWitnessRecorder:
    """Enabled-only bounded record plus optional crash-surviving hash-chain journal.

    The journal contains replacements keyed by collection/index. A running entry
    is flushed before long numerical work, so a killed job is visibly incomplete.
    Record and journal have separate byte ceilings, both set by max_bytes.
    """
    def __init__(self, record, *, max_evaluations=5000, max_minimizations=50000,
                 max_bytes=256 * 1024 * 1024, journal_path=None):
        for name, value in (("max_evaluations", max_evaluations),
                            ("max_minimizations", max_minimizations), ("max_bytes", max_bytes)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if max_bytes < 512:
            raise ValueError("max_bytes must be at least 512 to retain base failure metadata")
        self.record = record
        self.limits = {"evaluations": max_evaluations, "minimizations": max_minimizations}
        self.max_bytes, self.bytes, self.journal_bytes = max_bytes, 0, 0
        self.terminal_reserve = min(2048, max_bytes // 3)
        self.journal_terminal_reserve = min(4096, max_bytes // 2)
        self.sizes, self.sequence, self.head = {}, 0, None
        self.journal = None
        self.journal_poisoned = False
        record.clear()
        record.update(schema_version=1, status="running", complete=False,
                      budgets={**self.limits, "record_bytes": max_bytes, "journal_bytes": max_bytes,
                               "overflow_policy": "fail; retain explicitly incomplete partial evidence"},
                      minimization_count_unit="candidate seed _minimize_once trials; SLSQP and MIGRAD strategy passes are not separate budget units",
                      evaluations=[], minimizations=[], profile_calls=[], frozen_pools=[], root_passes=[])
        if journal_path is not None:
            self.journal = Path(journal_path).open("xb")
            record["journal_path"] = str(Path(journal_path).resolve())
        metadata = {key: value for key, value in record.items()
                    if key not in ("evaluations", "minimizations", "profile_calls", "frozen_pools", "root_passes")}
        self.bytes = len(_canonical(record)) + 128  # reserved journal-head bookkeeping
        self.sizes[("metadata", None)] = len(_canonical(metadata))
        if self.bytes > max_bytes:
            if self.journal is not None:
                self.journal.close()
            self._exhausted("profile witness initial record byte budget exceeded")

    def _exhausted(self, reason):
        self.record.update(status="failed", complete=False, budget_error=reason)
        raise ProfileWitnessBudgetError(reason)

    def _error(self, error):
        raw = str(error).encode("utf-8")
        capacity = min(512, max(16, self.max_bytes // 10))
        return {"type": type(error).__name__[:64], "message": raw[:capacity].decode("utf-8", errors="replace"),
                "message_truncated": len(raw) > capacity, "message_bytes": len(raw),
                "message_sha256": hashlib.sha256(raw).hexdigest()}

    def _emit(self, collection, index, value, *, terminal=False):
        if self.journal is None or self.journal_poisoned:
            return
        event = {"sequence": self.sequence, "previous_sha256": self.head,
                 "collection": collection, "index": index, "value": value}
        digest = hashlib.sha256(_canonical(event)).hexdigest()
        payload = _canonical({**event, "sha256": digest}) + b"\n"
        ceiling = self.max_bytes if terminal else self.max_bytes - self.journal_terminal_reserve
        if self.journal_bytes + len(payload) > ceiling:
            self._exhausted("profile witness journal byte budget exceeded")
        try:
            self.journal.write(payload)
            self.journal.flush()
            os.fsync(self.journal.fileno())
        except BaseException as exc:
            # A complete line may have reached the file even when durability
            # failed. Never reuse its sequence/head by appending another event.
            self.journal_poisoned = True
            self.record["journal_error"] = self._error(exc)
            raise
        self.journal_bytes += len(payload)
        self.sequence += 1
        self.head = digest
        self.record["journal_head_sha256"] = digest

    def update(self, collection, index, **values):
        current = self.record if collection == "metadata" else self.record[collection][index]
        proposed = {**current, **_json_value(values)}
        # Metadata excludes event arrays and self-referential journal bookkeeping.
        measured = {key: value for key, value in proposed.items()
                    if key not in ("evaluations", "minimizations", "profile_calls", "frozen_pools", "root_passes",
                                   "journal_head_sha256")} if collection == "metadata" else proposed
        size = len(_canonical(measured))
        key = (collection, index)
        total = self.bytes - self.sizes.get(key, 0) + size
        if total > self.max_bytes - self.terminal_reserve:
            self._exhausted("profile witness record byte budget exceeded")
        self._emit(collection, index, measured)
        current.update(_json_value(values))
        self.bytes, self.sizes[key] = total, size
        return current

    def start(self, collection, **values):
        items = self.record[collection]
        if collection in self.limits and len(items) >= self.limits[collection]:
            self._exhausted(f"profile witness {collection} count budget exceeded")
        index = len(items)
        # The enclosing array's comma is not part of an entry's serialized size.
        if index:
            self.bytes += 1
        items.append({})
        try:
            return self.update(collection, index, **values)
        except BaseException:
            items.pop()
            if index:
                self.bytes -= 1
            raise

    def finish(self, status, error=None):
        terminal = {"status": status, "complete": status == "succeeded"}
        if error is not None:
            terminal["error"] = self._error(error)
        if "budget_error" in self.record:
            terminal["budget_error"] = self.record["budget_error"]
        if self.journal_poisoned:
            terminal["journal_error"] = self.record["journal_error"]
            terminal["complete"] = False
        proposed = {**self.record, **terminal}
        if len(_canonical(proposed)) > self.max_bytes and "error" in terminal:
            terminal["error"]["message"] = ""
            terminal["error"]["message_truncated"] = terminal["error"]["message_bytes"] > 0
        # Reserved capacity bounds error text and lets exhaustion itself become
        # a terminal journal event. No model/trace arrays are repeated here.
        try:
            self._emit("terminal", None, terminal, terminal=True)
        finally:
            self.record.update(terminal)
            if self.journal is not None:
                self.journal.close()


def _source_identity(target):
    try:
        path = Path(inspect.getfile(target)).resolve()
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    except (TypeError, OSError):
        return {"available": False}


class robust_optimizer(scipy_optimizer):
    """SLSQP convergence checks with a guarded MIGRAD fallback.

    Check finite objective values, fixed coordinates and convergence evidence.
    Refit distrusted candidates with native fixed parameters and retain the lower
    valid objective. A fallback escalates later fits and invalidates cached CLs
    points from the previous optimizer policy.

    Within bounded profile searches, finite original-objective candidates with
    projected gradient at most 1e-3 can recover from invalid line-search trials.
    Invalid final candidates require a guarded refit. Observed/expected objective
    nesting, current-data start scores and fresh reverse-order root checks also
    apply. These numerical checks do not establish a global minimum or coverage.
    """

    n_fits = 0          # minimizations attempted
    n_fallback = 0      # minimizations re-run through guarded MIGRAD after SLSQP distrust
    n_escalated = 0     # minimizations sent straight to MIGRAD (post-escalation)
    n_nan_flagged = 0   # fallbacks triggered by a non-finite objective evaluation
    escalated = False   # sticky: this process' current model surface is distrusted
    _announced = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._profile_enabled = False
        self._profile_frozen = False
        self._profile_pool = []
        self.profile_trials = 0
        self.profile_improvements = 0
        self.profile_max_improvement = 0.0
        self.profile_invalid_trials = 0
        self.profile_recovered_transients = 0
        self.profile_rejected_candidates = []
        self._witness = None
        self._witness_evaluation = None

    def begin_model(self):
        """Scope start vectors to one inference, never reuse another model's results."""
        self._profile_enabled = True
        self._profile_frozen = False
        self._profile_pool = []
        self.profile_trials = self.profile_improvements = 0
        self.profile_max_improvement = 0.0
        self.profile_invalid_trials = 0
        self.profile_recovered_transients = 0
        self.profile_rejected_candidates = []

    def _minimize(self, minimizer, func, x0, do_grad=False, bounds=None, fixed_vals=None, options={}):
        call = None
        if self._witness is not None:
            call = self._witness.start("profile_calls", status="running",
                evaluation_index=self._witness_evaluation, nominal_seed=x0, bounds=bounds,
                fixed_coordinates=fixed_vals or [], options=options, analytic_gradient=bool(do_grad),
                pool_size=len(self._profile_pool), pool_frozen=self._profile_frozen)
        try:
            return self._profile_minimize(minimizer, func, x0, do_grad, bounds, fixed_vals, options, call)
        except BaseException as exc:
            if call is not None and not isinstance(exc, ProfileWitnessBudgetError):
                self._witness.update("profile_calls", len(self._witness.record["profile_calls"])-1,
                    status="failed", error={"type": type(exc).__name__, "message": str(exc)})
            raise

    def _profile_minimize(self, minimizer, func, x0, do_grad, bounds, fixed_vals, options, call):
        initial = np.asarray(x0, dtype=float).copy()

        def admissible(seed):
            x = np.asarray(seed, dtype=float).copy()
            for i, (lo, hi) in enumerate(bounds or []):
                if lo is not None:
                    x[i] = max(lo, x[i])
                if hi is not None:
                    x[i] = min(hi, x[i])
            for i, value in fixed_vals or []:
                x[i] = value
            return x

        initial = admissible(initial)
        scalar = (lambda x: func(x)[0]) if do_grad else func
        seeds = [initial]
        scores = [] if call is not None else None
        if self._profile_enabled:
            # Candidate parameters are only starts: every score and minimization
            # uses THIS objective/data and reinstates THIS fit's fixed coordinates.
            # Ranking by the prior fit's NLL would mix different statistical tasks.
            ranked = []
            for pool_index, previous in enumerate(self._profile_pool):
                if len(previous) != len(initial):
                    continue
                seed = admissible(previous)
                value = float(np.asarray(scalar(seed)).ravel()[0])
                if scores is not None:
                    scores.append({"pool_index": pool_index, "objective": _json_value(value)})
                if np.isfinite(value):
                    ranked.append((value, seed))
            for _, seed in sorted(ranked, key=lambda item: item[0]):
                if all(np.max(np.abs(seed - other)) > 1e-5 for other in seeds):
                    seeds.append(seed)
                if len(seeds) == 3:
                    break

        if call is not None:
            call_index = len(self._witness.record["profile_calls"]) - 1
            self._witness.update("profile_calls", call_index, current_objective_pool_scores=scores,
                                 selected_seeds=seeds)

        results, failures = [], []
        for seed in seeds:
            trial = None
            if call is not None:
                trial_index = len(self._witness.record["minimizations"])
                trial = self._witness.start("minimizations", status="running",
                    profile_call_index=call_index, evaluation_index=self._witness_evaluation, seed=seed,
                    escalated_before=bool(robust_optimizer.escalated))
                self._witness_trial = trial_index
            self.profile_trials += 1
            try:
                result = self._minimize_once(minimizer, func, seed.copy(), do_grad,
                                            bounds, fixed_vals, dict(options))
                results.append(result)
                if trial is not None:
                    self._witness.update("minimizations", trial_index, status="succeeded",
                        result=self._result_witness(result), escalated_after=bool(robust_optimizer.escalated))
            except (RuntimeError, ValueError) as exc:
                failures.append(str(exc))
                if trial is not None:
                    self._witness.update("minimizations", trial_index, status="failed",
                        error={"type": type(exc).__name__, "message": str(exc)})
            except BaseException as exc:
                if trial is not None and not isinstance(exc, ProfileWitnessBudgetError):
                    self._witness.update("minimizations", trial_index, status="failed",
                        error={"type": type(exc).__name__, "message": str(exc)})
                raise
        if not results:
            raise RuntimeError("robust_optimizer: no valid profile start: " + "; ".join(failures))
        best = min(results, key=lambda result: float(result.fun))
        improvement = float(results[0].fun) - float(best.fun)
        if improvement > 1e-5:
            self.profile_improvements += 1
            self.profile_max_improvement = max(self.profile_max_improvement, improvement)
        pool_added = [] if call is not None else None
        pool_trimmed = False
        if self._profile_enabled and not self._profile_frozen:
            for result in results:
                candidate = np.asarray(result.x, dtype=float).copy()
                if all(np.max(np.abs(candidate - old)) > 1e-5 for old in self._profile_pool):
                    self._profile_pool.append(candidate)
                    if pool_added is not None:
                        pool_added.append(candidate)
            # Preserve early bracket solutions and a bounded recent continuation
            # history. This is a finite search, not a proof of global optimality.
            if len(self._profile_pool) > 256:
                self._profile_pool = self._profile_pool[:32] + self._profile_pool[-224:]
                pool_trimmed = True
        if call is not None:
            self._witness.update("profile_calls", call_index, status="succeeded",
                chosen_result=self._result_witness(best), pool_added=pool_added, pool_trimmed=pool_trimmed,
                pool_size_after=len(self._profile_pool))
        return best

    @staticmethod
    def _result_witness(result):
        return {"parameters": np.asarray(result.x, dtype=float), "objective": float(result.fun),
                "success": bool(getattr(result, "success", False)),
                "message": str(getattr(result, "message", "")),
                "status": _json_value(getattr(result, "status", None)),
                "nfev": _json_value(getattr(result, "nfev", None))}

    def _trial_update(self, **values):
        if self._witness is not None:
            self._witness.update("minimizations", self._witness_trial, **values)

    @staticmethod
    def _bound_tolerance(lo, hi):
        """Roundoff allowance that cannot swallow a narrow physical interval."""
        finite = [abs(float(value)) for value in (lo, hi) if value is not None and np.isfinite(value)]
        tolerance = 64 * np.finfo(float).eps * max([1., *finite])
        if lo is not None and hi is not None and np.isfinite(hi - lo):
            tolerance = min(tolerance, max(0., hi - lo) * 1e-8)
        return tolerance

    @staticmethod
    def projected_gradient(x, gradient, bounds, fixed_vals):
        """Necessary first-order condition, in the supplied parameter coordinates.

        At a lower (upper) bound only a negative (positive) derivative permits
        feasible descent. Fixed coordinates have no feasible descent direction.
        This is not a global-optimum test: the profile portfolio and objective
        nesting checks are still required.
        """
        x, residual = np.asarray(x, dtype=float), np.asarray(gradient, dtype=float).copy()
        if residual.shape != x.shape or not np.all(np.isfinite(residual)):
            return float("inf")
        for i, (lo, hi) in enumerate(bounds or []):
            tolerance = robust_optimizer._bound_tolerance(lo, hi)
            if lo is not None and x[i] <= lo + tolerance:
                residual[i] = min(0., residual[i])
            elif hi is not None and x[i] >= hi - tolerance:
                residual[i] = max(0., residual[i])
        for i, _ in fixed_vals or []:
            residual[i] = 0.
        return float(np.max(np.abs(residual), initial=0.))

    def _minimize_once(self, minimizer, func, x0, do_grad=False, bounds=None, fixed_vals=None, options={}):
        last = [None, None]

        def components(x):
            if last[0] is None or not np.array_equal(x, last[0]):
                last[:] = [np.asarray(x).copy(), func(x)]
            return last[1]

        scalar = (lambda x: components(x)[0]) if do_grad else func
        gradient = (lambda x: components(x)[1]) if do_grad else None
        robust_optimizer.n_fits += 1
        if robust_optimizer.escalated:
            robust_optimizer.n_escalated += 1
            self._trial_update(path="sticky_migrad", fallback_status="running")
            return self._migrad(scalar, x0, bounds, fixed_vals, gradient=gradient)
        nan_seen = [0]

        def watched(x):
            v = func(x)
            values = v if do_grad else (v,)
            if not all(np.all(np.isfinite(np.asarray(item, dtype=float))) for item in values):
                nan_seen[0] += 1
            return v

        result, why = None, None
        self._trial_update(path="scipy", scipy_status="running")
        try:
            result = super()._minimize(minimizer, watched, x0, do_grad=do_grad, bounds=bounds,
                                       fixed_vals=fixed_vals, options=options)
        except Exception as exc:
            why = f"scipy raised {type(exc).__name__}"
        if self._witness is not None:
            self._trial_update(scipy_status="returned" if result is not None else "raised",
                               scipy_result=self._result_witness(result) if result is not None else None,
                               scipy_error=why)
        scipy_clean = (result is not None and bool(getattr(result, "success", False))
                       and self._valid_result(result.x, result.fun, scalar, bounds, fixed_vals))
        if why is None and not scipy_clean:
            why = "scipy reported failure or a non-finite minimum"
        if why is None and fixed_vals:
            for i, v in fixed_vals:
                if abs(float(result.x[i]) - float(v)) > 1e-6 * max(1.0, abs(float(v))):
                    why, scipy_clean = f"fixed parameter {i} drifted", False
                    break
        projected = None
        if scipy_clean and do_grad:
            projected = self.projected_gradient(result.x, gradient(result.x), bounds, fixed_vals)
            if projected > 1e-3:
                why, scipy_clean = "analytic projected gradient exceeds 0.001", False
        self.profile_invalid_trials += nan_seen[0]
        if why is None and nan_seen[0]:
            # A finite stationary final point after an invalid line-search trial
            # is usable ONLY in the analytic, multistart profile context. compute
            # additionally checks observed/Asimov nesting and fresh root stability.
            # The scalar legacy NaN-pocket policy remains sticky: it lacks this
            # independent derivative check and has a retained false-success case.
            if do_grad and self._profile_enabled and projected is not None:
                self.profile_recovered_transients += 1
            else:
                why = f"objective non-finite {nan_seen[0]}x during the minimization"
        if why is None:
            return result

        self.profile_rejected_candidates.append({
            "reason": why, "nonfinite_trials": nan_seen[0],
            "projected_gradient_max": projected if projected is None or np.isfinite(projected) else None,
            "objective": float(result.fun) if result is not None and np.isfinite(result.fun) else None,
            "analytic_gradient": bool(do_grad),
        })
        self.profile_rejected_candidates = self.profile_rejected_candidates[-100:]
        if nan_seen[0]:
            robust_optimizer.n_nan_flagged += 1
        robust_optimizer.n_fallback += 1
        # Analytic candidates have an independent final derivative check and
        # profile-level controls. A failed candidate triggers a local fallback,
        # not permanent rejection of every later fit on this model.
        robust_optimizer.escalated = not (do_grad and self._profile_enabled)
        if not robust_optimizer._announced:
            robust_optimizer._announced = True
            print(f"  note: SLSQP result untrusted ({why}) -- re-minimizing with NaN-guarded "
                  "iminuit MIGRAD" + (" with sticky scalar escalation" if robust_optimizer.escalated else
                  " for this analytic candidate") + " (totals in exclusion.json 'optimizer')",
                  file=sys.stderr, flush=True)
        self._trial_update(fallback_status="running", rejected_scipy_reason=why,
                           nonfinite_trials=nan_seen[0], projected_gradient_max=_json_value(projected))
        fallback = self._migrad(scalar, x0, bounds, fixed_vals, gradient=gradient)
        if self._witness is not None:
            self._trial_update(fallback_status="succeeded", fallback_result=self._result_witness(fallback))
        if scipy_clean and float(result.fun) <= float(fallback.fun):
            return result
        return fallback

    @staticmethod
    def _valid_result(x, value, func, bounds, fixed_vals):
        """Convergence flags cannot validate a penalty value or nonphysical parameters."""
        x = np.asarray(x, dtype=float)
        if x.ndim != 1 or not np.all(np.isfinite(x)) or not np.isfinite(float(value)):
            return False
        if bounds is not None and len(x) != len(bounds):
            return False
        if bounds is not None and any(
            (lo is not None and v < lo - robust_optimizer._bound_tolerance(lo, hi)) or
            (hi is not None and v > hi + robust_optimizer._bound_tolerance(lo, hi))
            for v, (lo, hi) in zip(x, bounds)
        ):
            return False
        if any(abs(x[i] - v) > robust_optimizer._bound_tolerance(
            *(bounds[i] if bounds is not None else (v, None))) for i, v in (fixed_vals or [])):
            return False
        actual = float(np.asarray(func(x)).ravel()[0])
        return bool(np.isfinite(actual) and np.isclose(actual, value, rtol=1e-7, atol=1e-7))

    @staticmethod
    def _migrad(func, x0, bounds, fixed_vals, gradient=None):
        try:
            from iminuit import Minuit
        except ImportError as exc:
            raise RuntimeError(f"robust_optimizer needs iminuit for its fallback ({exc}) -- "
                               "pip install pyhf[minuit] in the 'rivet' env") from exc
        import scipy.optimize as so
        x0 = np.asarray(x0, dtype=float).copy()
        fixed_vals = list(fixed_vals or [])
        for i, v in fixed_vals:
            x0[i] = v

        def f(*z):
            v = float(np.asarray(func(np.asarray(z, dtype=float))).ravel()[0])
            return v if np.isfinite(v) else 1e10  # the NaN guard: MIGRAD backs off the cliff

        def grad(*z):
            x = np.asarray(z, dtype=float)
            g = np.asarray(gradient(x), dtype=float)
            # The penalty plateau has no useful derivative. A final point on it
            # still fails the original-objective/gradient checks below.
            if not np.isfinite(float(np.asarray(func(x)).ravel()[0])) or not np.all(np.isfinite(g)):
                return np.zeros_like(x)
            return g

        m = Minuit(f, *x0, **({"grad": grad} if gradient is not None else {}))
        if bounds is not None:
            for i, b in enumerate(bounds):
                m.limits[i] = b
        for i, _v in fixed_vals:
            m.fixed[i] = True
        m.errordef = 1.0  # func is -2lnL
        # Analytic derivatives avoid repeated numerical derivative checks. A
        # Minuit valid flag alone does not satisfy the shared stationarity guard.
        stationary = False
        for strategy, tolerance in ([(0, 1e-5), (1, 1e-7), (2, 1e-9)] if gradient is not None
                                    else [(1, .1), (2, .1)]):
            m.strategy, m.tol = strategy, tolerance
            m.migrad(ncall=200000)
            stationary = gradient is None or robust_optimizer.projected_gradient(
                np.asarray(m.values), gradient(np.asarray(m.values)), bounds, fixed_vals) <= 1e-3
            if m.valid and stationary:
                break
        if not m.valid or not stationary:
            raise RuntimeError("robust_optimizer: guarded MIGRAD found no valid stationary minimum "
                               f"(fval={m.fval}, edm={m.fmin.edm}) -- refusing to report a limit "
                               "from an unconverged fit")
        if not robust_optimizer._valid_result(m.values, m.fval, func, bounds, fixed_vals):
            raise RuntimeError("robust_optimizer: MIGRAD minimum fails original-objective, "
                                 "finite-parameter or bound validation; refusing to report a limit")
        if gradient is not None and not np.all(np.isfinite(np.asarray(gradient(np.asarray(m.values))))):
            raise RuntimeError("robust_optimizer: MIGRAD minimum has a nonfinite analytic gradient")
        return so.OptimizeResult(x=np.asarray(m.values, dtype=float), fun=float(m.fval),
                                 success=True, message="migrad-fallback ok", nfev=m.nfcn)


pyhf.set_backend("numpy", robust_optimizer(maxiter=200000))


def profile_fit_consistency(model, data, fits, tolerance=1e-5):
    """Check objective nesting, including the exactly known Asimov generating fit.

    These are necessary numerical conditions, not global-optimum or coverage proofs.
    A successful optimizer flag cannot make a worse unrestricted fit acceptable.
    """
    asimov_data = model.expected_data(fits.asimov_pars)

    def nll(parameters, observations):
        value = float(np.asarray(pyhf.infer.mle.twice_nll(parameters, observations, model)).ravel()[0])
        if not np.isfinite(value):
            raise RuntimeError("nonfinite objective in profile-fit consistency check")
        return value

    values = {
        "free_data": nll(fits.free_fit_to_data, data),
        "fixed_data": nll(fits.fixed_poi_fit_to_data, data),
        "mu0_data": nll(fits.asimov_pars, data),
        "free_asimov": nll(fits.free_fit_to_asimov, asimov_data),
        "fixed_asimov": nll(fits.fixed_poi_fit_to_asimov, asimov_data),
        "generating_asimov": nll(fits.asimov_pars, asimov_data),
    }
    issues = []
    if values["free_data"] > min(values["fixed_data"], values["mu0_data"]) + tolerance:
        issues.append("unrestricted observed fit is worse than a constrained fit")
    if abs(values["free_asimov"] - values["generating_asimov"]) > tolerance:
        issues.append("unrestricted Asimov fit disagrees with the generating optimum")
    if values["fixed_asimov"] < values["generating_asimov"] - tolerance:
        issues.append("constrained Asimov fit is below its generating optimum")
    return {"passed": not issues, "twice_nll": values, "absolute_tolerance": tolerance,
            "issues": issues, "global_optimum_proven": False}


# --------------------------------------------------------------------------- #
# model builders
# --------------------------------------------------------------------------- #
# HistFactory-standard interpolation (ROOT parity) for every likelihood-mode model.
MODIFIER_SETTINGS = {
    "normsys": {"interpcode": "code4"},
    "histosys": {"interpcode": "code4p"},
}


def _number(value, name, *, positive=False):
    """Counting observations may be fractional Asimov counts, but never strings or booleans."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not np.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def _counting_inputs(sr):
    if not isinstance(sr, dict):
        raise ValueError("each counting SR must be an object with n, b, db, s")
    values = {key: _number(sr.get(key), key) for key in ("n", "b", "db", "s")}
    # pyhf shapesys disables its nuisance when b=0. A positive quoted db would be lost.
    if values["b"] == 0 and values["db"] > 0:
        raise ValueError("db > 0 with zero background cannot be represented by shapesys; "
                         "supply a likelihood with an appropriate background constraint")
    return values


def _read_json(path):
    """Reject ambiguous keys and nonfinite constants before model construction."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    with open(path) as stream:
        result = json.load(stream, object_pairs_hook=pairs)

    def check(value):
        if isinstance(value, float) and not np.isfinite(value):
            raise ValueError(f"nonfinite JSON number in {path}")
        if isinstance(value, dict):
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(result)
    return result


def scale_result(result, factor):
    """Change signal-strength units consistently in limits, curves and per-SR records."""
    factor = _number(factor, "sigma_scale", positive=True)
    if factor == 1:
        return
    result["sigma_scale_k"] = factor
    result["obs_limit_lo"] = result["obs_limit"]
    result["exp_limits_lo"] = list(result["exp_limits"])
    rescale_artifact(result, 1.0 / factor)
    result["scan_mu"] = [value / factor for value in result["scan_mu"]]
    for record in result.get("per_sr", {}).values():
        if "obs_limit" in record:
            rescale_artifact(record, 1.0 / factor)
        if "s" in record:
            record["s_lo"] = record["s"]
            record["s"] *= factor
    if "inference" in result:
        result["inference"]["root_atol"] /= factor
    if "fit_diagnostics" in result:
        result["fit_diagnostics"]["signal_strength_units"] = "original supplied-model units (before sigma_scale_k)"


def model_from_likelihood(bkg_path, patch_path):
    """Background-only workspace + signal JSON-Patch -> (model, data)."""
    import jsonpatch
    bkg = _read_json(bkg_path)
    patch = _read_json(patch_path)
    spec = jsonpatch.apply_patch(bkg, patch)
    ws = pyhf.Workspace(spec)
    model = ws.model(modifier_settings=MODIFIER_SETTINGS)
    data = ws.data(model)
    return model, data


def model_from_counting(sr):
    """One SR's (n,b,db,s) -> (model, data) single-bin counting experiment."""
    sr = _counting_inputs(sr)
    model = pyhf.simplemodels.uncorrelated_background(
        signal=[float(sr["s"])], bkg=[float(sr["b"])], bkg_uncertainty=[float(sr["db"])]
    )
    data = [float(sr["n"])] + model.config.auxdata
    return model, data


def model_from_counting_combined(srs):
    """All SRs -> ONE multi-channel counting model (statistical combination).

    An N-bin uncorrelated_background model is exactly N independent single-bin
    channels (independent Poissons + independent constraints) fit simultaneously
    -- valid only when the SRs are mutually EXCLUSIVE (e.g. by lepton count).
    Published correlations are not available for a counting input, so background
    constraints are taken uncorrelated; document this with the result.
    """
    if not isinstance(srs, list) or not srs:
        raise ValueError("combined counting needs a nonempty list of SRs")
    srs = [_counting_inputs(sr) for sr in srs]
    model = pyhf.simplemodels.uncorrelated_background(
        signal=[float(sr["s"]) for sr in srs],
        bkg=[float(sr["b"]) for sr in srs],
        bkg_uncertainty=[sr["db"] for sr in srs],
    )
    data = [float(sr["n"]) for sr in srs] + model.config.auxdata
    return model, data


def low_count_flags(sr):
    """Where asymptotic qtilde calibration needs scrutiny (shapesys is Poisson-constrained)."""
    flags = []
    if float(sr["b"]) < 5:
        flags.append("b<5")
    if float(sr["b"]) > 0 and float(sr["db"]) / float(sr["b"]) > 0.5:
        flags.append("db/b>0.5")
    if float(sr["n"]) < 5:
        flags.append("n<5")
    return flags


# --------------------------------------------------------------------------- #
# limit + scan
# --------------------------------------------------------------------------- #
def _cross(mu, cls, level=0.05):
    """First mu where the (decreasing) CLs curve crosses `level`, by linear interp."""
    mu = np.asarray(mu, float)
    cls = np.asarray(cls, float)
    for i in range(len(mu) - 1):
        if (cls[i] - level) * (cls[i + 1] - level) <= 0 and cls[i] != cls[i + 1]:
            f = (cls[i] - level) / (cls[i] - cls[i + 1])
            return float(mu[i] + f * (mu[i + 1] - mu[i]))
    # No crossing anywhere in the scan: the two ends mean OPPOSITE things.
    if cls[0] <= level:
        return float(mu[0])   # whole curve below level (hyper-excluded): the lowest scanned mu
                              # is an upper BOUND on the limit, not a limit (at_mu_floor flags it)
    return float(mu[-1])      # whole curve above level: report the ceiling (at_poi_cap flags it)


def compute(model, data, level=0.05, n_curve=11, poi_cap=128.0, *, root_rtol=1e-4,
            diagnostic_record=None, profile_witness_record=None, profile_witness_context=None,
            profile_witness_max_evaluations=5000, profile_witness_max_minimizations=50000,
            profile_witness_max_bytes=256 * 1024 * 1024, profile_witness_journal=None,
            profile_witness_limits=None):
    """Compute limits with scoped recovery and optional retained failure diagnostics.

    Passing a mutable profile_witness_record explicitly enables fitted vectors,
    model-local adaptive seed traces and root checks. profile_witness_limits maps
    evaluations/minimizations/bytes to positive ceilings; exhaustion raises and
    leaves an explicitly incomplete record. Minimizations count candidate seeds,
    not internal SLSQP/MIGRAD strategy passes. Optional caller context binds input
    receipts; a journal path writes exclusive, flushed hash-chain JSONL events so
    a hard-killed job retains running/partial evidence. Error text may be bounded
    with explicit truncation, original length and digest. Numerical defaults and
    starts are unchanged. This evidence does not certify a global optimum.
    """
    _, optimizer = pyhf.get_backend()
    record = {} if diagnostic_record is None else diagnostic_record
    record.update(status="running", evaluations=[])
    started = time.monotonic()
    witness = None
    try:
        if profile_witness_record is not None:
            limits = profile_witness_limits or {}
            if set(limits) - {"evaluations", "minimizations", "bytes"}:
                raise ValueError("unknown profile witness budget")
            witness = _ProfileWitnessRecorder(profile_witness_record,
                max_evaluations=limits.get("evaluations", profile_witness_max_evaluations),
                max_minimizations=limits.get("minimizations", profile_witness_max_minimizations),
                max_bytes=limits.get("bytes", profile_witness_max_bytes), journal_path=profile_witness_journal)
        elif profile_witness_journal is not None:
            raise ValueError("profile_witness_journal requires profile_witness_record")
        result = _compute(model, data, level, n_curve, poi_cap, root_rtol=root_rtol,
                          diagnostic_record=record, profile_witness=witness,
                          profile_witness_context=profile_witness_context)
        from ravel.validation import regression_triggers
        result['computed_checks'] = regression_triggers.consume_flags(result)
        result['computed_check_summary'] = regression_triggers.summary(result['computed_checks'])
        result['coverage'] = {'status': 'not_evaluated', 'general_likelihood_coverage_validated': False,
                              'scope': 'asymptotic qtilde on supplied likelihood'}
        record["status"] = "succeeded"
        if witness is not None:
            witness.finish("succeeded")
        return result
    except BaseException as exc:
        record.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        if witness is not None:
            witness.finish("failed", exc)
        raise
    finally:
        record["wall_seconds"] = time.monotonic() - started
        if isinstance(optimizer, robust_optimizer):
            record["rejected_candidates_last_100"] = list(optimizer.profile_rejected_candidates)
            record["profile_start_trials"] = optimizer.profile_trials
            record["profile_improvements"] = optimizer.profile_improvements
            optimizer._profile_enabled = False
            optimizer._profile_frozen = False
            optimizer._profile_pool = []
            optimizer._witness = None
            optimizer._witness_evaluation = None


def _compute(model, data, level=0.05, n_curve=11, poi_cap=128.0, *, root_rtol=1e-4,
             diagnostic_record=None, profile_witness=None, profile_witness_context=None):
    """Observed+expected 95% CL UL on mu plus a CLs-vs-mu curve, sharing ONE scan.

    Shared CLs evaluations bracket all six curves; Brent root refinement gives
    numerical precision independent of the plotting grid. This controls numerical
    inversion error, not the coverage of the asymptotic qtilde approximation.
    Unresolved endpoints retain their historical numeric bounds, with per-curve
    status. Nonfinite points may only be omitted below every crossing bracket.
    """
    bounds = model.config.suggested_bounds()
    poi_idx = model.config.poi_index
    level = _number(level, "level", positive=True)
    if level >= 1:
        raise ValueError("level must be between zero and one")
    poi_cap = _number(poi_cap, "poi_cap", positive=True)
    root_rtol = _number(root_rtol, "root_rtol", positive=True)
    if root_rtol < 4 * np.finfo(float).eps or root_rtol >= 1:
        raise ValueError("root_rtol must be between 4*machine-epsilon and one")
    if type(n_curve) is not int or n_curve < 2:
        raise ValueError("n_curve must be an integer >= 2")
    if poi_idx is None or model.config.suggested_fixed()[poi_idx]:
        raise ValueError("limit inference needs an unfixed parameter of interest")
    raw_data = np.asarray(data)
    if raw_data.dtype.kind not in "iuf":
        raise ValueError("data must contain numeric counts and auxiliary observations")
    data = np.asarray(data, dtype=float)
    if data.ndim != 1 or len(data) != model.config.nmaindata + model.config.nauxdata:
        raise ValueError("data shape does not match the model")
    # Gaussian auxiliary observations can be negative; Poisson main counts cannot.
    if not np.all(np.isfinite(data)) or np.any(data[:model.config.nmaindata] < 0):
        raise ValueError("data must be finite with nonnegative observed main-bin counts")
    offset = model.config.nmaindata
    for name in model.config.auxdata_order:
        parameter_set = model.config.param_set(name)
        auxiliary = data[offset:offset + parameter_set.n_parameters]
        if parameter_set.pdf_type == "poisson" and np.any(auxiliary < 0):
            raise ValueError(f"Poisson auxiliary counts for {name} must be nonnegative")
        offset += parameter_set.n_parameters
    # optimizer-guard provenance: snapshot the robust_optimizer counters so the
    # result can report how many minimizations in THIS computation needed the fallback.
    # Escalation is a property of one model's surface, so it is scoped per compute():
    # a NaN-pocketed SR must not tax later clean models in the same process.
    tensor_backend, optimizer = pyhf.get_backend()
    if not isinstance(optimizer, robust_optimizer):
        raise ValueError("compute requires robust_optimizer for profile validation; configure it explicitly")
    optimizer.begin_model()
    diagnostic_record.update(
        model_sha256=hashlib.sha256(json.dumps(model.spec, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        data_sha256=hashlib.sha256(json.dumps(data.tolist(),
            separators=(",", ":"), allow_nan=False).encode()).hexdigest())
    if profile_witness is not None:
        protocol = {"method": "asymptotic CLs", "test_stat": "qtilde", "level": level,
                    "n_curve": n_curve, "poi_cap": poi_cap, "root_rtol": root_rtol,
                    "root_atol": 1e-10, "root_maxiter": 100, "root_cls_atol": 5e-4,
                    "poi_fit_bounds_rule": "[0, max(1.5 * tested_mu, 2.0)]",
                    "nesting_atol": 1e-5, "nesting_attempts": 3, "profile_passes": 3,
                    "fresh_cls_atol": 1e-5, "analytic_projected_gradient_atol": 1e-3,
                    "profile_start_rule": PROFILE_START_RULE,
                    "backend": tensor_backend.name, "precision": tensor_backend.precision,
                    "fit_tolerance": getattr(optimizer, "tolerance", None),
                    "optimizer_maxiter": getattr(optimizer, "maxiter", None),
                    "migrad_policy": {"scalar_strategy_tolerance": [[1, .1], [2, .1]],
                        "analytic_strategy_tolerance": [[0, 1e-5], [1, 1e-7], [2, 1e-9]],
                        "ncall_per_strategy": 200000, "errordef": 1.0,
                        "nonfinite_objective_penalty": 1e10,
                        "acceptance": "valid flag, original objective/bounds/fixed validation, analytic projected gradient <= 0.001"},
                    "modifier_settings": model.config.modifier_settings}
        profile_witness.update("metadata", None, model_spec=model.spec, data=data,
            parameter_names=model.config.par_names, parameter_order=model.config.par_order,
            parameter_slices={name: [entry["slice"].start, entry["slice"].stop]
                              for name, entry in model.config.par_map.items()},
            channel_order=model.config.channels, channel_nbins=model.config.channel_nbins,
            poi_index=poi_idx, bounds=bounds, suggested_fixed=model.config.suggested_fixed(),
            nominal_parameters=model.config.suggested_init(),
            nmaindata=model.config.nmaindata, nauxdata=model.config.nauxdata,
            auxdata_order=model.config.auxdata_order,
            model_sha256=diagnostic_record["model_sha256"], data_sha256=diagnostic_record["data_sha256"],
            protocol=protocol, protocol_sha256=hashlib.sha256(_canonical(protocol)).hexdigest(),
            source_context=profile_witness_context or {}, engine_source=_source_identity(sys.modules[__name__]),
            pyhf_version=pyhf.__version__, pyhf_source=_source_identity(pyhf),
            backend_source=_source_identity(type(tensor_backend)),
            calculator_source=_source_identity(pyhf.infer.calculators),
            mle_source=_source_identity(pyhf.infer.mle),
            test_statistics_source=_source_identity(pyhf.infer.test_statistics),
            optimizer_source=_source_identity(scipy_optimizer),
            covariance=None, global_optimum_proven=False, coverage_validated=False)
        optimizer._witness = profile_witness
    opt0 = (robust_optimizer.n_fits, robust_optimizer.n_fallback,
            robust_optimizer.n_nan_flagged, robust_optimizer.n_escalated)
    robust_optimizer.escalated = False

    def par_bounds(hi):
        b = [list(x) for x in bounds]
        b[poi_idx] = [0.0, float(hi)]
        return b

    cache = {}
    stage = {"phase": "bracket_up"}
    fit_diagnostics = {"available": False, "reason": "calculator supplied no fit diagnostics",
                       "covariance": None, "nuisance_pull_uncertainties": None}

    def evaluate(mu):
        try:
            return _evaluate(mu)
        except BaseException as exc:
            if profile_witness is not None and not isinstance(exc, ProfileWitnessBudgetError):
                index = optimizer._witness_evaluation
                if index is not None:
                    profile_witness.update("evaluations", index, status="failed",
                        error={"type": type(exc).__name__, "message": str(exc)})
            raise

    def _evaluate(mu):
        nonlocal fit_diagnostics
        fit_bounds = par_bounds(max(mu * 1.5, 2.0))
        consistency = None
        for attempt in range(3):
            diagnostic = {"mu": float(mu), "attempt": attempt + 1, "status": "running"}
            diagnostic_record["evaluations"].append(diagnostic)
            evaluation_index = None
            if profile_witness is not None:
                evaluation_index = len(profile_witness.record["evaluations"])
                profile_witness.start("evaluations", **diagnostic, stage=dict(stage), fit_bounds=fit_bounds,
                                      minimization_begin=len(profile_witness.record["minimizations"]))
                optimizer._witness_evaluation = evaluation_index
            try:
                returned = hypotest(mu, data, model, par_bounds=fit_bounds, test_stat="qtilde",
                                    return_expected_set=True, return_calculator=True)
            except BaseException as exc:
                diagnostic.update(status="failed", error=str(exc))
                if profile_witness is not None and not isinstance(exc, ProfileWitnessBudgetError):
                    profile_witness.update("evaluations", evaluation_index, status="failed",
                        error={"type": type(exc).__name__, "message": str(exc)})
                raise
            observed, expected = returned[:2]
            diagnostic.update(status="evaluated", cls=[float(v) if np.isfinite(float(v)) else None
                for v in [observed, *expected]])
            calculator = returned[2] if len(returned) == 3 else None
            fits = getattr(calculator, "fitted_pars", None)
            if fits is None:
                if profile_witness is not None:
                    profile_witness.update("evaluations", evaluation_index, status="failed",
                                          error={"type": "RuntimeError", "message": "calculator fitted_pars unavailable"})
                    raise RuntimeError("retained profile witnesses require calculator fitted_pars")
                break
            if profile_witness is not None:
                vectors = {name: np.asarray(getattr(fits, name), dtype=float) for name in (
                    "asimov_pars", "free_fit_to_data", "fixed_poi_fit_to_data",
                    "free_fit_to_asimov", "fixed_poi_fit_to_asimov")}
                profile_witness.update("evaluations", evaluation_index, fitted_parameters=vectors,
                    asimov_data=np.asarray(model.expected_data(fits.asimov_pars), dtype=float),
                    cls=[float(observed), *map(float, expected)], status="evaluated",
                    minimization_end=len(profile_witness.record["minimizations"]))
            consistency = profile_fit_consistency(model, data, fits)
            diagnostic["profile_consistency"] = consistency
            if profile_witness is not None:
                profile_witness.update("evaluations", evaluation_index, profile_consistency=consistency,
                                      status="succeeded" if consistency["passed"] else "nesting_failed")
            if consistency["passed"]:
                break
            if attempt == 2:
                raise RuntimeError("profile-fit nesting failed: " + "; ".join(consistency["issues"]))
        if fits is not None:
            pars = np.asarray(fits.free_fit_to_data, dtype=float)
            fixed = model.config.suggested_fixed()
            parameters = []
            for i, (name, value, (lower, upper)) in enumerate(zip(model.config.par_names, pars, fit_bounds)):
                tolerance = 1e-5 * max(1.0, abs(upper - lower))
                parameters.append({"name": name, "value": float(value), "fixed": bool(fixed[i]),
                                   "bounds": [float(lower), float(upper)],
                                   "near_lower_bound": bool(value - lower <= tolerance),
                                   "near_upper_bound": bool(upper - value <= tolerance)})
            fit_diagnostics = {
                "available": True, "source": "pyhf AsymptoticCalculator free_fit_to_data",
                "reference_mu": float(mu), "twice_nll": float(pyhf.infer.mle.twice_nll(pars, data, model)[0]),
                "parameters": parameters, "covariance": None, "nuisance_pull_uncertainties": None,
                "unavailable_reason": "profile-error and covariance diagnostics were not computed",
                "signal_strength_units": "supplied-model units",
                "profile_consistency": consistency,
            }
        return observed, expected

    def checked_cls(o, e):
        values = np.asarray([float(o), *map(float, e)])
        if values.shape != (6,):
            raise RuntimeError("CLs result needs an observed value and five expected quantiles")
        finite = values[np.isfinite(values)]
        if np.any(finite < 0) or np.any(finite > 1):
            raise RuntimeError("CLs probabilities must lie in [0, 1]")
        if np.all(np.isfinite(values)) and np.any(np.diff(values[1:]) < -1e-6):
            raise RuntimeError("CLs expected quantiles are out of order")
        return float(values[0]), values[1:].tolist()

    def cls_at(mu):
        if mu not in cache:
            esc_before = robust_optimizer.escalated
            o, e = evaluate(mu)
            if robust_optimizer.escalated and not esc_before:
                # This hypotest just flipped escalation: the model's surface is NaN-pocketed,
                # so every CLs point computed BEFORE the flip mixed now-untrusted SLSQP minima
                # Recompute cached points and the
                # triggering point itself, whose pre-flip sub-fits are equally untrusted.
                stale = sorted(cache)
                cache.clear()
                if stale:
                    print(f"  note: optimizer escalated mid-scan -- recomputing {len(stale)} "
                          "earlier CLs point(s) with the guarded-MIGRAD path",
                          file=sys.stderr, flush=True)
                for m2 in stale:
                    original_stage = dict(stage)
                    stage.update(phase="escalation_recompute")
                    o2, e2 = evaluate(m2)
                    stage.clear(); stage.update(original_stage)
                    cache[m2] = checked_cls(o2, e2)
                    print(f"  [cls scan] recompute mu={m2:.6g} CLs_obs={cache[m2][0]:.4g}",
                          file=sys.stderr, flush=True)
                o, e = evaluate(mu)
            cache[mu] = checked_cls(o, e)  # obs, [-2,-1,med,+1,+2]sigma
            # heartbeat (stall-guard interop): one line per fresh hypotest so the redirected log's
            # mtime advances during the multi-minute CLs scan -- stage_supervisor.py's progress-stall
            # watchdog keys on log writes and killed silent-but-progressing pyhf fits at 12 min
            # (a pyhf.failure.json with reason 'progress-stall'). stderr: line-buffered under redirection, and kept out of stdout
            # parsing. Numerics untouched.
            print(f"  [cls scan] mu={mu:.6g} CLs_obs={cache[mu][0]:.4g} ({len(cache)} pts)",
                  file=sys.stderr, flush=True)
        return cache[mu]

    # bracket: double mu from 1 until BOTH the observed AND the +2sigma-EXPECTED CLs are < level.
    # The +2sigma expected limit is the largest of the five; bracketing on the observed alone leaves
    # the upper expected band pinned at the ceiling (the half-resolved-band bug). e=[-2,-1,med,+1,+2].
    hi = min(1.0, poi_cap)
    while True:
        o, e = cls_at(hi)
        if (o <= level and e[4] <= level) or hi == poi_cap:
            break
        hi = min(hi * 2.0, poi_cap)

    # bracket DOWN as well. On a hyper-excluded point CLs(mu=1) is already << level, the
    # upward loop exits immediately at hi=1.0, and the whole CLs curve sits below `level`: _cross
    # then has no low-side anchor and the reported "limit" is a scan-edge artifact (the fig3
    # m60_dm5/m70_dm5 dark-red diff-map cells). Halve mu until EVERY column rises above `level`
    # (observed + all five expected bands -- then every crossing is bracketed) or the floor is
    # hit (truly hyper-excluded: flagged at_mu_floor below, never reported as a limit).
    lo, mu_floor = min(1.0, hi), min(1e-6, hi / 1000)
    stage.clear(); stage.update(phase="bracket_down")
    while lo > mu_floor:
        o, e = cls_at(lo)
        if o > level and all(v > level for v in e):
            break
        lo = max(lo / 2.0, mu_floor)

    # shared scan over [~0, hi]; reuse the bracket points already in the cache. If the downward
    # bracket ran (lo < 1), add geometric points across the low decades so the interpolation near
    # a low crossing has resolution comparable to the linear grid near mu~1.
    base = set(np.linspace(min(1e-3, hi / 1000), hi, n_curve))
    if lo < min(1.0, hi):
        base |= set(np.geomspace(max(lo / 2.0, mu_floor / 10), min(1.0, hi), n_curve))
    scan = sorted(base.union(k for k in cache))
    stage.clear(); stage.update(phase="scan")
    for mu in scan:
        cls_at(mu)
    def validated_scan():
        ordered = sorted(cache)
        finite = [m for m in ordered if np.all(np.isfinite([cache[m][0], *cache[m][1]]))]
        if len(finite) < 2:
            raise RuntimeError("CLs scan has fewer than two finite points")
        omitted = [m for m in ordered if m not in finite]
        for m in omitted:
            # A numerical problem below a proven common low bracket cannot affect
            # any root. A hole inside or above that bracket cannot be interpolated away.
            if not any(m2 > m and min([cache[m2][0], *cache[m2][1]]) > level for m2 in finite):
                raise RuntimeError(f"nonfinite CLs at mu={m:g} intersects the inference range")
        values = np.asarray([[cache[m][0], *cache[m][1]] for m in finite])
        if np.any(np.diff(values, axis=0) > 1e-5):
            raise RuntimeError("CLs observed or expected curve is not monotonically decreasing")
        return finite, values, omitted

    from scipy.optimize import brentq

    def limits_from_scan():
        scan, values, omitted = validated_scan()
        limits, statuses, brackets = [], [], []
        for col in range(6):
            curve = values[:, col]
            if curve[0] < level:
                limits.append(float(scan[0]))
                statuses.append("below_scan")
                brackets.append([None, float(scan[0])])
                continue
            if curve[-1] > level:
                limits.append(float(scan[-1]))
                statuses.append("above_scan")
                brackets.append([float(scan[-1]), None])
                continue
            exact = np.flatnonzero(curve == level)
            if len(exact):
                a = b = float(scan[exact[0]])
                root = a
            else:
                i = next(i for i in range(len(scan) - 1) if curve[i] > level > curve[i + 1])
                a, b = float(scan[i]), float(scan[i + 1])

                def objective(mu):
                    stage.clear(); stage.update(phase="root", quantile_index=col,
                                                bracket=[a, b], profile_pass=profile_pass)
                    observed, expected = cls_at(float(mu))
                    value = [observed, *expected][col]
                    if not np.isfinite(value):
                        raise RuntimeError(f"nonfinite CLs inside root bracket at mu={mu:g}")
                    return value - level

                root = float(brentq(objective, a, b, xtol=1e-10, rtol=root_rtol, maxiter=100))
            limits.append(root)
            statuses.append("resolved")
            brackets.append([a, b])
        return limits, statuses, brackets

    refresh_evaluations = 0

    def refresh(points, *, reverse=True):
        nonlocal refresh_evaluations
        changed = False
        escalation_before = robust_optimizer.escalated
        # Reverse order checks the continuation history used during root finding.
        # It never sorts or smooths CLs values, or accepts the first root on failure.
        for mu in sorted(set(points), reverse=reverse):
            stage.clear(); stage.update(phase="fresh_check" if optimizer._profile_frozen else "repair",
                order="descending" if reverse else "ascending", profile_pass=profile_pass,
                frozen_pool_index=(len(profile_witness.record["frozen_pools"])-1
                                   if profile_witness is not None and optimizer._profile_frozen else None),
                quantile_indices=[i for i, value in enumerate(limits) if value == mu]
                                 if optimizer._profile_frozen else [])
            previous = np.asarray([cache[mu][0], *cache[mu][1]])
            cache[mu] = checked_cls(*evaluate(mu))
            current = np.asarray([cache[mu][0], *cache[mu][1]])
            changed |= not np.allclose(previous, current, rtol=0, atol=1e-5, equal_nan=True)
            refresh_evaluations += 1
            print(f"  [cls check] mu={mu:.6g} CLs_obs={cache[mu][0]:.4g}", file=sys.stderr, flush=True)
        return changed or robust_optimizer.escalated != escalation_before

    for profile_pass in range(3):
        try:
            escalated_before_roots = robust_optimizer.escalated
            limits, statuses, brackets = limits_from_scan()
            if robust_optimizer.escalated and not escalated_before_roots:
                limits, statuses, brackets = limits_from_scan()
        except RuntimeError as exc:
            if "monotonically" not in str(exc) or profile_pass == 2:
                raise
            refresh(list(cache))
            continue
        checks = {min(cache), max(cache), *limits}
        # Every final check uses the SAME start set. Late discoveries must not
        # change the context after a root was checked. Both orders also detect
        # repeat-evaluation drift before the bounded repair loop can accept.
        optimizer._profile_frozen = True
        try:
            if profile_witness is not None:
                pool = [np.asarray(seed, dtype=float).tolist() for seed in optimizer._profile_pool]
                profile_witness.start("frozen_pools", profile_pass=profile_pass, parameters=pool,
                    sha256=hashlib.sha256(_canonical(pool)).hexdigest(), check_points=sorted(checks),
                    start_rule=PROFILE_START_RULE)
                profile_witness.start("root_passes", profile_pass=profile_pass, limits=limits,
                    statuses=statuses, brackets=brackets,
                    bracket_cls=[[None if edge is None else [cache[edge][0], *cache[edge][1]]
                                  for edge in bracket] for bracket in brackets],
                    bracket_objectives=[[None if edge is None else
                        [value-level for value in [cache[edge][0], *cache[edge][1]]]
                        for edge in bracket] for bracket in brackets])
            changed = refresh(checks)
            changed = refresh(checks, reverse=False) or changed
        finally:
            optimizer._profile_frozen = False
        root_errors = [abs([cache[value][0], *cache[value][1]][index] - level)
                       for index, (value, status) in enumerate(zip(limits, statuses))
                       if status == "resolved"]
        if profile_witness is not None:
            profile_witness.update("root_passes", len(profile_witness.record["root_passes"])-1,
                fresh_check_changed=bool(changed), root_cls_errors=root_errors,
                checked_cls=[[cache[value][0], *cache[value][1]] for value in limits])
        try:
            scan, values, omitted = validated_scan()
        except RuntimeError as exc:
            if "monotonically" not in str(exc) or profile_pass == 2:
                raise
            changed = True
        if not changed and all(error <= 5e-4 for error in root_errors):
            break
        if profile_pass == 2:
            raise RuntimeError("CLs profile/root checks remain unstable after bounded refitting")
        refresh(list(cache))
    else:
        raise RuntimeError("CLs profile/root checks did not resolve")
    obs = values[:, 0].tolist()
    exp = values[:, 1:].tolist()
    obs_limit, exp_limits = limits[0], limits[1:]
    at_cap = statuses[0] == "above_scan"
    median_at_cap = statuses[3] == "above_scan"
    at_floor = "below_scan" in statuses
    band_degenerate = bool(exp_limits[4] / max(exp_limits[0], 1e-12) < 1.5)
    for name, status in zip(["observed", "expected -2sigma", "expected -1sigma",
                             "expected median", "expected +1sigma", "expected +2sigma"], statuses):
        if status != "resolved":
            print(f"  WARNING: {name} limit is {status}; reported value is a scan bound",
                  file=sys.stderr)

    return attach_limits({
        "obs_limit": obs_limit,
        "exp_limits": exp_limits,  # [-2,-1,med,+1,+2] sigma
        "scan_mu": [float(m) for m in scan],
        "scan_cls_obs": obs,
        "scan_cls_exp": exp,
        "n_fits": len(cache),
        "at_poi_cap": at_cap,          # observed limit itself is the scan ceiling
        "median_at_cap": median_at_cap,  # the median limit itself is the scan ceiling
        "at_mu_floor": at_floor,
        "band_degenerate": band_degenerate,  # expected band unusable, quote as bound only
        "cls_monotonic": True,
        "limit_status": {"observed": statuses[0], "expected": statuses[1:]},
        "limit_brackets": {"observed": brackets[0], "expected": brackets[1:]},
        "fit_diagnostics": fit_diagnostics,
        "inference": {"method": "asymptotic CLs", "test_stat": "qtilde", "level": level,
                      "root_solver": "scipy.brentq", "root_rtol": root_rtol,
                      "root_atol": 1e-10, "omitted_low_mu_nonfinite": omitted,
                      "root_cls_atol": 5e-4, "root_cls_max_error": max(root_errors, default=None),
                      "profile_passes": profile_pass + 1, "fresh_check_evaluations": refresh_evaluations,
                      "fresh_check_context": "frozen start portfolio, descending then ascending root/bound checks",
                      "backend": tensor_backend.name, "precision": tensor_backend.precision,
                      "fit_tolerance": getattr(optimizer, "tolerance", None),
                      "model_sha256": hashlib.sha256(json.dumps(model.spec, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                      "data_sha256": hashlib.sha256(json.dumps(data.tolist(),
                          separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                      "coverage_validated": False,
                      "scope": "statistical inversion of the supplied model; no acceptance certification"},
        "optimizer": {  # provenance: which fits needed the guarded-MIGRAD fallback
            "primary": "scipy.SLSQP",
            "fallback": "iminuit.MIGRAD nan-guarded",
            "escalated": bool(robust_optimizer.escalated),
            "n_minimizations": robust_optimizer.n_fits - opt0[0],
            "n_fallback": robust_optimizer.n_fallback - opt0[1],
            "n_nan_flagged": robust_optimizer.n_nan_flagged - opt0[2],
            "n_escalated": robust_optimizer.n_escalated - opt0[3],
            "profile_start_trials": getattr(optimizer, "profile_trials", None),
            "profile_improvements": getattr(optimizer, "profile_improvements", None),
            "profile_max_nll_improvement": getattr(optimizer, "profile_max_improvement", None),
            "profile_invalid_trial_evaluations": getattr(optimizer, "profile_invalid_trials", None),
            "profile_recovered_transients": getattr(optimizer, "profile_recovered_transients", None),
            "rejected_candidates_last_100": getattr(optimizer, "profile_rejected_candidates", None),
            "analytic_projected_gradient_atol": 1e-3,
            "analytic_acceptance": "finite original objective and projected gradient; multistart, nesting and fresh-root checks",
            "profile_search": "nominal start plus two best distinct retained starts scored on each current objective",
            "global_optimum_proven": False,
        },
    }, source="pyhf")


def plot(res, out_png, title, sr_label=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mu = np.array(res["scan_mu"])
    obs = np.array(res["scan_cls_obs"])
    exp = np.array(res["scan_cls_exp"])  # (N,5)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.fill_between(mu, exp[:, 0], exp[:, 4], color="gold", alpha=0.5, label=r"expected $\pm2\sigma$")
    ax.fill_between(mu, exp[:, 1], exp[:, 3], color="limegreen", alpha=0.6, label=r"expected $\pm1\sigma$")
    ax.plot(mu, exp[:, 2], "k--", lw=1.4, label="expected median")
    ax.plot(mu, obs, "ko-", ms=3, lw=1.6, label="observed")
    ax.axhline(0.05, color="red", lw=1.3, label=r"95% CL ($\mathrm{CL}_s=0.05$)")
    obs_curve = read_limits(res).observed
    relation = {"resolved": "=", "below_scan": "<", "above_scan": ">"}.get(obs_curve.status, "\\sim")
    qualifier = "" if obs_curve.status == "resolved" else f" ({obs_curve.status}; bound/report only)"
    ax.axvline(res["obs_limit"], color="navy", ls=":", lw=1.4,
               label=rf"$\mu^{{95}}_{{obs}}{relation}{res['obs_limit']:.2f}$" + qualifier)
    ax.set_xlabel(r"signal strength $\mu$")
    ax.set_ylabel(r"$\mathrm{CL}_s$")
    ax.set_ylim(0, 1.05)
    # zoom the x-axis around the crossing when the limit is small vs the scan range
    obs_lim = res["obs_limit"]
    xhi = mu.max() if obs_lim >= 0.4 * mu.max() else max(1.0, 2.5 * obs_lim)
    ax.set_xlim(0, xhi)
    sub = f"\n(most-sensitive SR: {sr_label})" if sr_label else ""
    ax.set_title(title + sub, fontsize=10)
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)
    print(f"  wrote {out_png}")


# --------------------------------------------------------------------------- #
def _nanpocket_model():
    """Synthetic likelihood-mode workspace whose -2lnL surface has NaN pockets.

    Each histosys nuisance's 'lo' template drives every bin NEGATIVE (code4p
    extrapolates linearly beyond |alpha|=1, so alpha pulled low -> negative
    Poisson rates -> NaN), and the synthetic data sit below nominal so the fit
    approaches the invalid-rate domain.
    """
    nominal = [40.0, 30.0, 20.0]
    mods = [{"name": f"np{k}", "type": "histosys",
             "data": {"hi_data": [v * 1.10 for v in nominal],
                      "lo_data": [v * -1.5 for v in nominal]}}
            for k in range(6)]
    spec = {"channels": [{"name": "SR", "samples": [
        {"name": "signal", "data": [18.0, 15.0, 12.0],
         "modifiers": [{"name": "mu", "type": "normfactor", "data": None}]},
        {"name": "bkg", "data": list(nominal), "modifiers": mods},
    ]}]}
    model = pyhf.Model(spec, poi_name="mu", modifier_settings=MODIFIER_SETTINGS)
    data = [20.0, 14.0, 9.0] + model.config.auxdata
    return model, data


class MissingReferenceInput(ValueError):
    """A numerical reference must be explicitly supplied by the caller."""
    reason = "missing_reference_input"


def check_fit_reference(reference=None):
    """Fit supplied likelihood inputs and compare supplied numerical references.

    This is a numerical comparison, with no installation or physics authority.
    All tolerances and reference values belong to the selected input.
    """
    required = {"background", "patch", "expected", "output_format"}
    if not isinstance(reference, dict) or not required <= reference.keys():
        raise MissingReferenceInput("background, patch, expected and output_format required")
    if reference["output_format"] not in ("json", "jsonl"):
        raise ValueError("reference output_format must be json or jsonl")
    expected = reference["expected"]
    if not isinstance(expected, dict) or set(expected) != {"mu_hat", "twice_nll"}:
        raise MissingReferenceInput("explicit mu_hat and twice_nll comparisons required")
    for name, rule in expected.items():
        if not isinstance(rule, dict) or set(rule) != {"value", "atol", "rtol"}:
            raise MissingReferenceInput("value, atol and rtol required for " + name)
        for key, value in rule.items():
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)) or not np.isfinite(value):
                raise ValueError("finite numerical reference values and tolerances required")
            if key != "value" and value < 0:
                raise ValueError("nonnegative comparison tolerances required")
    for key in ("background", "patch"):
        if not isinstance(reference[key], (str, Path)) or not Path(reference[key]).is_file():
            raise MissingReferenceInput("selected " + key + " file required")
    # Capture identity before fitting and refuse changed source bytes afterwards.
    paths = [Path(reference[key]) for key in ("background", "patch")]
    pins = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    # The reference comparison uses this engine's guarded NumPy optimizer.
    # Other in-process clients can replace pyhf's global optimizer after this
    # module was imported; the default SLSQP can report success at the initial
    # point on constrained models. Scope the policy to this call and restore
    # the caller's backend, precision and optimizer even on a failed fit.
    previous_backend = pyhf.get_backend()
    try:
        pyhf.set_backend("numpy", robust_optimizer(maxiter=200000), precision="64b")
        model, data = model_from_likelihood(*paths)
        robust_optimizer.escalated = False
        pars, nll = pyhf.infer.mle.fit(data, model, return_fitted_val=True)
        actual = {"mu_hat": float(pars[model.config.poi_index]), "twice_nll": float(nll)}
    finally:
        pyhf.set_backend(*previous_backend)
    if pins != [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]:
        raise ValueError("selected reference input changed during fit")
    checks = {name: bool(np.isfinite(value) and abs(value - expected[name]["value"])
                        <= expected[name]["atol"] + expected[name]["rtol"] * abs(expected[name]["value"]))
              for name, value in actual.items()}
    result = {"schema_version": 1, "status": "passed" if all(checks.values()) else "failed",
              "actual": actual, "expected": expected, "checks": checks,
              "inputs": [{"path": str(path), "sha256": pin} for path, pin in zip(paths, pins)],
              "context": reference.get("context", {}), "output_format": reference["output_format"]}
    result["rendered"] = json.dumps(result, indent=2 if reference["output_format"] == "json" else None,
                                    allow_nan=False) + "\n"
    return result


def _retained_freefit_selftest(reference=None):
    """Compatibility seam: there is no installed reference selection."""
    return check_fit_reference(reference)


def selftest():
    """Synthetic counting regimes, numerical bounds and optimizer failure controls.

    Source likelihood comparisons use check_fit_reference with supplied inputs.
    """
    cases = [
        # a healthy crossing must NOT carry the cap/degeneracy flags; the
        # unconstrained regime's median sits at the scan ceiling -> median_at_cap,
        # and its five cap-pinned quantiles are a degenerate band.
        ("normal", dict(name="SR", n=5, b=5.0, db=1.0, s=8.0),
         lambda r: not r["at_mu_floor"] and not r["at_poi_cap"] and 0.05 < r["obs_limit"] < 5.0
                   and not r.get("median_at_cap", True) and not r.get("band_degenerate", True)),
        ("hyper-excluded", dict(name="SR", n=5, b=5.0, db=1.0, s=2.0e4),
         lambda r: r["obs_limit"] < 5e-3 and not r["at_mu_floor"]
                   and r["obs_limit"] != 1.0 and len(set(r["exp_limits"])) > 1),
        ("unconstrained", dict(name="SR", n=5, b=5.0, db=1.0, s=1e-4),
         lambda r: r["at_poi_cap"] and r.get("median_at_cap", False)
                   and r.get("band_degenerate", False)),
    ]
    failed = []
    for label, sr, ok in cases:
        model, data = model_from_counting(sr)
        r = compute(model, data, poi_cap=32.0)
        verdict = "PASS" if ok(r) else "FAIL"
        print(f"  selftest {label:15s} obs_limit={r['obs_limit']:.4g}  "
              f"at_mu_floor={r['at_mu_floor']} at_poi_cap={r['at_poi_cap']}  -> {verdict}")
        if verdict == "FAIL":
            failed.append(label)

    # --- silent-optimizer-failure regressions ------------------------------- #
    # nan-pocket: the hardened optimizer must (a) survive the NaN pockets, (b) match
    # the guarded-MIGRAD reference limit (pyhf_tnc_exclude lineage, 2026-08-28), and
    # (c) REPORT that the fallback actually fired -- (c) keeps the case honest: if the
    # surface ever stops exercising the guard, the case fails instead of testing nothing.
    model, data = _nanpocket_model()
    r = compute(model, data, poi_cap=32.0)
    ref = 2.4359
    # Escalation must be reported across the model after a distrusted fit.
    ok = (np.isfinite(r["obs_limit"]) and abs(r["obs_limit"] - ref) / ref < 0.02
          and not r["at_poi_cap"] and not r["at_mu_floor"]
          and r.get("optimizer", {}).get("n_fallback", 0) >= 1
          and r.get("optimizer", {}).get("escalated") is True)
    verdict = "PASS" if ok else "FAIL"
    print(f"  selftest {'nan-pocket':15s} obs_limit={r['obs_limit']:.4g} (ref {ref})  "
          f"n_fallback={r.get('optimizer', {}).get('n_fallback', 0)} "
          f"escalated={r.get('optimizer', {}).get('escalated')}  -> {verdict}")
    if not ok:
        failed.append("nan-pocket")

    if failed:
        sys.exit(f"pyhf_exclude selftest FAILED: {failed}")
    print("pyhf_exclude selftest: CLs regimes, cap/band flags, and "
          "NaN-pocket optimizer guard all PASS.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    sub.add_parser("selftest", help="regressions: CLs regimes, cap/band flags, "
                                    "NaN-pocket optimizer guard")

    a = sub.add_parser("likelihood")
    a.add_argument("--bkg", required=True)
    a.add_argument("--patch", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--label", default="serialized likelihood")
    a.add_argument("--sigma-scale", type=float, default=1.0, help="NLO+NLL k-factor (µ₉₅ on NLO σ = µ₉₅/k)")

    c = sub.add_parser("counting")
    c.add_argument("--srs", required=True, help="JSON list of {name,n,b,db,s}")
    c.add_argument("--out", required=True)
    c.add_argument("--label", default="counting model")
    c.add_argument("--sigma-scale", type=float, default=1.0, help="NLO+NLL k-factor (µ₉₅ on NLO σ = µ₉₅/k)")
    c.add_argument("--combined", action="store_true",
                   help="headline limit from the SIMULTANEOUS multi-channel fit of all SRs "
                        "(valid only for mutually exclusive SRs); per-SR limits + best_sr "
                        "are still computed and reported")
    for parser in (a, c):
        parser.add_argument("--backend", choices=["numpy", "jax"], default="numpy",
                            help="explicit tensor backend; missing dependencies are an error")
        parser.add_argument("--fit-tolerance", type=float, default=1e-9,
                            help="SLSQP stopping tolerance (finite and strictly between zero and one)")
        parser.add_argument("--retain-profile-witnesses", action="store_true",
                            help="retain bounded fitted vectors and adaptive search evidence")
        parser.add_argument("--profile-witness-max-evaluations", type=int, default=5000)
        parser.add_argument("--profile-witness-max-minimizations", type=int, default=50000)
        parser.add_argument("--profile-witness-max-bytes", type=int, default=256 * 1024 * 1024)
        parser.add_argument("--profile-witness-journal", help="exclusive JSONL journal path for crash-surviving progress")

    args = ap.parse_args()
    if args.mode == "selftest":
        selftest()
        return
    try:
        _number(args.sigma_scale, "sigma_scale", positive=True)
        _number(args.fit_tolerance, "fit_tolerance", positive=True)
        if args.fit_tolerance >= 1:
            raise ValueError("fit_tolerance must be strictly less than one")
        if any(value <= 0 for value in (args.profile_witness_max_evaluations,
                                        args.profile_witness_max_minimizations, args.profile_witness_max_bytes)):
            raise ValueError("profile witness budgets must be positive integers")
        if args.profile_witness_journal and not args.retain_profile_witnesses:
            raise ValueError("--profile-witness-journal requires --retain-profile-witnesses")
    except ValueError as exc:
        ap.error(str(exc))
    try:
        pyhf.set_backend(args.backend, robust_optimizer(maxiter=200000, tolerance=args.fit_tolerance),
                         precision="64b")
    except Exception as exc:
        ap.error(f"requested {args.backend} backend could not be configured: {exc}")

    paths = ([Path(args.bkg), Path(args.patch)] if args.mode == "likelihood" else [Path(args.srs)])
    input_artifacts = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                       for path in paths]
    engine_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    os.makedirs(args.out, exist_ok=True)

    dependencies = {}
    for name in ("pyhf", "numpy", "scipy", "iminuit", *(["jax", "jaxlib"] if args.backend == "jax" else [])):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    provenance = {"inputs": input_artifacts, "engine_sha256": engine_sha256,
                                   "backend": args.backend, "precision": "64b",
                                   "fit_tolerance": args.fit_tolerance, "dependencies": dependencies}

    witness_references = []

    def witness_destination(path):
        return path if not path.exists() else path.with_name(f"{path.stem}-{uuid.uuid4().hex}{path.suffix}")

    def persist_witness(witnesses, diagnostic):
        destination = witness_destination(Path(args.out) / "profile_witnesses.json")
        payload = _canonical({"schema_version": 1, "execution_provenance": provenance,
                              "profile_witnesses": witnesses, "diagnostics": diagnostic}) + b"\n"
        with destination.open("xb") as stream:
            stream.write(payload)
        reference = {"path": str(destination.resolve()), "sha256": hashlib.sha256(payload).hexdigest(),
                     "complete": witnesses.get("complete", False), "status": witnesses.get("status")}
        if witnesses.get("journal_path"):
            path = Path(witnesses["journal_path"])
            reference["journal"] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                    "head_sha256": witnesses.get("journal_head_sha256")}
        witness_references.append(reference)
        return reference

    def run_compute(model, data, **kwargs):
        diagnostic = {}
        witnesses = {} if args.retain_profile_witnesses else None
        if witnesses is not None:
            journal = (witness_destination(Path(args.profile_witness_journal))
                       if args.profile_witness_journal else None)
            kwargs.update(profile_witness_record=witnesses, profile_witness_context=provenance,
                profile_witness_limits={"evaluations": args.profile_witness_max_evaluations,
                    "minimizations": args.profile_witness_max_minimizations, "bytes": args.profile_witness_max_bytes},
                profile_witness_journal=journal)
        try:
            result = compute(model, data, diagnostic_record=diagnostic, **kwargs)
            if witnesses is not None:
                result["profile_witnesses"] = persist_witness(witnesses, diagnostic)
            return result
        except BaseException:
            failure = {"schema_version": 1, "status": "failed", "execution_provenance": provenance,
                       "diagnostics": diagnostic, "scope": "failed numerical inference; no limit emitted"}
            if witnesses is not None:
                failure["profile_witnesses"] = persist_witness(witnesses, diagnostic)
            destination = Path(args.out) / "inference_failure.json"
            if destination.exists():
                destination = Path(args.out) / f"inference_failure-{uuid.uuid4().hex}.json"
            with destination.open("x") as stream:
                json.dump(failure, stream, indent=2, allow_nan=False)
                stream.write("\n")
            raise

    if args.mode == "likelihood":
        model, data = model_from_likelihood(args.bkg, args.patch)
        print(f"likelihood model: {model.config.nmaindata} bins, {len(model.config.par_order)} parameters")
        res = run_compute(model, data)
        res["mode"] = "likelihood"
        res["model_scope"] = {"correlations": "preserved from the supplied workspace modifier structure",
                              "acceptance_validated": False}
        best_label = None
    else:
        srs = _read_json(args.srs)
        if not isinstance(srs, list) or not srs:
            ap.error("counting inputs must be a nonempty list of SRs")
        names = []
        for sr in srs:
            _counting_inputs(sr)
            name = sr.get("name")
            if not isinstance(name, str) or not name.strip() or name in names:
                ap.error("counting SR names must be distinct nonempty strings")
            names.append(name)
        # per-SR limits always computed: they feed best_sr (best EXPECTED sensitivity)
        # and the per_sr record consumers (cert engines, the benchmark gate).
        best, best_res = None, None
        per_sr = {}
        for sr in srs:
            entry = {"n": sr["n"], "b": sr["b"], "db": sr["db"], "s": sr["s"]}
            from ravel.validation.delivery_checks import counting_calibration
            # Independent count ordering is a reference, never a replacement
            # for the requested asymptotic profile-likelihood quantity.
            entry['statistical_calibration'] = counting_calibration({**sr, 's': sr['s'] * args.sigma_scale})
            flags = low_count_flags(sr)
            if flags:
                entry["low_count_flags"] = flags
            if float(sr["s"]) == 0.0:
                # a zero-signal SR puts NO constraint on mu: the bracket would run to
                # the poi cap and record a ceiling that is not a limit. Skip honestly.
                entry["skipped"] = "zero signal (s<=0): no constraint on mu"
                per_sr[sr["name"]] = entry
                print(f"  SR {sr['name']:6s}: s=0 -> SKIPPED (no constraint on mu)")
                continue
            model, data = model_from_counting(sr)
            r = run_compute(model, data, n_curve=25)  # counting fits are instant -> fine grid
            entry.update({"obs_limit": r["obs_limit"], "exp_median": r["exp_limits"][2]})
            entry["exp_limits"] = r["exp_limits"]
            entry["limit_status"] = r["limit_status"]
            entry["limit_brackets"] = r["limit_brackets"]
            if "profile_witnesses" in r:
                entry["profile_witnesses"] = r["profile_witnesses"]
            attach_limits(entry, result=read_limits(r))
            for flag in ("at_poi_cap", "median_at_cap", "band_degenerate"):
                if r[flag]:
                    entry[flag] = True
            per_sr[sr["name"]] = entry
            print(f"  SR {sr['name']:6s}: s={sr['s']:.2f} b={sr['b']:.1f}+-{sr['db']:.1f} n={sr['n']:.0f}"
                  f"  -> mu_obs={r['obs_limit']:.2f} (exp {r['exp_limits'][2]:.2f})")
            if r["limit_status"]["expected"][2] == "resolved" and (
                best is None or r["exp_limits"][2] < best_res["exp_limits"][2]
            ):
                best, best_res = sr["name"], r
        if best is None:
            sys.exit("counting: no resolved median expected limit; cannot rank a best SR")
        per_sr[best]["is_best"] = True
        if getattr(args, "combined", False):
            # headline = simultaneous fit of all constraining channels (exclusive SRs);
            # zero-signal channels are inert for mu and omitted from the fit.
            fit_srs = [sr for sr in srs if float(sr["s"]) > 0.0]
            model, data = model_from_counting_combined(fit_srs)
            res = run_compute(model, data, n_curve=25)
            res["mode"] = "counting-combined"
            res["combined_channels"] = [sr["name"] for sr in fit_srs]
            res["mode_notes"] = ("simultaneous multi-channel counting fit; background "
                                 "constraints uncorrelated (no published correlations); "
                                 "valid for mutually exclusive SRs only")
            print(f"  COMBINED ({len(fit_srs)} ch): mu_obs={res['obs_limit']:.2f} "
                  f"(exp {res['exp_limits'][2]:.2f})")
        else:
            res = best_res
            res["mode"] = "counting"
        res["best_sr"] = best
        res["per_sr"] = per_sr
        res["model_scope"] = {
            "background_constraint": "independent Poisson shapesys constraints",
            "correlations": "background correlations unavailable; assumed independent",
            "mutual_exclusivity": "required but not inferred from yields" if args.combined else "best-expected SR only",
            "acceptance_validated": False,
        }
        best_label = best

    res["label"] = args.label
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
           for path, entry in zip(paths, input_artifacts)):
        raise RuntimeError("inference inputs changed while computing the result")
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != engine_sha256:
        raise RuntimeError("inference engine changed while computing the result")
    res["execution_provenance"] = provenance
    if witness_references:
        res["all_profile_witnesses"] = witness_references
    # apply the NLO+NLL k-factor: a stronger nominal σ scales the signal-strength limit by 1/k.
    k = getattr(args, "sigma_scale", 1.0)
    if k != 1.0:
        scale_result(res, k)
        print(f"  applied NLO+NLL k={k}: µ₉₅(LO)={res['obs_limit_lo']:.3f} -> µ₉₅(NLO)={res['obs_limit']:.3f}")
    from ravel.validation import regression_triggers
    res['computed_checks'] = regression_triggers.consume_flags(res)
    res['computed_check_summary'] = regression_triggers.summary(res['computed_checks'])
    json.dump(res, open(os.path.join(args.out, "exclusion.json"), "w"), indent=2, allow_nan=False)
    plot(res, os.path.join(args.out, "exclusion.png"), args.label, sr_label=best_label)

    print("\n=== 95% CL upper limit on mu ===")
    print(f"  observed : {res['obs_limit']:.3f}")
    el = res["exp_limits"]
    print(f"  expected : {el[2]:.3f}  (+1s {el[3]:.3f} / -1s {el[1]:.3f})")
    verdict = ("EXCLUDED (mu=1 disfavoured)" if res["obs_limit"] < 1.0
               else "NOT excluded at this confidence level")
    if res["limit_status"]["observed"] != "resolved":
        verdict = "UNRESOLVED: scan bound only; inspect limit_status"
    print(f"  nominal signal (mu=1): {verdict}")


if __name__ == "__main__":
    main()
