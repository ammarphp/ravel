# Review record

```json
{
  "skill": "snakemake-workflows",
  "reviewed": "2026-10-13",
  "reviewer": "machine",
  "sources": [
    "native/setup/toolchain-manifest.json: site-root-wms",
    "src/ravel/workflow/agent_surface.py: policy and shell discipline interfaces",
    "src/ravel/workflow/wms_runtime.py: separate environment resolution",
    "docs/reference/site-workflows.md: retained procedure export contract"
  ],
  "tested_versions": {},
  "executable_blocks": ["workflow-route-check"],
  "illustrative_blocks": [],
  "limits": [
    "The Python example is tested against synthetic policy files only.",
    "Workflow-manager launch, retry and site-record interfaces require integration with their owners.",
    "No native tool, scheduler, remote site or network was exercised."
  ]
}
```
