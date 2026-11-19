import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.item_hierarchy import ItemHierarchy


class HierarchyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = ProjectRepository()
        self.repo.create(Path(self.temp.name)/'project with spaces','Test')
        self.store = self.repo.item_hierarchy

    def test_nested_membership_rename_duplicate_delete_reopen(self):
        item = self.repo.create_item('potions')
        original = item.path.read_bytes()
        group = self.store.create_group('potions')
        child = self.store.create_group(group)
        self.store.rename(child,'Protection')
        self.store.assign(item,child)
        self.store.rename('potions','Custom potions','CUSTOM')
        self.assertEqual(self.store.location(item),child)
        self.assertEqual(self.store.row('potions')['source'],'potions')
        copy = self.store.duplicate(group)
        self.assertEqual(self.store.row(copy[child])['parent'],copy[group])
        self.assertNotIn('code',self.store.row(child))
        self.assertEqual(item.path.read_bytes(),original)
        reopened = ItemHierarchy(self.repo.root)
        self.assertEqual(reopened.location(item),child)
        self.store.delete(group)
        self.assertEqual(self.store.location(item),'potions')
        self.store.delete('potions')
        self.assertEqual(self.store.location(item),'')
        self.assertEqual(item.path.read_bytes(),original)

    def test_item_id_and_copy_keep_group(self):
        item = self.repo.create_item('potions')
        group = self.store.create_group('potions')
        self.store.assign(item,group)
        renamed = self.repo.edit(item,{},instance='ITPO_RENAMED')
        self.assertEqual(self.store.location(renamed),group)
        copy = self.repo.duplicate(renamed)
        self.assertEqual(self.store.location(copy),group)
        self.repo.delete(copy)
        self.assertNotIn(copy.instance.casefold(),self.store.data['items'])

    def test_validation_and_atomic_failure(self):
        group = self.store.create_group('potions')
        before = deepcopy(self.store.data)
        with self.assertRaises(ValueError):self.store.rename('potions','Name','ARMOR')
        with self.assertRaises(ValueError):self.store.rename(group,' ')
        sword = self.repo.create_item('onehand')
        with self.assertRaises(ValueError):self.store.assign(sword,group)
        invalid = deepcopy(before)
        invalid['nodes'][-1]['parent'] = group
        with self.assertRaises(ValueError):self.store.commit(invalid)
        with patch.object(Path,'replace',side_effect=OSError('Disk')):
            with self.assertRaises(OSError):self.store.rename(group,'Changed')
        self.assertEqual(self.store.data,before)
        self.assertEqual(ItemHierarchy(self.repo.root).data,before)


class HierarchyUiTests(unittest.TestCase):
    def test_actions_inspector_and_recipe_compatibility(self):
        from gothic_editor.app import EditorApp
        from gothic_editor.core.settings import SettingsStore
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(root/'settings.json')):
                app = EditorApp()
            try:
                app.repo.create(root/'project','Test')
                app.show_project()
                controller = app.item_hierarchy_controller
                node = app.repo.item_hierarchy.tree()[0]
                controller.action('create',node)
                group = app.properties.node
                app.properties.node_name.delete(0,'end')
                app.properties.node_name.insert(0,'Protection')
                self.assertTrue(app._save_editors())
                self.assertEqual(app.repo.item_hierarchy.row(group.key)['name'],'Protection')
                row = app.hierarchy.sections['project'].category_rows[group.key]
                def check_icon(color):
                    from gothic_editor.ui.widgets import ACCENT
                    icon = app.hierarchy.icons.frames('editor/union.png', 18, ACCENT, color)[0]
                    self.assertEqual(str(row.icon_label.cget('image')), str(icon))
                    self.assertEqual(icon.width(), 18)

                check_icon('#3a4d66')
                category_row = app.hierarchy.sections['project'].category_rows['potions']
                self.assertFalse(category_row.icon_label.cget('image'))
                app.hierarchy.selected_node = None
                row.refresh_selection()
                row.header.set_hover(True)
                check_icon('#26364a')
                row.header.set_hover(False)
                check_icon(row.cget('bg'))
                self.assertFalse(any(widget.cget('text')=='+' for widget in row.header.winfo_children()
                                     if 'text' in widget.keys()))
                app.properties.node_name.delete(0,'end')
                app.properties.node_name.insert(0,'Protection updated')
                row.select_node()  # Saving the previous draft can rebuild this very row.
                self.assertEqual(app.repo.item_hierarchy.row(group.key)['name'],'Protection updated')
                item = app.repo.create_item('potions')
                controller.move(item,group.key)
                self.assertEqual(app.repo.item_hierarchy.location(item),group.key)
                with patch('tkinter.Menu.tk_popup'):
                    app.hierarchy.context_node(SimpleNamespace(x_root=0,y_root=0),group)
                self.assertEqual(app.hierarchy._context_menu.index('end'),5)
                controller.action('duplicate',group)
                with patch('tkinter.messagebox.askyesno',return_value=False):
                    controller.action('delete',group)
                self.assertTrue(app.repo.item_hierarchy.row(group.key))
                app._switch_resource_browser('recipes')
                app.update()
            finally:app.destroy()

if __name__ == '__main__':unittest.main()
