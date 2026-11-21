"""Media replacements stay inside the project and build into the correct paths."""
from pathlib import Path
import struct
import tempfile
import unittest

from gothic_editor.core.build_assets import BuildAssetService
from gothic_editor.core.game_media import GameMedia
from gothic_editor.core.textures import read_ztex


def tga():
    header = struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0, 2, 2, 24, 32)
    return header + b'\x00\x00\xff' * 4


class GameMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'project'
        (self.project / 'Assets').mkdir(parents=True)
        self.media = GameMedia(self.project)

    def test_image_import_and_build_mapping(self):
        source = Path(self.temp.name) / 'original.tga'
        source.write_bytes(tga())
        path = self.media.import_file('images', 'STARTSCREEN.TGA', source)
        self.assertEqual(path.name, 'STARTSCREEN-C.TEX')
        self.assertEqual((read_ztex(path.read_bytes()).width, read_ztex(path.read_bytes()).height), (2, 2))
        packaged = BuildAssetService(self.project).collect()
        self.assertEqual(packaged['_work/data/Textures/_compiled/STARTSCREEN-C.TEX'], path.read_bytes())
        self.media.delete('images', 'STARTSCREEN.TGA')
        self.assertFalse(path.exists())

    def test_bik_is_exported_separately_and_never_in_mod(self):
        source = Path(self.temp.name) / 'intro.bik'
        source.write_bytes(b'BIKi' + b'example video')
        path = self.media.import_file('videos', 'Intro.bik', source)
        self.assertEqual(path.read_bytes(), source.read_bytes())
        self.assertEqual(self.media.videos(), [path])
        self.assertFalse(any('Intro.bik' in name for name in BuildAssetService(self.project).collect()))

    def test_rejects_invalid_file_and_path(self):
        source = Path(self.temp.name) / 'broken.bik'
        source.write_bytes(b'not bink')
        with self.assertRaises(ValueError):
            self.media.import_file('videos', 'Intro.bik', source)
        with self.assertRaises(ValueError):
            self.media.path('images', '../outside')
        with self.assertRaises(ValueError):
            self.media.path('images', 'picture.png')
        with self.assertRaises(ValueError):
            self.media.path('videos', 'bad.mp4')


if __name__ == '__main__':
    unittest.main()
