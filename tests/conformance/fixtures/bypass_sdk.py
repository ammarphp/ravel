# census-module: ravel.workflow.synthetic_caller
"""Provider SDK and upstream loop imports, direct and dynamic."""
import importlib


def direct_import():
    import anthropic
    return anthropic


def dynamic_import():
    return importlib.import_module("anthropic")


def from_import():
    from openai import OpenAI
    return OpenAI


def upstream_loop(core, agents):
    return core.ReviewLoop(agents["a"], agents["b"])


def upstream_package():
    import autogen
    return autogen
