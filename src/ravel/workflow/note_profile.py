"""Build a page-limited note formatting contract from a supplied rule pack.

A rule pack carries a venue's or challenge's page ceiling, counted sections,
figure and table limits and required sections as data. This command validates a
pack and writes the formatting contract that the manuscript writer and the
compiled-PDF build both enforce. It never authors text or runs a model.
"""
import argparse
import hashlib
import json
from pathlib import Path

from . import manuscript_format

RENDER_DEFAULTS = {'frontmatter': 'title-before-abstract', 'graphics': 'inline', 'line_numbers': False,
                   'appendices': 'after-references', 'citation_style': 'numeric-brackets',
                   'post_reference_sections': [], 'quantitative_position': 'main'}


def pin(path):
    path = Path(path).absolute()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON field: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs)


def check(pack_path):
    pack = manuscript_format.validate_rule_pack(_read_json(pack_path))
    return {'rule_pack': pin(pack_path), 'id': pack['id'], 'max_main_pages': pack['max_main_pages'],
            'max_figures': pack['max_figures'], 'max_tables': pack['max_tables'],
            'required_semantics': pack['required_semantics'], 'main_text_semantics': pack['main_text_semantics'],
            'requires_supplied_requirements': pack['requires_supplied_requirements']}


def contract(pack_path, out, *, stage='draft', article_type='internal note', render_class='article',
             template_assets=(), source_basis=None, sections=None):
    """Write a new formatting contract; existing files are never replaced."""
    out = Path(out).absolute()
    if out.exists():
        raise ValueError('formatting contract output must be a new file')
    pack = manuscript_format.validate_rule_pack(_read_json(pack_path))
    if render_class not in {'article', 'revtex4-2', 'svjour3', 'source-template'}:
        raise ValueError('unsupported note class')
    if render_class == 'source-template' and not template_assets:
        raise ValueError('a source-template note needs its supplied template assets')
    basis = _read_json(source_basis) if source_basis is not None else None
    value = manuscript_format.build_note_contract(
        pack, pin(pack_path), stage=stage, article_type=article_type,
        render={'class': render_class, **RENDER_DEFAULTS}, source_basis=basis,
        template_assets=[pin(p) for p in template_assets],
        sections=_read_json(sections) if sections is not None else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
    # The written contract must load through the same reader the writer uses.
    manuscript_format.load(pin(out), out.parent, {})
    return {'contract': pin(out), 'rule_pack': value['rule_pack'], 'rules': [r['id'] for r in value['rules']]}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel note-profile', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    c = commands.add_parser('check', help='validate a note rule pack')
    c.add_argument('--rule-pack', type=Path, required=True)
    w = commands.add_parser('contract', help='write a formatting contract from a rule pack')
    w.add_argument('--rule-pack', type=Path, required=True)
    w.add_argument('--out', type=Path, required=True)
    w.add_argument('--stage', default='draft')
    w.add_argument('--article-type', default='internal note')
    w.add_argument('--class', dest='render_class', default='article')
    w.add_argument('--template-asset', type=Path, action='append', default=[])
    w.add_argument('--source-basis', type=Path, help='located source text JSON for a publisher or challenge pack')
    w.add_argument('--sections', type=Path, help='explicit section mapping JSON')
    args = parser.parse_args(argv)
    try:
        if args.command == 'check':
            result = check(args.rule_pack)
        else:
            result = contract(args.rule_pack, args.out, stage=args.stage, article_type=args.article_type,
                              render_class=args.render_class, template_assets=args.template_asset,
                              source_basis=args.source_basis, sections=args.sections)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'note profile: {exc}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
