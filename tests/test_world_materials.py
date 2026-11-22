"""Regression coverage for real MSH feature indices and material-to-chunk mapping."""
import struct
import unittest
from io import BytesIO

from gothic_editor.core.mesh_materials import mrm_materials
from gothic_editor.core.world_preview import build_world_chunks
from gothic_editor.core.zen_geometry import parse_mesh_and_bsp


def chunk(kind, data=b''):
    return struct.pack('<HI', kind, len(data)) + data


def materials():
    header = (b'ZenGin Archive\nver 1\nzCArchiverGeneric\nBINARY\n'
              b'saveGame 0\ndate 1.1.2002\nuser test\nEND\nobjects 1\nEND\n')
    fields = b'GRASS\0' + bytes([4]) + bytes((255, 255, 255, 255)) + struct.pack('<f', 0.)
    fields += b'GRASS.TGA\0'
    object_body = struct.pack('<HI', 17408, 0) + b'%\0zCMaterial\0' + fields
    return header + struct.pack('<I', 1) + b'GRASS\0' + struct.pack('<I', len(object_body) + 4) + object_body


def mesh():
    points = struct.pack('<I9f', 3, 0, 0, 0, 1, 0, 0, 0, 1, 0)
    features = (struct.pack('<I', 3) +
                b''.join(struct.pack('<2fI3f', u, v, 0xffffffff, 0, 0, 1)
                         for u, v in ((0., 0.), (1., 0.), (0., 1.))))
    polygon = (struct.pack('<Hhf3fBhB', 0, -1, 0., 0., 0., 1., 0, 0, 3)
               + b''.join(struct.pack('<II', i, i) for i in range(3)))
    body = (chunk(0xB000, struct.pack('<H', 265)) + chunk(0xB020, materials())
            + chunk(0xB030, points) + chunk(0xB040, features)
            + chunk(0xB050, struct.pack('<I', 1) + polygon) + chunk(0xB060))
    return struct.pack('<II', 0, len(body)) + body


class WorldMaterialsTests(unittest.TestCase):
    def test_binary_material_archive_contains_original_texture(self):
        self.assertEqual(mrm_materials(materials(), 1), [('GRASS', 'GRASS.TGA')])

    def test_world_uvs_and_textures_remain_aligned_with_chunk_faces(self):
        data = mesh()
        geometry, end = parse_mesh_and_bsp(BytesIO(data), len(data), include_triangles=True)
        self.assertEqual(end, len(data))
        self.assertEqual(geometry.triangles, ((0, 1, 2),))
        self.assertEqual(geometry.triangle_uvs, (((0., 0.), (1., 0.), (0., 1.)),))
        self.assertEqual(geometry.texture_names, ('GRASS.TGA',))
        world = build_world_chunks(geometry)
        self.assertEqual(world.chunk_uvs[(0, 0)], geometry.triangle_uvs)
        self.assertEqual(world.chunk_textures[(0, 0)], ('GRASS.TGA',))

    def test_gothic_one_16bit_vertex_and_32bit_feature_indices(self):
        data = mesh()
        # Gothic I stores a 16-bit vertex index and a 32-bit feature
        # index per polygon corner, unlike Gothic II's two 32-bit indices.
        payload = (struct.pack('<I', 1) +
                   struct.pack('<Hhf3f', 0, -1, 0., 0., 0., 1.) +
                   b'\\0' * 4 + b'\\x03' +
                   b''.join(struct.pack('<HI', i, i) for i in range(3)))
        original_chunk = chunk(0xB050, struct.pack('<I', 1) +
                               struct.pack('<Hhf3fBhB', 0, -1, 0., 0., 0., 1., 0, 0, 3) +
                               b''.join(struct.pack('<II', i, i) for i in range(3)))
        header = chunk(0xB000, struct.pack('<H', 265))
        gothic_one = (data.replace(header, chunk(0xB000, struct.pack('<H', 9)))
                      .replace(original_chunk, chunk(0xB050, payload)))
        gothic_one = gothic_one[:4] + struct.pack('<I', len(gothic_one) - 8) + gothic_one[8:]
        geometry, _ = parse_mesh_and_bsp(BytesIO(gothic_one), len(gothic_one),
                                         include_triangles=True)
        self.assertEqual(geometry.triangles, ((0, 1, 2),))
        self.assertEqual(geometry.triangle_uvs, (((0., 0.), (1., 0.), (0., 1.)),))

    def test_counts_mode_skips_texture_allocation(self):
        data = mesh()
        geometry, _ = parse_mesh_and_bsp(BytesIO(data), len(data))
        self.assertEqual(geometry.triangle_count, 1)
        self.assertEqual(geometry.triangle_uvs, ())
        self.assertEqual(geometry.texture_names, ())


if __name__ == '__main__':
    unittest.main()
