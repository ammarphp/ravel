"""Package only the curated replay inputs, never an entire research run directory."""
from pathlib import Path
import runpy

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        select = runpy.run_path(str(root / "src/ravel/resources.py"))["payload_files"]
        # Preserve repository-relative paths and fail if an exported checkout lacks inputs.
        for relative in select(root):
            destination = (f"ravel/_payload/{relative}" if self.target_name == "wheel"
                           else relative)
            build_data["force_include"][str(root / relative)] = destination
