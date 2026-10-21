"""Strict bounded-memory JSON validation and small top-level table summaries.

Payload values are never built. Limits refuse explicitly: UTF-8 JSON, 200 nested
containers, 4096 characters per key, 4096 keys per object, 65536 active keys and
262144 active key characters, 4096 characters per number, and 16384 characters
per extracted description/doi. Array lengths and skipped strings are unbounded.
"""
from __future__ import annotations

import codecs
import json
import math
import re

CHUNK = 64 << 10
MAX_DEPTH = 200
MAX_KEY_CHARS = 4096
MAX_OBJECT_KEYS = 4096
MAX_ACTIVE_KEYS = 65536
MAX_ACTIVE_KEY_CHARS = 262144
MAX_NUMBER_CHARS = 4096
MAX_METADATA_CHARS = 16384
_SPACE = re.compile(r'[ \t\r\n]*')
_SPECIAL = re.compile('["\\\\\x00-\x1f]')
_NUMBER_PART = re.compile(r'[-+0-9.eE]+')
_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')
_HEX = frozenset('0123456789abcdefABCDEF')


class JSONRefused(ValueError):
    """An invalid JSON document or an explicit finite validator limit."""
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


class _Parser:
    def __init__(self, source):
        self.source = source
        self.decoder = codecs.getincrementaldecoder('utf-8-sig')('strict')
        self.buffer, self.pos, self.eof = '', 0, False
        self.active_keys = self.active_chars = 0
        self.summary = {'object': False, 'values_nonempty': False, 'description': '', 'doi': ''}

    def fail(self, detail, code='invalid_json'):
        raise JSONRefused(code, detail)

    def fill(self):
        while self.pos == len(self.buffer) and not self.eof:
            raw = self.source.read(CHUNK)
            if not isinstance(raw, bytes):
                self.fail('validator needs a binary source')
            self.eof = not raw
            try:
                self.buffer = self.decoder.decode(raw, final=self.eof)
            except UnicodeError as exc:
                self.fail('payload must be valid UTF-8 JSON: ' + str(exc))
            self.pos = 0
        return self.pos < len(self.buffer)

    def peek(self):
        return self.buffer[self.pos] if self.fill() else ''

    def take(self):
        result = self.peek()
        if not result:
            self.fail('truncated document')
        self.pos += 1
        return result

    def whitespace(self):
        while self.fill():
            match = _SPACE.match(self.buffer, self.pos)
            self.pos = match.end()
            if self.pos < len(self.buffer):
                break

    def string(self, limit=None):
        if self.take() != '"':
            self.fail('object keys must be strings')
        pieces = [] if limit is not None else None
        length = 0
        def keep(text):
            nonlocal length
            if pieces is not None:
                length += len(text)
                if length > limit * 12:
                    self.fail('captured string exceeds its character ceiling', 'json_metadata_limit')
                pieces.append(text)
        while self.fill():
            found = _SPECIAL.search(self.buffer, self.pos)
            end = found.start() if found else len(self.buffer)
            keep(self.buffer[self.pos:end])
            self.pos = end
            if found is None:
                continue
            char = self.take()
            if char == '"':
                if pieces is None:
                    return None
                text = json.loads('"' + ''.join(pieces) + '"')
                if len(text) > limit:
                    self.fail('captured string exceeds its character ceiling', 'json_metadata_limit')
                return text
            if char != '\\':
                self.fail('unescaped control character in string')
            escape = self.take()
            keep('\\' + escape)
            if escape == 'u':
                for _ in range(4):
                    digit = self.take()
                    if digit not in _HEX:
                        self.fail('invalid Unicode escape')
                    keep(digit)
            elif escape not in '"\\/bfnrt':
                self.fail('invalid string escape')
        self.fail('unterminated string')

    def number(self):
        pieces, count = [], 0
        while self.fill():
            match = _NUMBER_PART.match(self.buffer, self.pos)
            if match is None:
                break
            part = match.group()
            count += len(part)
            if count > MAX_NUMBER_CHARS:
                self.fail('numeric token exceeds its character ceiling', 'json_number_limit')
            pieces.append(part)
            self.pos = match.end()
            if self.pos < len(self.buffer):
                break
        token = ''.join(pieces)
        if _NUMBER.fullmatch(token) is None:
            self.fail('invalid numeric token')
        if any(char in token for char in '.eE') and not math.isfinite(float(token)):
            self.fail('nonfinite JSON number')

    def value(self, depth=0, *, top=False, capture=False):
        self.whitespace()
        char = self.peek()
        if char in ('{', '['):
            if depth >= MAX_DEPTH:
                self.fail('container nesting exceeds its ceiling', 'json_depth_limit')
            if char == '{':
                self.object(depth + 1, top=top)
                return 'object', None
            return 'array', self.array(depth + 1)
        if char == '"':
            return 'string', self.string(MAX_METADATA_CHARS if capture else None)
        for literal, kind in (('true', 'boolean'), ('false', 'boolean'), ('null', 'null')):
            if char == literal[0]:
                for expected in literal:
                    if self.take() != expected:
                        self.fail('invalid literal')
                return kind, None
        if char and char in '-0123456789':
            self.number()
            return 'number', None
        self.fail('invalid or truncated value')

    def array(self, depth):
        self.take()
        self.whitespace()
        if self.peek() == ']':
            self.take()
            return False
        while True:
            self.value(depth)
            self.whitespace()
            char = self.take()
            if char == ']':
                return True
            if char != ',':
                self.fail('expected array comma or closing bracket')

    def object(self, depth, *, top):
        self.take()
        keys, chars = set(), 0
        try:
            self.whitespace()
            if self.peek() == '}':
                self.take()
                return
            while True:
                self.whitespace()
                key = self.string(MAX_KEY_CHARS)
                if key in keys:
                    self.fail('duplicate JSON key: ' + key)
                keys.add(key)
                chars += len(key)
                self.active_keys += 1
                self.active_chars += len(key)
                if (len(keys) > MAX_OBJECT_KEYS or self.active_keys > MAX_ACTIVE_KEYS
                        or self.active_chars > MAX_ACTIVE_KEY_CHARS):
                    self.fail('object/member-key storage exceeds its ceiling', 'json_member_limit')
                self.whitespace()
                if self.take() != ':':
                    self.fail('expected object colon')
                capture = top and key in ('description', 'doi')
                kind, value = self.value(depth, capture=capture)
                if capture:
                    if kind not in ('string', 'null'):
                        self.fail(key + ' must be a string or null', 'json_metadata_type')
                    self.summary[key] = value if kind == 'string' else ''
                if top and key == 'values':
                    self.summary['values_nonempty'] = kind == 'array' and value is True
                self.whitespace()
                char = self.take()
                if char == '}':
                    return
                if char != ',':
                    self.fail('expected object comma or closing brace')
        finally:
            self.active_keys -= len(keys)
            self.active_chars -= chars

    def parse(self):
        self.whitespace()
        self.summary['object'] = self.peek() == '{'
        self.value(top=True)
        self.whitespace()
        if self.peek():
            self.fail('trailing data after document')
        return self.summary


def summarize(source):
    """Validate all bytes of an open binary stream; retain only bounded table metadata."""
    return _Parser(source).parse()
