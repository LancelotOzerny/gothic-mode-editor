"""World replacements keep original names and never modify original resources."""
import json
import os
from pathlib import Path
import tempfile
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gothic_editor.core.world_resources import WorldResources, resource_name
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.model_library import ModelLibrary
from gothic_editor.core.model_preview import load_model_preview
from gothic_editor.core.build_assets import BuildAssetService
from gothic_editor.core.mod_archive import read_mod
from gothic_editor.core.model_export import preview_3ds
from gothic_editor.core.mesh import read_3ds_bytes
from gothic_editor.core.textures import read_texture, write_ztex, validate_gothic_ztex
from test_model_preview import textured_3ds, tga
from test_models import write_vdf


class WorldFixture:
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='world resources ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Test')
        self.game=self.root/'game'
        self.model=self.game/'_work/data/Meshes/Architecture/House.3ds'
        self.model.parent.mkdir(parents=True)
        self.model.write_bytes(textured_3ds())
        self.archive=write_vdf(self.game/'Data/Textures.vdf',{'BOTTLE-C.TEX':write_ztex(read_texture(tga()))})
        self.repo.game=self.game
        self.repo.refresh()
        self.store=WorldResources(self.repo.root)
        self.replacement=self.root/'replacement.3ds'
        self.replacement.write_bytes(textured_3ds())
        self.texture=self.root/'green.tga'
        self.texture.write_bytes(tga((0,255,0)))


class WorldResourceTests(WorldFixture,unittest.TestCase):
    def test_animated_chest_catalog_and_preview_use_native_hierarchy(self):
        from test_npcs import mdm,chunk
        import struct
        skeleton=chunk(0xD100,struct.pack('<IH',3,0)+bytes(64))+chunk(0xD120)
        write_vdf(self.game/'Data/Chests.vdf',{'CHEST_TEST.MDL':skeleton+mdm(),
            'CHEST_TEST.MDM':mdm(),'CHEST_TEST.MDH':skeleton})
        self.repo.refresh()
        chests=[value for value in self.store.catalog(self.repo) if value.name.startswith('CHEST')]
        self.assertEqual(len(chests),1)
        self.assertTrue(chests[0].name.endswith('.MDL'))
        self.assertEqual(chests[0].category,'furniture')
        self.assertIn('Сундук',chests[0].title)
        preview=load_model_preview(chests[0].source,self.repo.root,self.game,with_textures=False,
                                  animation_entries=self.repo.archive_models.animation_entries)
        self.assertTrue(preview.mesh.faces)
        with self.assertRaisesRegex(ValueError,'анимированная'):self.store.replace('model',chests[0].name,self.replacement)

    def test_compiled_replacement_overrides_vdf_and_source_only_fails_clearly(self):
        from test_models import mrm_bytes
        archive=write_vdf(self.game/'Data/Meshes.vdf',{'HOUSE.MRM':mrm_bytes()})
        original=archive.read_bytes()
        self.store.replace('model','House.3ds',self.replacement)
        with self.assertRaisesRegex(ValueError,'MRM'):BuildAssetService(self.repo.root,self.game).collect()
        native=self.root/'ready.mrm'
        native.write_bytes(mrm_bytes())
        target=self.store.replace('model','House.3ds',native)
        self.assertEqual(target.suffix,'.mrm')
        files=BuildAssetService(self.repo.root,self.game).collect()
        self.assertEqual(files['_work/data/Meshes/_compiled/House.mrm'],native.read_bytes())
        self.assertNotIn('_work/data/Meshes/House.3ds',files)
        self.assertEqual(archive.read_bytes(),original)

    def test_catalog_is_lazy_and_groups_models_excluding_items(self):
        write_vdf(self.game/'Data/Objects.vdf',{'TREE.MRM':b'not parsed until selected',
                   'ITPO_BOTTLE.MRM':b'item', 'CHAIR.MRM':b'chair'})
        self.repo.refresh()
        with patch('gothic_editor.core.world_resources.read_3ds_bytes',side_effect=AssertionError('eager parse')):
            catalog=self.store.catalog(self.repo)
        self.assertEqual({value.name.casefold():value.category for value in catalog},
                         {'house.3ds':'architecture','tree.3ds':'vegetation','chair.3ds':'furniture'})

    def test_model_replacement_roundtrip_build_names_and_reset(self):
        original=self.model.read_bytes()
        path=self.store.replace('model','HOUSE.MRM',self.replacement,'architecture')
        self.assertEqual(path,self.repo.root/'Assets/Models/World/HOUSE.3ds')
        self.repo.refresh()
        resource=next(value for value in self.store.catalog(self.repo) if value.name.casefold()=='house.3ds')
        self.assertTrue(resource.overridden)
        self.assertEqual(resource.source,path)
        self.assertNotIn('house.3ds',ModelLibrary(self.repo.root).index())
        self.assertEqual(self.repo.mesh_index['house.3ds'],path)
        files=BuildAssetService(self.repo.root).collect()
        self.assertEqual(files,{'_work/data/Meshes/HOUSE.3ds':self.replacement.read_bytes()})
        compiled=self.root/'Gothic.dat'
        compiled.write_bytes(b'dat')
        output=self.root/'World.mod'
        BuildAssetService(self.repo.root).package(output,compiled,files)
        self.assertIn('_work/data/meshes/house.3ds',read_mod(output))
        self.store.remove('model','house.3ds')
        self.repo.refresh()
        self.assertFalse(path.exists())
        self.assertEqual(BuildAssetService(self.repo.root).collect(),{})
        self.assertEqual(self.model.read_bytes(),original)
        self.assertEqual(self.repo.mesh_index['house.3ds'],self.model)

    def test_texture_override_preview_and_compiled_mod_preserve_pixels_alpha_and_name(self):
        original=self.archive.read_bytes()
        path=self.store.replace('texture','BOTTLE-C.TEX',self.texture)
        self.assertEqual(path.name,'BOTTLE.TGA')
        preview=load_model_preview(self.model,self.repo.root,self.game,
                                   texture_entries=self.repo.archive_models.texture_entries)
        self.assertEqual(preview.textures['Bottle.TGA'].pixels[:4],bytes((0,255,0,255)))
        files=BuildAssetService(self.repo.root).collect()
        self.assertIn('_work/data/Textures/BOTTLE.TGA',files)
        self.assertIn('_work/data/Textures/_compiled/BOTTLE-C.TEX',files)
        compiled=files['_work/data/Textures/_compiled/BOTTLE-C.TEX']
        self.assertTrue(validate_gothic_ztex(compiled))
        self.assertEqual(int.from_bytes(compiled[8:12],'little'),10)  # DXT1, opaque
        decoded=read_texture(compiled)
        self.assertEqual((decoded.width,decoded.height),(4,4))
        self.assertEqual(decoded.pixels,bytes((0,255,0,255))*16)
        self.assertFalse(any('overrides.json' in name for name in files))
        self.store.remove('texture','bottle.tga')
        preview=load_model_preview(self.model,self.repo.root,self.game,
                                   texture_entries=self.repo.archive_models.texture_entries)
        self.assertEqual(preview.textures['Bottle.TGA'].pixels[:4],bytes((255,0,0,255)))
        self.assertEqual(self.archive.read_bytes(),original)

    def test_import_tex_then_replace_case_insensitively_without_duplicate_files(self):
        source=self.root/'source.tex'
        source.write_bytes(write_ztex(read_texture(tga((0,0,255)))))
        first=self.store.replace('texture','stone.tex',source)
        second=self.store.replace('texture','STONE.TGA',self.texture)
        self.assertEqual(first,second)
        self.assertEqual(len(self.store.overrides('texture')),1)
        self.assertEqual(read_texture(second.read_bytes()).pixels[:4],bytes((0,255,0,255)))

    def test_failed_manifest_write_keeps_previous_replacement_and_failed_import_creates_nothing(self):
        target=self.store.replace('texture','Bottle.tga',self.texture)
        original=target.read_bytes()
        red=self.root/'red.tga'
        red.write_bytes(tga())
        with patch.object(self.store,'_save',side_effect=OSError('full disk')):
            with self.assertRaises(OSError):self.store.replace('texture','Bottle.tga',red)
            with self.assertRaises(OSError):self.store.remove('texture','Bottle.tga')
        self.assertEqual(target.read_bytes(),original)
        self.replacement.write_bytes(b'bad')
        with self.assertRaises(ValueError):self.store.replace('model','House.3ds',self.replacement)
        self.assertEqual(self.store.overrides('model'),{})

    def test_manifest_paths_and_category_are_validated_and_missing_assets_fail_build(self):
        target=self.store.replace('model','House.3ds',self.replacement)
        target.unlink()
        with self.assertRaisesRegex(ValueError,'House.3ds'):BuildAssetService(self.repo.root).collect()
        data=json.loads(self.store.manifest.read_text('utf-8'))
        data['resources']['model:house.3ds']['path']='../outside.3ds'
        self.store.manifest.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'путь'):self.store.overrides('model')

    def test_shared_model_bundles_keep_their_names_and_local_textures(self):
        library=ModelLibrary(self.repo.root)
        model=library.create('Bottle',textured_3ds(),[self.texture])
        # Name the local texture as referenced by the material.
        self.texture.rename(self.root/'Bottle.TGA')
        (model.parent/'Bottle.TGA').write_bytes(tga())
        legacy_world=library.create('World',textured_3ds(),[])
        self.store.replace('texture','Bottle.TGA',self.root/'Bottle.TGA')
        self.store.replace('model','House.3ds',self.replacement)
        index=library.index()
        self.assertIn('bottle.3ds',index)
        self.assertIn('world.3ds',index)
        self.assertNotIn('house.3ds',index)
        preview=load_model_preview(model,self.repo.root,self.game,item_assets=model.parent)
        self.assertEqual(preview.textures['Bottle.TGA'].pixels[:4],bytes((255,0,0,255)))
        self.assertTrue(legacy_world.exists())

    def test_resource_name_aliases_and_uv_export_roundtrip(self):
        self.assertEqual(resource_name('DIR\\WALL.MRM','model'),'WALL.3ds')
        self.assertEqual(resource_name('WALL-C.TEX','texture'),'WALL.TGA')
        self.assertEqual(resource_name('WALL','texture'),'WALL.tga')
        original=read_3ds_bytes(textured_3ds(),preview=True)
        exported=read_3ds_bytes(preview_3ds(original),preview=True)
        self.assertEqual(exported.vertices,original.vertices)
        self.assertEqual(exported.faces,original.faces)
        self.assertEqual(exported.uvs,original.uvs)
        self.assertEqual(exported.texture_names,original.texture_names)
        self.assertEqual(exported.material_names,original.material_names)

    def test_game_texture_references_are_allowed_but_missing_ones_fail_packaging(self):
        from gothic_editor.core.item_assets import replace_texture_references
        self.store.replace('model','House.3ds',self.replacement)
        files=BuildAssetService(self.repo.root,self.game).collect()
        self.assertIn('_work/data/Meshes/House.3ds',files)
        self.replacement.write_bytes(replace_texture_references(textured_3ds(),{'Bottle.TGA':'Missing.TGA'}))
        self.store.replace('model','House.3ds',self.replacement)
        with self.assertRaisesRegex(ValueError,'Missing.TGA'):BuildAssetService(self.repo.root,self.game).collect()

    def test_ztex_keeps_alpha_and_orders_mipmaps_smallest_first(self):
        import struct
        from gothic_editor.core.textures import Texture
        pixels=bytes((1,2,3,4, 5,6,7,8, 9,10,11,12, 13,14,15,16))
        texture=Texture(2,2,pixels)
        data=write_ztex(texture)
        self.assertEqual(struct.unpack_from('<8I',data,4),(0,12,4,4,1,4,4,0))
        self.assertEqual(len(data),36+16)  # One 4x4 DXT3 block
        self.assertTrue(validate_gothic_ztex(data))
        decoded=read_texture(data)
        self.assertEqual((decoded.width,decoded.height),(4,4))
        self.assertEqual(len(decoded.pixels),4*4*4)
        self.assertTrue(any(alpha<255 for alpha in decoded.pixels[3::4]))


class WorldUITests(WorldFixture,unittest.TestCase):
    def test_navigation_async_preview_replacement_and_return_to_items(self):
        from gothic_editor.app import EditorApp
        from gothic_editor.core.settings import SettingsStore
        with patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(self.root/'settings.json')):
            app=EditorApp()
        try:
            app.withdraw()
            app.repo=self.repo
            app.show_project()
            app._switch_resource_browser('world')
            self.assertEqual(app._resource_browser,'world')
            self.assertEqual(len(app.world.catalog),1)
            app.world_panel.search.set('not found')
            self.assertEqual(app.world_panel.entries,{})
            app.world_panel.search.set('house')
            app.world.select(app.world.catalog[0])
            deadline=monotonic()+5
            while app._model_future is not None and monotonic()<deadline:app.update()
            self.assertIsNone(app._model_future)
            self.assertTrue(app.viewer.vertices)
            self.assertIsNone(app.current)
            self.assertIsNone(app.properties.current)
            self.store.replace('model','House.3ds',self.replacement,'architecture')
            app.world._changed()
            self.assertTrue(app.world.current.overridden)

            from gothic_editor.ui.panels.hierarchy import CategoryRow, HierarchyRow
            panel = app.world_panel
            branch = panel.category_rows['architecture']
            row = panel.rows['model:house.3ds']
            self.assertIsInstance(branch, CategoryRow)
            self.assertIsInstance(row, HierarchyRow)
            self.assertIs(branch.master, panel.area.content)
            self.assertIs(panel.import_button.master, panel.heading_bar)
            self.assertIn('Проект', row.title_label.cget('text'))
            with patch.object(panel, 'popup') as popup:
                panel.context(None, 'model:house.3ds')
            self.assertTrue(row.selected)
            self.assertEqual(popup.call_args.args[1][-1][1], panel.on_remove)
            panel.search.set('')
            branch = panel.category_rows['architecture']
            self.assertFalse(branch.opened)
            panel.navigate(SimpleNamespace(widget=panel, keysym='Right'))
            self.assertFalse(branch.opened)
            panel.select_category('architecture')
            self.assertFalse(branch.opened)
            panel.navigate(SimpleNamespace(widget=panel, keysym='Right'))
            panel.rebuild()
            self.assertTrue(panel.category_rows['architecture'].opened)
            self.assertFalse(panel.rows['model:house.3ds'].selected)
            panel.navigate(SimpleNamespace(widget=panel, keysym='Down'))
            self.assertTrue(panel.rows['model:house.3ds'].selected)
            panel.navigate(SimpleNamespace(widget=panel, keysym='Up'))
            panel.navigate(SimpleNamespace(widget=panel, keysym='Left'))
            self.assertFalse(panel.category_rows['architecture'].opened)

            from gothic_editor.core.project_selection import ProjectSelection
            ProjectSelection(app.repo.root,'Worlds').add('House.3ds')
            with patch('gothic_editor.ui.controllers.world.messagebox.askyesno',return_value=False):
                app.world.remove()
            self.assertTrue(app.world.current.overridden)
            with patch('gothic_editor.ui.controllers.world.messagebox.askyesno',return_value=True):
                app.world.remove()
            self.assertIsNone(app.world.current)
            self.assertFalse(self.store.overrides('model'))
            self.assertFalse(ProjectSelection(app.repo.root,'Worlds').read())
            self.assertFalse(app.world_panel.entries)
            self.assertEqual(self.model.read_bytes(),textured_3ds())
            app._switch_resource_browser('items')
            self.assertIsNone(app.world.current)
            self.assertEqual(app._resource_browser,'items')
            self.assertIsNone(app._model_future)
        finally:app.destroy()


class WorldGameBuildTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('GOTHIC_TEST_GAME') and os.environ.get('GOTHIC_TEST_COMPILER'),
                         'Optional real Gothic/GDC integration')
    def test_actual_architecture_and_texture_compile_and_package_in_temporary_project(self):
        from gothic_editor.core.project_tools import ProjectTools
        from gothic_editor.core.mod_package import ModPackageService
        with tempfile.TemporaryDirectory(prefix='world game build ') as temporary:
            root=Path(temporary)
            repo=ProjectRepository()
            repo.create(root/'project','WorldTest')
            repo.game=Path(os.environ['GOTHIC_TEST_GAME'])
            repo.refresh()
            store=WorldResources(repo.root)
            resource=next(value for value in store.catalog(repo) if value.category=='architecture' and Path(value.source.name).suffix.lower()=='.mrm')
            original=resource.source.read_bytes()
            preview=load_model_preview(resource.source,repo.root,repo.game,with_textures=False)
            source=root/'replacement.mrm'
            source.write_bytes(original)
            store.replace('model',resource.name,source,resource.category)
            name=next(name for name in preview.mesh.texture_names if name)
            texture=root/'color.tga'
            texture.write_bytes(tga())
            store.replace('texture',name,texture)
            with patch.object(ModPackageService,'packer',return_value=None):
                result=ProjectTools(repo.root,repo.game,os.environ['GOTHIC_TEST_COMPILER']).compile()
            packed=read_mod(result.output)
            self.assertIn('_work/data/meshes/_compiled/'+str(Path(resource.name).with_suffix('.mrm')).casefold(),packed)
            texture_name=resource_name(name,'texture')
            compiled='_work/data/textures/_compiled/'+Path(texture_name).stem.casefold()+'-c.tex'
            self.assertEqual(read_texture(packed[compiled]).pixels,read_texture(texture.read_bytes()).pixels)
            self.assertEqual(resource.source.read_bytes(),original)
