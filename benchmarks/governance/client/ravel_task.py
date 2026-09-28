#!/usr/bin/env python3
"""ravel-task: command-line client for the task service (operations are described in tools.md).

Reads RAVEL_TASK_ENDPOINT and RAVEL_TASK_TOKEN from the environment, sends one
operation and prints the service's JSON response on standard output. Exit status:
0 when the response is ok, 3 when the service returned an error, 2 for a usage
error, 4 when the service cannot be reached. Talks only to a loopback endpoint and
never through a proxy. Each request also reports the NAMES (never the values) of
the variables in this process's environment, in the X-Ravel-Client-Env header.
Standard library only (Python 3.8+).
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
TIMEOUT_SECONDS = 1800
ENV_HEADER = "X-Ravel-Client-Env"
ENV_HEADER_LIMIT = 8192
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parser():
    p = argparse.ArgumentParser(prog="ravel-task", description="Client for the task service.")
    ops = p.add_subparsers(dest="op", metavar="operation")
    ops.required = True
    ops.add_parser("inputs", help="list current inputs and prior artifacts")
    ops.add_parser("status", help="show used and remaining operations and submissions")
    show = ops.add_parser("show", help="show one artifact")
    show.add_argument("handle")
    fit = ops.add_parser("fit", help="fit a workspace")
    fit.add_argument("--workspace", required=True, metavar="HANDLE")
    convert = ops.add_parser("convert", help="convert a fit with a luminosity record")
    convert.add_argument("--fit", required=True, metavar="HANDLE")
    convert.add_argument("--luminosity", required=True, metavar="HANDLE")
    report = ops.add_parser("report", help="render a report from a conversion and a title")
    report.add_argument("--conversion", required=True, metavar="HANDLE")
    report.add_argument("--title", required=True, metavar="HANDLE")
    census = ops.add_parser("census", help="check an event sample and apply a selection")
    census.add_argument("--events", required=True, metavar="HANDLE")
    census.add_argument("--manifest", required=True, metavar="HANDLE")
    census.add_argument("--selection", required=True, metavar="HANDLE")
    calc = ops.add_parser("calc", help="record a product or quotient of bound artifact values")
    calc.add_argument("--expr", required=True, metavar="EXPRESSION")
    calc.add_argument("--bind", required=True, action="append", metavar="NAME=HANDLE:FIELD")
    calc.add_argument("--unit", required=True)
    calc.add_argument("--label")
    submit = ops.add_parser("submit", help="submit claims and a report (JSON file)")
    submit.add_argument("file")
    note = ops.add_parser("note", help="record a decision note (JSON file)")
    note.add_argument("file")
    return p


def usage_error(message):
    print(f"ravel-task: {message}", file=sys.stderr)
    return 2


def load_object(path):
    """Strict JSON object: no duplicate keys, no NaN or Infinity."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    with open(path, encoding="utf-8") as handle:
        value = json.load(handle, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def environment_names():
    """The sorted variable names of this process's environment, comma-separated (names only, never values),
    with a final "!invalid" when some name is not a plain identifier (it is left out); "!overflow" past
    ENV_HEADER_LIMIT bytes."""
    names = sorted(n for n in os.environ if NAME.fullmatch(n))
    if len(names) != len(os.environ):
        names.append("!invalid")
    report = ",".join(names)
    return report if len(report) <= ENV_HEADER_LIMIT else "!overflow"


def arguments(args):
    if args.op in ("inputs", "status"):
        return {}
    if args.op == "show":
        return {"handle": args.handle}
    if args.op == "fit":
        return {"workspace": args.workspace}
    if args.op == "convert":
        return {"fit": args.fit, "luminosity": args.luminosity}
    if args.op == "report":
        return {"conversion": args.conversion, "title": args.title}
    if args.op == "census":
        return {"events": args.events, "manifest": args.manifest, "selection": args.selection}
    if args.op == "calc":
        return {"expr": args.expr, "bind": bindings(args.bind), "unit": args.unit, "label": args.label}
    return load_object(args.file)


def bindings(values):
    """{name: {handle, field}} of repeated --bind NAME=HANDLE:FIELD options."""
    result = {}
    for value in values:
        name, _, rest = value.partition("=")
        handle, _, field = rest.partition(":")
        if not name or not handle or not field:
            raise ValueError(f"--bind {value!r}: expected NAME=HANDLE:FIELD")
        if name in result:
            raise ValueError(f"--bind: {name} is bound twice")
        result[name] = {"handle": handle, "field": field}
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    endpoint, token = os.environ.get("RAVEL_TASK_ENDPOINT"), os.environ.get("RAVEL_TASK_TOKEN")
    if not endpoint or not token:
        return usage_error("RAVEL_TASK_ENDPOINT and RAVEL_TASK_TOKEN must be set")
    try:
        parts = urllib.parse.urlsplit(endpoint)
        local = parts.scheme == "http" and parts.hostname in LOOPBACK and parts.port is not None
    except ValueError:
        local = False
    if not local:
        return usage_error("RAVEL_TASK_ENDPOINT must be an http loopback URL with a port")
    try:
        body = json.dumps({"op": args.op, "args": arguments(args)}, allow_nan=False).encode()
    except (OSError, ValueError) as exc:
        return usage_error(f"cannot read {args.file}: {exc}" if hasattr(args, "file") else str(exc))
    request = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Ravel-Task-Token": token, ENV_HEADER: environment_names()})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
    except (urllib.error.URLError, OSError) as exc:
        print(f"ravel-task: service unreachable: {exc}", file=sys.stderr)
        return 4
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
            raise ValueError("not a service response")
    except ValueError as exc:
        print(f"ravel-task: invalid response from the service: {exc}", file=sys.stderr)
        return 4
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
