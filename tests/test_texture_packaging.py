"""Texture import/packaging regressions using temporary assets, without property schemas."""
from pathlib import Path
import struct
import tempfile
import unittest

from gothic_editor.core.build_assets import BuildAssetService
from gothic_editor.core.item_assets import ItemAssetManager,texture_references,replace_texture_references
from gothic_editor.core.mesh import read_3ds_bytes
from gothic_editor.core.model_preview import load_model_preview
from gothic_editor.core.mod_archive import read_mod
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.scripts import Item
from test_model_preview import textured_3ds,tga,ztex


class TexturePackagingTests(unittest.TestCase):
    REFERENCE='c6bf7ff0-e268-4df4-8268-aa110b4fb690'

    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='texture packaging ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Test')
        code='INSTANCE ItPo_Skill_02(C_Item) {mainflag=ITEM_KAT_POTIONS; name="Test";};'
        source=Item('ItPo_Skill_02',self.root/'synthetic.d','project',code,{},0,len(code))
        folder=self.repo.components.import_item(source)
        self.item=self.repo.components.read_item(folder/'item.json')
        self.manager=ItemAssetManager(self.repo.root)
        self.service=BuildAssetService(self.repo.root)

    def model(self,reference):
        source=self.root/'source.3ds'
        source.write_bytes(replace_texture_references(textured_3ds(),{'Bottle.TGA':reference}))
        self.manager.import_model(self.item,source)
        self.item=self.repo.components.read_item(self.item.path)
        return source

    def test_separate_import_of_uuid_tga_matches_preview_and_packages_fixed_model(self):
        source=self.model(self.REFERENCE)
        original=source.read_bytes()
        with self.assertRaisesRegex(ValueError,'отсутствует текстура'):self.service.collect()
        texture=self.root/(self.REFERENCE+'.TGA')
        texture.write_bytes(tga())
        self.manager.import_textures(self.item,[texture])
        owned=self.repo.root/'Assets/Models/source/model.3ds'
        preview=load_model_preview(owned,self.repo.root,item_assets=owned.parent)
        self.assertFalse(preview.missing)
        self.assertIn(self.REFERENCE,preview.textures)
        files=self.service.collect()
        model_key='_work/data/Meshes/source.3ds'
        packed_texture='source_'+texture.name
        self.assertEqual(texture_references(files[model_key]),(packed_texture,))
        self.assertEqual(read_3ds_bytes(files[model_key]),read_3ds_bytes(original))
        self.assertEqual(files['_work/data/Textures/'+packed_texture],texture.read_bytes())
        self.assertEqual(source.read_bytes(),original)
        self.assertEqual(owned.read_bytes(),original)
        self.assertEqual(files,self.service.collect())
        compiled=self.root/'Gothic.dat'
        compiled.write_bytes(b'synthetic dat')
        output=self.root/'Test.mod'
        self.service.package(output,compiled,files)
        packed=read_mod(output)
        self.assertEqual(texture_references(packed[model_key.lower()]),(packed_texture,))
        self.assertEqual(packed[('_work/data/Textures/'+packed_texture).lower()],texture.read_bytes())

    def test_model_import_auto_finds_extensionless_texture_next_to_source(self):
        texture=self.root/(self.REFERENCE+'.tga')
        texture.write_bytes(tga())
        self.model(self.REFERENCE)
        self.assertEqual((self.repo.root/'Assets/Models/source'/texture.name).read_bytes(),texture.read_bytes())
        self.service.collect()

    def test_extensionless_reference_accepts_compiled_texture_and_keeps_tex_bytes(self):
        self.model(self.REFERENCE)
        texture=self.root/(self.REFERENCE+'-C.TEX')
        texture.write_bytes(ztex(1,bytes((1,2,3,255))*16))
        self.manager.import_textures(self.item,[texture])
        files=self.service.collect()
        self.assertEqual(texture_references(files['_work/data/Meshes/source.3ds']),
                         ('source_'+self.REFERENCE+'.TGA',))
        self.assertEqual(files['_work/data/Textures/_compiled/source_'+texture.name],texture.read_bytes())

    def test_global_assets_case_and_embedded_paths_use_the_same_lookup(self):
        folder=self.repo.root/'Assets/Models/custom'
        folder.mkdir()
        source=folder/'model.3ds'
        reference=r'C:\Export\Bottle'
        source.write_bytes(replace_texture_references(textured_3ds(),{'Bottle.TGA':reference}))
        textures=folder
        (textures/'bOtTlE.TgA').write_bytes(tga())
        files=self.service.collect()
        self.assertEqual(texture_references(files['_work/data/Meshes/custom.3ds']),('custom_bOtTlE.TgA',))
        self.assertEqual(texture_references(source.read_bytes()),(reference,))

    def test_packaging_preserves_source_bytes_and_missing_unrelated_texture_fails(self):
        source=self.model('Bottle.TGA')
        texture=self.root/'BOTTLE.tga'
        texture.write_bytes(tga())
        self.manager.import_textures(self.item,[texture])
        files=self.service.collect()
        self.assertEqual(texture_references(files['_work/data/Meshes/source.3ds']),('source_'+texture.name,))
        folder=self.repo.root/'Assets/Models/source'
        self.assertEqual((folder/'model.3ds').read_bytes(),source.read_bytes())
        (folder/texture.name).rename(folder/'Other.tga')
        with self.assertRaisesRegex(ValueError,'отсутствует текстура Bottle.TGA'):self.service.collect()

    def test_rewrite_updates_nested_chunk_sizes_and_preserves_uvs_and_unknown_chunks(self):
        data=textured_3ds()
        unknown=struct.pack('<HI',0x7777,10)+b'keep'
        data=struct.pack('<HI',0x4D4D,len(data)+len(unknown))+data[6:]+unknown
        replacement='Длинное имя текстуры.TGA'
        result=replace_texture_references(data,{'Bottle.TGA':replacement})
        self.assertEqual(texture_references(result),(replacement,))
        self.assertEqual(struct.unpack_from('<I',result,2)[0],len(result))
        self.assertTrue(result.endswith(unknown))
        before,after=read_3ds_bytes(data,preview=True),read_3ds_bytes(result,preview=True)
        self.assertEqual((before.vertices,before.faces,before.uvs),(after.vertices,after.faces,after.uvs))
        self.assertEqual(after.texture_names,[replacement])
        self.assertEqual(replace_texture_references(result,{}),result)
        with self.assertRaises(ValueError):replace_texture_references(result[:-1],{'unused':'x'})
