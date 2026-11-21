"""Media replacements stay inside the project and build into the correct paths."""
from pathlib import Path
import struct
import tempfile
import unittest

from gothic_editor.core.build_assets import BuildAssetService
from gothic_editor.core.game_media import GameMedia, media_category
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

    def test_export_image_to_editable_png(self):
        import zlib
        from gothic_editor.core.game_media import MediaResource
        source=Path(self.temp.name)/'original.tga'
        source.write_bytes(tga())
        resource=MediaResource('LOADING-C.TEX','images',source,'chapters')
        output=Path(self.temp.name)/'export.png'
        GameMedia.export_file(resource,output)
        data=output.read_bytes()
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(struct.unpack_from('>II',data,16),(2,2))
        offset=8
        chunks={}
        while offset<len(data):
            length=struct.unpack_from('>I',data,offset)[0]
            kind=data[offset+4:offset+8]
            chunks[kind]=data[offset+8:offset+8+length]
            offset+=12+length
        pixels=zlib.decompress(chunks[b'IDAT'])
        self.assertEqual(pixels[0],0)
        self.assertEqual(len(pixels),2*(1+2*4))

    def test_bik_is_read_from_vdf_catalog(self):
        from gothic_editor.core.mod_archive import write_mod
        from gothic_editor.core.vdf import VdfArchive
        archive=Path(self.temp.name)/'Videos.vdf'
        write_mod(archive,{'_work/data/Video/Intro.bik':b'BIKi'+bytes(range(8))})
        entry=VdfArchive(archive).entries['intro.bik']
        self.assertEqual(entry.read_bytes(),b'BIKi'+bytes(range(8)))

    def test_export_video_is_byte_identical(self):
        from gothic_editor.core.game_media import MediaResource
        source=Path(self.temp.name)/'intro.bik'
        source.write_bytes(b'BIKi'+bytes(range(64)))
        resource=MediaResource('intro.bik','videos',source,'videos')
        output=Path(self.temp.name)/'export.bik'
        GameMedia.export_file(resource,output)
        self.assertEqual(output.read_bytes(),source.read_bytes())
        with self.assertRaises(ValueError):
            GameMedia.export_file(resource,Path(self.temp.name)/'bad.mp4')

    def test_png_and_jpeg_replace_into_gothic_texture(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow is optional; Windows uses its native decoder')
        for suffix in ('.png','.jpg'):
            with self.subTest(suffix=suffix):
                source=Path(self.temp.name)/('replacement'+suffix)
                image=Image.new('RGB',(4,3),(200,50,20))
                image.save(source)
                path=self.media.replace_image('LOADING.TGA',source)
                texture=read_ztex(path.read_bytes())
                self.assertEqual((texture.width,texture.height),(4,3))
                self.assertEqual(path.name,'LOADING-C.TEX')

    def test_catalog_uses_game_resources_and_project_overrides(self):
        from types import SimpleNamespace
        source=Path(self.temp.name)/'original.tga'
        source.write_bytes(tga())
        archive=SimpleNamespace(
            texture_entries={'startscreen.tga':source,'chapter1.tga':source,
                             'miscicon.tga':source},
            entries={'intro.bik':source})
        catalog=self.media.catalog(archive)
        self.assertEqual({row.category for row in catalog},
                         {'menu','chapters','images','videos'})
        image=next(row for row in catalog if row.name=='startscreen-C.TEX')
        self.assertFalse(image.overridden)
        self.media.import_file('images','startscreen.tga',source)
        catalog=self.media.catalog(archive)
        image=next(row for row in catalog if row.name.casefold()=='startscreen-c.tex')
        self.assertTrue(image.overridden)
        self.assertEqual(media_category('MENU_LOGO.TGA'),'menu')

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
