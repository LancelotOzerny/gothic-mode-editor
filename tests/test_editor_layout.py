import tempfile
import tkinter as tk
import unittest
from concurrent.futures import Future
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.localization import localization, tr
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.project_tools import ToolResult
from gothic_editor.core.settings import SettingsStore
from gothic_editor.ui.hierarchy import CategoryRow


class OriginalCopyTests(unittest.TestCase):
    def test_copy_keeps_original_instance_and_existing_project_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ProjectRepository()
            repository.create(root / 'project', 'Test')
            game_content = root / 'game/_work/Data/Scripts/Content/Items'
            game_content.mkdir(parents=True)
            script = game_content / 'IT_Test.d'
            source = ('INSTANCE ITPO_TEST (C_Item) { name = "Original"; mainflag = ITEM_KAT_POTIONS; };\n'
                      'INSTANCE ITPO_OTHER (C_Item) { name = "Other"; mainflag = ITEM_KAT_POTIONS; };')
            script.write_text(source, encoding='utf-8')
            repository.set_game_path(str(root / 'game'))
            original = repository.game_items[0]
            copied = repository.copy_to_project(original)
            self.assertEqual(copied.instance, original.instance)
            self.assertEqual(copied.origin, 'project')
            self.assertEqual(len(repository.game_items), 2)
            self.assertEqual(len(repository.project_items), 1)
            repository.edit(copied, {'name': '"Edited"'})
            self.assertEqual(repository.copy_to_project(original).title, 'Edited')
            self.assertEqual(repository.game_items[0].title, 'Original')
            self.assertEqual(script.read_text('utf-8'), source)
            self.assertNotIn('ITPO_OTHER',copied.path.read_text('utf-8-sig'))
            other=next(item for item in repository.game_items if item.instance=='ITPO_OTHER')
            copied_other=repository.copy_to_project(other)
            self.assertEqual(len(repository.project_items),2)
            self.assertEqual(repository.copy_to_project(original).title,'Edited')
            repository.delete(copied_other)
            self.assertEqual(len(repository.project_items),1)
            repository.delete(repository.project_items[0])
            self.assertFalse(copied.path.exists())


class EditorLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        store = SettingsStore(self.root / 'settings.json')
        with patch('gothic_editor.app.SettingsStore', return_value=store):
            try:
                self.app = EditorApp()
            except tk.TclError as exc:
                self.skipTest(str(exc))
        self.addCleanup(self.app.destroy)
        self.app.geometry('1240x760+50+50')
        self.app.update()

    def wait(self, seconds):
        deadline = monotonic() + seconds
        while monotonic() < deadline:
            self.app.update()

    def create_project(self):
        self.app.repo.create(self.root / 'project', 'Test')
        self.app.repo.create_item('potions')
        self.app.show_project(reset_hierarchy=True)

    def test_terminal_menu_full_width_default_height_and_resize_persistence(self):
        self.assertEqual(len(self.app.workspace.panes()), 1)
        view = self.app.nametowidget(self.app.main_menu.entrycget(3, 'menu'))
        windows = self.app.nametowidget(view.entrycget(0, 'menu'))
        windows.invoke(0)
        self.app.update()
        self.assertEqual(len(self.app.workspace.panes()), 2)
        self.assertAlmostEqual(self.app.bottom_dock.winfo_height(), 200, delta=2)
        self.assertEqual(self.app.bottom_dock.winfo_width(), self.app.workspace.winfo_width())
        self.app.workspace.sash_place(0, 0, self.app.workspace.winfo_height() - 287)
        self.app.update()
        self.app._remember_terminal_height()
        self.assertAlmostEqual(self.app.terminal_height, 280, delta=2)
        self.assertEqual(self.app.settings_store.load().get_value('interface.terminal.height'), self.app.terminal_height)
        self.app.hide_terminal()
        self.assertEqual(len(self.app.workspace.panes()), 1)
        self.app.show_terminal()
        self.app.update()
        self.assertAlmostEqual(self.app.bottom_dock.winfo_height(), self.app.terminal_height, delta=2)

    def test_category_counts_collapsed_origins_and_clockwise_animation(self):
        self.create_project()
        panel = self.app.hierarchy
        project = panel.sections['project']
        row = next(row for row in project.inner.winfo_children() if row.category.key == 'potions')
        self.assertEqual(panel.expanded, {})
        self.assertFalse(row.opened)
        self.assertIn('[1]', project.heading.cget('text'))
        self.assertIn('[0]', panel.sections['game'].heading.cget('text'))
        row.toggle()
        self.wait(.07)
        self.assertGreater(row.angle, 0)
        self.assertLess(row.angle, len(row.frames) - 1)
        self.wait(.15)
        self.assertEqual(row.angle, len(row.frames) - 1)
        self.assertNotIn(('game', 'potions'), panel.expanded)
        for y in range(18):
            for x in range(18):
                self.assertEqual(row.frames[-1].get(x, y), row.frames[0].get(y, 17 - x))
        panel.select(self.app.repo.project_items[0])
        self.assertTrue(row.winfo_exists())
        self.app.show_project(reset_hierarchy=True)
        self.assertEqual(panel.expanded, {})

    def test_original_context_copies_to_project(self):
        copied = []
        panel = self.app.hierarchy
        panel.on_copy = copied.append
        item = SimpleNamespace(origin='game')
        labels = []
        def popup(menu, x, y):
            labels.append(menu.entrycget(0, 'label'))
        with patch('tkinter.Menu.tk_popup', popup):
            panel.context(SimpleNamespace(x_root=0, y_root=0), item)
        menu=panel._context_menu
        self.app.update()
        self.assertTrue(menu.winfo_exists())
        self.assertEqual(copied, [])
        menu.invoke(0)  # The user chooses an action after tk_popup has returned.
        self.assertEqual(labels, [tr('hierarchy.copy_to_project')])
        self.assertEqual(copied, [item])

    def test_deferred_menu_command_copies_original_to_project(self):
        self.app.repo.create(self.root/'project','Test')
        source=self.root/'game/_work/Data/Scripts/Content/Items/IT_Test.d'
        source.parent.mkdir(parents=True)
        source.write_text('INSTANCE ITPO_TEST (C_Item) { name = "Original"; };',encoding='utf-8')
        self.app.repo.set_game_path(str(self.root/'game'))
        self.app.show_project(reset_hierarchy=True)
        panel=self.app.hierarchy
        original=self.app.repo.game_items[0]
        with patch('tkinter.Menu.tk_popup'):
            panel.context(SimpleNamespace(x_root=self.app.winfo_rootx()+20,
                                          y_root=self.app.winfo_rooty()+100),original)
        menu=panel._context_menu
        self.app.after(40,lambda:menu.invoke(0))
        self.wait(.1)
        menu.unpost()
        self.assertEqual(self.app.current.origin,'project')
        self.assertEqual(self.app.current.instance,original.instance)
        self.assertEqual(len(self.app.repo.project_items),1)
        self.assertEqual(len(self.app.repo.game_items),1)
        self.assertTrue(self.app.current.path.is_file())

    def test_compile_summary_follows_warnings_and_is_distinct_from_sync(self):
        log_path=self.root/'compile.log'
        log_path.write_text('warning W5: original script warning\nCompilation completed successfully.\n',encoding='utf-8')
        future=Future()
        with patch.object(self.app._tool_runner.executor,'submit',return_value=future):
            self.app._tool_runner.start('Build',lambda report:None,log_path)
        future.set_result(ToolResult(self.root/'Gothic.dat',warnings=1))
        self.wait(.1)
        output=self.app.terminal.log.get('1.0','end').strip()
        summary=tr('tools.compile_success',path=str(self.root/'Gothic.dat'),warnings=1)
        self.assertTrue(output.endswith(summary))
        self.assertIn('warning W5',output)
        self.assertNotIn(tr('tools.sync_success',path=str(self.root/'Gothic.dat'),count=0),output)

    def test_settings_is_centered_and_terminal_height_applies(self):
        self.app.show_settings()
        window = self.app.settings_window
        self.app.update()
        expected_x = self.app.winfo_rootx() + (self.app.winfo_width() - window.winfo_width()) // 2
        expected_y = self.app.winfo_rooty() + (self.app.winfo_height() - window.winfo_height()) // 2
        # Window-manager decorations can shift the client area by a few pixels.
        self.assertAlmostEqual(window.winfo_x(), expected_x, delta=3)
        self.assertAlmostEqual(window.winfo_y(), expected_y, delta=3)
        window.values['interface.terminal.height'][0].set('250')
        window.save()
        self.app.show_terminal()
        self.app.update()
        self.assertAlmostEqual(self.app.bottom_dock.winfo_height(), 250, delta=2)

    def test_terminal_survives_language_rebuild_while_operation_runs(self):
        self.create_project()
        self.app.show_terminal()
        future = Future()
        with patch.object(self.app._tool_runner.executor, 'submit', return_value=future):
            self.app._tool_runner.start('Build', lambda report: None)
        self.app._tool_runner.messages.put('Before language change')
        self.wait(.07)
        self.app._rebuild_translated_ui()
        self.assertIn('Before language change', self.app.terminal.log.get('1.0', 'end'))
        self.app._tool_runner.messages.put('After language change')
        future.set_result(ToolResult(self.root / 'Gothic.dat'))
        self.wait(.1)
        self.assertFalse(self.app._tool_runner.running)
        self.assertIn('After language change', self.app.terminal.log.get('1.0', 'end'))
        self.assertIn('Gothic.dat', self.app.terminal.log.get('1.0', 'end'))
        self.assertFalse(any(isinstance(widget, tk.Toplevel) for widget in self.app.winfo_children()))

    def test_toolbar_uses_icon_images(self):
        for button in (self.app.play_button, self.app.sync_button):
            self.assertTrue(button.cget('image'))
            self.assertEqual(button.cget('text'), '')


if __name__ == '__main__':
    unittest.main()
