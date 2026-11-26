import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gothic_editor.core.recipe_categories import RecipeCategories, stock_binding
from gothic_editor.core.recipes import RecipeStore
from test_recipes import recipe


class CategoryActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.categories = RecipeCategories(self.project)
        self.recipes = RecipeStore(self.project)
        self.recipes.save(dict(recipe(), category='health'))

    def test_rename_duplicate_delete_preserve_recipes_and_binding(self):
        self.categories.change('health', {'id':'healing', 'name':'Лечение'})
        self.assertEqual(self.recipes.load()[0]['category'], 'healing')
        self.assertEqual(stock_binding(next(row for row in self.categories.load() if row['id']=='health')), 'health')
        copy = self.categories.duplicate('healing')
        self.assertEqual(copy['id'], 'healing_copy')
        self.assertEqual(copy['name'], 'Лечение')
        self.assertIsNone(stock_binding(copy))
        self.assertEqual(self.categories.duplicate('healing')['id'], 'healing_copy_1')
        self.assertEqual(len(self.recipes.load()), 1)
        self.categories.change('healing', None)
        self.assertEqual(self.recipes.load()[0]['category'], '')
        self.assertEqual(self.recipes.load()[0]['ingredients'], recipe()['ingredients'])
        copy = self.recipes.duplicate(self.recipes.load()[0])
        self.assertEqual(copy['id'], 'TEST_copy')
        self.assertEqual(copy['name'], recipe()['name'])

    def test_conflicting_code_and_publish_failure_keep_original_files(self):
        with self.assertRaises(ValueError):
            self.categories.change('health', {'id':'MANA', 'name':'Ошибка'})
        self.categories.save(self.categories.load())
        files = [self.categories.path, self.recipes.path('TEST')]
        before = {p:p.read_bytes() for p in files}
        original = Path.replace
        def fail_recipe(path, destination):
            if Path(destination)==self.recipes.path('TEST') and path.suffix=='.tmp':
                raise OSError('disk failure')
            return original(path, destination)
        with patch.object(Path, 'replace', fail_recipe):
            with self.assertRaises(OSError):
                self.categories.change('health', {'id':'healing', 'name':'Лечение'})
        for path, data in before.items():self.assertEqual(path.read_bytes(), data)
