"""Include workflow instructions and required installation assets."""
from pathlib import Path
import importlib
import sys
import types

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        # Bind selectors to this build's source even when another ravel was
        # imported by the caller. A private namespace avoids cache interference
        # without removing or replacing the caller's ordinary ravel modules.
        namespace = f"_ravel_build_payload_{id(self):x}"
        if namespace in sys.modules:
            raise RuntimeError("build payload namespace is already occupied")
        package = types.ModuleType(namespace)
        package.__path__ = [str(root / "src/ravel")]
        sys.modules[namespace] = package
        try:
            # Full Python requirements and required isolated-engine/native setup
            # source assets are public build inputs, not local installation state.
            installation = importlib.import_module(namespace + ".python_installation")
            installation.validate_aliases(root)
            for logical in installation.setup_files(root):
                source = str(root / logical)
                destination = (f"ravel/data/installation/{logical}" if self.target_name == "wheel"
                               else logical)
                build_data["force_include"][source] = destination
            # Canonical instructions are build inputs, including inside an sdist.
            # A copied bundle may not silently replace a newer source document.
            paths = importlib.import_module(namespace + ".paths")
            instructions = paths.WORKFLOW_INSTRUCTIONS
            if not instructions or len(instructions) != len(set(instructions)):
                raise ValueError("unique finite workflow instruction inventory required")
            bundled_root = root / "src/ravel/data/workflow"
            bundled = set()
            for path in bundled_root.rglob("*"):
                if path.is_symlink() or not (path.is_file() or path.is_dir()):
                    raise ValueError("regular workflow instruction bundle required")
                if path.is_file():
                    bundled.add(path.relative_to(bundled_root).as_posix())
            if bundled != set(instructions):
                raise ValueError("complete declared workflow instruction bundle required")
            for logical in instructions:
                canonical = paths.workflow_instruction(logical, source_root=root)
                copied = paths.workflow_instruction(logical, source_root=bundled_root)
                if (canonical["sha256"], canonical["size"]) != (copied["sha256"], copied["size"]):
                    raise ValueError("workflow instruction differs from canonical source: " + logical)
                if self.target_name == "wheel":
                    build_data["force_include"][canonical["path"]] = f"ravel/data/workflow/{logical}"
                else:
                    # The next wheel build enforces the identical source law.
                    build_data["force_include"][canonical["path"]] = logical
                    build_data["force_include"][copied["path"]] = f"src/ravel/data/workflow/{logical}"
        finally:
            for name in list(sys.modules):
                if name == namespace or name.startswith(namespace + "."):
                    del sys.modules[name]
