#!/usr/bin/env python3
"""ravel-task: command-line client for the task service (operations are described in tools.md).

Reads RAVEL_TASK_ENDPOINT and RAVEL_TASK_TOKEN from the environment, sends one
operation and prints the service's JSON response on standard output. Exit status:
0 when the response is ok, 3 when the service returned an error, 2 for a usage
error, 4 when the service cannot be reached. Talks only to a loopback endpoint and
never through a proxy. Standard library only (Python 3.8+).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
TIMEOUT_SECONDS = 1800


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
    return load_object(args.file)


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
        return usage_error(f"cannot read {args.file}: {exc}")
    request = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Ravel-Task-Token": token})
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
