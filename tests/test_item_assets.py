import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.item_migration import ItemMigrationService
from gothic_editor.core.item_assets import ItemAssetManager, texture_references
from gothic_editor.core.build_assets import BuildAssetService
from gothic_editor.core.mod_archive import read_mod, write_mod
from gothic_editor.core.model_export import geometry_3ds
from gothic_editor.core.scripts import parse_items
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.vdf import VdfArchive
from gothic_editor.app import EditorApp
from gothic_editor.core.settings import SettingsStore


def model(texture=None):
    import struct
    data=geometry_3ds([(0.,0.,0.),(1.,0.,0.),(0.,1.,0.)],[(0,1,2)])
    if texture:
        def chunk(kind,payload):return struct.pack('<HI',kind,len(payload)+6)+payload
        # A legal material sibling of the edit section, inside the root chunk.
        material=chunk(0xAFFF,chunk(0xA200,chunk(0xA300,texture.encode()+b'\0')))
        data=chunk(0x4D4D,data[6:]+chunk(0x3D3D,material))
    return data


class ItemAssetsTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Assets')
        self.item=self.repo.create_item('potions')
        self.manager=ItemAssetManager(self.repo.root)

    def legacy(self, item=None):
        item=item or self.item
        old=self.repo.root/'Items'/item.instance
        item.path.parent.rename(old)
        return old

    def test_migration_confirmation_backup_and_idempotence(self):
        old=self.legacy()
        (old/'assets').mkdir()
        (old/'assets/model.3ds').write_bytes(model())
        (old/'extra.d').write_text('// Preserve',encoding='utf-8')
        before={p.relative_to(old):p.read_bytes() for p in old.rglob('*') if p.is_file()}
        with patch('builtins.input',side_effect=AssertionError('No console prompts')):
            self.repo.open(self.repo.root,confirm_migration=lambda count:False)
        self.assertTrue(old.exists())
        self.assertEqual(self.repo.project_items[0].path.parent,old)
        confirmed=[]
        self.repo.open(self.repo.root,confirm_migration=lambda count:confirmed.append(count) or True)
        self.assertEqual(confirmed,[1])
        self.assertFalse(old.exists())
        folder=self.repo.project_items[0].path.parent
        self.assertEqual(folder,self.repo.root/'Items/Potions'/self.item.instance)
        self.assertEqual({p.relative_to(folder):p.read_bytes() for p in folder.rglob('*') if p.is_file()},before)
        backup=next((self.repo.root/'backups').glob('item-migration-*'))/'Items'/self.item.instance
        self.assertEqual({p.relative_to(backup):p.read_bytes() for p in backup.rglob('*') if p.is_file()},before)
        self.repo.open(self.repo.root,confirm_migration=lambda _:self.fail('Migration repeated'))
        self.assertEqual(len(self.repo.project_items),1)

    def test_migration_collision_never_overwrites_and_failure_rolls_back(self):
        old=self.legacy()
        destination=self.repo.components.root/self.item.instance
        destination.mkdir()
        (destination/'keep').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'уже существует'):ItemMigrationService(self.repo.root).migrate()
        self.assertTrue(old.is_dir())
        self.assertEqual((destination/'keep').read_bytes(),b'keep')
        shutil.rmtree(destination)
        other=self.repo.create_item('potions')
        second=self.legacy(other)
        rename=Path.rename
        def fail(path,target):
            if path==second:raise OSError('Failed move')
            return rename(path,target)
        with patch.object(Path,'rename',fail),self.assertRaisesRegex(OSError,'Failed move'):
            ItemMigrationService(self.repo.root).migrate()
        self.assertTrue(old.is_dir())
        self.assertTrue(second.is_dir())
        self.assertFalse(destination.exists())

    def test_import_replace_rename_duplicate_remove_and_portability(self):
        source=self.root/'custom.3ds'
        first=model('POTION.TGA')
        source.write_bytes(first)
        (self.root/'POTION.TGA').write_bytes(b'texture')
        original=self.item.path.read_bytes()
        self.assertFalse((self.item.path.parent/'assets').exists())
        self.manager.import_model(self.item,source)
        self.assertEqual(source.read_bytes(),first)
        self.assertEqual(self.item.path.read_bytes(),original)  # Fallback visual untouched.
        self.repo.refresh()
        item=self.repo.project_items[0]
        self.assertEqual(item.visual,'model_ItPo_Potion1.3ds')
        self.assertEqual(self.repo.mesh_index[item.visual.casefold()],item.path.parent/'assets/model.3ds')
        self.assertEqual(texture_references(first),('POTION.TGA',))
        second=model()
        source.write_bytes(second)
        backup=self.manager.import_model(item,source)
        self.assertEqual((backup/'model.3ds').read_bytes(),first)
        self.assertEqual((item.path.parent/'assets/POTION.TGA').read_bytes(),b'texture')
        changed=self.repo.edit(item,{},instance='ItPo_Changed')
        self.assertEqual(changed.visual,'model_ItPo_Changed.3ds')
        self.assertEqual((changed.path.parent/'assets/model.3ds').read_bytes(),second)
        duplicate=self.repo.duplicate(changed)
        self.assertEqual(duplicate.visual,f'model_{duplicate.instance}.3ds')
        self.assertEqual((duplicate.path.parent/'assets/model.3ds').read_bytes(),second)
        other=ProjectRepository()
        other.create(self.root/'other','Other')
        shutil.copytree(changed.path.parent,other.components.root/changed.instance)
        other.refresh()
        self.assertEqual(other.project_items[0].visual,'model_ItPo_Changed.3ds')
        self.manager.remove_model(changed)
        self.repo.refresh()
        fallback=next(i for i in self.repo.project_items if i.instance==changed.instance)
        self.assertEqual(fallback.visual,'ItPo_Perm_Health.3ds')

    def test_asset_failure_does_not_replace_original(self):
        source=self.root/'custom.3ds'
        source.write_bytes(model())
        self.manager.import_model(self.item,source)
        source.write_bytes(b'broken')
        with self.assertRaises(ValueError):self.manager.import_model(self.item,source)
        self.assertEqual((self.item.path.parent/'assets/model.3ds').read_bytes(),model())
        real_rename=Path.rename
        def fail(path,target):
            if path.name=='assets' and path.parent.name.startswith('.assets-'):
                raise OSError('Commit failed')
            return real_rename(path,target)
        source.write_bytes(model('TEX.TGA'))
        with patch.object(Path,'rename',fail),self.assertRaises(OSError):
            self.manager.import_model(self.item,source)
        self.assertEqual((self.item.path.parent/'assets/model.3ds').read_bytes(),model())

    def test_resource_conflicts_missing_textures_and_mod_contents(self):
        source=self.root/'custom.3ds'
        source.write_bytes(model('Shared.TGA'))
        self.manager.import_model(self.item,source)
        service=BuildAssetService(self.repo.root)
        with self.assertRaisesRegex(ValueError,'отсутствует текстура'):service.collect()
        texture=self.root/'Shared.TGA'
        texture.write_bytes(b'texture')
        self.manager.import_textures(self.item,[texture])
        files=service.collect()
        compiled=self.root/'Gothic.dat'
        compiled.write_bytes(b'compiled')
        archive=self.root/'Gothic.mod'
        service.package(archive,compiled,files)
        packed=read_mod(archive)
        self.assertEqual(packed['_work/data/meshes/model_itpo_potion1.3ds'],source.read_bytes())
        self.assertEqual(packed['_work/data/textures/shared.tga'],b'texture')
        self.assertEqual(packed['_work/data/scripts/_compiled/gothic.dat'],b'compiled')
        self.assertIn('model_itpo_potion1.3ds',VdfArchive(archive).entries)
        second=self.repo.create_item('potions')
        self.manager.import_model(second,source)
        self.manager.import_textures(second,[texture])
        with self.assertRaisesRegex(ValueError,'Конфликт имени ресурса'):service.collect()

    def test_generated_scripts_reference_custom_model_in_staging(self):
        content=self.root/'game/_work/Data/Scripts/Content'
        (content/'Items').mkdir(parents=True)
        (content/'Gothic.src').write_bytes(b'Items\\IT_*.d\n')
        source=self.root/'custom.3ds'
        source.write_bytes(model())
        self.manager.import_model(self.item,source)
        with tempfile.TemporaryDirectory() as temporary:
            staged,_,_=ProjectTools(self.repo.root,self.root/'game')._prepare(Path(temporary),lambda _:None)
            generated=parse_items(staged/'Items/GE_ComponentPotions.d','build')[0]
            self.assertEqual(generated.visual,'model_ItPo_Potion1.3ds')


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        with patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(self.root/'settings.json')):
            self.app=EditorApp()
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.app.repo.create(self.root/'project','Appearance')
        self.item=self.app.repo.create_item('potions')
        self.app.show_project()
        self.app.select(self.item)

    def test_import_updates_preview_and_replacement_requires_confirmation(self):
        source=self.root/'model.3ds'
        source.write_bytes(model())
        with patch('gothic_editor.ui.controllers.item_appearance.filedialog.askopenfilename',return_value=str(source)):
            self.app.appearance.import_model(self.item)
        item=self.app.current
        self.assertEqual(self.app.viewer.faces,[(0,1,2)])
        self.assertEqual(item.visual,'model_ItPo_Potion1.3ds')
        self.assertTrue(any(p.name=='model.3ds' for p in self.app.resources.paths.values()))
        changed=geometry_3ds([(0.,0.,0.),(2.,0.,0.),(0.,2.,0.)],[(0,1,2)])
        source.write_bytes(changed)
        with patch('gothic_editor.ui.controllers.item_appearance.filedialog.askopenfilename',return_value=str(source)), \
                patch('gothic_editor.ui.controllers.item_appearance.messagebox.askyesno',return_value=False) as confirm:
            self.app.appearance.import_model(item)
        confirm.assert_called_once()
        self.assertEqual((item.path.parent/'assets/model.3ds').read_bytes(),model())
        with patch('gothic_editor.ui.controllers.item_appearance.filedialog.askopenfilename',return_value=str(source)), \
                patch('gothic_editor.ui.controllers.item_appearance.messagebox.askyesno',return_value=True):
            self.app.appearance.import_model(item)
        self.assertEqual(self.app.viewer.vertices[1],(2.,0.,0.))
        self.assertTrue(any(self.app.repo.root.glob('backups/item-assets-*')))

    def test_open_legacy_project_requests_migration_confirmation(self):
        old=self.app.repo.root/'Items'/self.item.instance
        self.item.path.parent.rename(old)
        with patch('gothic_editor.app.messagebox.askyesno',return_value=True) as confirm:
            self.app.open_project_path(self.app.repo.root)
        confirm.assert_called_once()
        self.assertFalse(old.exists())
        self.assertEqual(self.app.repo.project_items[0].path.parent.parent.name,'Potions')
        with patch('gothic_editor.app.messagebox.askyesno') as confirm:
            self.app.open_project_path(self.app.repo.root)
        confirm.assert_not_called()

    def test_import_original_makes_project_copy_and_hides_original_row(self):
        content=self.root/'game/_work/Data/Scripts/Content/Items'
        content.mkdir(parents=True)
        script=content/'IT_Potions.d'
        original=b'INSTANCE ItPo_Original(C_Item) { name="Original"; mainflag=ITEM_KAT_POTIONS; };'
        script.write_bytes(original)
        self.app.repo.set_game_path(str(self.root/'game'))
        self.app.update_hierarchy()
        original_item=self.app.repo.game_items[0]
        self.assertIn(original_item,self.app.hierarchy.items)
        source=self.root/'model.3ds'
        source.write_bytes(model())
        with patch('gothic_editor.ui.controllers.item_appearance.filedialog.askopenfilename',return_value=str(source)):
            self.app.appearance.import_model(original_item)
        rows=[i for i in self.app.hierarchy.items if i.instance=='ItPo_Original']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].origin,'project')
        self.assertEqual(script.read_bytes(),original)
