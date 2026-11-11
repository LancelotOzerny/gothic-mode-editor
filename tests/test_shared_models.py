"""Shared model workflows with temporary assets and synthetic item data."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.item_assets import ItemAssetManager, texture_references
from gothic_editor.core.model_library import ModelLibrary
from gothic_editor.core.build_assets import BuildAssetService
from gothic_editor.core.model_preview import load_model_preview
from gothic_editor.core.model_export import resolve_model_source
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.item_layout import project_scripts
from gothic_editor.core.scripts import parse_items
from gothic_editor.core.item_spreadsheet import export_items, ItemSpreadsheetService
from gothic_editor.ui.controllers.item_appearance import ItemAppearanceController
from gothic_editor.ui.windows.dialog import EditorDialog
from gothic_editor.ui.widgets.choice_field import ExpressionChoiceField
from test_editor_responsiveness import temporary_item, schema
from test_model_preview import textured_3ds, tga


class SharedModelFixture:
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='shared models ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Shared')
        self.item=temporary_item(self.repo)
        self.library=ModelLibrary(self.repo.root)
        self.manager=ItemAssetManager(self.repo.root)

    def source(self,name='Bottle'):
        folder=self.root/name
        folder.mkdir(exist_ok=True)
        (folder/'Bottle.TGA').write_bytes(tga())
        model=folder/(name+'.3ds')
        model.write_bytes(textured_3ds())
        return model

    def imported(self,name='Bottle'):
        model=self.manager.import_model(self.item,self.source(name))
        self.repo.refresh()
        self.item=next(item for item in self.repo.project_items if item.instance==self.item.instance)
        return model


class SharedModelTests(SharedModelFixture, unittest.TestCase):
    def test_import_reuse_duplicate_rename_detach_and_reopen(self):
        model=self.imported()
        self.assertEqual(model,self.repo.root/'Assets/Models/Bottle/model.3ds')
        self.assertEqual(self.item.visual,'Bottle.3ds')
        self.assertFalse((self.item.path.parent/'assets').exists())
        duplicate=self.repo.duplicate(self.item)
        self.assertEqual(duplicate.visual,self.item.visual)
        renamed=self.repo.edit(duplicate,{},instance='ItPo_Renamed')
        self.assertEqual(renamed.visual,'Bottle.3ds')
        self.manager.import_model(renamed,model)
        self.assertEqual(list(self.library.index().values()),[model])
        self.manager.remove_model(renamed)
        self.assertTrue(model.is_file())
        self.assertEqual(self.repo.components.read_item(renamed.path).visual,'')
        self.repo.open(self.repo.root)
        self.assertEqual(next(i for i in self.repo.items if i.instance==self.item.instance).visual,'Bottle.3ds')
        self.assertEqual(resolve_model_source('Bottle.3ds',self.repo.mesh_index,self.repo.archive_models),model)

    def test_preview_and_packaging_distinguish_identically_named_files(self):
        model=self.imported('First')
        second=self.imported('Second')
        self.assertEqual(model.name,second.name)
        preview=load_model_preview(model,self.repo.root)
        self.assertFalse(preview.missing)
        files=BuildAssetService(self.repo.root).collect()
        self.assertEqual(texture_references(files['_work/data/Meshes/First.3ds']),('First_Bottle.TGA',))
        self.assertEqual(texture_references(files['_work/data/Meshes/Second.3ds']),('Second_Bottle.TGA',))
        self.assertEqual(files['_work/data/Textures/First_Bottle.TGA'],tga())
        self.assertEqual(files['_work/data/Textures/Second_Bottle.TGA'],tga())
        self.assertEqual(model.read_bytes(),textured_3ds())
        self.assertFalse(any(name.endswith('.json') or 'functions.d' in name for name in files))

    def test_legacy_migration_backups_and_idempotence(self):
        folder=self.item.path.parent/'assets'
        folder.mkdir()
        (folder/'model.3ds').write_bytes(textured_3ds())
        (folder/'Bottle.TGA').write_bytes(tga())
        (folder/'notes.txt').write_text('keep')
        original=self.item.path.read_bytes()
        self.repo.open(self.repo.root)
        moved=self.repo.root/'Assets/Models/model_ItPo_Test'
        self.assertEqual((moved/'model.3ds').read_bytes(),textured_3ds())
        self.assertEqual((moved/'Bottle.TGA').read_bytes(),tga())
        self.assertEqual(self.repo.project_items[0].visual,'model_ItPo_Test.3ds')
        self.assertEqual((folder/'notes.txt').read_text(),'keep')
        self.assertFalse((folder/'model.3ds').exists())
        backups=list((self.repo.root/'backups').glob('model-migration-*'))
        self.assertEqual((backups[0]/'item.json').read_bytes(),original)
        self.assertEqual((backups[0]/'assets/model.3ds').read_bytes(),textured_3ds())
        self.repo.open(self.repo.root)
        self.assertEqual(len(list((self.repo.root/'backups').glob('model-migration-*'))),1)
        self.assertEqual(self.repo.duplicate(self.repo.project_items[0]).visual,'model_ItPo_Test.3ds')
        self.assertIn('_work/data/Meshes/model_ItPo_Test.3ds',BuildAssetService(self.repo.root).collect())

    def test_loose_models_migrate_without_changing_visual(self):
        folder=self.library.root
        source=folder/'Custom.3ds'
        source.write_bytes(textured_3ds())
        (folder/'Bottle.TGA').write_bytes(tga())
        self.repo.edit(self.item,{'visual':'"Custom.3ds"'})
        self.repo.open(self.repo.root)
        self.assertFalse(source.exists())
        self.assertFalse((folder/'Bottle.TGA').exists())
        self.assertEqual((folder/'Custom/model.3ds').read_bytes(),textured_3ds())
        self.assertEqual(self.repo.project_items[0].visual,'Custom.3ds')

    def test_migration_keeps_spaced_names_and_global_texture_sources(self):
        source=self.library.root/'Old Bottle.3ds'
        source.write_bytes(textured_3ds())
        textures=self.repo.root/'Assets/Textures'
        textures.mkdir()
        (textures/'Bottle.TGA').write_bytes(tga())
        self.repo.edit(self.item,{'visual':'"Old Bottle.3ds"'})
        self.repo.open(self.repo.root)
        self.assertEqual(self.repo.project_items[0].visual,'Old Bottle.3ds')
        self.assertTrue((self.library.root/'Old Bottle/Bottle.TGA').exists())
        self.assertTrue((textures/'Bottle.TGA').exists())
        self.assertIn('_work/data/Meshes/Old Bottle.3ds',BuildAssetService(self.repo.root).collect())

    def test_generated_code_uses_shared_alias_and_does_not_change_game_sources(self):
        self.imported()
        game=self.root/'game'
        content=game/'_work/Data/Scripts/Content'
        (content/'Items').mkdir(parents=True)
        (content/'Gothic.src').write_text('Items/*.d')
        original=content/'Items/Base.d'
        original.write_text('const int BASE = 1;')
        staging=self.root/'staging'
        staging.mkdir()
        generated,_,_=ProjectTools(self.repo.root,game)._prepare(staging,lambda _:None)
        item=parse_items(generated/'Items/GE_ComponentPotions.d','project')[0]
        self.assertEqual(item.visual,'Bottle.3ds')
        self.assertEqual(original.read_text(),'const int BASE = 1;')

    def test_components_build_without_user_script_directory(self):
        (self.repo.root/'Assets/Scripts').rename(self.root/'unused_scripts')
        game=self.root/'game'
        content=game/'_work/Data/Scripts/Content'
        (content/'Items').mkdir(parents=True)
        (content/'Gothic.src').write_text('Items/*.d')
        (content/'Items/Base.d').write_text('const int BASE = 1;')
        staging=self.root/'staging'
        staging.mkdir()
        generated,_,_=ProjectTools(self.repo.root,game)._prepare(staging,lambda _:None)
        items=parse_items(generated/'Items/GE_ComponentPotions.d','project')
        self.assertEqual(items[0].instance,self.item.instance)
        self.assertFalse((self.repo.root/'Assets/Scripts/Content').exists())

    def test_legacy_content_is_not_hidden_by_empty_assets_scripts(self):
        (self.repo.root/'Assets/Scripts/Content').rename(self.root/'unused_content')
        (self.repo.root/'Assets/Scripts/Actions').mkdir()
        legacy=self.repo.root/'Scripts/Content'
        legacy.mkdir(parents=True)
        self.assertEqual(project_scripts(self.repo.root),legacy.parent)
        (self.repo.root/'Assets/Scripts/Content').mkdir()
        self.assertEqual(project_scripts(self.repo.root),self.repo.root/'Assets/Scripts')

    def test_old_duplicate_texture_names_and_migration_leftovers_do_not_conflict(self):
        duplicate=self.repo.duplicate(self.item)
        for item,texture in ((self.item,tga()),(duplicate,tga()+b'different')):
            folder=item.path.parent/'assets'
            folder.mkdir()
            (folder/'model.3ds').write_bytes(textured_3ds())
            (folder/'Bottle.TGA').write_bytes(texture)
        files=BuildAssetService(self.repo.root).collect()
        for item in (self.item,duplicate):
            prefix='model_'+item.instance
            self.assertEqual(texture_references(files['_work/data/Meshes/'+prefix+'.3ds']),
                             (prefix+'_Bottle.TGA',))
        self.repo.open(self.repo.root)
        leftover=self.item.path.parent/'assets'
        leftover.mkdir()
        (leftover/'Bottle.TGA').write_bytes(b'unused old copy')
        migrated=BuildAssetService(self.repo.root).collect()
        self.assertEqual(migrated,files)
        self.assertTrue((leftover/'Bottle.TGA').exists())

    def test_import_failure_and_name_collision_preserve_existing_resources(self):
        model=self.imported()
        self.manager.import_model(self.item,self.source())
        self.assertTrue((self.library.root/'Bottle_2/model.3ds').is_file())
        broken=self.root/'Broken.3ds'
        broken.write_bytes(b'broken')
        with self.assertRaises(ValueError):self.manager.import_model(self.item,broken)
        self.assertEqual(model.read_bytes(),textured_3ds())
        source=self.source('Rollback')
        with patch.object(self.manager.store,'edit',side_effect=OSError('write failed')):
            with self.assertRaises(OSError):self.manager.import_model(self.item,source)
        self.assertFalse((self.library.root/'Rollback').exists())

    def test_spreadsheet_keeps_shared_visual_without_item_asset_copies(self):
        model=self.imported()
        sheet=self.root/'items.xlsx'
        export_items([self.item],sheet)
        with patch('gothic_editor.core.item_spreadsheet.schema_for',return_value=schema()):
            ItemSpreadsheetService(self.repo).import_file(sheet,'replace')
        self.assertEqual(self.repo.project_items[0].visual,'Bottle.3ds')
        self.assertTrue(model.exists())
        self.assertFalse((self.item.path.parent/'assets').exists())


class SharedModelChoiceTests(SharedModelFixture, unittest.TestCase):
    def test_model_options_only_include_library_and_game(self):
        self.imported()
        game=self.root/'game'
        (game/'Meshes').mkdir(parents=True)
        standard=game/'Meshes/Standard.3ds'
        standard.write_bytes(textured_3ds())
        stray=self.repo.root/'Assets/Scripts/Stray.3ds'
        stray.write_bytes(textured_3ds())
        self.repo.game=game
        self.repo.mesh_index.update({'standard.3ds':standard,'stray.3ds':stray})
        controller=ItemAppearanceController(SimpleNamespace(repo=self.repo))
        self.assertEqual({value for _,value in controller.model_options()},{'Bottle.3ds','Standard.3ds'})

    def test_picker_assigns_reference_without_creating_files(self):
        model=self.imported()
        window=tk.Tk()
        self.addCleanup(window.destroy)
        window.repo=self.repo
        controller=ItemAppearanceController(window)
        saved=[]
        controller._run=lambda item,operation:(operation(item,self.manager),saved.append(True))
        with patch.object(controller,'_confirm_replace',return_value=True):
            controller.choose(self.item)
            dialog=next(child for child in window.winfo_children() if isinstance(child,EditorDialog))
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            choice=next(child for child in descendants(dialog) if isinstance(child,ExpressionChoiceField))
            self.assertEqual(choice.get(),'Bottle.3ds')
            controller.app.update()
            # The dialog button calls the same assignment path used by the picker.
            button=next(child for child in dialog.winfo_children() if hasattr(child,'command'))
            button.command()
        self.assertTrue(saved)
        self.assertEqual(list(self.library.index().values()),[model])
