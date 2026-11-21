"""Read-only, bounded inspection of ZenGin world archives.

ASCII and BIN_SAFE archives expose VOB properties. Unannotated BINARY
archives support metadata inspection only. Large mesh payloads are not
decoded; this module does not rewrite or unpack game files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import struct

from .zen_binsafe import BinSafeError, read_binsafe


_HEADER_BYTES = 16 * 1024
_MAX_ASCII_BYTES = 128 * 1024 * 1024
_BEGIN = re.compile(r'^\[([^\]\s]+)\s+(\S+)\s+(\d+)\s+(\d+)\]$')


@dataclass(frozen=True)
class ZenWorldObject:
    name: str
    classes: str
    index: int
    parent_index: int | None
    properties: dict[str, str]


@dataclass(frozen=True)
class ZenWorldInfo:
    source: Path
    encoding: str
    archiver: str
    version: int
    is_save: bool
    object_count: int | None
    objects: tuple[ZenWorldObject, ...]
    has_world_mesh: bool
    has_vob_tree: bool
    details_available: bool


class ZenWorldError(ValueError):
    """Malformed or unsupported ZEN archive."""


def _header(stream):
    """Parse headers without reading the large world payload."""
    consumed = 0

    def line():
        nonlocal consumed
        raw = stream.readline(_HEADER_BYTES - consumed + 1)
        consumed += len(raw)
        if not raw or consumed > _HEADER_BYTES or not raw.endswith(b'\n'):
            raise ZenWorldError('Повреждённый или слишком большой заголовок ZEN.')
        return raw.rstrip(b'\r\n').decode('latin-1')

    if line() != 'ZenGin Archive':
        raise ZenWorldError('Файл не является архивом ZenGin.')
    version_line = line()
    if not re.fullmatch(r'ver \d+', version_line):
        raise ZenWorldError('Неизвестная версия заголовка ZEN.')
    archiver = line()
    encoding = line()
    if archiver not in ('zCArchiverGeneric', 'zCArchiverBinSafe') or encoding not in ('ASCII', 'BINARY', 'BIN_SAFE'):
        raise ZenWorldError('Неподдерживаемый тип архива ZEN.')
    save_line = line()
    if save_line not in ('saveGame 0', 'saveGame 1'):
        raise ZenWorldError('Некорректный признак сохранения ZEN.')
    for _ in range(32):
        if line() == 'END':
            break
    else:
        raise ZenWorldError('Не найден конец основного заголовка ZEN.')
    if encoding == 'BIN_SAFE':
        raw = stream.read(12)
        if len(raw) != 12:
            raise ZenWorldError('Неполный бинарный заголовок BIN_SAFE.')
        _, count, hash_offset = struct.unpack('<III', raw)
        if hash_offset < stream.tell():
            raise ZenWorldError('Некорректное положение таблицы BIN_SAFE.')
        return int(version_line[4:]), archiver, encoding, save_line.endswith('1'), count, hash_offset
    count = None
    for _ in range(32):
        part = line()
        if re.fullmatch(r'objects \d+', part):
            count = int(part.split()[1])
        if part == 'END':
            return int(version_line[4:]), archiver, encoding, save_line.endswith('1'), count, None
    raise ZenWorldError('Не найден конец заголовка объектов ZEN.')


def inspect_zen(path: str | Path, *, include_objects: bool = True) -> ZenWorldInfo:
    """Inspect a loose .ZEN file without changing it or loading binary meshes.

    ASCII and BIN_SAFE can return VOB properties. BINARY is header-only.
    Geometry payloads are deliberately not decoded yet.
    """
    source = Path(path)
    if source.suffix.casefold() != '.zen':
        raise ZenWorldError('Выберите файл мира с расширением .ZEN.')
    with source.open('rb') as stream:
        version, archiver, encoding, saved, count, hash_offset = _header(stream)
        if encoding == 'BIN_SAFE' and include_objects:
            try:
                entries, has_mesh, has_tree = read_binsafe(
                    stream, stream.tell(), hash_offset, source.stat().st_size)
            except BinSafeError as exc:
                raise ZenWorldError(str(exc)) from exc
            objects = tuple(ZenWorldObject(
                entry.name, entry.classes, entry.index, entry.parent_index,
                entry.properties) for entry in entries)
            return ZenWorldInfo(source, encoding, archiver, version, saved, count,
                                objects, has_mesh, has_tree, True)
        if encoding != 'ASCII' or not include_objects:
            return ZenWorldInfo(source, encoding, archiver, version, saved, count, (), False, False, False)
        if source.stat().st_size > _MAX_ASCII_BYTES:
            raise ZenWorldError('ASCII ZEN превышает лимит 128 МБ для текстового анализа.')
        payload = stream.read().decode('latin-1')
    objects = []
    stack: list[tuple[int | None, bool]] = []
    has_mesh = False
    has_tree = False
    for raw in payload.splitlines():
        value = raw.strip()
        if not value:
            continue
        if value == '[]':
            if not stack:
                raise ZenWorldError('Лишнее закрытие объекта в ASCII ZEN.')
            stack.pop()
            continue
        match = _BEGIN.fullmatch(value)
        if match:
            name, classes, _, index = match.groups()
            is_vob = 'zCVob' in classes.split(':')
            if name == 'MeshAndBsp':
                has_mesh = True
            if name == 'VobTree':
                has_tree = True
            parent = next((i for i, vob in reversed(stack) if vob), None)
            if is_vob:
                objects.append(ZenWorldObject(name, classes, int(index), parent, {}))
            stack.append((int(index) if is_vob else None, is_vob))
            continue
        if '=' in value and stack:
            key, _, entry = value.partition('=')
            if stack[-1][1] and objects:
                _, separator, content = entry.partition(':')
                if separator and key in ('vobName', 'visual', 'trafoOSToWSPos', 'presetName', 'itemInstance'):
                    objects[-1].properties[key] = content
            continue
        raise ZenWorldError('Неизвестная строка в ASCII ZEN.')
    if stack:
        raise ZenWorldError('Незакрытый объект в ASCII ZEN.')
    return ZenWorldInfo(source, encoding, archiver, version, saved, count,
                        tuple(objects), has_mesh, has_tree, True)


def discover_zen(game: str | Path) -> list[Path]:
    """List loose world files without recursively searching entire installation."""
    game = Path(game)
    locations = (game / '_work' / 'data' / 'Worlds', game / 'Worlds')
    seen: set[Path] = set()
    result = []
    for folder in locations:
        if not folder.is_dir():
            continue
        for path in folder.rglob('*'):
            if path.is_file() and path.suffix.casefold() == '.zen':
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    result.append(path)
    return sorted(result, key=lambda path: str(path).casefold())
