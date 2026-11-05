"""Structural, case-insensitive overlays of top-level Daedalus definitions.

Only declaration spans are replaced. Strings, comments and nested delimiters
are scanned lexically; untouched original text is retained verbatim.
"""
from __future__ import annotations

import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .scripts import load_text, mask_comments


class DaedalusMergeError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    value: str
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class Definition:
    kind: str
    names: tuple[str, ...]
    start: int
    end: int
    leading_start: int


def _error(label, text, offset, message):
    line = text.count('\n', 0, offset) + 1
    return DaedalusMergeError(f'{label}:{line}: {message}')


def _tokens(text, label):
    position = 0
    while position < len(text):
        start = position
        char = text[position]
        if char.isspace() or char == '\ufeff':
            position += 1
        elif text.startswith('//', position):
            end = text.find('\n', position)
            position = len(text) if end < 0 else end + 1
        elif text.startswith('/*', position):
            end = text.find('*/', position + 2)
            if end < 0:
                raise _error(label, text, start, 'Незавершённый комментарий')
            position = end + 2
        elif char == '"':
            position += 1
            while position < len(text):
                if text[position] == '\\':
                    position += 2
                elif text[position] == '"':
                    position += 1
                    yield Token(text[start:position], start, position, 'string')
                    break
                else:
                    position += 1
            else:
                raise _error(label, text, start, 'Незавершённая строка')
        elif char.isascii() and (char.isalpha() or char == '_'):
            position += 1
            while position < len(text) and text[position].isascii() and (
                    text[position].isalnum() or text[position] == '_'):
                position += 1
            yield Token(text[start:position], start, position, 'name')
        elif char.isdigit():
            position += 1
            while position < len(text) and text[position].isascii() and (
                    text[position].isalnum() or text[position] in '._'):
                position += 1
            yield Token(text[start:position], start, position, 'number')
        else:
            position += 1
            yield Token(char, start, position, 'symbol')


def definitions(text: str, label='<script>') -> list[Definition]:
    tokens = list(_tokens(text, label))
    result = []
    index, previous_end = 0, 0
    pairs = {')': '(', ']': '[', '}': '{'}
    block_kinds = {'instance', 'prototype', 'func', 'class'}
    while index < len(tokens):
        first = tokens[index]
        if first.value == ';':  # Old partial copies can contain empty statements.
            index += 1
            continue
        kind = first.value.casefold()
        if first.kind != 'name' or kind not in block_kinds | {'const', 'var'}:
            raise _error(label, text, first.start, 'Неподдерживаемый текст вне определения: ' + first.value)
        name_index = index + (2 if kind in ('func', 'const', 'var') else 1)
        if name_index >= len(tokens) or tokens[name_index].kind != 'name':
            raise _error(label, text, first.start, 'Не найден идентификатор определения')
        names = [tokens[name_index].value]
        stack = []
        cursor = name_index + 1
        finished = False
        while cursor < len(tokens):
            token = tokens[cursor]
            if token.kind == 'symbol':
                value = token.value
                if value == ',' and not stack:
                    if cursor + 1 >= len(tokens) or tokens[cursor + 1].kind != 'name':
                        raise _error(label, text, token.start, 'Не найден идентификатор после запятой')
                    names.append(tokens[cursor + 1].value)
                if value in ('(', '[', '{'):
                    stack.append(value)
                elif value in pairs:
                    if not stack or stack.pop() != pairs[value]:
                        raise _error(label, text, token.start, 'Несогласованные скобки')
                    if value == '}' and not stack and kind in block_kinds:
                        cursor += 1
                        if cursor < len(tokens) and tokens[cursor].value == ';':
                            cursor += 1
                        finished = True
                        break
                elif value == ';' and not stack:
                    cursor += 1
                    finished = True
                    break
            cursor += 1
        if not finished:
            raise _error(label, text, first.start, 'Незавершённое определение ' + names[0])
        end = tokens[cursor - 1].end
        result.append(Definition(kind, tuple(names), first.start, end, previous_end))
        previous_end, index = end, cursor
    return result


def normalize_compiler_whitespace(text: str):
    """Replace form feed used as whitespace; quoted/comment text is preserved."""
    if '\f' not in text:
        return text, 0
    masked = mask_comments(text)
    strings = [(token.start, token.end) for token in _tokens(text, '<script>') if token.kind == 'string']
    positions = [index for index, char in enumerate(masked) if char == '\f'
                 and not any(start <= index < end for start, end in strings)]
    result = list(text)
    for index in positions:
        result[index] = ' '
    return ''.join(result), len(positions)


@dataclass
class Document:
    path: Path
    text: str
    codec: str
    definitions: list[Definition]


class ScriptTree:
    def __init__(self, root: Path):
        self.root = root
        self.paths = {}
        self.documents = {}
        self.symbols = defaultdict(list)
        for path in sorted(root.rglob('*')):
            if not path.is_file():
                continue
            key = path.relative_to(root).as_posix().casefold()
            if key in self.paths:
                raise DaedalusMergeError(f'Неоднозначный путь: {self.paths[key]} / {path}')
            self.paths[key] = path
            if path.suffix.casefold() != '.d':
                continue
            text, codec = load_text(path)
            if codec == 'utf-8-sig' and not path.read_bytes().startswith(b'\xef\xbb\xbf'):
                codec = 'utf-8'
            document = Document(path, text, codec, definitions(text, path))
            self.documents[path] = document
            for definition in document.definitions:
                for name in definition.names:
                    self.symbols[name.casefold()].append((path, definition))

    def unique(self, name, kind=None):
        matches = self.symbols.get(name.casefold(), [])
        if len(matches) > 1:
            locations = ', '.join(f'{path}:{definition.start}' for path, definition in matches)
            raise DaedalusMergeError(f'Неоднозначное определение {name}: {locations}')
        if not matches:
            return None
        path, definition = matches[0]
        if kind is not None and definition.kind != kind:
            raise DaedalusMergeError(f'Конфликт идентификатора {name}: {definition.kind} / {kind} ({path})')
        return path, definition

    def apply(self, changes):
        for path, edits in changes.items():
            document = self.documents[path]
            text = document.text
            for start, end, replacement in sorted(edits, reverse=True):
                text = text[:start] + replacement + text[end:]
            try:
                encoded = text.encode(document.codec)
            except UnicodeEncodeError as exc:
                raise DaedalusMergeError(f'{path}: изменения не представимы в кодировке {document.codec}') from exc
            if encoded != path.read_bytes():
                path.write_bytes(encoded)


def declaration_text(text, definition):
    block = text[definition.start:definition.end]
    return block + ';' if block.rstrip().endswith('}') else block


def _signature(text):
    tokens = list(_tokens(text, '<definition>'))
    if tokens and tokens[-1].value == ';':
        tokens.pop()
    return [(token.kind, token.value.casefold() if token.kind == 'name' else token.value) for token in tokens]


def target_path(root: Path, relative: Path):
    """Resolve existing path components without depending on filesystem casing."""
    path = root
    for part in relative.parts:
        matches = [child for child in path.iterdir() if child.name.casefold() == part.casefold()] if path.is_dir() else []
        if len(matches) > 1:
            raise DaedalusMergeError(f'Неоднозначный путь: {path / part}')
        path = matches[0] if matches else path / part
    return path


def _trivia(text):
    # Legacy copies can leave ';' behind after removed INSTANCE blocks. They
    # are not declarations and must not be emitted ahead of new definitions.
    for token in reversed(list(_tokens(text, '<trivia>'))):
        if token.value == ';':
            text = text[:token.start] + text[token.end:]
    return text


def _new_document(document):
    parts, end = [], 0
    for definition in document.definitions:
        parts.extend((_trivia(document.text[end:definition.start]),
                      declaration_text(document.text, definition)))
        end = definition.end
    parts.append(_trivia(document.text[end:]))
    return ''.join(parts)


def _insertion_point(document, position, tree, destination):
    # Keep newly declared variables/helpers before the project definitions that
    # use them, rather than blindly appending all new symbols at end-of-file.
    for definition in document.definitions[position + 1:]:
        match = tree.unique(definition.names[0], definition.kind)
        if match is not None and match[0] == destination:
            return match[1].start
    for definition in reversed(document.definitions[:position]):
        match = tree.unique(definition.names[0], definition.kind)
        if match is not None and match[0] == destination:
            return match[1].end
    return len(tree.documents[destination].text)


def merge_project_scripts(content: Path, project_source: Path):
    """Apply validated project definitions to the original staging tree only."""
    tree, project = ScriptTree(content), ScriptTree(project_source)
    changes = defaultdict(list)
    additions = defaultdict(list)
    insertions = defaultdict(lambda: defaultdict(list))
    affected = set()
    for name, matches in project.symbols.items():
        if len(matches) > 1:
            raise DaedalusMergeError(f'Неоднозначное проектное определение {name}: ' +
                                     ', '.join(str(path) for path, _ in matches))
    for source, document in project.documents.items():
        relative = source.relative_to(project_source)
        destination = tree.paths.get(relative.as_posix().casefold(), target_path(content, relative))
        for position, definition in enumerate(document.definitions):
            matches = [tree.unique(name, definition.kind) for name in definition.names]
            existing = {match for match in matches if match is not None}
            if existing:
                if len(existing) != 1 or any(match is None for match in matches):
                    raise DaedalusMergeError(f'Неоднозначная группа идентификаторов {definition.names}: {source}')
                path, original = next(iter(existing))
                if {name.casefold() for name in original.names} != {name.casefold() for name in definition.names}:
                    raise DaedalusMergeError(f'Нельзя частично заменить групповое объявление {original.names}: {source}')
                replacement = declaration_text(document.text, definition)
                original_text = tree.documents[path].text[original.start:original.end]
                if _signature(original_text) != _signature(replacement):
                    changes[path].append((original.start, original.end, replacement))
                    affected.add(path)
            else:
                block = (_trivia(document.text[definition.leading_start:definition.start]) +
                         declaration_text(document.text, definition))
                if destination in tree.documents:
                    point = _insertion_point(document, position, tree, destination)
                    insertions[destination][point].append(block)
                else:
                    additions[destination].append(block)
                affected.add(destination)
        # A genuinely new file keeps all its comments and whitespace as well.
        if destination not in tree.documents and all(not tree.symbols.get(name.casefold())
                for definition in document.definitions for name in definition.names):
            additions[destination] = [_new_document(document)]
            affected.add(destination)
    for path, positions in insertions.items():
        for position, blocks in positions.items():
            changes[path].append((position, position, '\n' + '\n'.join(blocks) + '\n'))
    tree.apply(changes)
    for path, blocks in additions.items():
        if path.exists():
            text, codec = load_text(path)
            if path in tree.documents:
                codec = tree.documents[path].codec
            text += '\n' + '\n'.join(blocks) + '\n'
        else:
            codec = next(document.codec for source, document in project.documents.items()
                         if source.relative_to(project_source).as_posix().casefold() == path.relative_to(content).as_posix().casefold())
            text = '\n'.join(blocks)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode(codec))
    for key, source in project.paths.items():
        if source.suffix.casefold() == '.d':
            continue
        destination = tree.paths.get(key, target_path(content, source.relative_to(project_source)))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        affected.add(destination)
    return sorted((path.relative_to(content) for path in affected), key=lambda path: path.as_posix().casefold())
