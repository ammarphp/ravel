"""Strict, read-only application of single-file unified integration fragments."""
import re

HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def apply(source, fragment):
    lines = source.splitlines(keepends=True)
    changes = fragment.splitlines(keepends=True)
    if len(changes) < 3 or not changes[0].startswith('--- a/') or not changes[1].startswith('+++ b/'):
        raise ValueError('one ordinary relative file patch required')
    old_name, new_name = changes[0][6:].strip(), changes[1][6:].strip()
    if old_name != new_name or old_name.startswith('/') or '..' in old_name.split('/'):
        raise ValueError('patch cannot rename or escape its target')
    output, cursor, i = [], 0, 2
    while i < len(changes):
        match = HUNK.match(changes[i])
        if not match:
            raise ValueError('malformed patch hunk')
        start, count = int(match[1]) - 1, int(match[2] or 1)
        if start < cursor or start > len(lines):
            raise ValueError('patch hunk outside source')
        output.extend(lines[cursor:start]); cursor = start
        i += 1
        consumed = produced = 0
        while i < len(changes) and not changes[i].startswith('@@ '):
            line = changes[i]
            if line.startswith('\\ No newline'):
                raise ValueError('newline-less fragments are not supported')
            if not line or line[0] not in (' ', '+', '-'):
                raise ValueError('malformed patch line')
            if line[0] in (' ', '-'):
                if cursor >= len(lines) or lines[cursor] != line[1:]:
                    raise ValueError(f'patch preimage differs at line {cursor + 1}')
                cursor += 1; consumed += 1
            if line[0] in (' ', '+'):
                output.append(line[1:]); produced += 1
            i += 1
        if consumed != count or produced != int(match[4] or 1):
            raise ValueError('patch hunk population differs')
    output.extend(lines[cursor:])
    return ''.join(output)
