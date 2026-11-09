import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.settings import SettingsStore
from gothic_editor.ui.windows.item_dialog import AddItemDialog


class AddItemTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with patch('gothic_editor.app.SettingsStore', return_value=SettingsStore(self.root / 'settings.json')):
            self.app = EditorApp()
        self.addCleanup(self.app.destroy)
        self.app.state('normal')
        self.app.geometry('1240x760+30+30')
        self.app.repo.create(self.root / 'project', 'Test')
        source = self.root / 'game/_work/Data/Scripts/Content/Items/Test.d'
        source.parent.mkdir(parents=True)
        potions = [f'INSTANCE ITPO_{i:02}(C_Item) {{ name="Potion {i:02}"; mainflag=ITEM_KAT_POTIONS; }};'
                   for i in range(15)]
        weapons = ['INSTANCE SWORD(C_Item) { name="Sword"; mainflag=ITEM_KAT_NF; flags=ITEM_SWD; };',
                   'INSTANCE BOW(C_Item) { name="Bow"; mainflag=ITEM_KAT_FF; flags=ITEM_BOW; };']
        source.write_text('\n'.join(potions + weapons), encoding='utf-8')
        self.source = source
        self.app.repo.set_game_path(str(self.root / 'game'))
        self.app.show_project()
        self.app.update()

    def test_search_limits_results_and_uses_only_selected_category(self):
        dialog = AddItemDialog(self.app, 'potions', self.app.repo.game_items)
        self.addCleanup(lambda: dialog.destroy() if dialog.winfo_exists() else None)
        self.assertEqual(len(dialog.matches), 10)
        dialog.search.set('itpo_14')
        self.assertEqual([item.instance for item in dialog.matches], ['ITPO_14'])
        dialog.search.set('pOtIoN 13')
        self.assertEqual([item.instance for item in dialog.matches], ['ITPO_13'])
        dialog.search.set('Sword')
        self.assertEqual(dialog.matches, [])

    def test_parent_category_includes_descendants_and_dialog_is_centered(self):
        dialog = AddItemDialog(self.app, 'weapons', self.app.repo.game_items)
        self.app.update()
        self.assertEqual({item.instance for item in dialog.matches}, {'BOW', 'SWORD'})
        dialog.name.set('Blocked weapon')
        dialog.projects.selection_set('0')
        dialog.projects.event_generate('<<TreeviewSelect>>')
        self.assertEqual(str(dialog.create_button['state']),'disabled')
        self.assertEqual(str(dialog.copy_button['state']),'disabled')
        dialog.create()
        dialog.copy()
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.grab_current(), dialog)
        x = self.app.winfo_rootx() + (self.app.winfo_width() - dialog.winfo_width()) // 2
        y = self.app.winfo_rooty() + (self.app.winfo_height() - dialog.winfo_height()) // 2
        self.assertAlmostEqual(dialog.winfo_x(), x, delta=3)
        self.assertAlmostEqual(dialog.winfo_y(), y, delta=3)
        dialog.destroy()

    def test_modal_copy_keeps_original_and_adds_only_one_project_item(self):
        before = self.source.read_bytes()
        def choose(dialog):
            dialog.search.set('ITPO_14')
            dialog.projects.selection_set('0')
            dialog.copy()
        with patch.object(self.app, 'wait_window', side_effect=choose):
            self.app.create_item('potions')
        self.assertEqual([item.instance for item in self.app.repo.project_items], ['ITPO_14'])
        self.assertEqual(self.app.current.origin, 'project')
        self.assertEqual(set(self.app.hierarchy.sections), {'project'})
        self.assertEqual(self.app.hierarchy.items, self.app.repo.items)
        self.assertEqual(sum(item.instance=='ITPO_14' for item in self.app.hierarchy.items),1)
        self.assertEqual(self.source.read_bytes(), before)

    def test_modal_creates_named_item_and_cancel_changes_nothing(self):
        def create(dialog):
            dialog.name.set('Named potion')
            dialog.create()
        with patch.object(self.app, 'wait_window', side_effect=create):
            self.app.create_item('potions')
        self.assertEqual(self.app.current.title, 'Named potion')
        self.assertEqual(self.app.current.path.name, 'item.json')
        with patch.object(self.app, 'wait_window', side_effect=lambda dialog: dialog.destroy()):
            self.app.create_item('potions')
        self.assertEqual(len(self.app.repo.project_items), 1)

    def test_other_categories_cannot_be_added_copied_duplicated_or_deleted(self):
        before=self.source.read_bytes()
        for key in ('weapons','onehand','armor','runes','food','rings','documents','ammo','misc'):
            with patch('gothic_editor.app.AddItemDialog') as dialog:
                self.app.create_item(key)
            dialog.assert_not_called()
        sword=next(item for item in self.app.repo.game_items if item.instance=='SWORD')
        # Existing project items stay readable; app commands must not modify them.
        existing=self.app.repo.copy_to_project(sword)
        stored=existing.path.read_bytes()
        with patch.object(self.app.repo,'copy_to_project') as copy, \
                patch.object(self.app.repo,'duplicate') as duplicate, \
                patch.object(self.app.repo,'delete') as delete, \
                patch.object(self.app.repo,'edit') as edit, \
                patch('gothic_editor.app.messagebox.askyesno') as confirm:
            self.app.copy_to_project(sword)
            self.app.duplicate(existing)
            self.app.delete(existing)
            self.app.rename(existing,'Blocked')
            self.app.save_fields(existing,{'name':'"Blocked"'})
        for operation in (copy,duplicate,delete,edit,confirm):operation.assert_not_called()
        self.assertEqual(existing.path.read_bytes(),stored)
        self.assertEqual(self.source.read_bytes(),before)
        with patch('tkinter.Menu.tk_popup'):
            self.app.hierarchy.context(type('Event',(),{'x_root':0,'y_root':0})(),existing)
        menu=self.app.hierarchy._context_menu
        self.assertEqual(menu.entrycget(0,'state'),'disabled')
        self.assertEqual(menu.entrycget(1,'state'),'disabled')
