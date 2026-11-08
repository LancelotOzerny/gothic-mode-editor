import json
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.recent_projects import RecentProjects
from gothic_editor.core.settings import EditorSettings, SettingsStore
from gothic_editor.ui.project_dialog import NewProjectDialog


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
        self.assertEqual(len(self.app.welcome.rows),10)
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
        screen.selected=screen.entries[4]
        chosen=screen.entries[4].path
        with patch.object(screen,'wait_window',side_effect=lambda dialog:dialog.confirm()):
            screen.open_selected()
        self.assertEqual(self.app.repo.root,chosen)
        self.assertIsNone(self.app.welcome)

    def test_new_project_uses_explicit_location_and_project_name(self):
        expected=self.root/'Chosen Location/FreshProject'
        expected.parent.mkdir()
        def complete(dialog):
            dialog.name.set('FreshProject')
            dialog.directory.set(str(expected.parent))
            dialog.submit()
        with patch.object(self.app,'wait_window',side_effect=complete):
            self.app.create_project()
        self.assertEqual(self.app.repo.root,expected)
        self.assertTrue((expected/'project.json').is_file())
        self.assertEqual(self.app.recent_projects.entries[0].path,expected)
        self.assertTrue((self.projects[-1]/'project.json').is_file())

    def test_existing_folder_and_invalid_names_are_not_used(self):
        before=list(self.app.recent_projects.entries)
        for name in ('../Outside','Project11'):
            dialog=NewProjectDialog(self.app,self.root/'Mods')
            dialog.name.set(name)
            with patch('gothic_editor.ui.project_dialog.messagebox.showerror') as error:
                dialog.submit()
            error.assert_called_once()
            self.assertIsNone(dialog.result)
            dialog.destroy()
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

    def test_startup_with_no_history_can_browse_and_cancel_creation(self):
        self.app.recent_projects.entries=[]
        self.app._update_recent_menu()
        self.app.show_welcome()
        self.assertEqual(len(self.app.welcome.rows),0)
        self.assertEqual(self.app.recent_menu.entrycget(0,'state'),'disabled')
        with patch('gothic_editor.app.filedialog.askdirectory',return_value='') as picker:
            self.app.welcome.open_selected()
        picker.assert_called_once()
        with patch.object(self.app,'wait_window',side_effect=lambda dialog:dialog.destroy()):
            self.app.create_project()
        self.assertIsNone(self.app.repo.root)

    def test_search_matches_name_and_full_path_without_changing_history(self):
        screen=self.app.welcome
        before=list(self.app.recent_projects.entries)
        screen.query.set('PROJECT 11')
        self.assertEqual([entry.name for entry,_,_ in screen.rows],['Project 11'])
        screen.query.set(str(self.projects[5]))
        self.assertEqual([entry.path for entry,_,_ in screen.rows],[self.projects[5]])
        screen.query.set('no such project')
        self.assertEqual(screen.rows,[])
        screen.query.set('')
        self.assertEqual(len(screen.rows),10)
        self.assertEqual(self.app.recent_projects.entries,before)

    def test_language_rebuild_keeps_startup_and_history(self):
        self.app._rebuild_translated_ui()
        self.assertTrue(self.app.welcome.winfo_exists())
        self.assertEqual(len(self.app.welcome.rows),10)
        self.assertEqual(self.app.recent_menu.index('end'),4)

    def test_removal_confirmation_only_changes_history(self):
        screen=self.app.welcome
        entry=screen.entries[0]
        original=(entry.path/'project.json').read_bytes()
        with patch.object(screen,'wait_window',side_effect=lambda dialog:dialog.destroy()):
            screen.remove_recent(entry)
        self.assertIn(entry,self.app.recent_projects.entries)
        with patch.object(screen,'wait_window',side_effect=lambda dialog:dialog.confirm()):
            screen.remove_recent(entry)
        self.assertNotIn(entry,self.app.recent_projects.entries)
        self.assertNotIn(entry,RecentProjects(self.app.recent_projects.path).entries)
        self.assertEqual((entry.path/'project.json').read_bytes(),original)
        self.assertEqual(len(screen.rows),9)
        self.assertNotIn(entry.name,self.app.recent_menu.entrycget(0,'label'))

    def test_open_folder_does_not_open_project_or_ask_confirmation(self):
        screen=self.app.welcome
        entry=screen.entries[0]
        with patch('gothic_editor.ui.welcome.os.startfile',create=True) as start, \
                patch('gothic_editor.ui.welcome.sys.platform','win32'), \
                patch('gothic_editor.ui.welcome.messagebox.askyesno') as confirm:
            screen.open_folder(entry)
        start.assert_called_once_with(str(entry.path))
        confirm.assert_not_called()
        self.assertIsNone(self.app.repo.root)

    def test_missing_icons_fall_back_without_loading_images(self):
        screen=self.app.welcome
        screen.icons.directory=self.root/'absent-icons'
        with patch.object(screen.icons,'frames') as frames:
            screen.render_projects()
            self.assertEqual(screen.icon('search.png','Search')['text'],'Search')
            self.assertEqual(screen.rows[0][2][0].text,'[П]')
        frames.assert_not_called()

    def test_row_hover_and_single_click_confirm_before_opening_project(self):
        screen=self.app.welcome
        self.app.deiconify()
        self.app.update()
        entry,row,buttons=screen.rows[1]
        with patch.object(row,'winfo_pointerxy',return_value=(row.winfo_rootx()+5,row.winfo_rooty()+5)):
            row.event_generate('<Enter>')
            deadline=time.monotonic()+.6
            while time.monotonic()<deadline:
                self.app.update()
                time.sleep(.01)
        self.assertTrue(all(button.winfo_manager()=='grid' for button in buttons))
        self.assertEqual(row.progress,6)
        with patch.object(row,'winfo_pointerxy',return_value=(-1,-1)):
            row.event_generate('<Leave>')
            deadline=time.monotonic()+.6
            while time.monotonic()<deadline:
                self.app.update()
                time.sleep(.01)
        self.assertTrue(all(not button.winfo_manager() for button in buttons))
        with patch.object(screen,'on_open') as opened, \
                patch.object(screen,'wait_window',side_effect=lambda dialog:dialog.destroy()) as modal:
            row.event_generate('<ButtonPress-1>',x=5,y=5)
            row.event_generate('<ButtonRelease-1>',x=5,y=5)
            modal.assert_called_once()
            opened.assert_not_called()
        with patch.object(screen,'on_open') as opened, \
                patch.object(screen,'wait_window',side_effect=lambda dialog:dialog.confirm()):
            screen.open_entry(entry)
            opened.assert_called_once_with(entry.path)

    def test_resizing_keeps_search_buttons_and_scrollable_rows(self):
        self.app.deiconify()
        screen=self.app.welcome
        for width in (870,1200):
            self.app.geometry(f'{width}x540')
            self.app.update()
            self.assertTrue(screen.search.winfo_viewable())
            self.assertTrue(screen.actions.winfo_viewable())
            self.assertLessEqual(screen.actions.winfo_x()+screen.actions.winfo_width(),screen.header.winfo_width())
        screen.canvas.yview_moveto(1)
        self.app.update()
        self.assertGreater(screen.canvas.yview()[0],0)
        with patch('gothic_editor.app.filedialog.askdirectory',return_value='') as picker:
            screen.actions.winfo_children()[1].invoke()
        picker.assert_called_once()

    def test_welcome_is_centered_borderless_and_editor_restores_its_chrome(self):
        self.app.deiconify()
        self.app.update()
        self.assertEqual((self.app.winfo_width(),self.app.winfo_height()),(720,480))
        self.assertTrue(self.app.overrideredirect())
        self.assertEqual(self.app.cget('menu'),'')
        self.assertAlmostEqual(self.app.winfo_x(),(self.app.winfo_screenwidth()-720)//2,delta=2)
        self.assertAlmostEqual(self.app.winfo_y(),(self.app.winfo_screenheight()-480)//2,delta=2)
        self.app.open_project_path(self.projects[-1])
        self.assertFalse(self.app.overrideredirect())
        self.assertEqual(str(self.app.cget('menu')),str(self.app.main_menu))
        self.assertEqual(self.app.minsize(),(870,540))

    def test_missing_directory_disables_opening_and_removes_without_confirmation(self):
        entry=self.app.recent_projects.entries[0]
        (entry.path/'project.json').unlink()
        entry.path.rmdir()
        screen=self.app.welcome
        screen.render_projects()
        _,row,buttons=screen.rows[0]
        self.assertFalse(row.available)
        self.assertIn('overstrike',str(row.name_label.cget('font')))
        self.assertEqual(len(buttons),1)
        with patch.object(screen,'on_open') as opened, patch.object(screen,'wait_window') as modal:
            screen.open_entry(entry)
            screen.remove_recent(entry)
        opened.assert_not_called()
        modal.assert_not_called()
        self.assertNotIn(entry,self.app.recent_projects.entries)

    def test_action_buttons_are_40_pixels_and_use_their_actual_background(self):
        screen=self.app.welcome
        self.app.deiconify()
        self.app.update()
        button=screen.rows[0][2][1]
        button.grid()
        button.paint(background='#252e3c',opacity=1)
        self.app.update_idletasks()
        self.assertEqual((button.winfo_width(),button.winfo_height()),(40,40))
        self.assertEqual((screen.close_button.winfo_width(),screen.close_button.winfo_height()),(30,30))
        self.assertEqual(button.cget('bg'),'#252e3c')
        self.assertIsNotNone(button.image)
        self.assertEqual((button.image.width(),button.image.height()),(20,20))

    def test_fullscreen_restores_size_and_opening_restores_editor_window(self):
        screen=self.app.welcome
        self.app.deiconify()
        self.app.update()
        original=self.app.geometry()
        screen.fullscreen_button.invoke()
        self.app.update()
        self.assertTrue(self.app.attributes('-fullscreen'))
        self.assertTrue(screen.is_fullscreen)
        screen.fullscreen_button.invoke()
        self.app.update()
        self.assertFalse(self.app.attributes('-fullscreen'))
        self.assertEqual(self.app.geometry(),original)
        screen.fullscreen_button.invoke()
        self.app.update()
        self.app.open_project_path(self.projects[-1])
        self.assertFalse(self.app.attributes('-fullscreen'))
        self.assertFalse(self.app.overrideredirect())

    def test_history_write_failure_keeps_visible_project(self):
        screen=self.app.welcome
        entry=screen.entries[0]
        before=list(self.app.recent_projects.entries)
        with patch.object(screen,'wait_window',side_effect=lambda dialog:dialog.confirm()), \
                patch('gothic_editor.core.recent_projects.Path.replace',side_effect=OSError('write failed')), \
                patch('gothic_editor.ui.welcome.messagebox.showerror') as error:
            screen.remove_recent(entry)
        error.assert_called_once()
        self.assertEqual(self.app.recent_projects.entries,before)
        self.assertEqual(len(screen.rows),10)


if __name__=='__main__':
    unittest.main()
