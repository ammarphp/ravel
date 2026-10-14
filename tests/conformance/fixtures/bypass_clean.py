# census-module: ravel.workflow.synthetic_caller
"""Look-alikes that are not agent call sites."""
import re
import subprocess


def pattern():
    return re.compile(r"\d+")


def listing(path):
    return subprocess.run(["ls", path], capture_output=True)


def settings():
    return {"instructions_path": "docs/readme.md"}
