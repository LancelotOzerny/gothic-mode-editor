"""Selection, shared actions and category-safe batch moves."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from gothic_editor.app import EditorApp
from gothic_editor.core.settings import SettingsStore
from gothic_editor.core.item_hierarchy import ItemHierarchy


class MultipleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(self.root/'settings.json')):
            self.app = EditorApp()
        self.addCleanup(self.app.destroy)
        self.app.repo.create(self.root/'project','Test')
        self.first = self.app.repo.create_item('potions','First')
        self.second = self.app.repo.create_item('potions','Second')
        self.sword = self.app.repo.create_item('onehand','Sword')
        self.store = self.app.repo.item_hierarchy
        self.group = self.store.create_group('potions')
        self.child = self.store.create_group(self.group)
        self.app.show_project()
        self.panel = self.app.hierarchy
        self.controller = self.app.item_hierarchy_controller

    def select_pair(self):
        self.panel.select(self.first)
        self.panel.toggle_selection(self.second)

    def test_shift_toggle_inspector_and_context(self):
        self.select_pair()
        self.assertEqual(len(self.panel.selection_keys()),2)
        self.assertIsNone(self.app.properties.current)
        self.assertEqual(self.app.properties.info.cget('text'),'')
        with patch('tkinter.Menu.tk_popup'):
            self.panel.context(SimpleNamespace(x_root=0,y_root=0),self.first)
        self.assertEqual(len(self.panel.selection_keys()),2)
        menu = self.panel._context_menu
        labels = [menu.entrycget(index,'label') for index in range(menu.index('end')+1)]
        self.assertEqual(len(labels),3)  # duplicate, delete, move; no rename/export
        self.panel.toggle_selection(self.second)
        self.assertEqual(self.panel.selection_keys(),{self.panel.item_key(self.first)})
        self.assertEqual(self.app.properties.current.instance,self.first.instance)
        self.panel.toggle_selection(self.first)
        self.assertFalse(self.panel.selection_keys())
        self.assertIsNone(self.app.properties.current)

    def test_mixed_nodes_common_actions_and_ancestor_dedup(self):
        self.controller.refresh(self.group)
        node = self.app.properties.node
        child = next(n for n in self.panel.categories()[0].children[0].children if n.key==self.child)
        self.panel.toggle_selection(child)
        self.assertEqual(self.panel.common_actions(),{'duplicate','delete'})
        before = len(self.store.data['nodes'])
        self.controller.batch('duplicate',self.panel.selected_values())
        self.assertEqual(len(self.store.data['nodes']),before+2)
        self.panel.select(self.first)
        self.panel.toggle_selection(node)
        self.assertEqual(self.panel.common_actions(),{'duplicate','delete'})

    def test_atomic_move_reopen_and_wrong_category(self):
        self.select_pair()
        self.controller.batch('move',self.panel.selected_values(),self.child)
        self.assertEqual(len(self.panel.selection_keys()),2)
        self.assertEqual(ItemHierarchy(self.app.repo.root).location(self.first),self.child)
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):self.store.assign_many([self.first,self.sword],self.group)
        self.assertEqual(self.store.path.read_bytes(),before)
        with patch.object(Path,'replace',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.store.assign_many([self.first,self.second],'')
        self.assertEqual(self.store.location(self.first),self.child)
        self.controller.batch('move',self.panel.selected_values(),'')
        self.assertEqual(self.store.location(self.first),'potions')
        self.assertEqual(self.store.location(self.second),'potions')

    def test_duplicate_delete_once_and_cancel(self):
        self.select_pair()
        values = self.panel.selected_values()
        self.controller.batch('duplicate',values)
        self.assertEqual(len(self.app.repo.project_items),5)
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm:
            self.controller.batch('delete',values)
            confirm.assert_called_once()
        self.assertEqual(len(self.app.repo.project_items),5)
        with patch('tkinter.messagebox.askyesno',return_value=True) as confirm:
            self.controller.batch('delete',values)
            confirm.assert_called_once()
        self.assertEqual(len(self.app.repo.project_items),3)

    def test_failed_save_blocks_selection(self):
        self.panel.select(self.first)
        before = self.panel.selection_keys()
        with patch.object(self.app,'_save_editors',return_value=False):
            # Callback is a bound method, so patch the panel's barrier as well.
            with patch.object(self.panel,'before_select',return_value=False):
                self.panel.toggle_selection(self.second)
                self.panel.select(self.second)
        self.assertEqual(self.panel.selection_keys(),before)

    def test_drag_multiple_and_single_to_root(self):
        self.select_pair()
        self.panel.expanded[('project','potions')] = True
        self.panel.rebuild()
        row = self.panel.sections['project'].category_rows[self.group]
        press = SimpleNamespace(state=0,x_root=10,y_root=10)
        release = SimpleNamespace(x_root=30,y_root=30)
        self.panel.press_item(press,self.first)
        self.panel.drag_motion(release)
        with patch.object(self.panel,'winfo_containing',return_value=row.title_label):
            self.panel.release_item(release)
        self.assertEqual(self.store.location(self.first),self.group)
        self.assertEqual(self.store.location(self.second),self.group)
        self.panel.select(self.first)
        self.panel.press_item(press,self.first)
        self.panel.drag_motion(release)
        with patch.object(self.panel,'winfo_containing',return_value=self.panel.sections['project'].canvas):
            self.panel.release_item(release)
        self.assertEqual(self.store.location(self.first),'potions')
        self.assertEqual(self.store.location(self.second),self.group)

    def test_shift_press_and_keyboard_use_whole_selection(self):
        self.panel.select(self.first)
        self.panel.press_item(SimpleNamespace(state=1,x_root=0,y_root=0),self.second)
        self.assertEqual(len(self.panel.selection_keys()),2)
        with patch.object(self.panel,'focus_get',return_value=self.panel), patch.object(self.panel,'on_batch') as batch:
            self.panel.shortcut(SimpleNamespace(keysym='d',keycode=68))
            self.assertEqual(batch.call_args.args[0],'duplicate')
            self.assertEqual(len(batch.call_args.args[1]),2)
            self.panel.shortcut(SimpleNamespace(keysym='Delete',keycode=46))
            self.assertEqual(batch.call_args.args[0],'delete')
        with patch('tkinter.Menu.tk_popup'):
            self.panel.context(SimpleNamespace(x_root=0,y_root=0),self.sword)
        self.assertEqual(self.panel.selection_keys(),{self.panel.item_key(self.sword)})
        self.assertEqual(self.app.current.instance,self.sword.instance)

    def test_drag_preview_target_feedback_and_cancel(self):
        self.select_pair()
        self.panel.expanded[('project','potions')] = True
        self.panel.rebuild()
        row = self.panel.sections['project'].category_rows[self.group]
        event = SimpleNamespace(state=0,x_root=10,y_root=10)
        motion = SimpleNamespace(x_root=40,y_root=40)
        self.panel.press_item(event,self.first)
        with patch.object(self.panel,'winfo_containing',return_value=row.title_label):
            self.panel.drag_motion(motion)
        self.assertIsNotNone(self.panel.drag_preview)
        self.assertEqual(self.panel.drop_target,(self.group,True))
        self.assertEqual(row.header.cget('bg'),'#315b50')
        self.assertIn(self.store.row(self.group)['name'],self.panel.drag_preview.status.cget('text'))
        armor = self.panel.sections['project'].category_rows['armor']
        with patch.object(self.panel,'winfo_containing',return_value=armor.title_label):
            self.panel.drag_motion(motion)
        self.assertEqual(self.panel.drop_target,('armor',False))
        self.assertEqual(armor.header.cget('bg'),'#683f48')
        self.assertNotEqual(row.header.cget('bg'),'#315b50')
        popup = self.panel.drag_preview
        self.panel.cancel_drag(SimpleNamespace())
        self.assertIsNone(self.panel.drag_preview)
        self.assertFalse(popup.winfo_exists())
        self.assertIsNone(self.panel.drop_target)
        self.assertEqual(armor.header.cget('bg'),armor.cget('bg'))
        self.assertEqual(self.store.location(self.first),'potions')

    def test_group_drag_keeps_subtree_and_membership(self):
        target = self.store.create_group('potions')
        self.store.assign(self.first,self.child)
        self.controller.refresh(self.group)
        node = self.app.properties.node
        self.panel.expanded[('project','potions')] = True
        self.panel.rebuild()
        row = self.panel.sections['project'].category_rows[target]
        self.panel.press_node(SimpleNamespace(state=0,x_root=10,y_root=10),node)
        with patch.object(self.panel,'winfo_containing',return_value=row.title_label):
            self.panel.drag_motion(SimpleNamespace(x_root=40,y_root=40))
            self.assertEqual(self.panel.drop_target,(target,True))
            self.panel.release_item(SimpleNamespace(x_root=40,y_root=40))
        self.assertEqual(self.store.row(self.group)['parent'],target)
        self.assertEqual(self.store.row(self.child)['parent'],self.group)
        self.assertEqual(self.store.location(self.first),self.child)
        self.assertIsNone(self.panel.drag_preview)
        self.assertEqual(ItemHierarchy(self.app.repo.root).row(self.group)['parent'],target)

    def test_group_cycles_categories_and_atomic_failure(self):
        from gothic_editor.core.categories import walk_categories
        nodes = {node.key:node for node in walk_categories(self.store.tree())}
        group,child = nodes[self.group],nodes[self.child]
        before = self.store.path.read_bytes()
        for destination in (self.group,self.child,'onehand'):
            self.assertFalse(self.store.can_move([group],destination))
            with self.assertRaises(ValueError):self.store.move_many([group],destination)
        self.assertFalse(self.store.can_move([nodes['potions']],self.group))
        self.assertEqual(self.store.path.read_bytes(),before)
        target = self.store.create_group('potions')
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):self.store.move_many([group,self.sword],target)
        self.assertEqual(self.store.path.read_bytes(),before)
        with patch.object(Path,'replace',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.store.move_many([group],target)
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertEqual(self.store.row(self.group)['parent'],'potions')
        self.store.assign(self.first,self.child)
        self.store.move_many([group,child,self.first,self.second],target)
        self.assertEqual(self.store.row(self.group)['parent'],target)
        self.assertEqual(self.store.row(self.child)['parent'],self.group)
        self.assertEqual(self.store.location(self.first),self.child)
        self.assertEqual(self.store.location(self.second),target)

    def test_multiple_groups_drag_and_outside_drop(self):
        from gothic_editor.core.categories import walk_categories
        other = self.store.create_group('potions')
        target = self.store.create_group('potions')
        self.controller.refresh(self.group)
        node = self.app.properties.node
        other_node = next(value for value in walk_categories(self.store.tree()) if value.key==other)
        self.panel.toggle_selection(other_node)
        self.panel.press_node(SimpleNamespace(state=0,x_root=10,y_root=10),node)
        row = self.panel.sections['project'].category_rows[target]
        with patch.object(self.panel,'winfo_containing',return_value=row.title_label):
            self.panel.drag_motion(SimpleNamespace(x_root=40,y_root=40))
            self.panel.release_item(SimpleNamespace(x_root=40,y_root=40))
        self.assertEqual(self.store.row(self.group)['parent'],target)
        self.assertEqual(self.store.row(other)['parent'],target)
        self.assertEqual(len(self.panel.selection_keys()),2)
        self.panel.press_node(SimpleNamespace(state=0,x_root=10,y_root=10),node)
        with patch.object(self.panel,'winfo_containing',return_value=None):
            self.panel.drag_motion(SimpleNamespace(x_root=40,y_root=40))
            self.panel.release_item(SimpleNamespace(x_root=40,y_root=40))
        self.assertIsNone(self.panel.drag_preview)
        self.assertEqual(self.store.row(self.group)['parent'],target)

    def test_originals_cannot_be_deleted_in_mixed_selection(self):
        from dataclasses import replace
        original = replace(self.second,origin='game')
        self.panel.items.append(original)
        self.panel.select(self.first)
        self.panel.toggle_selection(original)
        self.assertEqual(self.panel.common_actions(),{'move'})

if __name__=='__main__':unittest.main()
