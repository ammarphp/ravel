"""Supplied routine discovery; no installed selection population."""
from ..analysis_packages import discover, load_routine

class RoutineUnavailable(ValueError):
    def __init__(self, routine, reason='routine_module_absent', detail=None):
        self.routine = routine
        self.reason = reason
        super().__init__(f'{routine}: {reason}' + (f'; {detail}' if detail else ''))

def retained_asset_module():
    """Removed evidence assets never grant executable admission."""
    return None

class RoutineRegistry(dict):
    def __contains__(self, name):
        return super().__contains__(name) or name in discover()
    def __iter__(self):
        return iter(set(super().__iter__()) | set(discover()))
    def __getitem__(self, name):
        if super().__contains__(name):
            return super().__getitem__(name)
        rows = discover()
        if name not in rows:
            raise RoutineUnavailable(name, 'missing_analysis_package')
        return rows[name]['manifest_path']
    def get(self, name, default=None):
        return self[name] if name in self else default

REGISTRY = RoutineRegistry()

def resolve_routine(name):
    path = REGISTRY[name]
    return load_routine(path, require_qualification=True)
