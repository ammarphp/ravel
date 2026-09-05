"""Include only curated replay data; Python engines are normal package modules."""
from pathlib import Path
import sys

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        sys.path.insert(0, str(root / "src"))
        try:
            from ravel.evidence_layout import resolve
            from ravel.resources import payload_files
            data_root = root / "src/ravel/data/replay"
            if not (data_root / "benchmarks/cases.json").is_file():
                data_root = root
            for relative in payload_files(data_root):
                destination = (f"ravel/data/replay/{relative}" if self.target_name == "wheel"
                               else f"src/ravel/data/replay/{relative}")
                build_data["force_include"][str(resolve(data_root, relative))] = destination
        finally:
            sys.path.pop(0)
