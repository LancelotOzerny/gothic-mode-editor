import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.resources import item_resource_files, open_in_editor, open_in_folder
from gothic_editor.core.settings import SettingsStore


class ResourceFilesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gothic resources ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root/'Items/ItPo_Health_01'
        self.folder.mkdir(parents=True)
        (self.folder/'item.json').write_text('{}',encoding='utf-8')
        (self.folder/'functions.d').write_text('// helpers',encoding='utf-8')

    def test_case_insensitive_folder_and_nested_files(self):
        nested = self.folder/'nested'
        nested.mkdir()
        (nested/'data.json').write_text('{}',encoding='utf-8')
        folder, files = item_resource_files(self.root,'ITPO_HEALTH_01')
        self.assertEqual(folder,self.folder)
        self.assertEqual([path.relative_to(folder).as_posix() for path in files],
                         ['functions.d','item.json','nested/data.json'])
        _, empty = item_resource_files(self.root,'Missing')
        self.assertEqual(empty,[])
        for instance in ('../other', '..', r'..\other'):
            with self.assertRaises(ValueError):
                item_resource_files(self.root,instance)

    def test_external_editor_receives_separate_arguments_for_paths_with_spaces(self):
        editor = self.root/'Editor With Spaces.exe'
        editor.write_bytes(b'editor')
        path = self.folder/'item.json'
        with patch('gothic_editor.core.resources.subprocess.Popen') as launch:
            open_in_editor(path,editor.name,self.root)
        args,kwargs = launch.call_args
        self.assertEqual(args[0],[str(editor.resolve()),str(path.resolve())])
        self.assertNotIn('shell',kwargs)
        self.assertEqual(kwargs['cwd'],path.parent)
        with self.assertRaises(ValueError):
            open_in_editor(path,'',self.root)
        with self.assertRaises(ValueError):
            open_in_editor(path,'missing.exe',self.root)

    @unittest.skipUnless(os.name=='nt','Windows folder integration')
    def test_open_in_folder_opens_the_parent_directory(self):
        with patch('gothic_editor.core.resources.os.startfile') as launch:
            open_in_folder(self.folder/'item.json')
        launch.assert_called_once_with(str(self.folder.resolve()))


class ResourceDockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(self.root/'settings.json')):
            try:
                self.app = EditorApp()
            except tk.TclError as exc:
                self.skipTest(str(exc))
        self.addCleanup(self.app.destroy)
        self.app.withdraw()
        self.app.repo.create(self.root/'project','Test')
        self.item = self.app.repo.create_item('potions')
        self.app.show_project(reset_hierarchy=True)
        self.app.select(self.item)
        self.app.update_idletasks()

    def test_tabs_enable_independently_keep_order_and_allow_extensions(self):
        self.assertEqual(self.app.bottom_dock.visible_keys(),['terminal','resources'])
        self.assertEqual(self.app.bottom_dock.selected_key(),'resources')
        self.app.hide_terminal()
        self.app.show_bottom_tab('resources')
        self.assertEqual(self.app.bottom_dock.visible_keys(),['resources'])
        self.assertEqual(len(self.app.workspace.panes()),2)
        self.app.show_terminal()
        self.assertEqual(self.app.bottom_dock.visible_keys(),['terminal','resources'])
        self.assertEqual(self.app.bottom_dock.selected_key(),'terminal')
        self.app.hide_terminal()
        self.assertEqual(self.app.bottom_dock.visible_keys(),['resources'])
        self.assertEqual(self.app.bottom_dock.selected_key(),'resources')
        self.app.register_bottom_tab('extra','tools.title',lambda parent:tk.Frame(parent))
        self.app.show_bottom_tab('extra')
        self.assertEqual(self.app.bottom_dock.visible_keys(),['resources','extra'])
        self.app.show_terminal()
        self.assertEqual(self.app.bottom_dock.visible_keys(),['terminal','resources','extra'])
        for key in ('terminal','resources','extra'):
            self.app.hide_bottom_tab(key)
        self.assertEqual(len(self.app.workspace.panes()),1)

    def test_resources_follow_selected_item_and_clear_on_project_change(self):
        resources = self.app.resources
        self.assertEqual({path.name for path in resources.paths.values()},
                         {'item.json','params.json','functions.json','functions.d'})
        first_folder = self.item.path.parent
        self.assertTrue(all(path.parent==first_folder for path in resources.paths.values()))
        second = self.app.repo.create_item('potions')
        self.app.select(second)
        self.assertTrue(all(path.parent==second.path.parent for path in resources.paths.values()))
        self.app.show_project()
        self.assertEqual(resources.paths,{})

    def test_double_click_and_context_menu_open_editor_and_folder(self):
        resources = self.app.resources
        path = next(path for path in resources.paths.values() if path.name=='item.json')
        event = SimpleNamespace(y=1,x_root=0,y_root=0)
        resources.select_file(path)
        with patch('gothic_editor.ui.panels.resources.open_in_editor') as launch:
            resources.open_selected()
            launch.assert_called_once_with(self.item.path,self.app.repo.resource_editor_path,self.app.repo.root)
        with patch('tkinter.Menu.tk_popup'):
            resources.context(event)
        self.assertTrue(resources.menu.winfo_exists())
        with patch('gothic_editor.ui.panels.resources.open_in_editor') as launch, \
                patch('gothic_editor.ui.panels.resources.open_in_folder') as reveal:
            resources.menu.invoke(0)
            resources.menu.invoke(1)
        launch.assert_called_once()
        reveal.assert_called_once_with(self.item.path)

    def test_editor_setting_is_shared_and_preserved_when_game_changes(self):
        editor = self.root/'editor.exe'
        editor.write_bytes(b'editor')
        self.app.show_settings()
        window = self.app.settings_window
        window.values['resources.editor.path'][0].set(str(editor))
        window.save()
        self.assertFalse(window.winfo_exists())
        self.assertEqual(self.app.repo.resource_editor_path,str(editor))
        self.app.repo.set_game_path('')
        data = json.loads((self.app.repo.root/'project.json').read_text('utf-8'))
        self.assertNotIn('resource_editor_path',data)
        self.assertEqual(self.app.settings_store.load().get_value('resources.editor.path'),str(editor))

    def test_language_rebuild_keeps_selected_tab_terminal_and_resource_files(self):
        self.app.show_terminal()
        self.app.terminal.append('Compiler output')
        self.app.show_bottom_tab('resources')
        self.app._rebuild_translated_ui()
        self.app.update_idletasks()
        self.assertEqual(self.app.bottom_dock.visible_keys(),['terminal','resources'])
        self.assertEqual(self.app.bottom_dock.selected_key(),'resources')
        self.assertIn('Compiler output',self.app.terminal.log.get('1.0','end'))
        self.assertEqual(len(self.app.resources.paths),4)


if __name__=='__main__':
    unittest.main()
