"""Export source 3DS files or convert archived MRM geometry without dependencies."""
from pathlib import Path
import math
import struct

from .localization import tr
from .mesh import MeshFormatError, read_mrm


def geometry_3ds(vertices, faces):
    if not vertices or not faces:
        raise MeshFormatError(tr('viewer.no_triangles'))
    if len(vertices) > 65535 or len(faces) > 65535:
        raise MeshFormatError(tr('model_export.too_large'))
    if any(not math.isfinite(number) for vertex in vertices for number in vertex):
        raise MeshFormatError(tr('viewer.invalid_format'))
    if any(min(face) < 0 or max(face) >= len(vertices) for face in faces):
        raise MeshFormatError(tr('viewer.invalid_format'))

    def chunk(kind, payload):
        return struct.pack('<HI', kind, len(payload) + 6) + payload

    points = chunk(0x4110, struct.pack('<H', len(vertices)) +
                   b''.join(struct.pack('<3f', *vertex) for vertex in vertices))
    triangles = chunk(0x4120, struct.pack('<H', len(faces)) +
                      b''.join(struct.pack('<4H', *face, 0) for face in faces))
    mesh = chunk(0x4100, points + triangles)
    obj = chunk(0x4000, b'model\0' + mesh)
    version = chunk(0x0002, struct.pack('<I', 3))
    mesh_version = chunk(0x3D3E, struct.pack('<I', 3))
    return chunk(0x4D4D, version + chunk(0x3D3D, mesh_version + obj))


def export_model_3ds(visual, mesh_index, archives, destination):
    """Return True for MRM conversion; preserve source 3DS bytes when available."""
    name = Path(visual.replace('\\', '/')).name.lower()
    source_name = str(Path(name).with_suffix('.3ds')) if Path(name).suffix == '.mrm' else name
    source = mesh_index.get(source_name)
    converted = False
    if source is not None and source.is_file():
        data = source.read_bytes()
    else:
        entry = archives.find(visual) if visual else None
        if entry is None:
            raise ValueError(tr('messages.no_mesh', visual=visual or tr('viewer.no_visual')))
        data = entry.read_bytes()
        if Path(entry.name).suffix.lower() == '.mrm':
            data = geometry_3ds(*read_mrm(data))
            converted = True
    Path(destination).write_bytes(data)
    return converted
