"""Include workflow instructions and required installation assets."""
from pathlib import Path
from runpy import run_path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# The exporter reads this hook-owned census from the release tree.
SUBMISSION_INPUTS = 'src/ravel/submission_build.py'


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        run_path(str(Path(self.root) / SUBMISSION_INPUTS))['initialize'](self, build_data)
