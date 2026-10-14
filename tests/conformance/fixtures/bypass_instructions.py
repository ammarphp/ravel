# census-module: ravel.workflow.synthetic_caller
"""Instruction literals handed to a model node instead of a rendered card."""


def literal_dict(context):
    return {"instructions": "Review the synthetic plan and list its defects.", "context": context}


def literal_subscript(parameters):
    parameters["instructions"] = "Summarize the synthetic result in two sentences."
    return parameters


def rendered(parameters, role_registry, card):
    parameters["instructions"] = role_registry.render("governed-node")[card]
    return parameters


def bound_then_used(model):
    instructions = f"Judge the synthetic claim as reviewer {model}. "
    instructions += "Return the declared schema."
    return {"parameters": {"instructions": instructions, "model": model}}


def from_prompt_file(instruction):
    from ravel.workflow.research_protocol import instruction as prompt
    return {"instructions": prompt("synthetic_step")}
