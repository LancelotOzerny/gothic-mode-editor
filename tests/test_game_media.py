"""Media replacements stay inside the project and build into the correct paths."""
from pathlib import Path
import struct
import tempfile
import unittest

from gothic_editor.core.build_assets import BuildAssetService
from gothic_editor.core.game_media import GameMedia, media_category
from gothic_editor.core.textures import read_ztex


def tga():
    header = struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0, 4, 4, 24, 32)
    return header + b'\x00\x00\xff' * 16


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
        self.assertEqual((read_ztex(path.read_bytes()).width, read_ztex(path.read_bytes()).height), (4, 4))
        packaged = BuildAssetService(self.project).collect()
        self.assertEqual(packaged['_work/data/Textures/_compiled/STARTSCREEN-C.TEX'], path.read_bytes())
        self.media.delete('images', 'STARTSCREEN.TGA')
        self.assertFalse(path.exists())

    def test_gothic_compatible_dxt_mipmaps(self):
        from gothic_editor.core.textures import Texture, write_ztex
        for alpha, kind in ((255, 10), (100, 12)):
            with self.subTest(alpha=alpha):
                rgba = bytes((220, 40, 15, alpha)) * (8 * 8)
                encoded = write_ztex(Texture(8, 8, rgba))
                self.assertEqual(encoded[:4], b'ZTEX')
                self.assertEqual(struct.unpack_from('<I', encoded, 8)[0], kind)
                self.assertEqual(struct.unpack_from('<I', encoded, 20)[0], 2)
                # ZenGin DXT mipmaps stop at 4x4: 4x4 and 8x8 = 1+4 blocks.
                self.assertEqual(len(encoded), 36 + 5 * (8 if kind == 10 else 16))
                decoded = read_ztex(encoded)
                self.assertEqual((decoded.width, decoded.height), (8, 8))
                self.assertLess(abs(decoded.pixels[0] - 220), 15)
                self.assertLess(abs(decoded.pixels[3] - alpha), 18)

    def test_build_repairs_legacy_dxt_with_too_many_levels(self):
        from gothic_editor.core.textures import Texture, write_ztex, _encode_dxt_block
        pixels=bytes((30,90,170,255))*64
        source=Texture(8,8,pixels)
        correct=write_ztex(source)
        # Simulate the old editor: 1x1 and 2x2 levels preceding the 4x4 one.
        extra=b''.join(_encode_dxt_block(level.pixels,level.width,level.height,0,0,False)
                       for level in reversed(source.mipmaps[2:]))
        wrong=bytearray(correct)
        struct.pack_into('<I',wrong,20,4)
        wrong=wrong[:36]+extra+wrong[36:]
        path=self.media.path('images','LOADING.TGA')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(wrong)
        rebuilt=self.media.collect_images()['_work/data/Textures/_compiled/LOADING-C.TEX']
        self.assertEqual(struct.unpack_from('<I',rebuilt,20)[0],2)
        self.assertEqual(len(rebuilt),len(correct))
        self.assertEqual(path.read_bytes(),wrong)

    def test_build_repairs_legacy_uncompressed_media(self):
        from gothic_editor.core.textures import Texture
        rgba = bytes((100, 50, 20, 255)) * 16
        legacy = bytearray(b'ZTEX' + struct.pack('<8I', 0, 0, 4, 4, 1, 4, 4, 0))
        for offset in range(0, len(rgba), 4):
            r, g, b, a = rgba[offset:offset + 4]
            legacy.extend((b, g, r, a))
        path = self.media.path('images', 'LOADING.TGA')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(legacy)
        compiled = self.media.collect_images()['_work/data/Textures/_compiled/LOADING-C.TEX']
        self.assertEqual(struct.unpack_from('<I', compiled, 8)[0], 10)
        self.assertEqual(path.read_bytes(), legacy)
        self.assertEqual(read_ztex(compiled).width, 4)

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
        self.assertEqual(struct.unpack_from('>II',data,16),(4,4))
        offset=8
        chunks={}
        while offset<len(data):
            length=struct.unpack_from('>I',data,offset)[0]
            kind=data[offset+4:offset+8]
            chunks[kind]=data[offset+8:offset+8+length]
            offset+=12+length
        pixels=zlib.decompress(chunks[b'IDAT'])
        self.assertEqual(pixels[0],0)
        self.assertEqual(len(pixels),4*(1+4*4))

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

    def test_external_bink_frame_queue(self):
        from gothic_editor.core.bink_process import BinkProcessDecoder
        from queue import Queue
        from types import SimpleNamespace
        decoder=SimpleNamespace(error=None,queue=Queue(),finished=False,number=0)
        self.assertIs(BinkProcessDecoder.next_frame(decoder),False)
        decoder.queue.put(bytes([10,20,30]))
        self.assertEqual(BinkProcessDecoder.next_frame(decoder),bytes([10,20,30]))
        self.assertEqual(decoder.number,1)
        decoder.finished=True
        self.assertIsNone(BinkProcessDecoder.next_frame(decoder))

    def test_external_bink_exact_reader(self):
        import io
        from gothic_editor.core.bink_process import BinkProcessDecoder
        stream=io.BytesIO(b'abcde')
        self.assertEqual(BinkProcessDecoder._exact(stream,3),b'abc')
        with self.assertRaises(EOFError):
            BinkProcessDecoder._exact(stream,3)

    def test_bink_dll_architecture_detection(self):
        from gothic_editor.core.bink_decoder import dll_compatible
        for machine,bits in ((0x14c,32),(0x8664,64)):
            with self.subTest(machine=machine):
                header=bytearray(256)
                header[:2]=b'MZ'
                struct.pack_into('<I',header,0x3c,128)
                header[128:132]=b'PE\0\0'
                struct.pack_into('<H',header,132,machine)
                path=Path(self.temp.name)/'test.dll'
                path.write_bytes(header)
                self.assertTrue(dll_compatible(path,bits))
                self.assertFalse(dll_compatible(path,64 if bits==32 else 32))

    def test_png_and_jpeg_replace_into_gothic_texture(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow is optional; Windows uses its native decoder')
        for suffix in ('.png','.jpg'):
            with self.subTest(suffix=suffix):
                source=Path(self.temp.name)/('replacement'+suffix)
                image=Image.new('RGB',(8,8),(200,50,20))
                image.save(source)
                path=self.media.replace_image('LOADING.TGA',source)
                texture=read_ztex(path.read_bytes())
                self.assertEqual((texture.width,texture.height),(8,8))
                self.assertEqual(path.name,'LOADING-C.TEX')

    def test_imported_selection_persists_after_reopen(self):
        from gothic_editor.core.project_selection import ProjectSelection
        chosen=ProjectSelection(self.project,'Media')
        chosen.add('images:STARTSCREEN-C.TEX')
        reopened=ProjectSelection(self.project,'Media')
        self.assertIn('images:startscreen-c.tex',reopened.read())
        self.assertTrue(reopened.path.is_file())
        self.assertEqual(reopened.path.parent.name,'Media')

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
