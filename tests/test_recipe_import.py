"""Batch Gothic recipe import respects stock categories and nested destinations."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.core.recipe_categories import RecipeCategories
from gothic_editor.core.recipe_import import import_category_recipes
from gothic_editor.core.recipes import RecipeStore
from gothic_editor.core.edit_history import EditHistory


def template(code, category):
    return {
        'schema_version': 1, 'id': f'COPY_{code}', 'name': code,
        'category': category, 'result': 'POTION', 'result_count': 1,
        'ingredients': [{'instance': 'WATER', 'count': 1}],
        'availability': {'type': 'always'},
    }


class RecipeImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'Assets/Recipes/Alchemy').mkdir(parents=True)
        self.categories = RecipeCategories(self.root)
        self.categories.save(self.categories.load() + [
            {'id': 'experience', 'name': 'Зелья опыта', 'parent': 'special'},
            {'id': 'more_experience', 'name': 'Усиленные', 'parent': 'experience'},
            {'id': 'custom_root', 'name': 'Без привязки'},
        ])
        self.store = RecipeStore(self.root)
        self.templates = [
            template('HEALTH', 'health'),
            template('SPECIAL_1', 'special'),
            template('SPECIAL_2', 'special'),
            template('MANA', 'mana'),
        ]
        self.patch = patch('gothic_editor.core.recipe_import.game_recipes',
                           return_value=(self.templates, ['unrecognized']))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_potions_root_imports_every_stock_category(self):
        imported, existing, unsupported = import_category_recipes(self.root, None, 'potions')
        self.assertEqual((imported, existing, unsupported), (4, 0, 1))
        self.assertEqual({row['category'] for row in self.store.load()},
                         {'health', 'special', 'mana'})
        self.assertEqual(self.categories.load()[0]['id'], 'potions')
        self.assertEqual(next(row for row in self.categories.load() if row['id']=='health')['parent'],
                         'potions')

    def test_only_matching_stock_category_is_imported(self):
        imported, existing, unsupported = import_category_recipes(
            self.root, None, 'health')
        self.assertEqual((imported, existing, unsupported), (1, 0, 1))
        self.assertEqual([(row['id'], row['category']) for row in self.store.load()],
                         [('COPY_HEALTH', 'health')])

    def test_nested_category_uses_stock_parent(self):
        imported, existing, _ = import_category_recipes(
            self.root, None, 'more_experience')
        self.assertEqual((imported, existing), (2, 0))
        self.assertEqual({row['category'] for row in self.store.load()},
                         {'more_experience'})

    def test_repeat_import_skips_existing_and_preserves_user_edits(self):
        imported, _, _ = import_category_recipes(self.root, None, 'experience')
        self.assertEqual(imported, 2)
        recipe = next(row for row in self.store.load()
                      if row['id'] == 'COPY_SPECIAL_1')
        recipe['name'] = 'Моё изменённое имя'
        self.store.save(recipe, recipe['id'])
        imported, existing, _ = import_category_recipes(
            self.root, None, 'experience')
        self.assertEqual((imported, existing), (0, 2))
        self.assertEqual(next(row['name'] for row in self.store.load()
                              if row['id'] == 'COPY_SPECIAL_1'),
                         'Моё изменённое имя')

    def test_reimport_restores_stock_knowledge_without_touching_ingredients(self):
        self.store.save(template('HEALTH', 'health'))
        original = self.store.load()[0]
        original['name'] = 'Мой рецепт'
        original['ingredients'] = [{'instance': 'CUSTOM_WATER', 'count': 3}]
        self.store.save(original, original['id'])
        updated = template('HEALTH', 'health')
        updated['availability'] = {'type': 'stock_talent',
                                   'talent': 'POTION_Health_01'}
        self.templates[0] = updated
        imported, existing, _ = import_category_recipes(
            self.root, None, 'health')
        self.assertEqual((imported, existing), (0, 1))
        saved = self.store.load()[0]
        self.assertEqual(saved['name'], 'Мой рецепт')
        self.assertEqual(saved['ingredients'], original['ingredients'])
        self.assertEqual(saved['availability'], updated['availability'])

    def test_custom_root_without_gothic_binding_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'нет исходного раздела Gothic'):
            import_category_recipes(self.root, None, 'custom_root')

    def test_import_is_one_undo_action(self):
        history = EditHistory()
        history.reset(self.root)
        imported, _, _ = import_category_recipes(
            self.root, None, 'special', history=history)
        self.assertEqual(imported, 2)
        self.assertEqual(len(history.undo_stack), 1)
        self.assertTrue(history.apply())
        self.assertEqual(self.store.load(), [])


if __name__ == '__main__':
    unittest.main()
