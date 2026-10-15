"""Install RAVEL's toolchain from the manifest: plan, run, resume.

Usage (normally through ``bash scripts/setup/install.sh``)::

    install.py            # install everything for this platform
    install.py --plan # show the ordered steps, change nothing
    install.py --only madgraph,lhapdf-sets
    install.py --resume                  # continue after a failure

The installer writes only inside the prefix (default ``<repo>/native/build``),
the repository's ``.venv*`` environments and ``.ravel/native-prefix``. It never
edits shell start-up files, conda or container configuration in your home
directory, Wolfram settings or agent configuration.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import shlex

from . import host_config
from . import manifest as mf
from .fetch import DigestMismatch, FetchError, Fetcher
from .state import InstallState, LockedError, RunLog, install_lock, write_receipt, utc_stamp
from .steps import Conflict, Context, Deferred, Runner, StepError, fingerprint, outputs, run_step, \
    subprocess_environment

POINTER = ".ravel/native-prefix"
GPL_LIKE = ("GPL", "LGPL", "AGPL", "NCSA", "LicenseRef")


def default_prefix(repo):
    repo = Path(repo)
    legacy = repo / "stages/01-event-generation/build"
    return legacy if legacy.is_dir() else repo / "native/build"


def resolve_prefix(repo, explicit=None, environ=None):
    """--prefix > RAVEL_NATIVE_BUILD > .ravel/native-prefix > legacy build > native/build."""
    environ = os.environ if environ is None else environ
    repo = Path(repo)
    if explicit:
        prefix = Path(explicit).expanduser()
    elif environ.get("RAVEL_NATIVE_BUILD"):
        prefix = Path(environ["RAVEL_NATIVE_BUILD"]).expanduser()
    elif (repo / POINTER).is_file():
        prefix = Path((repo / POINTER).read_text(encoding="utf-8").strip()).expanduser()
    else:
        prefix = default_prefix(repo)
    prefix = Path(os.path.abspath(prefix))
    if any(ch.isspace() for ch in str(prefix)):
        raise mf.ManifestError(f"the prefix {prefix} contains whitespace, which Miniforge refuses; "
                               f"choose another with --prefix")
    return prefix


def container_engine(prefix, platform_key, environ=None, which=shutil.which):
    environ = os.environ if environ is None else environ
    if environ.get("RAVEL_CONTAINER_ENGINE"):
        return environ["RAVEL_CONTAINER_ENGINE"]
    if platform_key.startswith("macos"):
        return str(Path(prefix) / "bin/ravel-podman")
    for name in ("podman", "docker", "apptainer", "singularity"):
        found = which(name)
        if found:
            return found
    return "podman"


class Installer:
    def __init__(self, repo, prefix, *, platform_key=None, manifest=None, catalog=None, runner=None,
                 fetcher=None, jobs=None, offline=False, adopt=False, environ=None, stream=None,
                 accept_licenses=False, interactive=None):
        self.repo = Path(repo)
        self.prefix = Path(prefix)
        if manifest is None:
            manifest, catalog = mf.load(self.repo)
        self.manifest, self.catalog = manifest, catalog
        self.platform = platform_key or mf.detect_platform()
        environ = os.environ if environ is None else environ
        self.values = mf.variables(self.prefix, self.repo, self.platform, jobs=jobs,
                                   container_engine=container_engine(self.prefix, self.platform, environ),
                                   installer_python=sys.executable)
        self.values['LCG_VIEW'] = environ.get('RAVEL_LCG_VIEW', '')
        self.runner = runner or Runner()
        self.fetcher = fetcher or Fetcher(self.prefix / "downloads", offline=offline)
        self.adopt = adopt
        self.environ = environ
        self.stream = stream or sys.stdout
        self.accept_licenses = accept_licenses
        self.interactive = sys.stdin.isatty() if interactive is None else interactive

    # ------------------------------------------------------------ planning
    def groups(self, profile=None, only=None, skip=None):
        return mf.profile_groups(self.manifest, profile, only=only, skip=skip)

    def plan(self, profile=None, only=None, skip=None):
        """Ordered steps for this platform with their current state; changes nothing."""
        state = InstallState(self.prefix) if (self.prefix / "state/install-state.json").is_file() else None
        rows = []
        byid = mf.by_id(self.manifest)
        for gid in self.groups(profile, only, skip):
            group = byid[gid]
            route = mf.route_for(group, self.platform)
            entry = {"group": gid, "title": group["title"], "route": route, "size_gb": group["size_gb"],
                     "minutes": group["minutes"], "licenses": group.get("licenses", []), "steps": []}
            if route in ("remote", "unsupported", "manual"):
                entry["note"] = group.get("manual") or group.get("notes", "")
            else:
                for step in group["steps"]:
                    if not mf.applies(step, self.platform):
                        continue
                    key = gid + "/" + step["id"]
                    expanded = mf.expand(step, self.values)
                    status = "pending"
                    if state and state.get(key):
                        recorded = state.get(key)
                        if recorded.get("fingerprint") == fingerprint(gid, step, self.values, self.repo, self.catalog):
                            status = recorded.get("status", "pending")
                    item = {"id": step["id"], "kind": step["kind"], "state": status}
                    for field in ("url", "commit", "dest", "name", "image", "digest", "recipe", "argv", "size", "path",
                                  "instruction"):
                        if field in expanded:
                            item[field] = expanded[field]
                    if step["kind"] == "pdf_sets":
                        item["sets"] = [s["name"] for s in self.catalog["sets"]]
                    entry["steps"].append(item)
            rows.append(entry)
        return {"platform": self.platform, "prefix": str(self.prefix), "groups": rows,
                "disk_gb": round(sum(r["size_gb"] for r in rows), 1),
                "minutes": sum(r["minutes"] for r in rows)}

    # ------------------------------------------------------------ dry run
    def _fetches(self, step, expanded):
        """(network, urls) for one step: yes with the sources, no, or possible when a recipe decides."""
        kind = step["kind"]
        if kind in ("git", "archive", "download"):
            return "yes", [expanded["url"]]
        if kind == "miniforge":
            asset = self.manifest["miniforge"]["assets"].get(self.platform)
            if asset:
                return "yes", [mf.expand(self.manifest["miniforge"]["url"], {"asset": asset["name"]})]
            return "yes", [self.manifest["miniforge"]["url"]]
        if kind == "container_pull":
            return "yes", [f"{expanded['image']}@{expanded['digest']}"]
        if kind == "conda_env":
            urls = ["conda-forge (conda channel)"]
            return "yes", urls + (["PyPI"] if step.get("pip") else [])
        if kind == "pip":
            extra = [o for o in step.get("options", []) if o.startswith("http")]
            return "yes", ["PyPI"] + extra
        if kind == "pdf_sets":
            return "yes", [self.catalog["base_url"] + "/" + s["name"] + ".tar.gz" for s in self.catalog["sets"]]
        if kind in ("container_build", "command"):
            return "possible", []
        return "no", []

    def dry_run(self, profile=None, only=None, skip=None):
        """Every action an install would take: prefix, size estimate, network fetches. Changes nothing."""
        plan = self.plan(profile, only, skip)
        byid = mf.by_id(self.manifest)
        actions = []
        for entry in plan["groups"]:
            group = byid[entry["group"]]
            if not entry["steps"]:
                actions.append({"group": entry["group"], "step": None, "kind": entry["route"], "network": "no",
                                "fetch": [], "writes": None, "state": "pending",
                                "what": entry.get("note") or "no local step on this platform"})
                continue
            steps = {s["id"]: s for s in group["steps"]}
            for item in entry["steps"]:
                step = steps[item["id"]]
                expanded = mf.expand(step, self.values)
                network, urls = self._fetches(step, expanded)
                written = outputs(step, self.values)
                what = item.get("url") or item.get("image") or item.get("name") or item.get("dest") or \
                    item.get("path") or (" ".join(item["argv"]) if item.get("argv") else "") or \
                    item.get("instruction", "") or (urls[0] if urls else step["kind"])
                actions.append({"group": entry["group"], "step": item["id"], "kind": item["kind"],
                                "what": what, "network": network, "fetch": urls, "state": item["state"],
                                "writes": str(written[0]) if written else None,
                                **({"bytes": step["size"]} if step.get("size") else {})})
        prefix = self.prefix
        return {"mode": "dry-run", "profile": profile or ("custom" if only else "default"), "platform": plan["platform"],
                "prefix": plan["prefix"], "groups": plan["groups"], "actions": actions,
                "network_fetches": sorted({u for a in actions for u in a["fetch"]}),
                "fixed_writes": [str(prefix / "state/install-state.json"), str(prefix / "logs"),
                                 str(prefix / "receipts"), str(prefix / "config/ravel-env.sh"),
                                 str(prefix / "downloads"), str(self.repo / POINTER) + " (non-default prefix only)"],
                "disk_gb": plan["disk_gb"], "minutes": plan["minutes"],
                "size_basis": "manifest estimate; measured disk and time come from the root queue job"}

    # ------------------------------------------------------------ licences
    def _licences(self, group_ids, state):
        byid = mf.by_id(self.manifest)
        pending = []
        for gid in group_ids:
            for licence in byid[gid].get("licenses", []):
                key = gid + ":" + licence["component"]
                if key not in state.data["licenses_accepted"]:
                    pending.append((key, licence))
        if not pending:
            self.license_acceptance = "recorded"
            return True
        self.say("These components are fetched from their upstream sources under their own licences "
                 "(nothing is redistributed by RAVEL):")
        for _, licence in pending:
            self.say(f"  {licence['component']}: {licence['spdx']}" +
                     (f" ({licence['source']})" if licence.get("source") else ""))
        accepted = self.accept_licenses
        if not accepted and self.interactive:
            answer = input("Install them? [y/N] ").strip().lower()
            accepted = answer in ("y", "yes")
        if not accepted:
            self.say("Licences not accepted. Rerun with --accept-licenses to continue.")
            return False
        for key, licence in pending:
            state.data["licenses_accepted"][key] = {"spdx": licence["spdx"], "accepted": utc_stamp(),
                                                     "method": "flag" if self.accept_licenses else "prompt"}
        self.license_acceptance = "flag" if self.accept_licenses else "prompt"
        state.save()
        return True

    def say(self, text):
        print(text, file=self.stream, flush=True)

    # ------------------------------------------------------------ running
    def run(self, profile=None, only=None, skip=None):
        """Install the selected groups. Returns a summary dict; never raises for step failures."""
        group_ids = self.groups(profile, only, skip)
        byid = mf.by_id(self.manifest)
        self.prefix.mkdir(parents=True, exist_ok=True)
        with install_lock(self.prefix):
            state = InstallState(self.prefix)
            log = RunLog(self.prefix)
            # Baseline digests of the agent host configuration; the installer never edits those files.
            host_config.record(self.values["CONFIG"], self.environ.get("HOME") or str(Path.home()))
            if not self._licences(group_ids, state):
                return {"status": "licences_not_accepted", "log_dir": str(log.directory)}
            env = subprocess_environment(self.prefix, self.values, self.environ)
            for key in ('APPTAINER_CACHEDIR','APPTAINER_TMPDIR',*(('TMPDIR',) if self.platform.startswith('linux') else ())):
                Path(env[key]).mkdir(parents=True,exist_ok=True)
            ctx = Context(prefix=self.prefix, repo=self.repo, platform_key=self.platform, values=self.values,
                          runner=self.runner, fetcher=self.fetcher, manifest=self.manifest, catalog=self.catalog,
                          base_env=env, adopt=self.adopt)
            ctx.install_authority = {"kind": "installer-command", "authority": "installer",
                                     "command": getattr(self, "invocation", shlex.split(self._rerun_command(profile, only, skip))),
                                     "command_source": "invocation" if hasattr(self, "invocation") else "normalized-install-options",
                                     "license_acceptance": self.license_acceptance,
                                     "licenses": dict(state.data["licenses_accepted"])}
            if self.accept_licenses and not hasattr(self, "invocation"):
                ctx.install_authority["command"].append("--accept-licenses")
            blocked = {}
            result = {"status": "complete", "groups": {}, "failed": []}
            result["rerun"] = self._rerun_command(profile, only, skip)
            for gid in group_ids:
                group = byid[gid]
                route = mf.route_for(group, self.platform)
                waiting = [d for d in group["depends_on"] if d in blocked]
                if waiting:
                    blocked[gid] = "waits for " + ", ".join(waiting)
                    result["groups"][gid] = {"status": "deferred", "reason": blocked[gid]}
                    log.event(gid, "deferred", reason=blocked[gid])
                    self.say(f"[deferred] {gid}: {blocked[gid]}")
                    continue
                if route in ("remote", "unsupported", "manual"):
                    note = group.get("manual") or ""
                    result["groups"][gid] = {"status": route, "note": note}
                    log.event(gid, route, note=note)
                    self.say(f"[{route}] {gid}: {note}".rstrip(": "))
                    if route in ("manual", "unsupported"):
                        blocked[gid] = route
                    continue
                outcome = self._run_group(group, ctx, state, log)
                result["groups"][gid] = outcome
                if outcome["status"] == "deferred":
                    blocked[gid] = outcome.get("reason", "deferred")
                if outcome["status"] in ("failed", "conflict", "digest_mismatch"):
                    blocked[gid] = outcome["status"]
                    result["failed"].append({"group": gid, **outcome})
            if result["failed"]:
                result["status"] = "incomplete"
            elif blocked:
                result["status"] = "complete_with_deferred"
            result["log_dir"] = str(log.directory)
            result["summary"] = str(log.write_summary(status=result["status"], platform=self.platform,
                                                      prefix=str(self.prefix), groups=result["groups"],
                                                      failed=result["failed"], rerun=result["rerun"]))
            self._write_env_file()
            self.say("Check readiness with: .venv/bin/ravel doctor" + (f" --profile {profile}" if profile and not only else ""))
            self.say(f"\nInstall {result['status'].replace('_', ' ')}. Logs: {log.directory}")
            for failure in result["failed"]:
                self.say(f"[failure] {failure['step']}: {failure['error']}\n"
                         f"          log: {failure['log']}\n          fix: {failure['fix']}")
            for gid in group_ids:
                if gid in blocked and gid not in {f['group'] for f in result['failed']}:
                    self.say(f"[blocked] {gid}: {blocked[gid]}")
            if blocked:
                self.say("Rerun: " + result["rerun"] + "\nFinished steps are skipped.")
            return result

    def _rerun_command(self, profile, only, skip):
        """The install command that resumes this run's selection with the same options."""
        argv = ["bash", "scripts/setup/install.sh", "--prefix", str(self.prefix), "--resume"]
        if only:
            argv += ["--only", ",".join(only)]
        elif profile:
            argv += ["--profile", profile]
        if skip:
            argv += ["--skip", ",".join(skip)]
        argv += ["--jobs", self.values["JOBS"]]
        if self.fetcher.offline:
            argv.append("--offline")
        if self.adopt:
            argv.append("--adopt")
        return shlex.join(argv)

    def _run_group(self, group, ctx, state, log):
        gid = group["id"]
        receipt = {"group": gid, "title": group["title"], "platform": self.platform,
                   "licenses": group.get("licenses", []), "steps": {}, "updated": utc_stamp()}
        for step in group["steps"]:
            if not mf.applies(step, self.platform):
                continue
            key = gid + "/" + step["id"]
            digest = fingerprint(gid, step, self.values, self.repo, self.catalog)
            recorded = state.get(key)
            produced = outputs(step, self.values)
            if (not step.get("revalidate") and recorded and recorded.get("status") == "done" and recorded.get("fingerprint") == digest
                    and all(p.exists() for p in produced)):
                receipt["steps"][step["id"]] = recorded.get("detail", {})
                log.event(key, "skip", reason="verified")
                self.say(f"[skip] {key} (verified)")
                continue
            ctx.log = log.step_log(key)
            ctx.log.touch(exist_ok=True)
            self.say(f"[run ] {key}")
            try:
                detail = run_step(step, ctx)
            except Deferred as reason:
                state.record(key, status="deferred", fingerprint=digest, detail={"reason": str(reason)})
                log.event(key, "deferred", reason=str(reason))
                self.say(f"[wait] {key}: {reason}")
                self._write_receipt(gid, receipt)
                return {"status": "deferred", "reason": str(reason), "step": key}
            except (StepError, FetchError, OSError, ValueError) as error:
                status = "digest_mismatch" if isinstance(error, DigestMismatch) else \
                         "conflict" if isinstance(error, Conflict) else "failed"
                fix = step.get("instruction") or (
                    "Move the conflicting destination aside; its files were preserved." if status == "conflict" else
                    "Remove the bad cached download and obtain the source matching the manifest digest; the bad file is quarantined."
                    if status == "digest_mismatch" else f"Read {ctx.log} and resolve the reported command error: {error}")
                fix += " Then run: " + self._rerun_command(None, [gid], None)
                with ctx.log.open("a", encoding="utf-8") as handle:
                    handle.write(f"{status}: {error}\nfix: {fix}\n")
                state.record(key, status="conflict" if status == "conflict" else "failed", fingerprint=digest,
                             log=str(ctx.log), detail={"error": str(error), "fix": fix})
                log.event(key, status, error=str(error), log=str(ctx.log), fix=fix)
                self._write_receipt(gid, receipt)
                self.say(f"[FAIL] {key}; continuing independent groups")
                return {"status": status, "error": str(error), "step": key, "log": str(ctx.log), "fix": fix}
            state.record(key, status="done", fingerprint=digest, log=str(ctx.log), detail=detail)
            receipt["steps"][step["id"]] = detail
            log.event(key, "done")
        self._write_receipt(gid, receipt)
        return {"status": "done"}

    def _write_receipt(self, gid, receipt):
        write_receipt(self.prefix, gid, receipt)

    def _write_env_file(self):
        """$P/config/ravel-env.sh: a file users may source by hand. Nothing sources it automatically."""
        lines = ["# owned by the RAVEL installer; source it to use this toolchain in a shell",
                 f"export RAVEL_NATIVE_BUILD={self.values['P']}",
                 f"export RAVEL_NATIVE_BIN={self.values['BIN']}",
                 f"export RAVEL_CONTAINER_ENGINE={self.values['CONTAINER_ENGINE']}",
                 f"export APPTAINER_CACHEDIR={self.prefix}/cache/apptainer",
                 f"export APPTAINER_TMPDIR={self.prefix}/tmp/apptainer"]
        if self.platform.startswith('linux'):
            lines.append(f"export TMPDIR={self.prefix}/tmp")
        for key, value in sorted(self.manifest.get("environment", {}).items()):
            lines.append(f"export {key}={mf.expand(value, self.values)}")
        path = self.prefix / "config/ravel-env.sh"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pointer(repo, prefix):
    """Record a non-default prefix so paths.sh, paths.py and the doctor find it."""
    repo, prefix = Path(repo), Path(prefix)
    pointer = repo / POINTER
    if prefix == default_prefix(repo):
        return None
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(prefix) + "\n", encoding="utf-8")
    return pointer


def format_plan(plan):
    lines = [f"Platform {plan['platform']}, prefix {plan['prefix']}",
             f"About {plan['disk_gb']} GB and {plan['minutes']} minutes in total.", ""]
    for group in plan["groups"]:
        lines.append(f"{group['group']} ({group['route']}, ~{group['size_gb']} GB, ~{group['minutes']} min): "
                     f"{group['title']}")
        if group.get("note"):
            lines.append("    " + group["note"])
        for step in group["steps"]:
            what = step.get("url") or step.get("image") or step.get("name") or step.get("dest") or \
                step.get("path") or (" ".join(step["argv"]) if step.get("argv") else "") or step.get("instruction", "")
            extra = f" @ {step['commit'][:12]}" if step.get("commit") else ""
            if step.get("sets"):
                what = ", ".join(step["sets"])
            lines.append(f"    [{step['state']}] {step['id']} ({step['kind']}) {what}{extra}")
    return "\n".join(lines)


def format_dry_run(plan):
    lines = [f"DRY RUN ({plan['profile']}): nothing is downloaded, built or written.",
             f"Platform {plan['platform']}, prefix {plan['prefix']}",
             f"Estimate {plan['disk_gb']} GB and {plan['minutes']} minutes ({plan['size_basis']}).", ""]
    for group in plan["groups"]:
        lines.append(f"{group['group']} ({group['route']}, ~{group['size_gb']} GB, ~{group['minutes']} min): "
                     f"{group['title']}")
        for action in (a for a in plan["actions"] if a["group"] == group["group"]):
            tag = {"yes": "network", "possible": "network?", "no": "local"}[action["network"]]
            lines.append(f"    [{tag}] {action['step'] or action['kind']} ({action['kind']}) {action['what']}")
    lines += ["", f"Network fetches ({len(plan['network_fetches'])}):"] + ["    " + u for u in plan["network_fetches"]]
    lines += ["", "Also written by a real install:"] + ["    " + w for w in plan["fixed_writes"]]
    return "\n".join(lines)


def parser():
    ap = argparse.ArgumentParser(prog="install.py", description="Install RAVEL's complete toolchain.")
    ap.add_argument("--profile", choices=["site"], help="Linux analysis facility target; omit for the default toolchain")
    ap.add_argument("--only", help="comma-separated groups (their dependencies are included)")
    ap.add_argument("--skip", help="comma-separated groups to leave out")
    ap.add_argument("--prefix", help="where tools are installed (default: <repo>/native/build)")
    ap.add_argument('--lcg-view',help="site: explicit LCG view path or none; auto lists candidates and refuses")
    ap.add_argument("--plan", action="store_true", help="print the ordered steps and change nothing")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="print every action, the prefix, size estimates and network fetches; change nothing")
    ap.add_argument("--json", action="store_true", help="machine-readable --plan, --dry-run or summary")
    ap.add_argument("--resume", action="store_true", help="continue after a failure (finished steps are skipped)")
    ap.add_argument("--offline", action="store_true", help="use only the download cache")
    ap.add_argument("--adopt", action="store_true", help="keep existing environments and checkouts as they are")
    ap.add_argument("--jobs", type=int, help="build parallelism (default: half the cores)")
    ap.add_argument("--accept-licenses", action="store_true", help="accept the upstream licences non-interactively")
    ap.add_argument("--yes", action="store_true", help="do not ask questions (licences still need --accept-licenses)")
    return ap


def main(argv=None, *, repo=None):
    args = parser().parse_args(argv)
    repo = Path(repo or mf.repo_root())
    try:
        prefix = resolve_prefix(repo, args.prefix)
        environ = dict(os.environ)
        if args.lcg_view is not None:environ['RAVEL_LCG_VIEW'] = args.lcg_view
        installer = Installer(repo, prefix, jobs=args.jobs, offline=args.offline, adopt=args.adopt,
                              accept_licenses=args.accept_licenses, interactive=False if args.yes else None,environ=environ)
        installer.invocation = ["bash", "scripts/setup/install.sh", *(sys.argv[1:] if argv is None else argv)]
        only = [g for g in (args.only or "").split(",") if g]
        skip = [g for g in (args.skip or "").split(",") if g]
        if args.dry_run:
            plan = installer.dry_run(args.profile if not only else None, only or None, skip)
            print(json.dumps(plan, indent=2) if args.json else format_dry_run(plan))
            return 0
        if args.plan:
            plan = installer.plan(args.profile, only or None, skip)
            print(json.dumps(plan, indent=2) if args.json else format_plan(plan))
            return 0
        if args.profile == 'site':
            from ravel.workflow.site_doctor import Host, location_check
            from ravel.workflow.site_contract import lock_packages
            import importlib.util
            spec = importlib.util.spec_from_file_location('ravel_site_install_preflight',repo/'scripts/setup/site_installation.py')
            helper = importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
            choice=helper.lcg_choice(environ.get('RAVEL_LCG_VIEW'),prefix=prefix)
            lock_packages(repo/'requirements-site-wms.lock')
            row=location_check('prefix',prefix,host=Host(),threshold_gb=installer.manifest['profiles']['site']['disk_gb'])
            if row['status']=='fail':raise mf.ManifestError(row['detail']+'; '+row['fix'])
            helper.check_campaign(prefix,helper.release_id(repo),choice)
        write_pointer(repo, prefix)
        result = installer.run(args.profile, only or None, skip)
    except (mf.ManifestError, LockedError, ValueError) as error:
        print("install: " + str(error), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif result["status"] == "licences_not_accepted":
        print(f"Install licences not accepted. Logs: {result.get('log_dir')}")
    return 0 if result["status"] in ("complete", "complete_with_deferred") else 1


if __name__ == "__main__":
    raise SystemExit(main())
