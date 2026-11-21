"""Read-only ZEN metadata inspection, including binary format detection."""
import struct
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gothic_editor.core.zen_world import ZenWorldError, discover_zen, inspect_zen


HEADER = (b'ZenGin Archive\nver 1\nzCArchiverGeneric\n{encoding}\n'
          b'saveGame 0\ndate 17.9.2002 15:21:1\nuser test\nEND\n')


class ZenWorldTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'NEWWORLD.ZEN'

    def test_ascii_vob_hierarchy(self):
        data = (HEADER.replace(b'{encoding}', b'ASCII') + b'objects 3\nEND\n'
                b'[% oCWorld:zCWorld 64513 0]\n[VobTree % 0 0]\n'
                b'childs0=int:1\n[% zCVob 39168 1]\n'
                b'vobName=string:APPLE\nvisual=string:ITFO_APPLE.3DS\n'
                b'trafoOSToWSPos=vec3:10 20 30\n'
                b'[% oCItem:zCVob 39168 2]\n'
                b'vobName=string:APPLE2\n[]\n[]\n[]\n[]\n')
        self.path.write_bytes(data)
        info = inspect_zen(self.path)
        self.assertEqual(info.encoding, 'ASCII')
        self.assertTrue(info.has_vob_tree)
        self.assertEqual(len(info.objects), 2)
        self.assertEqual(info.objects[1].parent_index, 1)
        self.assertEqual(info.objects[0].properties['trafoOSToWSPos'], '10 20 30')
        self.assertEqual(self.path.read_bytes(), data)

    def test_binary_metadata_only(self):
        self.path.write_bytes(HEADER.replace(b'{encoding}', b'BINARY') + b'objects 8\nEND\n\x00')
        info = inspect_zen(self.path)
        self.assertEqual(info.object_count, 8)
        self.assertFalse(info.details_available)
        self.assertEqual(info.objects, ())

    def test_binsafe_binary_header(self):
        self.path.write_bytes(HEADER.replace(b'zCArchiverGeneric', b'zCArchiverBinSafe')
                              .replace(b'{encoding}', b'BIN_SAFE') + struct.pack('<III', 1, 42, 2048))
        info = inspect_zen(self.path)
        self.assertEqual(info.object_count, 42)
        self.assertFalse(info.details_available)

    def test_invalid_truncated_header(self):
        self.path.write_bytes(b'ZenGin Archive\nver 1\n')
        with self.assertRaises(ZenWorldError):
            inspect_zen(self.path)

    def test_discovery_in_worlds_folder(self):
        folder = self.root / '_work' / 'data' / 'Worlds' / 'Addon'
        folder.mkdir(parents=True)
        (folder / 'ADDONWORLD.ZEN').write_bytes(b'data')
        self.assertEqual(discover_zen(self.root), [folder / 'ADDONWORLD.ZEN'])


if __name__ == '__main__':
    unittest.main()
