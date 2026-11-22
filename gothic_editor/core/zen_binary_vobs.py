"""Bounded read-only BINARY ZenGin VOB-tree reader.

The raw layout follows ZenKit's World.cc, VobTree.cc, VirtualObject.cc and
ArchiveBinary.cc. Subclass payloads are skipped using their object sizes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import struct

from .zen_binary import _object_header
from .zen_geometry import ZenGeometryError

_MAX_NODES = 150000
_MAX_DEPTH = 512
_MAX_TEXT = 4096


@dataclass(frozen=True)
class BinaryVob:
    name: str
    classes: str
    index: int
    parent_index: int | None
    properties: dict[str, str]


def _exact(stream, size, end):
    if size < 0 or stream.tell() + size > end:
        raise ZenGeometryError('VOB выходит за границы BINARY ZEN.')
    data = stream.read(size)
    if len(data) != size:
        raise ZenGeometryError('Неожиданный конец VOB.')
    return data


def _int(stream, end):
    return struct.unpack('<i', _exact(stream, 4, end))[0]


def _string(stream, end):
    raw = bytearray()
    for _ in range(_MAX_TEXT):
        char = _exact(stream, 1, end)
        if char in (b'\0', b'\n'):
            return raw.decode('cp1252')
        raw.extend(char)
    raise ZenGeometryError('Слишком длинная строка VOB.')


def _object(stream, bound):
    start = stream.tell()
    name, classes, end = _object_header(stream, bound)
    if end <= start:
        raise ZenGeometryError('Повреждённый объект VOB.')
    return name, classes, end


def _parse_properties(stream, end, gothic2):
    packed = _int(stream, end)
    if packed not in (0, 1):
        raise ZenGeometryError('Неподдерживаемая упаковка VOB.')
    if packed:
        raw = _exact(stream, 83 if gothic2 else 74, end)
        floats = struct.unpack_from('<18f', raw)
        position = floats[6:9]
        rotation = floats[9:18]
        bit0 = raw[72]
        flags = struct.unpack_from('<H', raw, 73)[0] if gothic2 else raw[73]
        # The packed data only contains strings selected by the bitfield.
        if flags & 1:
            _string(stream, end)  # preset
        name = _string(stream, end) if flags & 2 else ''
        visual = _string(stream, end) if flags & 4 else ''
        show = bool(bit0 & 1)
    else:
        _string(stream, end)  # preset
        _exact(stream, 24, end)  # bbox
        rotation = struct.unpack('<9f', _exact(stream, 36, end))
        position = struct.unpack('<3f', _exact(stream, 12, end))
        name = _string(stream, end)
        visual = _string(stream, end)
        show = _exact(stream, 1, end) != b'\x00'
    if not all(math.isfinite(v) and abs(v) < 1e8 for v in position):
        raise ZenGeometryError('Некорректная позиция VOB.')
    if not all(math.isfinite(v) and abs(v) <= 2 for v in rotation):
        raise ZenGeometryError('Некорректный поворот VOB.')
    return {'vobName': name, 'visual': visual,
            'trafoOSToWSPos': ' '.join(str(v) for v in position),
            'trafoOSToWSRot': ' '.join(str(v) for v in rotation),
            'showVisual': '1' if show else '0'}


def _walk_tree(stream, section_end, gothic2):
    """Iterative traversal, because Gothic may have deeply nested objects."""
    root_count = _int(stream, section_end)
    if not 0 <= root_count <= _MAX_NODES:
        raise ZenGeometryError('Недопустимое число корневых VOB.')
    pending = [(root_count, None, 0)]
    nodes = []
    while pending:
        remaining, parent, depth = pending[-1]
        if not remaining:
            pending.pop()
            continue
        pending[-1] = (remaining - 1, parent, depth)
        if depth >= _MAX_DEPTH or len(nodes) >= _MAX_NODES:
            raise ZenGeometryError('Превышены ограничения дерева VOB.')
        name, classes, end = _object(stream, section_end)
        properties = {}
        if 'zCVob' in classes.split(':'):
            properties = _parse_properties(stream, end, gothic2)
        # Unknown subclass properties and nested visual/AI objects remain
        # within the VOB's declared object size.
        stream.seek(end)
        index = len(nodes)
        nodes.append(BinaryVob(name, classes, index, parent, properties))
        children = _int(stream, section_end)
        if not 0 <= children <= _MAX_NODES:
            raise ZenGeometryError('Недопустимое количество дочерних VOB.')
        pending.append((children, index, depth + 1))
    return tuple(nodes)


def read_binary_vobs(path: str | Path):
    """Parse BINARY VobTree with packed/unpacked VOB properties.

    Return (objects, status). Malformed data raises ValueError; terrain loading
    continues independently in the caller.
    """
    from .zen_world import _header
    source = Path(path)
    with source.open('rb') as stream:
        _, _, encoding, _, _, _ = _header(stream)
        if encoding != 'BINARY':
            raise ZenGeometryError('Ожидался BINARY ZEN.')
        payload = stream.tell()
        size = source.stat().st_size
        _, root_class, root_end = _object(stream, size)
        if 'zCWorld' not in root_class.split(':'):
            raise ZenGeometryError('Корневой объект не является миром Gothic.')
        root_body = stream.tell()
        gothic2 = False
        vob_offset = None
        vob_end = None
        # MeshAndBsp supplies the reliable Gothic version even when the VOB
        # section precedes it.
        while stream.tell() < root_end:
            name, _classes, end = _object(stream, root_end)
            if name == 'MeshAndBsp':
                version = struct.unpack('<I', _exact(stream, 4, end))[0]
                gothic2 = version == 0x4090000
            elif name == 'VobTree':
                vob_offset, vob_end = stream.tell(), end
            stream.seek(end)
        if vob_offset is None:
            return (), 'BINARY: VobTree отсутствует'
        stream.seek(vob_offset)
        objects = _walk_tree(stream, vob_end, gothic2)
        return objects, 'BINARY: дерево VOB прочитано'
