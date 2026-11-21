"""Bounded streaming reader for annotated BIN_SAFE ZenGin archives.

The decoder retains only selected VOB properties. Large raw mesh and BSP
payloads are skipped rather than loaded into memory. Nothing is written.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from .zen_geometry import parse_mesh_and_bsp, ZenGeometryError


class BinSafeError(ValueError):
    pass


@dataclass(frozen=True)
class BinSafeVob:
    name: str
    classes: str
    index: int
    parent_index: int | None
    properties: dict[str, str]


_WANTED = frozenset(('vobName', 'visual', 'trafoOSToWSPos', 'presetName',
                     'itemInstance'))
_MAX_NAMES = 100_000
_MAX_OBJECTS = 1_000_000
_MAX_DEPTH = 512
_MAX_NAME_LENGTH = 16_384


def _exact(stream, count, end):
    if count < 0 or stream.tell() + count > end:
        raise BinSafeError('BIN_SAFE: данные выходят за пределы секции.')
    result = stream.read(count)
    if len(result) != count:
        raise BinSafeError('BIN_SAFE: неожиданный конец файла.')
    return result


def _u16(stream, end):
    return struct.unpack('<H', _exact(stream, 2, end))[0]


def _u32(stream, end):
    return struct.unpack('<I', _exact(stream, 4, end))[0]


def _text(stream, end):
    length = _u16(stream, end)
    if length > _MAX_NAME_LENGTH:
        raise BinSafeError('BIN_SAFE: слишком длинная строка.')
    return _exact(stream, length, end).decode('cp1252')


def _names(stream, hash_offset, file_size):
    stream.seek(hash_offset)
    count = _u32(stream, file_size)
    if count > _MAX_NAMES:
        raise BinSafeError('BIN_SAFE: слишком много имён полей.')
    result = {}
    for _ in range(count):
        length = _u16(stream, file_size)
        index = _u16(stream, file_size)
        _u32(stream, file_size)  # bucket index
        if length > _MAX_NAME_LENGTH or index in result:
            raise BinSafeError('BIN_SAFE: некорректная таблица имён.')
        result[index] = _exact(stream, length, file_size).decode('cp1252')
    if len(result) != count:
        raise BinSafeError('BIN_SAFE: повреждена таблица имён.')
    return result


def _value(stream, kind, end, keep):
    if kind == 1:
        length = _u16(stream, end)
        if keep:
            if length > _MAX_NAME_LENGTH:
                raise BinSafeError('BIN_SAFE: слишком длинное значение поля.')
            return _exact(stream, length, end).decode('cp1252')
        _skip(stream, length, end)
        return None
    if kind in (9, 16):
        length = _u16(stream, end)
        _skip(stream, length * (4 if kind == 16 else 1), end)
        return None
    sizes = {2: 4, 3: 4, 4: 1, 5: 2, 6: 4, 7: 12, 8: 4, 17: 4}
    size = sizes.get(kind)
    if size is None:
        raise BinSafeError('BIN_SAFE: неизвестный тип поля: ' + str(kind))
    if not keep:
        _skip(stream, size, end)
        return None
    raw = _exact(stream, size, end)
    if kind == 7:
        return ' '.join(str(number) for number in struct.unpack('<3f', raw))
    if kind == 3:
        return str(struct.unpack('<f', raw)[0])
    if kind == 2:
        return str(struct.unpack('<i', raw)[0])
    if kind in (6, 17):
        return str(struct.unpack('<I', raw)[0])
    if kind == 5:
        return str(struct.unpack('<H', raw)[0])
    if kind == 4:
        return str(raw[0])
    return raw.hex()


def _skip(stream, size, end):
    if size < 0 or stream.tell() + size > end:
        raise BinSafeError('BIN_SAFE: поле выходит за пределы данных.')
    stream.seek(size, 1)


def read_binsafe(stream, payload_start, hash_offset, file_size, *, include_geometry=False):
    """Return (VOBs, has_mesh, has_tree, geometry) from a BIN_SAFE payload.

    Reads only until the hash table. Optional geometry output includes triangle
    vertices/indices; materials and BSP remain unsupported.
    """
    if hash_offset < payload_start or hash_offset > file_size:
        raise BinSafeError('BIN_SAFE: неверное смещение таблицы имён.')
    names = _names(stream, hash_offset, file_size)
    stream.seek(payload_start)
    objects = []
    stack = []  # (object index if VOB, is VOB, object record)
    has_mesh = False
    has_tree = False
    records = 0
    geometry = None
    while stream.tell() < hash_offset:
        tag = _exact(stream, 1, hash_offset)[0]
        if tag == 1:
            definition = _text(stream, hash_offset)
            if definition == '[]':
                if not stack:
                    raise BinSafeError('BIN_SAFE: лишний конец объекта.')
                stack.pop()
                continue
            parts = definition.removeprefix('[').removesuffix(']').split()
            if not definition.startswith('[') or not definition.endswith(']') or len(parts) != 4:
                raise BinSafeError('BIN_SAFE: повреждён заголовок объекта.')
            name, classes, version, index_text = parts
            try:
                int(version)
                index = int(index_text)
            except ValueError as exc:
                raise BinSafeError('BIN_SAFE: некорректный индекс объекта.') from exc
            records += 1
            if records > _MAX_OBJECTS or len(stack) >= _MAX_DEPTH:
                raise BinSafeError('BIN_SAFE: превышен лимит объектов или вложенности.')
            has_mesh |= name == 'MeshAndBsp'
            has_tree |= name == 'VobTree'
            is_vob = 'zCVob' in classes.split(':')
            record = None
            if is_vob:
                parent = next((previous[0] for previous in reversed(stack) if previous[1]), None)
                record = BinSafeVob(name, classes, index, parent, {})
                objects.append(record)
            stack.append((index if is_vob else None, is_vob, record))
            if name == 'MeshAndBsp':
                try:
                    geometry, _ = parse_mesh_and_bsp(
                        stream, hash_offset, include_triangles=include_geometry)
                except ZenGeometryError as exc:
                    raise BinSafeError(str(exc)) from exc
        elif tag == 18:
            if not stack:
                raise BinSafeError('BIN_SAFE: поле вне объекта.')
            field_index = _u32(stream, hash_offset)
            field = names.get(field_index)
            if field is None:
                raise BinSafeError('BIN_SAFE: неизвестный индекс поля.')
            kind = _exact(stream, 1, hash_offset)[0]
            record = stack[-1][2]
            keep = record is not None and field in _WANTED
            value = _value(stream, kind, hash_offset, keep)
            if keep and value is not None:
                record.properties[field] = value
        else:
            raise BinSafeError('BIN_SAFE: неизвестный маркер: ' + str(tag))
    if stack:
        raise BinSafeError('BIN_SAFE: незакрытые объекты.')
    return tuple(objects), has_mesh, has_tree, geometry
