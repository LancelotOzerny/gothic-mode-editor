"""Synthetic BIN_SAFE fixtures test bounded parsing without game assets."""
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

from gothic_editor.core.zen_world import ZenWorldError, inspect_zen


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


class BinSafeWorldTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'TEST.ZEN'

    def test_nested_vobs_and_skipped_geometry(self):
        body = (string('[% oCWorld:zCWorld 64513 0]')
                + string('[MeshAndBsp % 0 0]')
                + field(0, 9, struct.pack('<H', 5) + b'abcde')
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
        self.assertEqual(self.file.read_bytes(), data)

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
