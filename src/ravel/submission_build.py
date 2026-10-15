"""Build input census shared by the hook and release-tree submission export.

Selection reads source contracts only. It runs no installer or native program.
"""
from pathlib import Path
import importlib
import sys
import types


def input_map(root):
    """Source paths mapped to wheel and sdist destinations, with fresh validation."""
    root = Path(root)
    namespace = f'_ravel_build_payload_{id(root):x}'
    if namespace in sys.modules:
        raise RuntimeError('build payload namespace is already occupied')
    package = types.ModuleType(namespace)
    package.__path__ = [str(root / 'src/ravel')]
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.modules[namespace] = package
    try:
        installation = importlib.import_module(namespace + '.python_installation')
        installation.validate_aliases(root)
        selected = {logical: (f'ravel/data/installation/{logical}', logical)
                    for logical in installation.setup_files(root)}
        paths = importlib.import_module(namespace + '.paths')
        instructions = paths.WORKFLOW_INSTRUCTIONS
        if not instructions or len(instructions) != len(set(instructions)):
            raise ValueError('unique finite workflow instruction inventory required')
        bundled_root = root / 'src/ravel/data/workflow'
        bundled = set()
        for path in bundled_root.rglob('*'):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError('regular workflow instruction bundle required')
            if path.is_file():
                bundled.add(path.relative_to(bundled_root).as_posix())
        if bundled != set(instructions):
            raise ValueError('complete declared workflow instruction bundle required')
        for logical in instructions:
            canonical = paths.workflow_instruction(logical, source_root=root)
            copied = paths.workflow_instruction(logical, source_root=bundled_root)
            if (canonical['sha256'], canonical['size']) != (copied['sha256'], copied['size']):
                raise ValueError('workflow instruction differs from canonical source: ' + logical)
            selected[logical] = (f'ravel/data/workflow/{logical}', logical)
            selected['src/ravel/data/workflow/' + logical] = (None, 'src/ravel/data/workflow/' + logical)
        return selected
    finally:
        for name in list(sys.modules):
            if name == namespace or name.startswith(namespace + '.'):
                del sys.modules[name]
        sys.dont_write_bytecode = previous


def initialize(hook, build_data):
    for logical, destinations in input_map(hook.root).items():
        destination = destinations[0 if hook.target_name == 'wheel' else 1]
        if destination is not None:
            build_data['force_include'][str(Path(hook.root) / logical)] = destination
