"""Bounded, read-only extraction of compiled ZenGin world mesh geometry.

MeshAndBsp contains an embedded chunked MSH followed by a BSP tree. Materials
and lightmaps are intentionally not decoded in the first wireframe iteration.
"""
from __future__ import annotations
from dataclasses import dataclass
import struct


class ZenGeometryError(ValueError):
    pass


@dataclass(frozen=True)
class WorldGeometry:
    vertex_count: int
    polygon_count: int
    triangle_count: int
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    materials: tuple[int, ...]


MAX_VERTICES = 2_000_000
MAX_POLYGONS = 2_000_000
MAX_TRIANGLES = 4_000_000


def _read(stream, size, limit):
    if size < 0 or stream.tell() + size > limit:
        raise ZenGeometryError('Геометрия ZEN выходит за границы блока.')
    data = stream.read(size)
    if len(data) != size:
        raise ZenGeometryError('Неожиданный конец геометрии ZEN.')
    return data


def _uint(stream, limit):
    return struct.unpack('<I', _read(stream, 4, limit))[0]


def parse_mesh_and_bsp(stream, limit, *, include_triangles=False):
    """Read MeshAndBsp from its BSP version field; return (mesh, end offset).

    Streaming stats mode skips vertex and index data. Full mode returns
    triangles for an eventual wireframe preview. BSP is not decoded.
    """
    _bsp_version = _uint(stream, limit)
    size = _uint(stream, limit)
    end = stream.tell() + size
    if end > limit:
        raise ZenGeometryError('Некорректный размер MeshAndBsp.')
    vertices, triangles, materials = [], [], []
    vertex_count = polygon_count = triangle_count = 0
    version = None
    finished = False
    while stream.tell() < end:
        kind, length = struct.unpack('<HI', _read(stream, 6, end))
        chunk_end = stream.tell() + length
        if chunk_end > end:
            raise ZenGeometryError('Чанк MSH выходит за границы меша.')
        if kind == 0xB000:
            version = struct.unpack('<H', _read(stream, 2, chunk_end))[0]
            if version not in (9, 265):
                raise ZenGeometryError('Неподдерживаемая версия MSH: ' + str(version))
        elif kind == 0xB030:
            vertex_count = _uint(stream, chunk_end)
            if vertex_count > MAX_VERTICES or vertex_count * 12 > chunk_end - stream.tell():
                raise ZenGeometryError('Некорректное количество вершин MSH.')
            if include_triangles:
                vertices = [struct.unpack('<3f', _read(stream, 12, chunk_end))
                            for _ in range(vertex_count)]
        elif kind == 0xB050:
            if version is None:
                raise ZenGeometryError('Перед полигонами отсутствует версия MSH.')
            polygon_count = _uint(stream, chunk_end)
            if polygon_count > MAX_POLYGONS:
                raise ZenGeometryError('Слишком много полигонов MSH.')
            for _ in range(polygon_count):
                material = struct.unpack('<H', _read(stream, 2, chunk_end))[0]
                _read(stream, 18, chunk_end)  # lightmap, plane distance and normal
                _read(stream, 3 if version == 265 else 4, chunk_end)
                corners = _read(stream, 1, chunk_end)[0]
                if corners < 3:
                    raise ZenGeometryError('Полигон MSH содержит менее трёх вершин.')
                triangle_count += corners - 2
                if triangle_count > MAX_TRIANGLES:
                    raise ZenGeometryError('Слишком много треугольников MSH.')
                stride = 8 if version == 265 else 6
                if corners * stride > chunk_end - stream.tell():
                    raise ZenGeometryError('Некорректные индексы полигона MSH.')
                if include_triangles:
                    indices = []
                    for _ in range(corners):
                        index = (_uint(stream, chunk_end) if version == 265 else
                                 struct.unpack('<H', _read(stream, 2, chunk_end))[0])
                        _read(stream, 4, chunk_end)
                        if index >= vertex_count:
                            raise ZenGeometryError('Индекс полигона вне таблицы вершин.')
                        indices.append(index)
                    for j in range(1, corners - 1):
                        triangles.append((indices[0], indices[j], indices[j + 1]))
                        materials.append(material)
                else:
                    stream.seek(corners * stride, 1)
        elif kind == 0xB060:
            finished = True
            stream.seek(end)
            break
        stream.seek(chunk_end)
    if not finished:
        raise ZenGeometryError('Не найден завершающий чанк MSH.')
    if include_triangles and not vertices and triangle_count:
        raise ZenGeometryError('Не найдены вершины меша.')
    return (WorldGeometry(vertex_count, polygon_count, triangle_count,
                          tuple(vertices), tuple(triangles), tuple(materials)), end)
