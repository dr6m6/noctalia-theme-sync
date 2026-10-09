"""Bounded JSONC editing: preserve every byte outside selected color values.

Fastfetch allows comments/trailing commas but no imports. A small span parser
avoids a runtime dependency and avoids reserializing a user's layout/comments.
"""
import json
import re
from dataclasses import dataclass, field

TOKEN = re.compile(r'\s+|//[^\n]*|/\*.*?\*/|"(?:[^"\\\x00-\x1f]|\\.)*"|[{}\[\]:,]|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null', re.S)


@dataclass
class Node:
    start: int
    end: int
    value: object
    children: dict = field(default_factory=dict)
    trailing: bool = False


def parse(text):
    tokens = []
    pos = 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise ValueError('invalid JSONC input')
        if not m[0].isspace() and not m[0].startswith(('//', '/*')):
            tokens.append((m[0], m.start(), m.end()))
        pos = m.end()
    index = 0
    def node(depth=0):
        nonlocal index
        if depth > 64 or index >= len(tokens):
            raise ValueError('invalid or deeply nested JSONC')
        token, start, end = tokens[index]
        index += 1
        if token not in ('{', '['):
            if token in ('}', ']', ':', ','):
                raise ValueError('unexpected JSONC punctuation')
            return Node(start, end, json.loads(token))
        obj = token == '{'
        close = '}' if obj else ']'
        values, children, trailing = ({} if obj else []), {}, False
        while index < len(tokens) and tokens[index][0] != close:
            if obj:
                key = tokens[index][0]
                if not key.startswith('"'):
                    raise ValueError('JSONC key must be quoted')
                key = json.loads(key)
                index += 1
                if key in children or index >= len(tokens) or tokens[index][0] != ':':
                    raise ValueError('duplicate JSONC key or missing colon')
                index += 1
            item = node(depth + 1)
            if obj:
                values[key], children[key] = item.value, item
            else:
                values.append(item.value)
            if index < len(tokens) and tokens[index][0] == ',':
                index += 1
                trailing = True
            else:
                trailing = False
                break
        if index >= len(tokens) or tokens[index][0] != close:
            raise ValueError('unclosed JSONC container')
        end = tokens[index][2]
        index += 1
        return Node(start, end, values, children, trailing)
    root = node()
    if index != len(tokens) or not isinstance(root.value, dict):
        raise ValueError('JSONC config must contain one object')
    return root


def set_value(text, keys, value):
    root = parse(text)
    current = root
    for offset, key in enumerate(keys):
        if not isinstance(current.value, dict):
            raise ValueError('expected JSONC object at ' + '.'.join(keys[:offset]))
        if key not in current.children:
            nested = value
            for remaining in reversed(keys[offset + 1:]):
                nested = {remaining: nested}
            addition = (',' if current.children and not current.trailing else '') + '\n' + json.dumps(key) + ': ' + json.dumps(nested) + '\n'
            text = text[:current.end - 1] + addition + text[current.end - 1:]
            parse(text)
            return text
        child = current.children[key]
        if offset == len(keys) - 1:
            if child.value == value:
                return text
            text = text[:child.start] + json.dumps(value) + text[child.end:]
            parse(text)
            return text
        current = child
    raise ValueError('empty JSONC key path')
