import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.recent_projects import RecentProjects
from gothic_editor.core.settings import EditorSettings, SettingsStore


class RecentProjectsTests(unittest.TestCase):
    def test_ten_entries_persist_and_reopening_moves_project_to_front(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            history=RecentProjects(root/'recent_projects.json')
            for index in range(12):history.remember(root/f'Project{index}',f'Project {index}')
            self.assertEqual(len(history.entries),10)
            self.assertEqual(history.entries[0].path,root/'Project11')
            history.remember(root/'Project5/../Project5','Updated name')
            restored=RecentProjects(history.path)
            self.assertEqual(len(restored.entries),10)
            self.assertEqual(restored.entries[0].name,'Updated name')
            self.assertEqual(len({entry.path for entry in restored.entries}),10)

    def test_invalid_history_and_settings_save_do_not_break_recent_projects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            path=root/'recent_projects.json'
            path.write_bytes(b'bad json')
            history=RecentProjects(path)
            self.assertEqual(history.entries,[])
            history.remember(root/'Project','Project')
            SettingsStore(root/'settings.json').save(EditorSettings())
            self.assertEqual(RecentProjects(path).entries[0].path,root/'Project')
            path.write_text(json.dumps([None,{'path':4,'name':'bad'},
                                       {'path':str(root/'Project'),'name':'Valid'}]),encoding='utf-8')
            self.assertEqual(len(RecentProjects(path).entries),1)


class WelcomeTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.store=SettingsStore(self.root/'settings.json')
        history=RecentProjects(self.root/'recent_projects.json')
        self.projects=[]
        for index in range(12):
            folder=self.root/'Mods'/f'Project{index}'
            folder.mkdir(parents=True)
            (folder/'project.json').write_text(json.dumps({'name':f'Project {index}','game_path':''}),encoding='utf-8')
            history.remember(folder,f'Project {index}')
            self.projects.append(folder)
        with patch('gothic_editor.app.SettingsStore',return_value=self.store):
            try:self.app=EditorApp()
            except tk.TclError as exc:self.skipTest(str(exc))
        self.addCleanup(self.app.destroy)
        self.app.withdraw()
        self.app.update_idletasks()

    def test_startup_lists_ten_and_menu_lists_five(self):
        self.assertIsNone(self.app.repo.root)
        self.assertTrue(self.app.welcome.winfo_exists())
        self.assertEqual(len(self.app.welcome.projects.get_children()),10)
        self.assertEqual(self.app.recent_menu.index('end'),4)
        self.assertEqual(self.app.editor_frame.winfo_manager(),'')

    def test_recent_menu_opens_project_without_folder_picker_and_updates_history(self):
        chosen=self.app.recent_projects.entries[2].path
        with patch('gothic_editor.app.filedialog.askdirectory') as picker:
            self.app.recent_menu.invoke(2)
        picker.assert_not_called()
        self.assertEqual(self.app.repo.root,chosen)
        self.assertIsNone(self.app.welcome)
        self.assertEqual(self.app.editor_frame.winfo_manager(),'pack')
        self.assertEqual(RecentProjects(self.root/'recent_projects.json').entries[0].path,chosen)

    def test_startup_selection_opens_selected_project(self):
        screen=self.app.welcome
        screen.projects.selection_set('4')
        chosen=screen.entries[4].path
        screen.open_selected()
        self.assertEqual(self.app.repo.root,chosen)
        self.assertIsNone(self.app.welcome)

    def test_new_project_is_created_beside_last_project(self):
        with patch('gothic_editor.app.simpledialog.askstring',return_value='FreshProject'), \
                patch('gothic_editor.app.filedialog.askdirectory') as picker:
            self.app.create_project(beside_recent=True)
        picker.assert_not_called()
        expected=self.root/'Mods/FreshProject'
        self.assertEqual(self.app.repo.root,expected)
        self.assertTrue((expected/'project.json').is_file())
        self.assertEqual(self.app.recent_projects.entries[0].path,expected)
        self.assertTrue((self.projects[-1]/'project.json').is_file())

    def test_existing_folder_and_invalid_names_are_not_used(self):
        before=list(self.app.recent_projects.entries)
        for name in ('../Outside','Project11'):
            with patch('gothic_editor.app.simpledialog.askstring',return_value=name), \
                    patch('gothic_editor.app.messagebox.showerror') as error:
                self.app.create_project(beside_recent=True)
            error.assert_called_once()
        self.assertIsNone(self.app.repo.root)
        self.assertEqual(self.app.recent_projects.entries,before)

    def test_missing_project_does_not_replace_history_or_close_startup(self):
        entry=self.app.recent_projects.entries[0]
        (entry.path/'project.json').unlink()
        before=list(self.app.recent_projects.entries)
        with patch('gothic_editor.app.messagebox.showerror') as error:
            self.app.open_project_path(entry.path)
        error.assert_called_once()
        self.assertTrue(self.app.welcome.winfo_exists())
        self.assertEqual(self.app.recent_projects.entries,before)

    def test_startup_with_no_history_uses_folder_picker(self):
        self.app.recent_projects.entries=[]
        self.app._update_recent_menu()
        self.app.show_welcome()
        self.assertEqual(len(self.app.welcome.projects.get_children()),0)
        self.assertEqual(self.app.recent_menu.entrycget(0,'state'),'disabled')
        with patch('gothic_editor.app.filedialog.askdirectory',return_value='') as picker:
            self.app.create_project(beside_recent=True)
        picker.assert_called_once()

    def test_language_rebuild_keeps_startup_and_history(self):
        self.app._rebuild_translated_ui()
        self.assertTrue(self.app.welcome.winfo_exists())
        self.assertEqual(len(self.app.welcome.projects.get_children()),10)
        self.assertEqual(self.app.recent_menu.index('end'),4)


if __name__=='__main__':
    unittest.main()
