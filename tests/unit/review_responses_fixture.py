from copy import deepcopy
import threading,json
from ravel.workflow import execution
SCHEMA={"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"],"additionalProperties":False}

class Control:
    def __init__(self):
        self.cancel = threading.Event()
        self.calls = []
        self.saved = {}

    def cancelled(self):
        return self.cancel.is_set()

    def check_cancelled(self):
        if self.cancelled():
            raise RuntimeError("canceled")

    def call(self, label, kind, request, function, output_tokens=0):
        key = (label, execution.digest(request))
        if key in self.saved:
            return deepcopy(self.saved[key])
        self.calls.append({"label": label, "kind": kind, "request": deepcopy(request), "output_tokens": output_tokens})
        value = function()
        self.saved[key] = deepcopy(value)
        return value

def node(*, action="responses", role="proposer", inputs=(), packet=None, parameters=None):
    return {"id": "n1", "kind": "model", "role": role, "depends_on": [], "inputs": list(inputs), "packet": packet,
            "action": action, "parameters": parameters or {"instructions": "Inspect public evidence and return the answer.",
                "model": "requested-model", "reasoning_effort": "low", "max_output_tokens": 120,
                "output_schema": deepcopy(SCHEMA)}, "max_attempts": 1}

def request(n):
    return {"schema_version": 1, "graph_id": "g", "graph_revision": "a" * 64, "node_id": n["id"],
            "generation": 1, "node_sha256": execution.digest(n), "request_id": "b" * 64,
            "input_artifacts": deepcopy(n["inputs"]), "packet": deepcopy(n["packet"]), "dependencies": []}

def response(value=None, **changes):
    result = {"id": "resp-public", "model": "requested-model-snapshot", "status": "completed",
              "usage": {"input_tokens": 13, "output_tokens": 7, "total_tokens": 20,
                        "output_tokens_details": {"reasoning_tokens": 5}},
              "output": [{"type": "reasoning", "summary": [{"text": "PRIVATE-CANARY"}],
                          "encrypted_content": "ENCRYPTED-CANARY"},
                         {"type": "message", "role": "assistant", "status": "completed",
                          "content": [{"type": "output_text", "text": json.dumps(value or {"answer": "supported fixture"}),
                                      "annotations": [{"canary": "ANNOTATION-CANARY"}]}]}]}
    result.update(changes)
    return result
