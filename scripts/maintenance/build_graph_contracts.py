#!/usr/bin/env python3
"""Version and regenerate selected graph contracts from their registered builders."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))


def build(root, versions):
    from ravel.workflow import graph_registry, graph_substrate
    source = root / 'src/ravel/data/graphs/registry.json'
    raw = source.read_text()
    document = json.loads(raw)
    rows = {row['id']: row for row in document['graphs']}
    if not versions.keys() <= rows.keys():
        raise ValueError('select graphs declared in the registry source')
    for identity, version in versions.items():
        if version < rows[identity]['version']:
            raise ValueError('graph versions advance monotonically')
    instances = json.loads((root / 'src/ravel/data/agents/sanctioned.json').read_text())['introspection_instances']
    working = {identity: {**deepcopy(rows[identity]), 'version': version,
                          'structure_sha256': graph_registry.PIN} for identity, version in versions.items()}
    with tempfile.TemporaryDirectory(prefix='graph-contracts-') as temporary:
        for identity, version in versions.items():
            row = deepcopy(rows[identity])
            for child in row['subgraphs']:
                if child['id'] in versions:
                    child['version'] = versions[child['id']]
            ctx = graph_substrate.BuildContext(Path(temporary), identity, version, instances[identity], row=row)
            with graph_registry.registered(*working.values(), replace=True):
                module = __import__(row['module'], fromlist=['resource_contract'])
                resources = getattr(module, 'resource_contract', None)
                if callable(resources):
                    row['resources'] = resources(identity)
                builder = graph_registry.builder(row)(ctx)
                compiled = graph_substrate.finish(builder, identity)
                problems = graph_substrate.lint_graph(compiled)
            if problems:
                raise ValueError('; '.join(problems))
            roles = sorted({node.metadata['role'] for node in builder.nodes.values()
                            if (node.metadata or {}).get('role')})
            for child in row['subgraphs']:
                roles.extend(working.get(child['id'], graph_registry.get(child['id']))['roles'])
            if compiled.structure_sha256 != row['structure_sha256'] and version <= row['version']:
                raise ValueError('a changed graph structure requires an explicit version advance: ' + identity)
            row.update(version=version, structure_sha256=compiled.structure_sha256, roles=sorted(set(roles)))
            rows[identity].update(row)
            working[identity] = deepcopy(row)
    for row in document['graphs']:
        for child in row['subgraphs']:
            if child['id'] in versions:
                child['version'] = versions[child['id']]
    decoder = json.JSONDecoder()
    position = raw.index('[', raw.index('"graphs"')) + 1
    replacements = []
    for row in document['graphs']:
        while raw[position].isspace() or raw[position] == ',':
            position += 1
        before, end = decoder.raw_decode(raw, position)
        if before != row:
            content = json.dumps(row, indent=2).replace('\n', '\n    ')
            replacements.append((position, end, content))
        position = end
    for start, end, content in reversed(replacements):
        raw = raw[:start] + content + raw[end:]
    return source, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', action='append', required=True, metavar='ID=VERSION')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    versions = {identity: int(version) for identity, version in (item.split('=') for item in args.graph)}
    path, content = build(ROOT, versions)
    stale = path.read_text() != content
    if args.write and stale:
        path.write_text(content)
    print('graph contracts: ' + ('updated' if stale and args.write else 'stale' if stale else 'current'))
    return int(stale and not args.write)


if __name__ == '__main__':
    raise SystemExit(main())
