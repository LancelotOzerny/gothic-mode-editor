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


if __name__ == '__main__':
    unittest.main()
