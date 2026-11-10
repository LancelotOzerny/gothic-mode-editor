"""Assets layout and browser regressions using synthetic items only."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.item_layout import ItemLayout, project_scripts
from gothic_editor.core.asset_files import AssetFiles
from gothic_editor.core.scripts import Item, parse_items
from gothic_editor.ui.panels.resources import ResourcesPanel


class AssetsLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='assets project ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Test')

    def add_item(self):
        code='INSTANCE ItPo_Test(C_Item) {mainflag=ITEM_KAT_POTIONS; name="Test";};'
        source=Item('ItPo_Test',self.root/'source.d','project',code,{},0,len(code))
        folder=self.repo.components.import_item(source)
        self.repo.refresh()
        return folder

    def test_new_layout_save_reopen_and_staged_generation(self):
        project=self.repo.root
        self.assertTrue((project/'Assets/Models').is_dir())
        folder=self.add_item()
        self.assertEqual(folder,project/'Assets/Items/Potions/ItPo_Test')
        item=self.repo.project_items[0]
        self.repo.edit(item,{'name':'"Changed"'})
        reopened=ProjectRepository()
        reopened.open(project)
        self.assertEqual(reopened.project_items[0].title,'Changed')
        self.assertFalse((project/'Items').exists())
        self.assertFalse((project/'Scripts').exists())
        game=self.root/'game'
        content=game/'_work/Data/Scripts/Content'
        (content/'Items').mkdir(parents=True)
        (content/'Gothic.src').write_text('Items/*.d')
        (content/'Items/Base.d').write_text('const int BASE = 1;')
        overlay=project/'Assets/Scripts/Content/Items/Extra.d'
        overlay.write_text('INSTANCE ItSc_Test(C_Item) {name="Scroll";};')
        reopened.refresh()
        self.assertIn('ItSc_Test',[item.instance for item in reopened.project_items])
        tools=ProjectTools(project,game)
        staging=self.root/'staging'
        staging.mkdir()
        staged,manifest,files=tools._prepare(staging,lambda _:None)
        self.assertIn(Path('Items/Extra.d'),files)
        generated=staged/'Items/GE_ComponentPotions.d'
        self.assertEqual(parse_items(generated,'project')[0].title,'Changed')
        self.assertIn('Items/*.d',manifest.read_text())
        self.assertNotIn('Changed',(content/'Items/Base.d').read_text())

    def test_old_layout_fallback_and_assets_priority(self):
        project=self.root/'legacy'
        (project/'Items/Potions').mkdir(parents=True)
        (project/'Scripts/Content').mkdir(parents=True)
        self.assertEqual(ItemLayout(project).items,project/'Items')
        self.assertEqual(project_scripts(project),project/'Scripts')
        (project/'Assets/Items').mkdir(parents=True)
        (project/'Assets/Scripts').mkdir()
        self.assertEqual(ItemLayout(project).items,project/'Assets/Items')
        self.assertEqual(project_scripts(project),project/'Assets/Scripts')


class AssetsBrowserTests(unittest.TestCase):
    def setUp(self):
        self.window=tk.Tk()
        self.addCleanup(self.window.destroy)
        temporary=tempfile.TemporaryDirectory(prefix='assets browser ')
        self.addCleanup(temporary.cleanup)
        self.project=Path(temporary.name)
        self.assets=self.project/'Assets'
        for name in ('Items/Potions/Test','Models','Scripts/Content'):
            (self.assets/name).mkdir(parents=True)
        (self.assets/'Items/Potions/Test/item.json').write_text('{}')
        (self.assets/'Models/Mesh.3ds').write_bytes(b'model')
        self.panel=ResourcesPanel(self.window,lambda:'editor.exe',lambda:None)
        self.panel.pack(fill='both',expand=True)
        self.panel.set_item(self.project,None)
        self.window.update_idletasks()

    def test_navigation_tree_selection_and_item_independence(self):
        self.assertEqual({p.name for p in self.panel.paths.values()},{'Items','Models','Scripts'})
        self.panel.select_file(self.assets/'Items')
        self.panel.open_selected()
        self.assertEqual(self.panel.folder,self.assets/'Items')
        self.assertEqual([p.name for p in self.panel.paths.values()],['Potions'])
        node=next(node for node,path in self.panel._tree_paths.items() if path==self.assets/'Models')
        self.panel.tree.selection_set(node)
        self.panel._tree_select()
        self.assertEqual(self.panel.folder,self.assets/'Models')
        tile=next(iter(self.panel.tiles.values()))
        self.assertEqual(tile.caption,'Mesh.3ds')
        self.panel.set_item(self.project,object())
        self.assertEqual(self.panel.folder,self.assets/'Models')
        self.assertIs(next(iter(self.panel.tiles.values())),tile)
        self.panel.refresh()
        self.assertEqual(self.panel.folder,self.assets/'Models')

    def test_file_open_boundary_and_project_change(self):
        self.panel.open_folder(self.assets/'Items/Potions/Test')
        path=self.assets/'Items/Potions/Test/item.json'
        self.panel.select_file(path)
        with patch('gothic_editor.ui.panels.resources.open_in_editor') as launch:
            self.panel.open_selected()
            launch.assert_called_once_with(path,'editor.exe',self.project)
        with self.assertRaises(ValueError):self.panel._inside(self.project)
        self.panel.open_folder(self.project)
        self.assertEqual(self.panel.folder,path.parent)
        self.panel.set_item(None,None)
        self.assertFalse(self.panel.paths)
        self.assertFalse(self.panel.tree.get_children())

    def test_removed_folder_falls_back_to_existing_parent(self):
        folder=self.assets/'Empty'
        folder.mkdir()
        self.panel.refresh()
        self.panel.open_folder(folder)
        folder.rmdir()
        self.panel.refresh()
        self.assertEqual(self.panel.folder,self.assets)

    def popup(self):
        with patch('tkinter.Menu.tk_popup'):
            self.panel.context(SimpleNamespace(x_root=0,y_root=0))
        return self.panel.menu

    def test_dark_background_and_creation_menu(self):
        from gothic_editor.ui.widgets import PANEL
        self.assertEqual(self.panel.scroll_area.canvas.cget('bg'),PANEL)
        self.assertEqual(self.panel.scroll_area.content.cget('bg'),PANEL)
        menu=self.popup()
        self.assertEqual(menu.entrycget(0,'label'),'Создать директорию')
        self.assertEqual(menu.entrycget(1,'label'),'Скрипты')
        with patch('gothic_editor.ui.panels.resources.ResourceNameDialog') as dialog, \
                patch.object(self.panel,'wait_window'):
            dialog.return_value.result='New Folder'
            menu.invoke(0)
        folder=self.assets/'New Folder'
        self.assertTrue(folder.is_dir())
        self.panel.open_folder(folder)
        with patch('gothic_editor.ui.panels.resources.ResourceNameDialog') as dialog, \
                patch.object(self.panel,'wait_window'):
            dialog.return_value.result='Empty'
            self.panel.create_resource(True)
        self.assertEqual((folder/'Empty.d').read_bytes(),b'')

    def test_file_menu_duplicate_shortcuts_and_confirmed_delete(self):
        self.panel.open_folder(self.assets/'Models')
        source=self.assets/'Models/Mesh.3ds'
        self.panel.select_file(source)
        menu=self.popup()
        self.assertEqual([menu.entrycget(i,'label') for i in range(4)],
                         ['Дублировать','Открыть в папке','Удалить','Открыть'])
        menu.invoke(0)
        duplicate=source.with_name('Mesh_copy.3ds')
        self.assertEqual(duplicate.read_bytes(),source.read_bytes())
        self.panel.select_file(source)
        self.panel.shortcut(SimpleNamespace(keysym='c',keycode=67))
        self.panel.open_folder(self.assets/'Scripts/Content')
        self.panel.shortcut(SimpleNamespace(keysym='v',keycode=86))
        copied=self.assets/'Scripts/Content/Mesh.3ds'
        self.assertEqual(copied.read_bytes(),source.read_bytes())
        with patch('gothic_editor.ui.panels.resources.messagebox.askyesno',return_value=False):
            self.panel.delete_selected()
        self.assertTrue(copied.exists())
        with patch('gothic_editor.ui.panels.resources.messagebox.askyesno',return_value=True):
            self.panel.delete_selected()
        self.assertFalse(copied.exists())
        self.assertTrue(source.exists())

    def test_directory_menu_paths_and_copy_from_tree(self):
        folder=self.assets/'Models'
        self.panel.select_file(folder)
        menu=self.popup()
        self.assertEqual([menu.entrycget(i,'label') for i in range(4)],
                         ['Удалить','Дублировать','Копировать путь','Открыть'])
        self.panel.copy_path()
        self.assertEqual(self.window.clipboard_get(),'Assets/Models')
        self.panel.copy_path(True)
        self.assertEqual(self.window.clipboard_get(),str(folder))
        menu.invoke(3)
        self.panel.tree.focus_force()
        self.window.update()
        self.panel.copy_selected()
        self.panel.open_folder(self.assets/'Scripts')
        self.panel.paste()
        self.assertEqual((self.assets/'Scripts/Models/Mesh.3ds').read_bytes(),b'model')

    def test_cancelled_save_prevents_file_operation(self):
        self.panel.open_folder(self.assets/'Models')
        self.panel.select_file(self.assets/'Models/Mesh.3ds')
        self.panel.before_change=lambda:False
        self.panel.duplicate_selected()
        self.assertFalse((self.assets/'Models/Mesh_copy.3ds').exists())


class AssetFileOperationsTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='asset operations ')
        self.addCleanup(temporary.cleanup)
        self.project=Path(temporary.name)
        (self.project/'Assets').mkdir()
        self.files=AssetFiles(self.project)
        self.root=self.files.root

    def test_recursive_copy_unique_names_and_deletion(self):
        folder=self.files.create(self.root,'Folder.with.dots')
        nested=self.files.create(folder,'Nested')
        (nested/'data.bin').write_bytes(bytes(range(256)))
        first=self.files.copy(folder,self.root)
        second=self.files.copy(folder,self.root)
        self.assertEqual(first.name,'Folder.with.dots_copy')
        self.assertEqual(second.name,'Folder.with.dots_copy_2')
        self.assertEqual((first/'Nested/data.bin').read_bytes(),bytes(range(256)))
        self.files.delete(first)
        self.assertFalse(first.exists())
        self.assertTrue((folder/'Nested/data.bin').is_file())
        self.assertTrue(second.is_dir())

    def test_empty_script_extension_and_no_overwrite(self):
        script=self.files.create(self.root,'Script',True)
        self.assertEqual(script.name,'Script.d')
        self.assertEqual(script.read_bytes(),b'')
        script.write_bytes(b'original')
        with self.assertRaises(FileExistsError):self.files.create(self.root,'Script.d',True)
        copy=self.files.copy(script,self.root)
        self.assertEqual(copy.name,'Script_copy.d')
        self.assertEqual(copy.read_bytes(),b'original')
        self.files.delete(copy)
        self.assertEqual(script.read_bytes(),b'original')

    def test_boundaries_names_and_recursive_destination(self):
        folder=self.files.create(self.root,'Folder')
        nested=self.files.create(folder,'Nested')
        for path in (self.project,self.root):
            with self.assertRaises(ValueError):self.files.delete(path)
        for name in ('../outside','a/b','a\\b','..','bad:','CON','trailing.',' space'):
            with self.assertRaises(ValueError):self.files.create(self.root,name)
        with self.assertRaises(ValueError):self.files.copy(folder,nested)
        with self.assertRaises(ValueError):self.files.copy(folder,self.project)
        self.assertTrue(nested.is_dir())

    def test_links_are_not_followed_for_recursive_operations(self):
        folder=self.files.create(self.root,'Folder')
        outside=self.project/'Outside'
        outside.mkdir()
        (outside/'keep.txt').write_text('keep')
        link=folder/'Link'
        try:link.symlink_to(outside,target_is_directory=True)
        except OSError as exc:self.skipTest(str(exc))
        with self.assertRaises(ValueError):self.files.copy(folder,self.root)
        with self.assertRaises(ValueError):self.files.delete(folder)
        self.assertEqual((outside/'keep.txt').read_text(),'keep')
