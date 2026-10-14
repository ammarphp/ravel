"""A checkout validates its declared development route; a distributed tree uses the public one."""
import json
from pathlib import Path

from ravel import evidence_layout
from ravel.validation import check_agent_surface as surface

REPO = Path(__file__).resolve().parents[2]
# A declared route of a source checkout, in its settings file (`development_route`).
DECLARED_ROUTE = ("DIRECTORY.md", "docs/maintainers/status.md", "docs/maintainers/plan.md",
                  "CONTRIBUTING.md", "docs/maintainers/program.md")


def routing_tree(tmp_path, *, declared, order):
    registry = evidence_layout.public_registry(json.loads((REPO / evidence_layout.REGISTRY).read_text()))
    if declared:
        registry['distribution']['internal'] = ['docs/maintainers/**']
        registry['distribution']['source_checks'] = 'docs/maintainers/checks.json'
        settings = tmp_path / 'docs/maintainers/checks.json'
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({'schema_version': 1, 'development_route': list(DECLARED_ROUTE)}))
    path = tmp_path / evidence_layout.REGISTRY
    path.write_text(json.dumps(registry))
    instructions = 'New physics: docs/workflow/start.md\n- **Development request**: ' + ' -> '.join(order) + '\n'
    for name in ('AGENTS.md', 'CLAUDE.md'):
        (tmp_path / name).write_text(instructions)
    return tmp_path


def test_declared_route_is_accepted_in_order(tmp_path):
    root = routing_tree(tmp_path, declared=True, order=DECLARED_ROUTE)
    assert surface.check_fork(root) == []


def test_declared_route_refuses_reordered_documents(tmp_path):
    order = list(DECLARED_ROUTE)
    order[1], order[2] = order[2], order[1]
    root = routing_tree(tmp_path, declared=True, order=order)
    errors = surface.check_fork(root)
    assert len(errors) == 2 and all('out of canonical order' in e for e in errors)


def test_declared_route_refuses_a_missing_document(tmp_path):
    root = routing_tree(tmp_path, declared=True, order=DECLARED_ROUTE[:2] + DECLARED_ROUTE[3:])
    errors = surface.check_fork(root)
    assert len(errors) == 2 and all('plan.md' in e for e in errors)


def test_without_a_declared_route_contributing_comes_first(tmp_path):
    root = routing_tree(tmp_path, declared=False, order=surface.PUBLIC_DEV_READ_ORDER)
    assert surface.check_fork(root) == []
    assert surface.check_fork(root, public=True) == []


def test_public_mode_refuses_the_declared_route(tmp_path):
    root = routing_tree(tmp_path, declared=False, order=DECLARED_ROUTE)
    errors = surface.check_fork(root, public=True)
    assert len(errors) == 2 and all('out of canonical order' in e for e in errors)


def test_mentions_outside_the_route_bullet_do_not_reorder_it(tmp_path):
    root = routing_tree(tmp_path, declared=True, order=DECLARED_ROUTE)
    for name in ('AGENTS.md', 'CLAUDE.md'):
        path = root / name
        path.write_text('Current program: docs/maintainers/program.md\n\n' + path.read_text())
    assert surface.check_fork(root) == []


def test_correct_order_elsewhere_cannot_mask_a_wrong_route(tmp_path):
    root = routing_tree(tmp_path, declared=True, order=tuple(reversed(DECLARED_ROUTE)))
    for name in ('AGENTS.md', 'CLAUDE.md'):
        path = root / name
        path.write_text('See ' + ' -> '.join(DECLARED_ROUTE) + '\n\n' + path.read_text())
    assert len(surface.check_fork(root)) == 2


def test_this_checkout_declares_its_route_outside_the_product_code():
    assert not hasattr(surface, 'SOURCE_DEV_READ_ORDER')
    route = evidence_layout.source_settings(REPO).get('development_route')
    if evidence_layout.is_public_tree(REPO):
        assert route is None
    else:
        assert route and route[0] == 'DIRECTORY.md'
