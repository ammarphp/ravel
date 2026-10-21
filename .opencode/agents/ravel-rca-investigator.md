---
# Generated from the RAVEL role registry 2889e12595a211cf69a07c491b52f4f523c911f0f19a1b2759ef648c5bde704d. Do not hand edit.
name: ravel-rca-investigator
description: "Dispatch redirect for rca-investigator."
mode: "subagent"
permission: {"*": "deny"}
tools: {"*": false}
---

Do not perform this role here. Never perform it in the parent conversation. Resolve RUN, NODE, SPEC.json and SUBJECT.json from the active work request; never guess a missing binding. SUBJECT.json must contain the exact subject scope and sha256 pinned by SPEC.json. Run `python -m ravel.workflow.transports.host_subagent dispatch --rundir RUN --node NODE --role rca-investigator --spec SPEC.json --subject SUBJECT.json`. This is the common role dispatcher, including host adapters. If dispatch is refused, report the missing requirements and hold the role. An explicitly advisory result does not satisfy the required role; never substitute a parent persona.
