"""Read-only extraction of MeshAndBsp from ZenGin BINARY world archives."""
from __future__ import annotations

import struct

from .zen_geometry import parse_mesh_and_bsp, ZenGeometryError


def _null_string(stream, end):
    output = bytearray()
    while stream.tell() < end and len(output) <= 4096:
        value = stream.read(1)
        if value == b'\x00':
            return output.decode('cp1252')
        if not value:
            break
        output.extend(value)
    raise ZenGeometryError('Повреждённое имя объекта BINARY ZEN.')


def _object_header(stream, parent_end):
    start = stream.tell()
    if parent_end - start < 10:
        raise ZenGeometryError('Неполный заголовок объекта BINARY ZEN.')
    size, version, index = struct.unpack('<IHI', stream.read(10))
    end = start + size
    if size < 12 or end > parent_end:
        raise ZenGeometryError('Объект BINARY ZEN выходит за границы родителя.')
    name = _null_string(stream, end)
    class_name = _null_string(stream, end)
    return name, class_name, end


def read_binary_world_mesh(stream, payload_start, file_size, *, include_triangles=False):
    """Find MeshAndBsp in the root world object and parse its compiled mesh."""
    stream.seek(payload_start)
    root_name, root_class, world_end = _object_header(stream, file_size)
    if 'zCWorld' not in root_class.split(':'):
        raise ZenGeometryError('Корневой объект BINARY ZEN не является zCWorld.')
    while stream.tell() < world_end:
        name, _, object_end = _object_header(stream, world_end)
        if name == 'MeshAndBsp':
            mesh, _ = parse_mesh_and_bsp(
                stream, object_end, include_triangles=include_triangles)
            return mesh
        stream.seek(object_end)
    raise ZenGeometryError('В ZEN нет компилированного блока MeshAndBsp.')
