"""Check documentation prose for capability deferrals and behavioral hedges.

Code spans, fenced command examples, link destinations and JSON identifiers retain
literal source spelling. Human-facing JSON text fields are checked recursively.
Exceptions bind one exact passage, pattern and occurrence count to a review reason.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import html
from pathlib import Path
import re

PATTERNS = {
    'incapacity': r"\b(?:cannot|can['’]t|(?:does|do|is|are)\s+not\s+(?:support(?:ed)?|implement(?:ed)?|provide|execute|run|handle|produce|launch|plan|fit|import|port|supply|create|add|decode|process|render|interpolate|combine|copy|use|include)|not\s+(?:yet|available|supported|implemented|built|installed|shipped)|unsupported|unimplemented|unavailable|unprovided|unwired|not\s+(?:wired|integrated))\b",
    'deferral': r'\b(?:limitations?|known\s+gaps|out\s+of\s+scope|not\s+part\s+of\s+1\.3\.0|withheld|planned|future\s+(?:work|versions?|releases?|support|expansion)|pending\s+(?:implementation|integration|qualification)|await(?:s|ing)?\s+(?:implementation|integration|qualification)|road(?:map)|coming\s+soon|work\s+in\s+progress|deferred)\b',
    'hedge': r'\b(?:may|might|should\s+work|currently|experimental|best[ -]effort|where\s+possible|in\s+most\s+cases)\b',
}
COMPILED = {name: re.compile(pattern, re.I) for name, pattern in PATTERNS.items()}
TEXT_FIELDS = frozenset(('summary', 'description', 'title', 'notes', 'reason', 'rationale',
                         'help', 'purpose', 'scope', 'configuration_census', 'detail', 'explanation', 'text'))
JSON_LITERALS = frozenset(('id', 'source', 'path', 'module', 'expression', 'pattern', 'regex',
                            'command', 'argv', 'choices', 'default', 'pointer', 'identity'))
POLICY_LITERALS = {
    'public_scope': frozenset(('terms',)),
    'public_transforms': frozenset(('old', 'new')),
}
EXCEPTIONS = 'tests/fixtures/documentation-language-exceptions.json'


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    pattern: str
    text: str


def prose(text):
    """Mask literal syntax while keeping character offsets and line numbers."""
    original = text
    def mask(match):
        return re.sub(r'[^\n]', ' ', match.group())
    text = re.sub(r'^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$', mask, text, flags=re.M | re.S)
    # An inline code span is source spelling, including enum values and file paths.
    text = re.sub(r'(`+)[^\n]*?\1', mask, text)
    text = re.sub(r'(?<=\])\([^\n)]*\)', mask, text)
    def html_tag(match):
        visible = list(mask(match))
        raw_tag = original[match.start():match.end()]
        for attribute in re.finditer(r"\b(?:alt|title|aria-label|aria-description)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", raw_tag, re.I | re.S):
            group = next(index for index in (1, 2, 3) if attribute.group(index) is not None)
            decoded = html.unescape(attribute.group(group))
            visible[attribute.start(group):attribute.end(group)] = decoded.ljust(len(attribute.group(group)))
        return ''.join(visible)
    text = re.sub(r"</?(?:a|abbr|b|blockquote|br|code|dd|details|div|dl|dt|em|h[1-6]|hr|i|img|li|ol|p|picture|pre|s|section|small|source|span|strong|sub|summary|sup|table|tbody|td|th|thead|tr|ul)(?:\s+(?:[^<>\"']|\"[^\"]*\"|'[^']*')*)?\s*/?>", html_tag, text, flags=re.I)
    return html.unescape(text)


def passages(path, literal_fields=JSON_LITERALS):
    raw = path.read_text(encoding='utf-8')
    if path.as_posix().endswith('/src/ravel/data/instructions/catalogue.json'):
        root = path.parents[4]
        from ravel.controller.instructions import compiler
        expected_units = {}
        for unit in json.loads(raw).get('units', []):
            source = unit.get('id', '').split('#', 1)[0] or unit.get('source', '')
            if not (source.startswith(('docs/', '.claude/skills/', '.claude/rules/'))
                    or source in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md',
                                  'src/ravel/data/agent_surface/instructions.md')):
                continue
            text = unit.get('text', '')
            text = '\n'.join(text) if isinstance(text, list) else text
            canonical = root / source
            if canonical.is_file():
                if source not in expected_units:
                    content = canonical.read_text()
                    expected_units[source] = {row['id']: row for row in compiler.compile_markdown(source, content)}
                expected = expected_units[source].get(unit.get('id'))
                if expected and text == expected['text'] and unit.get('form') == expected['form']:
                    continue  # Complete canonical unit, including its code/prose form.
            yield 1, text
    elif path.suffix == '.svg':
        import xml.etree.ElementTree as ET
        def visible_text(element):
            parts = [element.text or '']
            for child in element:
                if any(name in child.attrib for name in ('x', 'y', 'dx', 'dy')):
                    parts.append(' ')
                parts.append(visible_text(child))
                parts.append(child.tail or '')
            return ''.join(parts)
        for element in ET.fromstring(raw).iter():
            if element.tag.rsplit('}', 1)[-1] in ('text', 'title', 'desc'):
                visible = visible_text(element)
                if visible.strip():
                    yield 1, visible
            for key in ('aria-label', 'aria-description', 'title', 'description'):
                if element.get(key):
                    yield 1, element.get(key)
    elif path.suffix == '.json':
        def walk(value, parent=''):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield from walk(child, key)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child, parent)
            elif isinstance(value, str) and (parent in TEXT_FIELDS or
                    (parent not in literal_fields and re.search(r'\s', value))):
                yield 1, value
        yield from walk(json.loads(raw))
    else:
        yield 1, raw


def policy_literals(root):
    registry = root / 'distribution.json'
    distribution = json.loads(registry.read_text()).get('distribution', {}) if registry.is_file() else {}
    return {distribution[field]: fields for field, fields in POLICY_LITERALS.items()
            if isinstance(distribution.get(field), str)}


def scan(path, relative, policies=None):
    if policies is None:
        root = path.parents[len(Path(relative).parts) - 1]
        policies = policy_literals(root)
    result = []
    for start, raw in passages(path, JSON_LITERALS | policies.get(relative, frozenset())):
        masked = prose(raw)
        for label, pattern in COMPILED.items():
            for match in pattern.finditer(masked):
                left = raw.rfind('\n', 0, match.start()) + 1
                right = raw.find('\n', match.end())
                if right < 0:
                    right = len(raw)
                result.append(Hit(relative, start + raw.count('\n', 0, match.start()), label, raw[left:right]))
    return result


def documentation_paths(root):
    """Authored documentation plus generated instruction copies in a checkout/export."""
    paths = {root / 'src/ravel/data/agent_surface/instructions.md',
             root / 'src/ravel/data/instructions/catalogue.json',
             *(root / name for name in ('README.md', 'DIRECTORY.md', 'CONTRIBUTING.md',
                                      'AGENTS.md', 'CLAUDE.md', 'GEMINI.md'))}
    for name in ('docs', '.claude/skills', '.claude/rules', '.claude/agents', '.agents/skills',
                 'src/ravel/data/workflow'):
        base = root / name
        if base.is_dir():
            paths.update(p for p in base.rglob('*') if p.suffix in ('.md', '.rst', '.txt', '.json', '.tex', '.svg', '.sty', '.cfg'))
    checked = []
    for path in sorted(path for path in paths if path.is_file()):
        relative = path.relative_to(root).as_posix()
        canonical = None
        if relative.startswith('src/ravel/data/workflow/'):
            canonical = root / relative.removeprefix('src/ravel/data/workflow/')
        elif relative.startswith('.agents/skills/'):
            canonical = root / relative.replace('.agents/skills/', '.claude/skills/', 1)
        elif relative == 'AGENTS.md':
            source = root / 'src/ravel/data/agent_surface/instructions.md'
            header, separator, body = path.read_text().partition('\n')
            generated = re.fullmatch(r'<!-- Generated from the RAVEL role registry [0-9a-f]{64}\. Do not hand edit\. -->', header)
            if source.is_file() and separator and generated and body == source.read_text():
                continue
        if canonical and canonical.is_file() and path.read_bytes() == canonical.read_bytes():
            continue  # One prose review for byte-identical copies; drift is scanned independently.
        checked.append(path)
    return checked


def errors(root, exceptions=None):
    root = Path(root)
    if exceptions is None:
        exceptions = json.loads((root / EXCEPTIONS).read_text(encoding='utf-8'))['exceptions']
    policies = policy_literals(root)
    hits = [hit for path in documentation_paths(root) for hit in scan(path, path.relative_to(root).as_posix(), policies)]
    counts = Counter((hit.path, hit.pattern, hit.text) for hit in hits)
    problems = []
    seen = set()
    for row in exceptions:
        key = row['path'], row['pattern'], row['text']
        if key in seen or not row.get('reason', '').strip() or row.get('count', 0) < 1:
            problems.append('invalid language exception: ' + repr(key))
        seen.add(key)
        if counts[key] != row['count']:
            problems.append('stale language exception: ' + repr(key))
        counts[key] -= row['count']
    for hit in hits:
        key = hit.path, hit.pattern, hit.text
        if counts[key] > 0:
            problems.append(f'{hit.path}:{hit.line}: {hit.pattern}: {hit.text}')
            counts[key] -= 1
    return problems
