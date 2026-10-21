"""Compile every instruction-bearing file into the instruction catalogue and its node manifests.

Inputs are the source tree, src/ravel/data/instructions/sources.json (inventory, mirror relations,
delivering nodes and manifest selectors), operation signatures, the knowledge atlas,
the effective role registry and the pinned census
citations (src/ravel/data/instructions/citations.json). Outputs are catalogue.json and
manifests.json beside them. Run after editing any instruction file, role card or the inventory:

    python scripts/maintenance/build_instruction_catalogue.py            # write
    python scripts/maintenance/build_instruction_catalogue.py --check    # report drift, exit 1
    python scripts/maintenance/build_instruction_catalogue.py --census OBLIGATIONS.jsonl.gz \
        --coverage COVERAGE.csv                                          # also re-pin the citations
    python scripts/maintenance/build_instruction_catalogue.py --refresh-preserved-source PATH \
        --reviewed-by REVIEWER --reason REASON                            # reviewed additive change

A discovered instruction file that is neither canonical nor a mirror of a catalogued source, a
selector that names no section and a unit that no node manifest delivers all fail the build.
Operation selectors carry their exact signature and complete linked source reading.
Units compile from canonical sources only; a mirror that differs from its source is reported
(its own sync or render gate restores byte equality). --citations-entry prints the generality citation-list entry the
catalogue needs (the cited identifiers its copied text carries).
"""
import argparse
from copy import deepcopy

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from ravel.controller.instructions import catalogue, compiler  # noqa: E402
from ravel.workflow import role_registry  # noqa: E402

DATA = ROOT / "src/ravel/data/instructions"


def published_view(root):
    """The export view of ``root``: in a source checkout that carries the export tooling, files read
    with their declared public edits; a public tree already holds the published text."""
    tooling = root / "scripts" / "export_layout.py"
    if not tooling.is_file():
        return catalogue.export_view(root)
    sys.path.insert(0, str(root / "scripts"))
    import export_layout
    return catalogue.export_view(root, transforms=export_layout.load_public_transforms(root),
                                 publish=export_layout.public_bytes)


def citations_entry(document):
    """{catalogue path: identifiers} from the shipped citation list, for the files the catalogue copies."""
    from ravel.validation import check_generality
    cited = check_generality.load_citations()
    copied = {row["path"] for row in document["files"]}
    text = catalogue.render(document)
    found = sorted({s for path in copied for s in cited.get(path, ()) if s in text})
    return {"src/ravel/data/instructions/catalogue.json": found} if found else {}


def refresh_preserved_sources(root, sources, citations, selected, *, reviewed_by, reason):
    """Rebind reviewed citations only after every old source unit survives in order."""
    if not isinstance(reviewed_by, str) or not reviewed_by.strip() or not isinstance(reason, str) or not reason.strip():
        raise ValueError('preserved-source refresh requires --reviewed-by and --reason')
    if not isinstance(citations, dict) or not isinstance(citations.get('rows'), list):
        raise ValueError('preserved-source refresh requires previous citations')
    previous_path = root / 'src/ravel/data/instructions/catalogue.json'
    if not previous_path.is_file():
        raise ValueError('preserved-source refresh requires a previous catalogue')
    previous = json.loads(previous_path.read_text())
    compiled = compiler.build(root, sources,
                              cards=role_registry.all_cards(roles_root=root / 'src/ravel/data/roles'),
                              view=published_view(root))
    refreshed = deepcopy(citations)

    def source(unit):
        return unit.get('source', unit['id'].split('#', 1)[0])

    def signature(unit):
        text = unit['text']
        text = '\n'.join(text) if isinstance(text, list) else text
        digest = compiler.digest_text(text)
        if unit.get('sha256') != digest:
            raise ValueError('invalid previous or current unit digest: ' + unit['id'])
        section = unit.get('section', unit['id'].split('#', 1)[1].rsplit('/', 1)[0])
        return unit['form'], digest, section

    for path in dict.fromkeys(selected):
        old = [unit for unit in previous['units'] if source(unit) == path]
        new = [unit for unit in compiled['units'] if source(unit) == path]
        rows = [row for row in refreshed['rows'] if row.get('source') == path]
        if not old or not new or path not in compiled['texts'] or not rows:
            raise ValueError('preserved-source refresh needs previous and current units and citations: ' + path)
        old_by_id = {unit['id']: unit for unit in old}
        signatures = [signature(unit) for unit in new]
        mapping, cursor = {}, 0
        for unit in old:
            wanted = signature(unit)
            while cursor < len(new) and signatures[cursor] != wanted:
                cursor += 1
            if cursor == len(new):
                raise ValueError('source unit removed, changed or reordered: ' + unit['id'])
            mapping[unit['id']] = new[cursor]['id']
            cursor += 1
        new_by_id = {unit['id']: unit for unit in new}
        current_sha = next(row['sha256'] for row in compiled['files'] if row['path'] == path)
        for row in rows:
            prior = row.get('migration')
            pins = prior.get('units') if isinstance(prior, dict) else None
            if prior is not None and (not isinstance(pins, dict) or not pins or any(
                    uid not in old_by_id or old_by_id[uid]['sha256'] != digest for uid, digest in pins.items())):
                raise ValueError('invalid prior migration unit pin: ' + row['id'])
            bound = [unit['id'] for unit in old if row['id'] in unit.get('census', [])]
            if not bound:
                bound = list(pins or {})
            if not bound:
                raise ValueError('no previous citation binding: ' + row['id'])
            mapped = [unit['id'] for unit in new] if row.get('line') == 1 else [mapping[uid] for uid in bound]
            migration = {'source_sha256': current_sha, 'reviewed_by': reviewed_by, 'reason': reason,
                         'units': {uid: new_by_id[uid]['sha256'] for uid in mapped}}
            if (prior is not None and prior.get('source_sha256') == current_sha
                    and pins == migration['units']
                    and all(isinstance(prior.get(field), str) and prior[field].strip()
                            for field in ('reviewed_by', 'reason'))):
                continue  # The current reviewed binding already records this exact refresh.
            if prior is not None:
                migration['prior_migration'] = deepcopy(prior)
            row['migration'] = migration
    return refreshed


def verify_refreshed_bindings(built, citations, selected):
    """Refuse any scope loss under the ordinary compiler's attachment precedence."""
    by_id = {unit['id']: unit for unit in built['units']}
    for row in citations['rows']:
        if row.get('source') not in selected:
            continue
        for uid, digest in row['migration']['units'].items():
            current = by_id.get(uid)
            if (current is None or current['sha256'] != digest
                    or row['id'] not in current.get('census', [])):
                raise ValueError('ordinary census attachment lost refreshed binding: ' + row['id'] + ' -> ' + uid)

def apply_reviewed_migrations(citations, review, compiled):
    """Apply reviewed source bindings while retaining every census row.

    This only updates the existing migration field. Original evidence, census
    identities and decision flags remain unchanged. The ordinary catalogue build
    still validates every binding and delivery manifest before writing output.

    Version 1 binds a whole-file citation to its complete current unit population.
    Version 2 also binds a quoted passage to exactly one complete current unit in
    the same source, with ``replaces_evidence`` pinning its exact original quote.
    Both versions pin the citation document, original row and current source bytes.
    """
    if (set(review) != {"schema_version", "citations_sha256", "migrations"} or
            type(review["schema_version"]) is not int or review["schema_version"] not in (1, 2)):
        raise ValueError("review requires schema_version, citations_sha256 and migrations")
    if review["citations_sha256"] != compiler.digest_value(citations):
        raise ValueError("review pins different citation data")
    result = deepcopy(citations)
    rows = {row["id"]: row for row in result["rows"]}
    units = {unit["id"]: unit for unit in compiled["units"]}
    seen = set()
    if not isinstance(review["migrations"], list) or not review["migrations"]:
        raise ValueError("review requires nonempty migrations")
    for entry in review["migrations"]:
        required = {"id", "row_sha256", "source_sha256", "units", "reviewed_by", "reason"}
        allowed = required | ({"replaces_evidence"} if review["schema_version"] == 2 else set())
        if (not required <= set(entry) <= allowed or
                entry["id"] in seen or entry["id"] not in rows):
            raise ValueError("invalid, duplicate or unknown reviewed citation")
        seen.add(entry["id"])
        row = rows[entry["id"]]
        whole_file = row.get("line") == 1 and row.get("evidence") is None
        if review["schema_version"] == 1 and not whole_file:
            raise ValueError("reviewed migration is limited to whole-file citations: " + entry["id"])
        if whole_file and set(entry) != required:
            raise ValueError("whole-file review has unexpected passage evidence: " + entry["id"])
        if not whole_file:
            evidence = row.get("evidence")
            if (not isinstance(evidence, str) or not evidence.strip() or
                    entry.get("replaces_evidence") != evidence):
                raise ValueError("passage review requires the exact original evidence: " + entry["id"])
        if compiler.digest_value(row) != entry["row_sha256"]:
            raise ValueError("review pins a different citation row: " + entry["id"])
        source = row.get("source")
        text = compiled["texts"].get(source)
        if text is None or hashlib.sha256(text.encode()).hexdigest() != entry["source_sha256"]:
            raise ValueError("review pins different source bytes: " + entry["id"])
        pins = entry["units"]
        if not isinstance(pins, dict) or not pins or any(
                uid not in units or units[uid]["source"] != source or
                compiler.digest_text(units[uid]["text"]) != digest for uid, digest in pins.items()):
            raise ValueError("review has missing, foreign or stale units: " + entry["id"])
        if whole_file and set(pins) != {uid for uid, unit in units.items() if unit["source"] == source}:
            raise ValueError("whole-file citation requires the complete current unit population: " + entry["id"])
        if not whole_file and len(pins) != 1:
            raise ValueError("passage citation requires exactly one complete current unit: " + entry["id"])
        if any(not isinstance(entry[key], str) or not entry[key].strip() for key in ("reviewed_by", "reason")):
            raise ValueError("migration requires reviewer and reason")
        row["migration"] = {key: entry[key] for key in ("reviewed_by", "reason", "source_sha256", "units")}
        if not whole_file:
            row["migration"]["replaces_evidence"] = entry["replaces_evidence"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="report drift without writing; exit 1 on drift")
    parser.add_argument("--census", type=Path, help="census obligations (jsonl or jsonl.gz) to re-pin citations")
    parser.add_argument("--coverage", type=Path, help="coverage table naming each census row's kind")
    parser.add_argument("--citations-entry", action="store_true", help="print the generality citation entry")
    parser.add_argument("--refresh-preserved-source", action="append", default=[], metavar="PATH",
                        help="review and re-pin an additively changed source, preserving every previous unit")
    parser.add_argument("--reviewed-by", help="reviewer of a preserved-source citation refresh")
    parser.add_argument("--reason", help="reviewed reason for a preserved-source citation refresh")

    parser.add_argument("--reviewed-migrations", type=Path,
                        help="apply a reviewed exact-byte census binding record before the ordinary build")
    args = parser.parse_args(argv)
    if args.refresh_preserved_source:
        if args.census or args.coverage:
            parser.error('--refresh-preserved-source cannot be combined with --census or --coverage')
        if not args.reviewed_by or not args.reviewed_by.strip() or not args.reason or not args.reason.strip():
            parser.error('--refresh-preserved-source requires --reviewed-by and --reason')
    root = args.root.resolve()
    data = root / "src/ravel/data/instructions"
    sources = compiler.load_sources(data / "sources.json")
    citations = None
    if args.census or args.coverage:
        if not (args.census and args.coverage):
            parser.error("--census and --coverage go together")
        previous = json.loads((data / 'citations.json').read_text()) if (data / 'citations.json').is_file() else None
        citations = catalogue.citations_from(args.census, args.coverage, sources, root, previous=previous)
    elif (data / "citations.json").is_file():
        citations = json.loads((data / "citations.json").read_text())
    drift, withheld = [], []
    try:
        if args.refresh_preserved_source:
            citations = refresh_preserved_sources(root, sources, citations, args.refresh_preserved_source,
                                                  reviewed_by=args.reviewed_by, reason=args.reason)

        if args.reviewed_migrations:
            if args.census or args.coverage or args.check or args.citations_entry:
                parser.error("--reviewed-migrations cannot combine with census, check or citation-entry modes")
            from ravel.workflow import role_registry
            compiled = compiler.build(root, sources, cards=role_registry.all_cards(
                roles_root=root / "src/ravel/data/roles"), view=published_view(root))
            citations = apply_reviewed_migrations(citations, json.loads(args.reviewed_migrations.read_text()), compiled)
        built, manifests = catalogue.build(root, sources=sources, citations=citations, drift=drift,
                                           withheld=withheld, view=published_view(root))
        if args.refresh_preserved_source:
            verify_refreshed_bindings(built, citations, args.refresh_preserved_source)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    outputs = {"catalogue.json": catalogue.render(built), "manifests.json": json.dumps(manifests, indent=1,
                                                                                         ensure_ascii=False) + "\n"}
    if citations is not None and (args.census or args.refresh_preserved_source or args.reviewed_migrations
                                  or not (data / "citations.json").is_file()):
        outputs["citations.json"] = json.dumps(citations, indent=1, ensure_ascii=False) + "\n"
    if args.citations_entry:
        print(json.dumps(citations_entry(built), indent=1))
        return 0
    stale = [name for name, text in outputs.items()
             if not (data / name).is_file() or (data / name).read_text() != text]
    if args.check:
        for name in stale:
            print("stale:", f"src/ravel/data/instructions/{name}")
        return 1 if stale else 0
    for name in stale:
        (data / name).write_text(outputs[name])
    for path in withheld:
        print("withheld by the export, outside the catalogue:", path, file=sys.stderr)
    for path in drift:
        print("mirror differs from its canonical source (its own sync or render restores it):", path, file=sys.stderr)
    kinds = {}
    for unit in built["units"]:
        kinds[unit["kind"]] = kinds.get(unit["kind"], 0) + 1
    print(f"{len(built['units'])} units ({kinds.get('duty', 0)} duty, {kinds.get('context', 0)} context) from "
          f"{len(built['files'])} sources and {len(built['mirrors'])} mirrors; wrote {', '.join(stale) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
