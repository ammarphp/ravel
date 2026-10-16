"""Signature-backed discovery and compatibility dispatch for the event/inference chain.

These declarations select adapters; they grant no execution or scientific authority.
Other science modes keep their existing compatibility dispatch.
"""
import ast
import importlib

from ravel.validation.core import fail

GROUP = 'event-inference-chain'
# Historical dispatch only: these rows deliberately contain no scientific signature.
# New operations join through signature declarations, never through this table.
LEGACY_BINDINGS = {
    'model-events': {'module': 'ravel.physics.model_events', 'dispatch_position': 22,
                     'dispatch_before': 'analyze', 'presentation': 'diagnostic_presentation'},
    'signal-template': {'module': 'ravel.physics.signal_templates', 'dispatch_position': 34,
                        'dispatch_before': 'stau-events'},
    'columnar-analysis': {'module': 'ravel.physics.columnar_analysis', 'dispatch_position': 94,
                         'dispatch_before': 'authored-analysis'},
}


def source_dispatch_enabled(tree):
    """Recognize the bounded declaration/dispatch seam without executing source.

    Both the startup mode population and adapter's early return must be present.
    Merely shipping this helper or a signature never establishes source dispatch.
    """
    declaration = ast.parse('from .operation_definitions import populate_modes as _chain_modes\n'
                            'MODES = _chain_modes(MODES)').body
    dispatch = ast.parse("from .operation_definitions import adapter_for\n"
                         "discovered = adapter_for(spec['mode'])\n"
                         "if discovered is not None:\n    return discovered").body
    dump = lambda nodes: [ast.dump(node, include_attributes=False) for node in nodes]
    declared = any(dump(tree.body[i:i + 2]) == dump(declaration)
                   for i in range(len(tree.body) - 1))
    adapter = next((node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'adapter'), None)
    return declared and adapter is not None and dump(adapter.body[:3]) == dump(dispatch)


def definitions(registry=None, executors=None, compatibility=None):
    """Discover declarations and bounded old dispatch; absent signatures remain None."""
    if registry is None:
        from ravel.validation.validate_request_plan import signatures
        registry = signatures()
    if executors is None:
        from .production_executor import executors as load_executors
        executors = load_executors()['operations']
    from ravel.workflow.operation_registration import executor_document, _implementation
    executors = executor_document({'operations': executors}, registry)['operations']
    result = {}
    for name, signature in registry.items():
        implementation = _implementation(name, signature)
        if implementation.get('dispatch_group') != GROUP:
            continue
        if not executors.get(name):
            fail(f'operations.{name}.executor', executors.get(name), 'executor role',
                 message=f'{name}: chain dispatch requires an adapter module and executor role')
        result[name] = {'signature': signature, 'implementation': implementation,
                        'executor_role': executors[name]}
    compatibility = LEGACY_BINDINGS if compatibility is None else compatibility
    for name, implementation in compatibility.items():
        if name in result:
            continue
        signature = registry.get(name)
        declared = signature.get('implementation', {}) if signature else {}
        if 'dispatch_group' in declared:
            fail(f'operations.{name}.implementation.dispatch_group', declared['dispatch_group'], GROUP,
                 message=f'{name}: invalid explicit chain dispatch declaration')
        if executors.get(name):
            if not implementation.get('module'):
                raise ValueError(f'{name}: legacy dispatch requires an adapter module')
            result[name] = {'signature': signature, 'implementation': implementation,
                            'executor_role': executors[name]}
    return result


def populate_modes(base, registry=None, executors=None, compatibility=None):
    """Restore declared compatibility positions; new unpositioned operations append."""
    rows = definitions(registry, executors, compatibility)
    modes = list(base)
    positioned, appended = [], []
    for name, row in rows.items():
        impl = row['implementation']
        (positioned if 'dispatch_position' in impl else appended).append((name, impl))
    positions = [impl['dispatch_position'] for _, impl in positioned]
    if any(type(p) is not int or p < 0 for p in positions) or len(set(positions)) != len(positions):
        fail('operations.implementation.dispatch_position', positions, 'distinct nonnegative integers',
             message='chain dispatch positions must be distinct nonnegative integers')
    for name, impl in sorted(positioned, key=lambda row: row[1]['dispatch_position']):
        if name not in modes:
            anchor = impl.get('dispatch_before')
            index = modes.index(anchor) if anchor in modes else min(impl['dispatch_position'], len(modes))
            modes.insert(index, name)
    modes.extend(name for name, _ in appended if name not in modes)
    return tuple(modes)


def adapter_for(mode):
    """Resolve a discovered operation's existing adapter, or None for compatibility modes."""
    definition = definitions().get(mode)
    return (importlib.import_module(definition['implementation']['module'])
            if definition is not None else None)


def presentation_for(mode, result):
    """Use an adapter-owned refusal/presentation hook when the signature declares one."""
    definition = definitions().get(mode)
    if definition is None:
        return None
    implementation = definition['implementation']
    hook = implementation.get('presentation')
    if hook is None:
        return None
    handler = getattr(importlib.import_module(implementation['module']), hook, None)
    if not callable(handler):
        raise ValueError(f'{mode}: presentation hook is not callable')
    return handler(result)
