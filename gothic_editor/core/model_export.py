"""Export source 3DS files or convert archived MRM geometry without dependencies."""
from pathlib import Path
import math
import struct

from .localization import tr
from .mesh import MeshFormatError, read_mrm


def resolve_model_source(visual,mesh_index,archives):
    name=Path(visual.replace('\\','/')).name.lower()
    source_name=str(Path(name).with_suffix('.3ds')) if Path(name).suffix=='.mrm' else name
    source=mesh_index.get(source_name)
    if source is not None and source.is_file():return source
    entry=archives.find(visual) if visual else None
    if entry is None:raise ValueError(tr('messages.no_mesh',visual=visual or tr('viewer.no_visual')))
    return entry


def export_texture(texture,source,destination):
    """Keep original texture bytes, or export decoded Gothic textures as TGA."""
    destination=Path(destination)
    if source is not None and Path(source.name).suffix.lower()==destination.suffix.lower():
        destination.write_bytes(source.read_bytes())
        return
    if destination.suffix.lower()!='.tga':raise ValueError('Для конвертации текстуры выберите формат TGA')
    header=struct.pack('<BBBHHBHHHHBB',0,0,2,0,0,0,0,0,texture.width,texture.height,32,40)
    rgba=texture.pixels
    bgra=bytearray(rgba)
    bgra[0::4]=rgba[2::4]
    bgra[2::4]=rgba[0::4]
    destination.write_bytes(header+bgra)


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


def preview_3ds(mesh):
    """Export static preview geometry retaining UV seams and texture assignments."""
    def chunk(kind, payload):
        return struct.pack('<HI', kind, len(payload) + 6) + payload
    vertices, uvs, faces, lookup, groups = [], [], [], {}, {}
    for index, face in enumerate(mesh.faces):
        coords = mesh.uvs[index] if index < len(mesh.uvs) else None
        triangle = []
        for corner, vertex in enumerate(face):
            uv = coords[corner] if coords else (0., 0.)
            key = vertex, tuple(uv)
            if key not in lookup:
                lookup[key] = len(vertices)
                vertices.append(mesh.vertices[vertex])
                uvs.append((uv[0], 1 - uv[1]))
            triangle.append(lookup[key])
        faces.append(tuple(triangle))
        texture = mesh.texture_names[index] if index < len(mesh.texture_names) else ''
        material = mesh.material_names[index] if index < len(mesh.material_names) else ''
        groups.setdefault((material,texture), []).append(index)
    # Reuse the exporter's bounds, index and finite-coordinate validation.
    geometry_3ds(vertices, faces)
    points = chunk(0x4110, struct.pack('<H', len(vertices)) + b''.join(struct.pack('<3f', *v) for v in vertices))
    mapping = chunk(0x4140, struct.pack('<H', len(uvs)) + b''.join(struct.pack('<2f', *uv) for uv in uvs))
    assignments, materials, used_names = b'', b'', set()
    for number, ((material,texture), indices) in enumerate(groups.items()):
        label = material or f'material_{number}'
        if label in used_names:label += f'_{number}'
        while label in used_names:label += '_'
        used_names.add(label)
        name = label.encode('cp1251') + b'\0'
        assignments += chunk(0x4130, name + struct.pack('<H', len(indices)) + struct.pack(f'<{len(indices)}H', *indices))
        material = chunk(0xA000, name)
        if texture:material += chunk(0xA200, chunk(0xA300, texture.encode('cp1251') + b'\0'))
        materials += chunk(0xAFFF, material)
    triangles = chunk(0x4120, struct.pack('<H', len(faces)) +
                      b''.join(struct.pack('<4H', *face, 0) for face in faces) + assignments)
    obj = chunk(0x4000, b'model\0' + chunk(0x4100, points + triangles + mapping))
    return chunk(0x4D4D, chunk(0x0002, struct.pack('<I', 3)) +
                 chunk(0x3D3D, chunk(0x3D3E, struct.pack('<I', 3)) + obj + materials))
