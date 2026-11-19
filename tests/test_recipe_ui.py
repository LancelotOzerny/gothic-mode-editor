import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.settings import SettingsStore
from gothic_editor.core.recipes import RecipeStore


class RecipeUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with patch('gothic_editor.app.SettingsStore', return_value=SettingsStore(self.root/'settings.json')):
            self.app = EditorApp()
        self.app.withdraw()
        self.addCleanup(self.cleanup_app)
        self.app.repo.create(self.root/'project', 'Test')
        self.app.show_project()
        self.app._switch_resource_browser('recipes')

    def cleanup_app(self):
        self.app.recipes.deselect()
        self.app.destroy()

    def fill(self):
        controller = self.app.recipes
        controller.create()
        form = self.app.recipe_properties
        form.fields['result'].insert(0, 'POTION')
        form.add_row({'instance': 'PLANT', 'count': 2})
        self.assertTrue(self.app._save_editors())

    def test_save_reopen_duplicate_delete_and_mode_barriers(self):
        self.fill()
        app = self.app
        first = app.recipes.current['id']
        app.recipes.duplicate()
        self.assertEqual(len(app.recipes.items), 2)
        self.assertNotEqual(app.recipes.current['id'], first)
        with patch('gothic_editor.ui.controllers.recipes.messagebox.askyesno', return_value=True):
            app.recipes.delete()
        self.assertEqual(len(app.recipes.items), 1)
        app.recipes.select(app.recipes.items[0])
        app.recipe_properties.fields['name'].delete(0, 'end')
        app._switch_resource_browser('items')
        self.assertEqual(app._resource_browser, 'recipes')
        self.assertEqual(app.recipe_properties.fields['name'].get(), '')
        self.assertTrue(app.recipe_properties.errors['name'].cget('text'))
        app.recipe_properties.fields['name'].insert(0, 'Changed')
        app._switch_resource_browser('items')
        self.assertEqual(app._resource_browser, 'items')
        app._switch_resource_browser('recipes')
        app.recipes.select(app.recipes.items[0])
        self.assertEqual(app.recipe_properties.fields['name'].get(), 'Changed')
        self.assertIsNone(app.recipes.pending)

    def test_autosave_and_disk_error_keeps_draft(self):
        self.fill()
        app = self.app
        form = app.recipe_properties
        form.fields['name'].delete(0, 'end')
        form.fields['name'].insert(0, 'Autosaved')
        app.after(1150, app.quit)
        app.mainloop()
        self.assertEqual(RecipeStore(app.repo.root).load()[0]['name'], 'Autosaved')
        form.fields['name'].insert('end', ' draft')
        with patch.object(app.recipes.store, 'save', side_effect=OSError('disk error')):
            app._switch_resource_browser('items')
        self.assertEqual(app._resource_browser, 'recipes')
        self.assertEqual(form.fields['name'].get(), 'Autosaved draft')
        self.assertTrue(app._save_editors())

    def test_selecting_current_row_flushes_and_uses_fresh_values(self):
        self.fill()
        app = self.app
        stale_row = app.recipes.items[0]
        app.recipe_properties.fields['name'].delete(0, 'end')
        app.recipe_properties.fields['name'].insert(0, 'Fresh')
        app.recipes.select(stale_row)
        self.assertEqual(app.recipe_properties.fields['name'].get(), 'Fresh')
        self.assertEqual(RecipeStore(app.repo.root).load()[0]['name'], 'Fresh')

    def test_category_settings_and_recipe_assignment(self):
        from gothic_editor.ui.windows.recipe_categories import RecipeCategoriesWindow
        from gothic_editor.core.recipe_categories import RecipeCategories
        self.fill()
        app = self.app
        window = RecipeCategoriesWindow(app, app.repo.root, lambda: None)
        window.add({'id': 'experience', 'name': 'Опыт'})
        window.save()
        self.assertEqual(RecipeCategories(app.repo.root).load()[-1]['id'], 'experience')
        app.recipes.select(app.recipes.current)
        app.recipe_properties.fields['category'].set_expression('experience')
        self.assertTrue(app._save_editors())
        self.assertEqual(RecipeStore(app.repo.root).load()[0]['category'], 'experience')
        window = RecipeCategoriesWindow(app, app.repo.root, lambda: None)
        window.rows.pop()[0].destroy()
        with patch('gothic_editor.ui.windows.recipe_categories.messagebox.showerror') as error:
            window.save()
            error.assert_called_once()
        self.assertEqual(RecipeCategories(app.repo.root).load()[-1]['id'], 'experience')
        window.destroy()

    def test_hierarchy_filters_categories_and_retains_expansion(self):
        self.app.recipes.create('health')
        form = self.app.recipe_properties
        form.fields['result'].insert(0, 'POTION')
        form.add_row({'instance':'HERB', 'count':1})
        self.assertTrue(self.app._save_editors())
        panel = self.app.recipe_list
        self.assertTrue(panel.category_rows['health'].opened)
        panel.search.set('маны')
        self.assertEqual(set(panel.category_rows), {'mana'})
        panel.search.set(self.app.recipes.current['name'])
        self.assertEqual(set(panel.category_rows), {'health'})
        panel.search.set('')
        self.assertTrue(panel.category_rows['health'].opened)
        panel.category_rows['health'].toggle()
        panel.populate()
        self.assertFalse(panel.category_rows['health'].opened)

    def test_modal_add_new_assigns_destination_category(self):
        from types import SimpleNamespace
        dialog = SimpleNamespace(result='new', show_centered=lambda **_:None)
        with patch('gothic_editor.ui.windows.recipe_add.AddRecipeDialog', return_value=dialog), patch.object(self.app,'wait_window'):
            self.app.recipes.add('mana')
        self.assertEqual(self.app.recipes.current['category'], 'mana')
        self.assertFalse(self.app.recipes.persisted)

    def test_ingredients_use_tiles_and_plus_tile_reflows(self):
        self.app.recipes.create('health')
        panel = self.app.recipe_properties
        self.assertEqual(len(panel.rows), 1)
        self.assertEqual(panel.rows[0][0].SIZE, 224)
        panel.add_row({'instance': 'WATER', 'count': 1})
        panel.add_row({'instance': 'HERB', 'count': 2})
        self.app.update_idletasks()
        self.assertEqual(len(panel.rows), 3)
        self.assertTrue(all(row[0].winfo_class() == 'Frame' for row in panel.rows))
        for row in panel.rows:
            self.assertEqual(row[0].winfo_width(), 224)
            self.assertEqual(row[0].winfo_height(), 224)
        panel.remove_ingredient(panel.rows[0])
        self.assertEqual(len(panel.rows), 2)

    def test_item_binding_select_quantity_and_remove(self):
        self.app.recipes.create('health')
        panel = self.app.recipe_properties
        tile, instance, count = panel.rows[-1]
        instance.set('HERB')
        self.assertEqual(len(panel.rows), 2)
        self.assertEqual(panel.rows[-1][1].get(), '')
        self.assertIn('[HERB]', tile.name.cget('text'))
        tile.step(-1)
        self.assertEqual(count.get(), '1')
        tile.step(1)
        self.assertEqual(count.get(), '2')
        with patch('gothic_editor.ui.widgets.item_binding.messagebox.askyesno', return_value=False):
            tile.remove()
        self.assertEqual(len(panel.rows), 2)
        with patch('gothic_editor.ui.widgets.item_binding.messagebox.askyesno', return_value=True):
            tile.remove()
        self.assertEqual(len(panel.rows), 1)

    def test_single_category_dialog_and_context_actions(self):
        from gothic_editor.ui.windows.recipe_categories import RecipeCategoryDialog
        from gothic_editor.core.recipe_categories import RecipeCategories
        from types import SimpleNamespace
        store = RecipeCategories(self.app.repo.root)
        dialog = RecipeCategoryDialog(self.app, store, lambda:None)
        dialog.code.insert(0, 'experience')
        dialog.name.insert(0, 'Опыт')
        dialog.save()
        self.assertEqual(store.load()[-1]['name'], 'Опыт')
        self.app.recipes.load()
        self.app.recipes.create('experience')
        form = self.app.recipe_properties
        form.fields['result'].insert(0,'POTION')
        form.add_row({'instance':'HERB','count':1})
        self.assertTrue(self.app._save_editors())
        panel = self.app.recipe_list
        with patch.object(panel,'popup') as popup:
            panel.category_context(SimpleNamespace(), 'experience')
            commands = popup.call_args.args[1]
            self.assertEqual(len(commands), 4)
            with patch.object(self.app.recipes, 'add') as add:
                commands[-1][1]()
                add.assert_called_once_with('experience')
            commands[1][1]()
        self.assertEqual(store.load()[-1]['id'], 'experience_copy')
        with patch('gothic_editor.ui.controllers.recipes.messagebox.askyesno',return_value=False):
            self.app.recipes.category_action('delete','experience')
        self.assertIn('experience', [r['id'] for r in store.load()])
        with patch('gothic_editor.ui.controllers.recipes.messagebox.askyesno',return_value=True):
            self.app.recipes.category_action('delete','experience')
        self.assertEqual(self.app.recipes.current['category'], '')
        with patch.object(panel,'popup') as popup:
            panel.recipe_context(SimpleNamespace(), self.app.recipes.items[0])
            popup.call_args.args[1][0][1]()
        self.assertTrue(self.app.recipes.current['id'].endswith('_copy'))


if __name__ == '__main__':
    unittest.main()
