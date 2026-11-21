"""Synthetic BIN_SAFE fixtures test bounded parsing without game assets."""
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

from gothic_editor.core.zen_world import ZenWorldError, inspect_zen, load_zen_geometry


HEADER = (b'ZenGin Archive\nver 1\nzCArchiverBinSafe\nBIN_SAFE\n'
          b'saveGame 0\ndate 17.9.2002 15:21:1\nuser test\nEND\n')


def string(value):
    data = value.encode('cp1252')
    return b'\x01' + struct.pack('<H', len(data)) + data


def field(index, kind, payload):
    return b'\x12' + struct.pack('<IB', index, kind) + payload


def string_field(index, value):
    data = value.encode('cp1252')
    return field(index, 1, struct.pack('<H', len(data)) + data)


def archive(body, names):
    offset = len(HEADER) + 12 + len(body)
    table = struct.pack('<I', len(names))
    for index, name in enumerate(names):
        encoded = name.encode('cp1252')
        table += struct.pack('<HHI', len(encoded), index, 0) + encoded
    return HEADER + struct.pack('<III', 1, 7, offset) + body + table


def chunk(kind, payload=b''):
    return struct.pack('<HI', kind, len(payload)) + payload


def world_mesh():
    vertices = struct.pack('<I9f', 3, 0, 0, 0, 1, 0, 0, 0, 1, 0)
    polygon = (struct.pack('<Hhf3fBhB', 2, -1, 0, 0, 0, 1, 0, 0, 3)
               + b''.join(struct.pack('<II', index, index) for index in range(3)))
    mesh = (chunk(0xB000, struct.pack('<H', 265)) +
            chunk(0xB030, vertices) +
            chunk(0xB050, struct.pack('<I', 1) + polygon) +
            chunk(0xB060))
    return struct.pack('<II', 0x4090000, len(mesh)) + mesh


class BinSafeWorldTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'TEST.ZEN'

    def test_nested_vobs_and_skipped_geometry(self):
        body = (string('[% oCWorld:zCWorld 64513 0]')
                + string('[MeshAndBsp % 0 0]')
                + world_mesh()
                + string('[]')
                + string('[VobTree % 0 0]')
                + string('[% zCVob 39168 1]')
                + string_field(1, 'First')
                + field(2, 7, struct.pack('<3f', 10, 20, -30))
                + string('[% oCItem:zCVob 39168 2]')
                + string_field(1, 'Second')
                + string_field(3, 'ITFO_APPLE.3DS')
                + string('[]') + string('[]') + string('[]') + string('[]'))
        data = archive(body, ['meshData', 'vobName', 'trafoOSToWSPos', 'visual'])
        self.file.write_bytes(data)
        info = inspect_zen(self.file)
        self.assertTrue(info.details_available)
        self.assertTrue(info.has_world_mesh)
        self.assertTrue(info.has_vob_tree)
        self.assertEqual(len(info.objects), 2)
        self.assertEqual(info.objects[1].parent_index, 1)
        self.assertEqual(info.objects[0].properties['trafoOSToWSPos'], '10.0 20.0 -30.0')
        self.assertEqual(info.objects[1].properties['visual'], 'ITFO_APPLE.3DS')
        mesh_info = load_zen_geometry(self.file)
        self.assertEqual((mesh_info.vertex_count, mesh_info.triangle_count), (3, 1))
        self.assertEqual(mesh_info.vertices, ())
        full = load_zen_geometry(self.file, include_triangles=True)
        self.assertEqual(full.triangles, ((0, 1, 2),))
        self.assertEqual(full.materials, (2,))
        self.assertEqual(full.vertices[1], (1.0, 0.0, 0.0))
        self.assertEqual(self.file.read_bytes(), data)

    def test_invalid_geometry_chunk_rejected(self):
        invalid_mesh = struct.pack('<II', 0x4090000, 6) + chunk(0xB030)
        data = archive(string('[MeshAndBsp % 0 0]') + invalid_mesh + string('[]'), [])
        self.file.write_bytes(data)
        with self.assertRaises(ZenWorldError):
            load_zen_geometry(self.file)

    def test_missing_mesh_rejected(self):
        self.file.write_bytes(archive(string('[VobTree % 0 0]') + string('[]'), []))
        with self.assertRaisesRegex(ZenWorldError, 'MeshAndBsp'):
            load_zen_geometry(self.file)

    def test_invalid_field_index(self):
        data = archive(string('[% zCVob 0 1]') + field(4, 2, struct.pack('<i', 1))
                       + string('[]'), ['vobName'])
        self.file.write_bytes(data)
        with self.assertRaisesRegex(ZenWorldError, 'индекс'):
            inspect_zen(self.file)

    def test_skipping_does_not_allow_crossing_hash_table(self):
        body = (string('[% zCVob 0 1]') +
                field(0, 9, struct.pack('<H', 65535)) + string('[]'))
        self.file.write_bytes(archive(body, ['rawField']))
        with self.assertRaisesRegex(ZenWorldError, 'пределы'):
            inspect_zen(self.file)

    def test_header_metadata_avoids_decoding_payload(self):
        self.file.write_bytes(archive(b'broken-body', []))
        info = inspect_zen(self.file, include_objects=False)
        self.assertEqual(info.object_count, 7)
        self.assertFalse(info.details_available)


if __name__ == '__main__':
    unittest.main()
