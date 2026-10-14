# census-module: ravel.workflow.cli_agent_host
"""Model CLI launches planted inside the sanctioned CLI host module."""
import subprocess


def rogue_literal(prompt):
    return subprocess.run(["claude", "-p", prompt], capture_output=True)


def rogue_assembled(prompt):
    argv = ["codex", "exec"]
    argv += [prompt]
    return subprocess.Popen(argv)


def rogue_template(prompt):
    return subprocess.run(f"gemini -p {prompt}", shell=True)


def harmless(path):
    return subprocess.run(["ls", path])
