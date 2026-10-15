"""ravel doctor: is every required tool installed and the right version?

Reads ``native/setup/toolchain-manifest.json`` and probes each check with a
short, shell-free, network-free command. Every problem comes with the exact
command (or the licence activation steps) that fixes it.

    ravel doctor                     # the required toolchain for this platform
    ravel doctor --profile site
    ravel doctor --group madgraph --json
    ravel doctor --strict            # exit 1 unless everything is ready

Statuses: ready, missing, version_mismatch, unconfigured, manual_required,
remote_route (runs on a Linux site, not on this machine), unsupported and
conflict. The doctor never changes anything: it does not activate Wolfram,
read API keys, start container machines or contact model providers.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys

from . import host_config
from . import manifest as mf
from .installer import container_engine, default_prefix, resolve_prefix
from .steps import engine_is_apptainer, pdf_set_ready, subprocess_environment

STATUS_ORDER = ("ready", "remote_route", "unconfigured", "manual_required", "version_mismatch", "missing",
                "conflict", "unsupported")
OK_STATUSES = ("ready", "remote_route")
WOLFRAM_VERSIONS = ("14.3", "15.0")
NO_KEY_ROUTE = ("Without an API key, research and review roles run in fresh external agent sessions: "
                "`ravel agent-graph prepare-external --graph GRAPH --node NODE` writes the role's request, "
                "a fresh Claude Code or Codex session answers it, and "
                "`ravel agent-graph deliver-external --graph GRAPH --node NODE --response RESPONSE.json` "
                "records the answer with that session's identity.")
# The shipped host configuration that answers model requests with an installed agent command line.
AGENT_CLI_HOST = "src/ravel/data/transports/hosts/agent-cli.json"
# What a tester runs on the Linux analysis facility to qualify a site group there, and what a passing
# result looks like. Each text is one line: the manifest's tester-qualification record carries the same
# words and the release check looks for them here.
TESTER_PROCEDURES = {
    "site-root-wms": "On the Linux analysis facility, in the RAVEL checkout, run `bash scripts/setup/install.sh --profile site --prefix /path/to/work/area/ravel-tools --lcg-view /absolute/lcg/view` (`--lcg-view none` on a site without CVMFS) and then `.venv/bin/ravel doctor --group site-root-wms`. It passes when the doctor reports site-analysis-python, site-wms-python, site-snakemake and site-wms-lock-plugin-view-caches ready, prints `Everything selected is ready.` and exits with status 0.",
    "site-access": "On the Linux analysis facility, in the RAVEL checkout, obtain your own grid proxy and Kerberos ticket, then run `.venv/bin/ravel doctor --group site-access`. It passes when the doctor reports cvmfs, grid-proxy, kerberos, htcondor, apptainer and agent-cli ready, prints `Everything selected is ready.` and exits with status 0.",
}


def probe(argv, *, env=None, timeout=15):
    """Run one bounded probe. Returns (exit code, combined output). Never uses a shell."""
    try:
        result = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout,
                                env=env, stdin=subprocess.DEVNULL, check=False)
    except FileNotFoundError:
        return 127, "not found"
    except PermissionError as error:
        return 126, str(error)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout} s"
    except OSError as error:
        return 125, str(error)
    return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()


def _version_tuple(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:4])


_NUMERIC = re.compile(r"^\d+(\.\d+)*$")


def version_matches(found, expect):
    """``expect`` is exact ("2.9.27"), a prefix pattern ("6.5.*"), a minimum (">=4")
    or alternatives joined by "|". Numeric versions compare by value, so 3.03.01 equals 3.3.1."""
    if expect is None:
        return True
    found = found.strip()
    for option in (part.strip() for part in expect.split("|")):
        if option.startswith(">="):
            if _version_tuple(found) >= _version_tuple(option[2:]):
                return True
        elif option.endswith("*"):
            stem = option[:-1].rstrip(".")
            if _NUMERIC.match(stem) and _NUMERIC.match(found.split("/")[0].replace("/", ".")):
                if _version_tuple(found)[:len(_version_tuple(stem))] == _version_tuple(stem):
                    return True
            elif found.startswith(option[:-1]):
                return True
        elif found == option:
            return True
        elif _NUMERIC.match(found) and _NUMERIC.match(option) and _version_tuple(found) == _version_tuple(option):
            return True
    return False


class Doctor:
    def __init__(self, repo, prefix, platform_key, manifest, catalog, *, environ=None, run_probe=probe,
                 which=shutil.which, glob_paths=glob.glob):
        self.repo, self.prefix = Path(repo), Path(prefix)
        self.platform = platform_key
        self.manifest, self.catalog = manifest, catalog
        self.environ = dict(os.environ if environ is None else environ)
        self.values = mf.variables(self.prefix, self.repo, platform_key,
                                   container_engine=container_engine(self.prefix, platform_key, self.environ, which))
        self.env = subprocess_environment(self.prefix, self.values, self.environ)
        self.run_probe = run_probe
        self.which = which
        self.glob = glob_paths
        self.probes = []

    # ------------------------------------------------------------ helpers
    def _probe(self, argv, timeout=15):
        argv = [str(a) for a in argv]
        self.probes.append(argv)
        env = self.env
        if os.path.isabs(argv[0]):
            # Tools in an environment's bin directory often start with
            # "#!/usr/bin/env python3": put that directory first, as activation would.
            env = dict(env, PATH=os.path.dirname(argv[0]) + os.pathsep + env.get("PATH", ""))
        return self.run_probe(argv, env=env, timeout=timeout)

    def fix_command(self, group_id):
        command = f"bash scripts/setup/install.sh --only {group_id}"
        if self.prefix != default_prefix(self.repo) and not (self.repo / ".ravel/native-prefix").is_file():
            command += f" --prefix {self.prefix}"
        return command

    # ------------------------------------------------------------ check kinds
    def _path_check(self, check):
        path = Path(mf.expand(check["path"], self.values))
        kind = check["kind"]
        if kind == "directory":
            ok = path.is_dir()
        elif kind == "executable":
            ok = path.is_file() and os.access(path, os.X_OK)
        else:
            ok = path.is_file()
        if not ok:
            return {"status": "missing", "detail": f"not found: {path}", "path": str(path)}
        result = {"status": "ready", "path": str(path)}
        if check.get("probe"):
            result.update(self._run_probe_check(check, path))
        if check.get("pdf_set"):
            row = next(r for r in self.catalog["sets"] if r["name"] == check["pdf_set"])
            if not pdf_set_ready(path, row):
                result.update(status="missing", detail=f"{path} is not the complete set with LHAID {row['lhaid']}")
        return result

    def _run_probe_check(self, check, path=None):
        spec = check["probe"]
        argv = mf.expand(spec["argv"], dict(self.values, path=str(path) if path else ""))
        code, output = self._probe(argv, timeout=spec.get("timeout", 15))
        if code != 0 and not spec.get("any_exit"):
            return {"status": "missing" if path is None else "version_mismatch" if spec.get("expect") else "missing",
                    "detail": f"{' '.join(argv[:3])} failed ({code}): {output[:200]}"}
        found = None
        if spec.get("regex"):
            match = re.search(spec["regex"], output, re.M)
            if not match:
                return {"status": "version_mismatch" if spec.get("expect") else "missing",
                        "detail": f"unexpected output from {Path(argv[0]).name}: {output[:200]}"}
            found = match.group(1) if match.groups() else match.group(0)
        if spec.get("expect") is not None and not version_matches(found or "", spec["expect"]):
            return {"status": "version_mismatch", "found": found, "expected": spec["expect"],
                    "detail": f"found {found}, expected {spec['expect']}"}
        return {"status": "ready", "found": found}

    def _provider_check(self, check):
        location = self.environ.get("RAVEL_HOST_CONFIG") or str(self.repo / ".ravel/host.json")
        path = Path(location)
        if not path.is_file():
            return {"status": "unconfigured", "path": str(path),
                    "detail": f"no model-provider configuration at {path}. Copy {self.prefix}/config/host.example.json "
                              f"there and set its api_key_env, copy {AGENT_CLI_HOST} there to answer with an "
                              f"installed agent command line and its own login, or use the no-API-key route. "
                              f"{NO_KEY_ROUTE}"}
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return {"status": "unconfigured", "path": str(path), "detail": f"{path} is not valid JSON: {error}"}
        kind = config.get("type")
        if kind == "command":
            return {"status": "ready", "path": str(path), "detail": "command adapter configured"}
        if kind == "agent-cli":
            # An installed agent command line answers with its own login. Presence only: no session starts.
            from ravel.workflow.cli_agent_host import AGENTS, LAUNCHERS
            agent = config.get("agent", "auto")
            if agent != "auto" and agent not in AGENTS:
                return {"status": "unconfigured", "path": str(path),
                        "detail": f"{path} names the agent {agent!r}; choose auto or one of " + ", ".join(AGENTS)}
            wanted = AGENTS if agent == "auto" else (agent,)
            found = next((LAUNCHERS[name] for name in wanted if self.which(LAUNCHERS[name])), None)
            if found:
                return {"status": "ready", "path": str(path),
                        "detail": f"agent command line host; {found} is on PATH and answers with its own login"}
            return {"status": "unconfigured", "path": str(path),
                    "detail": f"{path} expects an installed agent command line (" +
                              ", ".join(LAUNCHERS[name] for name in wanted) + "), and none is on PATH"}
        if config.get("privacy") == "local_only" and not config.get("api_key_env"):
            return {"status": "ready", "path": str(path), "detail": "local model endpoint configured"}
        name = config.get("api_key_env") or ("OPENAI_API_KEY" if kind == "responses" else None)
        if not name:
            return {"status": "unconfigured", "path": str(path), "detail": f"{path} names no api_key_env"}
        # Presence only: the value is never read into the report.
        if name in self.environ and self.environ[name] != "":
            return {"status": "ready", "path": str(path), "detail": f"{kind} provider; {name} is set"}
        return {"status": "unconfigured", "path": str(path),
                "detail": f"{path} expects the environment variable {name}, which is not set. {NO_KEY_ROUTE}"}

    def wolfram_kernel(self):
        found = self.which("wolframscript")
        if found:
            return found
        patterns = ["/Applications/Wolfram*.app/Contents/MacOS/wolframscript",
                    "/Applications/Mathematica*.app/Contents/MacOS/wolframscript",
                    "/usr/local/Wolfram/*/*/Executables/wolframscript",
                    "/usr/local/Wolfram/*/Executables/wolframscript",
                    "/opt/Wolfram/*/*/Executables/wolframscript"]
        for pattern in patterns:
            matches = sorted(self.glob(pattern))
            if matches:
                return matches[-1]
        return None

    def _wolfram_check(self, check):
        kernel = self.wolfram_kernel()
        if not kernel:
            fallbacks = check.get("fallbacks", "a supplied model, a pregenerated spectrum or a Python evaluator")
            return {"status": "manual_required",
                    "detail": "no Wolfram kernel found. Install Mathematica or the free Wolfram Engine "
                              "(https://www.wolfram.com/engine/), then run `wolframscript -activate` yourself.",
                    "hold": {"missing": "wolframscript",
                             "reason": "Wolfram-backed operations are held because no Wolfram kernel (wolframscript) "
                                       "was found; fallbacks: " + fallbacks + "."}}
        # Read the version only. The doctor never activates or changes the licence.
        code, output = self._probe([kernel, "-code", "$VersionNumber"], timeout=60)
        if code != 0 or re.search(r"activat|licen[cs]e|password", output, re.I):
            return {"status": "unconfigured", "path": kernel,
                    "detail": "the Wolfram kernel is installed but not activated; run `wolframscript -activate` "
                              "yourself (the doctor never changes the licence)"}
        match = re.search(r"(\d+)\.(\d*)", output)
        version = f"{match.group(1)}.{match.group(2) or 0}" if match else output[:20]
        expected = check.get("expect", "|".join(WOLFRAM_VERSIONS))
        if not version_matches(version, expected):
            return {"status": "version_mismatch", "path": kernel, "found": version, "expected": expected,
                    "detail": f"Wolfram {version} found; RAVEL's symbolic packages are pinned for {expected}"}
        loaded = self._wolfram_loads(kernel, check)
        if loaded is not None:
            return {"path": kernel, "found": version, **loaded}
        return {"status": "ready", "path": kernel, "found": version, "detail": "licensed kernel answers"}

    def _wolfram_loads(self, kernel, check):
        """Load each symbolic package in its own fresh kernel. Returns None when the check lists none."""
        rows = check.get("load") or []
        if not rows:
            return None
        failed, loaded = [], []
        for row in rows:
            root = mf.expand(row["root"], self.values)
            if row["name"] == "FeynRules":
                from ravel.physics.model_provider_bridge import namespace_load_script, namespace_checks
                code = namespace_load_script(root) + (
                    'Print["RAVEL-NAMESPACE:" <> ExportString[<|'
                    '"provider_loaded" -> (TrueQ[loaded] && TrueQ[FR$Loaded]), '
                    '"namespace_compatibility" -> providerNamespace|>, "RawJSON"]];')
                status, output = self._probe([kernel, "-code", code], timeout=300)
                try:
                    record, _ = json.JSONDecoder().raw_decode(output.split("RAVEL-NAMESPACE:", 1)[1].lstrip())
                    ok = (status == 0 and record.get("provider_loaded") is True
                          and namespace_checks(record.get("namespace_compatibility")))
                except (IndexError, ValueError, AttributeError):
                    ok = False
                (loaded if ok else failed).append(row["name"])
                continue
            symbol = ('$' + row["directory_symbol"] + ' = "' + root + '"; ') if row.get("directory_symbol") else ""
            code = (symbol + 'PrependTo[$Path, "' + root + '"]; Print[Quiet[Check[Needs["' + row["context"] +
                    '"]; "RAVEL-LOAD-OK", "RAVEL-LOAD-FAIL"]]]')
            status, output = self._probe([kernel, "-code", code], timeout=300)
            (loaded if status == 0 and "RAVEL-LOAD-OK" in output else failed).append(row["name"])
        if failed:
            return {"status": "unconfigured", "loaded": loaded, "load_failed": failed,
                    "detail": "the kernel is active but " + ", ".join(failed) + " did not load in a fresh kernel",
                    "hold": {"missing": ", ".join(failed),
                             "reason": "Wolfram-backed operations that need " + ", ".join(failed) +
                                       " are held because the package did not load in a fresh kernel; fallbacks: " +
                                       check.get("fallbacks", "a supplied model or a Python evaluator") + "."}}
        return {"status": "ready", "loaded": loaded,
                "detail": "activated kernel; " + ", ".join(loaded) + " load in a fresh kernel"}

    def _catalogue_check(self, check):
        from ravel.analysis_catalog import installed_catalog_path, load_catalog
        path = installed_catalog_path(self.prefix)
        fix = shlex.join(mf.expand(check["rebuild"], self.values))
        if not path.is_file():
            return {"status": "missing", "path": str(path), "detail": f"analysis catalogue missing: {path}", "fix": fix}
        try:
            catalog = load_catalog(path)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            return {"status": "unconfigured", "path": str(path), "detail": f"invalid analysis catalogue: {error}", "fix": fix}
        revision = catalog["sources"]["rivet"]["revision"]
        if revision != check["rivet_ref"]:
            return {"status": "version_mismatch", "found": revision, "expected": check["rivet_ref"],
                    "detail": f"catalogue Rivet revision {revision} differs from pinned {check['rivet_ref']}", "fix": fix}
        return {"status": "ready", "path": str(path), "found": revision}

    def _agent_cli_check(self, check):
        from ravel.workflow import transport_registry as registry
        candidates = [(name, self.which(name)) for name in ("claude", "codex")]
        older = None
        for name, path in candidates:
            if not path:
                continue
            code, version = self._probe([path, "--version"])
            if name == "claude" and (code != 0 or not version_matches(version, ">=2.1.296")):
                older = {"status": "version_mismatch", "path": path, "found": version,
                         "expected": ">=2.1.296", "detail": "Claude Code 2.1.296 or newer is required", "fix": "claude update"}
                continue
            transport_id = name + "-cli-worker"
            document = registry.load(transport_id)
            record = registry.read_probe(transport_id)
            try:
                current_sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            except OSError:
                current_sha = None
            matches = (record is not None and registry.probe_problem(record, document) is None
                       and not record["unusable"] and record["executable_sha256"] == current_sha
                       and Path(record["executable_path"]).resolve() == Path(path).resolve())
            qualification = registry.qualification_status(document, record if matches else None)
            qualified = matches and qualification == "live_qualified"
            detail = f"{name} command line found; {transport_id} " + (
                "is qualified on this host" if qualified else f"is not qualified on this host; run `ravel transport qualify {transport_id}`")
            return {"status": "ready", "path": path, "found": version, "transport": transport_id,
                    "qualification": qualification, "transport_qualified": qualified, "detail": detail}
        return older or {"status": "missing", "detail": "neither the claude nor the codex command line is on PATH",
                         "fix": "Install Claude Code or the Codex CLI and put its command on PATH."}

    def _container_image_check(self, check):
        engine = self.values["CONTAINER_ENGINE"]
        reference = check["image"] + "@" + check["digest"]
        if engine_is_apptainer(engine):
            sif = Path(self.values["CONTAINERS"]) / "images" / (check["name"] + ".sif")
            return {"status": "ready", "path": str(sif)} if sif.is_file() else \
                {"status": "missing", "detail": f"{sif} not found"}
        code, output = self._probe([engine, "image", "exists", reference] if Path(engine).name != "docker"
                                   else [engine, "image", "inspect", reference], timeout=30)
        if code == 0:
            return {"status": "ready", "found": reference}
        if code in (125, 127) or "Cannot connect" in output or "connection refused" in output.lower():
            return {"status": "missing", "detail": f"the container engine {engine} is not running or not installed; "
                                                   f"start it with `{engine} machine start ravel` (macOS) or install "
                                                   f"the container-runtime group"}
        return {"status": "missing", "detail": f"image {reference} is not present"}

    def _site_check(self, check):
        name = check["site"]
        if name == 'site-install':
            from ravel.workflow.site_doctor import runtime_checks,location_check,site_disk_gb
            doctor = self
            class HostAdapter:
                which = staticmethod(doctor.which)
                exists = staticmethod(lambda path: Path(path).exists())
                run = staticmethod(lambda argv: doctor._probe(argv))
            host=HostAdapter()
            rows = runtime_checks(self.prefix,host=host,environ=self.environ)
            rows.append(location_check('prefix',self.prefix,host=host,threshold_gb=site_disk_gb(),home=self.environ.get('HOME')))
            failed = [row for row in rows if row['status']=='fail']
            return {'status':'missing' if failed else 'ready',
                    'detail':'; '.join(row['name']+': '+row['detail'] for row in (failed or rows)),
                    'warnings':[row['name']+': '+row['detail']+((' -> '+row['fix']) if row.get('fix') else '')
                                for row in rows if row['status']=='warn'],
                    **({'fix':failed[0]['fix']} if failed else {})}
        if name == "cvmfs":
            record=self.prefix/'.ravel-site/lcg-view.json'
            try:
                view=json.loads(record.read_text())
                if view.get('choice')=='none' and view.get('path') is None:
                    return {'status':'ready','detail':'Explicit no-CVMFS site choice recorded'}
                ok = bool(view.get('path')) and (Path(view['path'])/'setup.sh').is_file()
            except (OSError,ValueError,TypeError,AttributeError):ok=False
            return {"status": "ready" if ok else "missing",
                    "detail": None if ok else "Recorded LCG view is missing; restore it or install into a new campaign prefix"}
        if name == "x509-proxy":
            proxy = self.environ.get("X509_USER_PROXY") or f"/tmp/x509up_u{os.getuid()}"
            if not Path(proxy).is_file():
                return {"status": "unconfigured", "detail": "no grid proxy; run `voms-proxy-init -voms atlas` yourself"}
            if self.which("voms-proxy-info"):
                code, output = self._probe(["voms-proxy-info", "--timeleft"])
                if code != 0 or output.strip() in ("0", ""):
                    return {"status": "unconfigured", "detail": "the grid proxy has expired; renew it with voms-proxy-init"}
                return {"status": "ready", "found": output.strip() + " s left"}
            return {"status": "ready", "path": proxy}
        if name == "kerberos":
            if not self.which("klist"):
                return {"status": "missing", "detail": "klist not found"}
            code, _ = self._probe(["klist", "-s"])
            return {"status": "ready"} if code == 0 else \
                {"status": "unconfigured", "detail": "no valid Kerberos ticket; run `kinit` yourself (krenew keeps "
                                                     "long sessions alive)"}
        if name == "condor":
            found = self.which("condor_submit")
            return {"status": "ready", "path": found} if found else \
                {"status": "missing", "detail": "HTCondor client (condor_submit) not found"}
        if name == "apptainer":
            found = self.which("apptainer") or self.which("singularity")
            return {"status": "ready", "path": found} if found else \
                {"status": "missing", "detail": "apptainer not found"}
        if name == "agent-cli":
            found = self.which("claude") or self.which("codex")
            return {"status": "ready", "path": found} if found else \
                {"status": "missing", "detail": "neither the claude nor the codex command line is on PATH"}
        if name == "servicex-config":
            places = [Path.cwd(), *Path.cwd().parents, Path.home()]
            names = ("servicex.yaml", ".servicex")
            found = next((p / n for p in places for n in names if (p / n).is_file()), None)
            # Presence only: the credential file is never read.
            return {"status": "ready", "path": str(found)} if found else \
                {"status": "unconfigured", "detail": "no servicex.yaml found in this directory, its parents or your home"}
        return {"status": "unsupported", "detail": "unknown site check " + name}

    def evaluate_check(self, group, check):
        kind = check["kind"]
        if kind == "probe" and "json_status" in check["probe"]:
            argv = mf.expand(check["probe"]["argv"], self.values)
            code, output = self._probe(argv, timeout=check["probe"].get("timeout", 120))
            try:
                passed = code == 0 and json.loads(output).get("status") == check["probe"]["json_status"]
            except (ValueError, AttributeError):
                passed = False
            result = {"status": "ready" if passed else "missing", "detail": None if passed else output[:500]}
            if not passed:
                stopped = any(word in output.lower() for word in ("cannot connect", "connection refused", "not running", "machine is stopped"))
                result["fix"] = ("ravel-podman machine start ravel; then ravel doctor --group " + group["id"]
                                 if stopped else self.fix_command(group["id"]) + " --jobs 4 --accept-licenses")
        elif kind in ("file", "directory", "executable"):
            result = self._path_check(check)
        elif kind == "probe":
            result = self._run_probe_check(check)
        elif kind == "provider":
            result = self._provider_check(check)
        elif kind == "wolfram":
            result = self._wolfram_check(check)
        elif kind == "analysis_catalogue":
            result = self._catalogue_check(check)
        elif kind == "agent_cli":
            result = self._agent_cli_check(check)
        elif kind == "container_image":
            result = self._container_image_check(check)
        elif kind == "site":
            result = self._site_check(check)
        else:  # manual prerequisite
            result = self._run_probe_check(check) if check.get("probe") else \
                {"status": "ready" if Path(mf.expand(check["path"], self.values)).exists() else "missing"}
            if result["status"] != "ready":
                result = {"status": "manual_required", "detail": check.get("instruction", "")}
        result.setdefault("detail", None)
        if result["status"] in ("missing", "version_mismatch"):
            result.setdefault("fix", check.get("instruction") if kind == "site" else self.fix_command(group["id"]))
        elif result["status"] in ("manual_required", "unconfigured"):
            result.setdefault("fix", check.get("instruction") or result.get("detail"))
        return result

    def host_config_warnings(self):
        home = self.environ.get("HOME") or str(Path.home())
        return host_config.warnings(self.values["CONFIG"], home)

    # ------------------------------------------------------------ report
    def census_report(self, census=None):
        """Project every census tool through the existing doctor checks."""
        from ravel.workflow.tool_census import doctor_report
        rows = doctor_report(self, census)
        if census is None:
            from ravel.workflow.recast_route import higgs_reference_readiness
            rows.append(higgs_reference_readiness())
        return rows

    def report(self, group_ids, profile=None):
        byid = mf.by_id(self.manifest)
        groups, resolved = [], {}
        for gid in group_ids:
            group = byid[gid]
            route = mf.route_for(group, self.platform)
            rows = []
            for check in group["checks"]:
                if not mf.applies(check, self.platform):
                    continue
                if route == "remote":
                    row = {"status": "remote_route", "detail": group.get("manual"), "fix": group.get("manual")}
                elif route == "unsupported":
                    row = {"status": "unsupported", "detail": group.get("manual")}
                else:
                    row = self.evaluate_check(group, check)
                    if row.get("path"):
                        resolved[check["id"]] = row["path"]
                rows.append({"id": check["id"], **row})
            status = max((r["status"] for r in rows), key=STATUS_ORDER.index) if rows else "ready"
            entry = {"group": gid, "title": group["title"], "route": route, "status": status, "checks": rows,
                     **group_label(group, status, rows)}
            if (group.get("qualification") or {}).get("status") == "tester-qualification":
                entry["tester_procedure"] = TESTER_PROCEDURES.get(gid) or group["qualification"].get("procedure")
            holds = [r["hold"] for r in rows if r.get("hold")]
            if group.get("hold"):
                holds.append(group["hold"])
            if holds:
                entry["holds"] = holds
            groups.append(entry)
        conflicts = []
        for left, right in self.manifest.get("incompatible_path_bindings", []):
            if left in resolved and right in resolved and \
                    Path(resolved[left]).resolve() == Path(resolved[right]).resolve():
                conflicts.append(f"{left} and {right} resolve to the same file {resolved[left]}")
        overall = max([g["status"] for g in groups] or ["ready"], key=STATUS_ORDER.index)
        if conflicts:
            overall = "conflict"
        summary = {}
        for entry in groups:
            summary[entry["label"]] = summary.get(entry["label"], 0) + 1
        return {"schema_version": 1, "kind": "ravel-doctor-report", "platform": self.platform,
                "prefix": str(self.prefix), "profile": profile, "expected_groups": list(group_ids),
                "summary": summary, "status": overall, "groups": groups, "conflicts": conflicts,
                "ready": overall in OK_STATUSES, "no_api_key_route": NO_KEY_ROUTE,
                "warnings": self.host_config_warnings(),
                "refusal_classes": [{k: r[k] for k in ("id", "title", "refused", "why", "would_make_it_possible")}
                                    for r in self.manifest.get("refusal_classes", [])]}


LABELS = {"ready": "ready", "remote_route": "remote", "manual_required": "owner-action",
          "unconfigured": "owner-action", "unsupported": "unsupported", "conflict": "not-ready",
          "missing": "not-ready", "version_mismatch": "not-ready"}


def group_label(group, status, rows):
    """The one label a reader sees for a group: ready, not-ready (with its fix), owner-action, remote or
    unsupported. Installation observations do not confer numerical qualification."""
    label = LABELS.get(status, "not-ready")
    fixes = []
    for row in rows:
        if row["status"] not in OK_STATUSES and row.get("fix") and row["fix"] not in fixes:
            fixes.append(row["fix"])
    from .qualification import installation_label
    entry = installation_label(group, status, label)
    if (group.get('qualification') or {}).get('status') == 'tester-qualification':
        entry['qualification_command'] = (
            'ravel site doctor --profile generic --prefix <work-prefix> --runs-dir <work-runs> '
            '--transcripts-dir <work-transcripts>; then run the synthetic site-qualification procedure '
            'in docs/reference/site-workflows.md on the facility as its user')
    if label != "ready" and label != "remote" and fixes:
        entry["fix"] = fixes[0] if len(fixes) == 1 else fixes
    return entry


def select_groups(manifest, *, profile=None, groups=None, mode=None):
    if groups:
        unknown = [g for g in groups if g not in mf.by_id(manifest)]
        if unknown:
            raise mf.ManifestError("unknown group: " + ", ".join(unknown))
        return [g["id"] for g in manifest["groups"] if g["id"] in groups]
    if mode:
        row = next((r for r in manifest.get("operations", []) if r["mode"] == mode), None)
        return mf.profile_groups(manifest, only=row["groups"] if row else ["python-host"])
    return mf.profile_groups(manifest, profile)


def format_report(report):
    lines = [f"RAVEL doctor: {report['platform']}, prefix {report['prefix']}", ""]
    width = max([len(g["group"]) for g in report["groups"]] + [5]) + 2
    for group in report["groups"]:
        if group.get("tester_procedure"):
            lines.append(f"{group['group']:<{width}}for testers on the site: {group['tester_procedure']}")
        failing = [c for c in group["checks"] if c["status"] not in OK_STATUSES]
        fixes = {c.get("fix") for c in failing}
        if group["status"] == "missing" and len(failing) == len(group["checks"]) and \
                all(c["status"] == "missing" for c in failing) and len(fixes) == 1:
            lines.append(f"{group['group']:<{width}}not installed")
            lines.append(f"{'':<{width}}  fix: {fixes.pop()}")
            if group.get('qualification_command'):
                lines.append(f"{'':<{width}}  qualification: {group['qualification_command']}")
            continue
        lines.append(f"{group['group']:<{width}}{group['status']}")
        if group.get('qualification_command'):
            lines.append(f"{'':<{width}}  qualification: {group['qualification_command']}")
        for check in group["checks"]:
            for warning in check.get('warnings',[]):
                lines.append(f"{'':<{width}}  warn: {warning}")
            if check["status"] in OK_STATUSES and check["status"] != "remote_route":
                continue
            detail = check.get("detail") or ""
            lines.append(f"{'':<{width}}  {check['id']}: {check['status']}" + (f" - {detail}" if detail else ""))
            if check.get("fix") and check["fix"] != detail:
                lines.append(f"{'':<{width}}    fix: {check['fix']}")
    for conflict in report["conflicts"]:
        lines.append("conflict: " + conflict)
    if report.get('tool_census'):
        lines.append('')
        lines.append('Tool census (readiness; historical evidence remains scoped):')
        for row in report['tool_census']:
            lines.append(f"  {row['title']}: {row['status'].replace('_', ' ')}; {row['readiness']}")
            if row.get('hold_status'):
                lines.append('    ' + row['hold_status'])
                lines.append('    fix: ' + str(row.get('fix')))
                lines.append('    would make possible: ' + str(row.get('would_make_possible')))
    lines.append("")
    lines.append("Everything selected is ready." if report["ready"] else
                 "Some tools need attention; each line above gives the fix.")
    return "\n".join(lines)


def parser():
    ap = argparse.ArgumentParser(prog="ravel doctor", description="Check that RAVEL's required tools are installed.")
    ap.add_argument("--profile", choices=["site"], help="Linux analysis facility target; omit for the default toolchain")
    ap.add_argument("--group", action="append", help="check one group (repeatable)")
    ap.add_argument("--mode", help="check the groups one science mode needs")
    ap.add_argument("--prefix", help="toolchain prefix (default: the installer's prefix)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--census", action="store_true", help="include a check and separate status for every census tool")
    ap.add_argument("--record-host-config", action="store_true",
                    help="accept the current agent host configuration files as the baseline for warnings")
    ap.add_argument("--strict", action="store_true", help="compatibility flag; failed checks always exit 1")
    return ap


def main(argv=None, *, repo=None, environ=None, run_probe=probe):
    args = parser().parse_args(argv)
    try:
        repo = Path(repo or mf.repo_root())
        if not (repo / "native/setup/toolchain-manifest.json").is_file():
            raise mf.ManifestError("ravel doctor needs a RAVEL source checkout (set RAVEL_ROOT or run inside it)")
        manifest, catalog = mf.load(repo)
        prefix = resolve_prefix(repo, args.prefix, environ)
        platform_key = mf.detect_platform()
        doctor = Doctor(repo, prefix, platform_key, manifest, catalog, environ=environ, run_probe=run_probe)
        if args.record_host_config:
            host_config.record(doctor.values["CONFIG"], doctor.environ.get("HOME") or str(Path.home()), replace=True)
        report = doctor.report(select_groups(manifest, profile=args.profile, groups=args.group, mode=args.mode),
                               profile=(args.profile or "default") if not (args.group or args.mode) else None)
        if args.census:
            report['tool_census'] = doctor.census_report()
            report['ready'] = report['ready'] and all(row['readiness'] in OK_STATUSES or row['readiness'] == 'excluded'
                                                     for row in report['tool_census'])
    except mf.ManifestError as error:
        print("ravel doctor: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 1 if not report["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
