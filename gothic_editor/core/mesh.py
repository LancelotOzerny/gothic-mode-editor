"""Static geometry readers, optionally including preview UVs and texture names."""
from dataclasses import dataclass, field
import math
import struct
from pathlib import Path

from .localization import tr


class MeshFormatError(ValueError):
    pass


@dataclass
class PreviewMesh:
    vertices: list
    faces: list
    uvs: list = field(default_factory=list)
    texture_names: list = field(default_factory=list)


def read_3ds(path: Path):
    """Read geometry for export; the preview reader also exposes UVs/materials."""
    return read_3ds_bytes(path.read_bytes())


def read_3ds_bytes(data: bytes, *, preview=False):
    if len(data) < 6 or struct.unpack_from('<H', data)[0] != 0x4D4D:
        raise MeshFormatError(tr('viewer.invalid_format'))
    vertices, faces = [], []
    uvs, face_materials, materials = [], [], {}

    def chunks(start, stop, visitor):
        pos = start
        while pos + 6 <= min(stop, len(data)):
            cid, size = struct.unpack_from('<HI', data, pos)
            if size < 6 or pos + size > len(data):
                break
            visitor(cid, pos + 6, pos + size)
            pos += size

    def parse_mesh(start, end):
        local_vertices, local_faces, local_uvs, groups = [], [], [], {}
        def part(cid, a, b):
            nonlocal local_vertices, local_faces, local_uvs
            if cid == 0x4110 and a + 2 <= b:
                n = struct.unpack_from('<H', data, a)[0]
                if a + 2 + n * 12 <= b:
                    local_vertices = [struct.unpack_from('<fff', data, a + 2 + k * 12) for k in range(n)]
            elif cid == 0x4120 and a + 2 <= b:
                n = struct.unpack_from('<H', data, a)[0]
                if a + 2 + n * 8 <= b:
                    local_faces = [struct.unpack_from('<HHH', data, a + 2 + k * 8) for k in range(n)]
                    if preview:
                        def group(kind, first, last):
                            if kind != 0x4130:
                                return
                            zero = data.find(b'\0', first, last)
                            if zero < 0 or zero + 3 > last:
                                return
                            name = data[first:zero].decode('cp1251')
                            count = struct.unpack_from('<H', data, zero + 1)[0]
                            if zero + 3 + count * 2 > last:
                                return
                            for index in struct.unpack_from(f'<{count}H', data, zero + 3):
                                groups[index] = name
                        chunks(a + 2 + n * 8, b, group)
            elif preview and cid == 0x4140 and a + 2 <= b:
                n = struct.unpack_from('<H', data, a)[0]
                if a + 2 + n * 8 <= b:
                    local_uvs = [struct.unpack_from('<ff', data, a + 2 + k * 8) for k in range(n)]
        chunks(start, end, part)
        base = len(vertices)
        vertices.extend(local_vertices)
        for index, (i, j, k) in enumerate(local_faces):
            if max(i, j, k) >= len(local_vertices):
                continue
            faces.append((base + i, base + j, base + k))
            if preview:
                coords = (tuple((local_uvs[v][0], 1 - local_uvs[v][1]) for v in (i, j, k))
                          if max(i, j, k) < len(local_uvs) else None)
                uvs.append(coords if coords and all(math.isfinite(n) for uv in coords for n in uv) else None)
                face_materials.append(groups.get(index, ''))

    def parse_material(start, end):
        name, texture = '', ''
        def part(kind, a, b):
            nonlocal name, texture
            if kind == 0xA000:
                name = data[a:b].split(b'\0', 1)[0].decode('cp1251')
            elif kind == 0xA300:
                texture = data[a:b].split(b'\0', 1)[0].decode('cp1251')
            elif kind == 0xA200:
                chunks(a, b, part)
        chunks(start, end, part)
        materials[name] = texture

    def parse(cid, a, b):
        if cid in (0x4D4D, 0x3D3D):
            chunks(a, b, parse)
        elif cid == 0x4000:
            zero = data.find(b'\x00', a, b)
            if zero != -1:
                chunks(zero+1, b, parse)
        elif cid == 0x4100:
            parse_mesh(a, b)
        elif preview and cid == 0xAFFF:
            parse_material(a, b)

    chunks(0, len(data), parse)
    if not vertices or not faces:
        raise MeshFormatError(tr('viewer.no_triangles'))
    if preview:
        if any(not math.isfinite(n) for vertex in vertices for n in vertex):
            raise MeshFormatError(tr('viewer.invalid_format'))
        return PreviewMesh(vertices, faces, uvs, [materials.get(name, '') for name in face_materials])
    return vertices, faces


def read_mrm(data: bytes, *, preview=False):
    """Read full-detail MRM geometry, resolving triangle -> wedge -> vertex.

    Layout reference: GothicKit/ZenKit, src/MultiResolutionMesh.cc.
    The optional preview includes wedge UVs and material texture names, without LOD updates.
    """
    position = 0
    while position + 6 <= len(data):
        kind, size = struct.unpack_from('<HI', data, position)
        start = position + 6
        end = start + size  # ZenGin chunk lengths exclude the six-byte header.
        if end > len(data):
            raise MeshFormatError(tr('viewer.invalid_mrm'))
        if kind == 0xB100:
            return _read_mrm_section(memoryview(data)[start:end], preview=preview)
        if kind == 0xB1FF:
            break
        position = end
    raise MeshFormatError(tr('viewer.invalid_mrm'))


def _read_mrm_section(data, *, preview=False):
    def invalid():
        return MeshFormatError(tr('viewer.invalid_mrm'))

    if len(data) < 6:
        raise invalid()
    version, content_size = struct.unpack_from('<HI', data)
    if version not in (0x305, 0x805, 0x905):
        raise MeshFormatError(tr('viewer.unsupported_mrm', version=hex(version)))
    content_start = 6
    content_end = content_start + content_size
    if content_end + 17 > len(data):
        raise invalid()
    submeshes = data[content_end]
    vertex_offset, vertex_count, _, _ = struct.unpack_from('<4I', data, content_end + 1)
    metadata = content_end + 17
    if metadata + submeshes * 80 > len(data) or vertex_count > 500_000:
        raise invalid()

    def section(offset, count, stride):
        if offset + count * stride > content_size:
            raise invalid()
        return data[content_start + offset:content_start + offset + count * stride]

    vertices = list(struct.iter_unpack('<fff', section(vertex_offset, vertex_count, 12)))
    if any(not math.isfinite(number) for vertex in vertices for number in vertex):
        raise invalid()
    faces = []
    uvs, texture_names = [], []
    if preview:
        from .mesh_materials import mrm_textures
        materials = mrm_textures(bytes(data[metadata + submeshes * 80:]), submeshes)
    for index in range(submeshes):
        triangle_offset, triangle_count, wedge_offset, wedge_count = struct.unpack_from(
            '<4I', data, metadata + index * 80)
        if triangle_count + len(faces) > 500_000:
            raise invalid()
        triangles = section(triangle_offset, triangle_count, 6)
        wedges = section(wedge_offset, wedge_count, 24)
        vertex_indices = [struct.unpack_from('<H', wedges, offset + 20)[0]
                          for offset in range(0, len(wedges), 24)]
        for triangle in struct.iter_unpack('<HHH', triangles):
            if max(triangle) >= len(vertex_indices):
                raise invalid()
            face = tuple(vertex_indices[wedge] for wedge in triangle)
            if max(face) >= len(vertices):
                raise invalid()
            faces.append(face)
            if preview:
                coords = tuple(struct.unpack_from('<ff', wedges, wedge * 24 + 12) for wedge in triangle)
                uvs.append(coords if all(math.isfinite(n) for uv in coords for n in uv) else None)
                texture_names.append(materials[index])
    if not vertices or not faces:
        raise MeshFormatError(tr('viewer.no_triangles'))
    return PreviewMesh(vertices, faces, uvs, texture_names) if preview else (vertices, faces)


