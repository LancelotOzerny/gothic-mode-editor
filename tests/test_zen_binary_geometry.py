"""Regression fixtures for real ZenGin BINARY layout and BIN_SAFE RAW_FLOAT lengths."""
import struct
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gothic_editor.core.zen_world import load_zen_geometry, inspect_zen
from test_zen_binsafe import archive, string, field, world_mesh


BINARY_HEADER = (b'ZenGin Archive\nver 1\nzCArchiverGeneric\nBINARY\n'
                 b'saveGame 0\ndate 17.9.2002 15:21:1\nuser test\n'
                 b'END\nobjects 3\nEND\n')


def binary_object(name, class_name, body):
    metadata = struct.pack('<HI', 0, 0) + name.encode('cp1252') + b'\x00' + class_name.encode('cp1252') + b'\x00'
    payload = metadata + body
    return struct.pack('<I', len(payload) + 4) + payload


class BinaryGeometryTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'NEWWORLD.ZEN'

    def test_binary_world_geometry(self):
        mesh = binary_object('MeshAndBsp', '%', world_mesh())
        other = binary_object('EndMarker', '%', b'')
        data = BINARY_HEADER + binary_object('%', 'oCWorld:zCWorld', mesh + other)
        self.path.write_bytes(data)
        model = load_zen_geometry(self.path, include_triangles=True)
        self.assertEqual(model.vertex_count, 3)
        self.assertEqual(model.triangles, ((0, 1, 2),))
        self.assertEqual(model.materials, (2,))
        self.assertEqual(self.path.read_bytes(), data)

    def test_binary_non_world_rejected(self):
        self.path.write_bytes(BINARY_HEADER + binary_object('%', 'zCVob', b''))
        with self.assertRaisesRegex(ValueError, 'zCWorld'):
            load_zen_geometry(self.path)

    def test_binsafe_raw_float_length_is_bytes_not_float_count(self):
        body = (string('[% oCWorld:zCWorld 64513 0]') +
                field(0, 16, struct.pack('<H', 8) + struct.pack('<2f', 1, 2)) +
                string('[MeshAndBsp % 0 0]') + world_mesh() +
                string('[]') + string('[]'))
        self.path.write_bytes(archive(body, ['bbox']))
        model = load_zen_geometry(self.path)
        self.assertEqual(model.triangle_count, 1)
        info = inspect_zen(self.path)
        self.assertTrue(info.has_world_mesh)


if __name__ == '__main__':
    unittest.main()
