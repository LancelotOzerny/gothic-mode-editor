"""Geometry readers for static model previews (no materials or animation)."""
import math
import struct
from pathlib import Path

from .localization import tr


class MeshFormatError(ValueError):
    pass


def read_3ds(path: Path):
    """Read vertices + triangular faces from a simple 3DS mesh.

    Materials, textures, keyframed animation and Gothic MRM are intentionally
    outside this reader. Objects are combined into a single mesh.
    """
    return read_3ds_bytes(path.read_bytes())


def read_3ds_bytes(data: bytes):
    if len(data) < 6 or struct.unpack_from('<H', data)[0] != 0x4D4D:
        raise MeshFormatError(tr('viewer.invalid_format'))
    vertices, faces = [], []

    def chunks(start, stop, visitor):
        pos = start
        while pos + 6 <= min(stop, len(data)):
            cid, size = struct.unpack_from('<HI', data, pos)
            if size < 6 or pos + size > len(data):
                break
            visitor(cid, pos + 6, pos + size)
            pos += size

    def parse_mesh(start, end):
        local_vertices, local_faces = [], []
        def part(cid, a, b):
            nonlocal local_vertices, local_faces
            if cid == 0x4110 and a + 2 <= b:
                n = struct.unpack_from('<H', data, a)[0]
                if a + 2 + n * 12 <= b:
                    local_vertices = [struct.unpack_from('<fff', data, a + 2 + k * 12) for k in range(n)]
            elif cid == 0x4120 and a + 2 <= b:
                n = struct.unpack_from('<H', data, a)[0]
                if a + 2 + n * 8 <= b:
                    local_faces = [struct.unpack_from('<HHH', data, a + 2 + k * 8) for k in range(n)]
        chunks(start, end, part)
        base = len(vertices)
        vertices.extend(local_vertices)
        faces.extend((base+i, base+j, base+k) for i,j,k in local_faces if max(i,j,k) < len(local_vertices))

    def parse(cid, a, b):
        if cid in (0x4D4D, 0x3D3D):
            chunks(a, b, parse)
        elif cid == 0x4000:
            zero = data.find(b'\x00', a, b)
            if zero != -1:
                chunks(zero+1, b, parse)
        elif cid == 0x4100:
            parse_mesh(a, b)

    chunks(0, len(data), parse)
    if not vertices or not faces:
        raise MeshFormatError(tr('viewer.no_triangles'))
    return vertices, faces


def read_mrm(data: bytes):
    """Read full-detail MRM geometry, resolving triangle -> wedge -> vertex.

    Layout reference: GothicKit/ZenKit, src/MultiResolutionMesh.cc.
    Materials and LOD updates are intentionally not used for static previews.
    """
    position = 0
    while position + 6 <= len(data):
        kind, size = struct.unpack_from('<HI', data, position)
        start = position + 6
        end = start + size  # ZenGin chunk lengths exclude the six-byte header.
        if end > len(data):
            raise MeshFormatError(tr('viewer.invalid_mrm'))
        if kind == 0xB100:
            return _read_mrm_section(memoryview(data)[start:end])
        if kind == 0xB1FF:
            break
        position = end
    raise MeshFormatError(tr('viewer.invalid_mrm'))


def _read_mrm_section(data):
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
    if not vertices or not faces:
        raise MeshFormatError(tr('viewer.no_triangles'))
    return vertices, faces


