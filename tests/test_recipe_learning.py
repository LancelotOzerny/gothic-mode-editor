"""Learning a potion recipe via a parameterized Daedalus action."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gothic_editor.core.item_actions import ActionCatalog, read_functions
from gothic_editor.core.recipe_learning import (
    ACTION_ID, OUTPUT, prepare_recipe_learning, prioritize_learning,
    recipe_code, recipe_options,
)
from gothic_editor.core.recipes import RecipeStore


def recipe(code, variable):
    return {
        'schema_version': 1,
        'id': code,
        'name': 'Зелье ' + code,
        'result': 'POTION',
        'result_count': 1,
        'ingredients': [{'instance': 'HERB', 'count': 1}],
        'availability': {'type': 'global_variable', 'variable': variable},
    }


class RecipeLearningTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / 'project'
        self.content = Path(temporary.name) / 'Content'
        self.content.mkdir()
        self.store = RecipeStore(self.project)
        self.store.save(recipe('HEALTH', 'Knows_Health'))
        self.store.save(recipe('MANA', 'Knows_Mana'))

    def test_stable_ids_and_parameter_choices(self):
        self.assertEqual(recipe_code('HEALTH'), recipe_code('health'))
        self.assertEqual(len({value for _, value in recipe_options(self.project)}), 2)
        catalog = ActionCatalog(self.project)
        self.assertEqual(catalog.groups()[0][0], 'Алхимия')
        function = catalog.resolve(ACTION_ID)
        self.assertEqual(function.parameters[0].kind, 'int')
        self.assertEqual(len(function.parameters[0].options), 2)

    def test_generated_script_sets_only_selected_recipe(self):
        target = prepare_recipe_learning(self.project, self.content)
        self.assertEqual(target, OUTPUT)
        script = (self.content / target).read_text('cp1251')
        self.assertIn('func void GE_LearnRecipe(var int recipe)', script)
        self.assertIn('const int GE_RECIPE_HEALTH = ', script)
        self.assertIn('const int GE_RECIPE_MANA = ', script)
        self.assertIn('Knows_Health = TRUE;', script)
        self.assertIn('Knows_Mana = TRUE;', script)
        self.assertEqual(script.count('var int Knows_Health;'), 1)
        function = next(item for item in read_functions(self.content / target, 'generated')
                        if item.name == 'GE_LearnRecipe')
        self.assertEqual((function.parameters[0].name, function.parameters[0].kind),
                         ('recipe', 'int'))

    def test_existing_knowledge_variable_is_reused(self):
        (self.content / 'base.d').write_text('var int Knows_Health;', 'cp1251')
        prepare_recipe_learning(self.project, self.content)
        script = (self.content / OUTPUT).read_text('cp1251')
        self.assertNotIn('var int Knows_Health;', script)

    def test_manifest_places_learning_before_action_wrappers(self):
        manifest = self.content / 'Gothic.src'
        manifest.write_text('Items\\GE_ComponentPotions.d\nGE_Recipes\\Learning.d\n', 'cp1251')
        prioritize_learning(manifest)
        lines = manifest.read_text('cp1251').splitlines()
        self.assertEqual(lines[0], 'GE_Recipes\\Learning.d')

    def test_no_learnable_recipes_no_generated_script(self):
        only = recipe('HEALTH', 'Knows_Health')
        only['availability'] = {'type': 'always'}
        self.store.save(only, 'HEALTH')
        other = recipe('MANA', 'Knows_Mana')
        other['availability'] = {'type': 'always'}
        self.store.save(other, 'MANA')
        self.assertIsNone(prepare_recipe_learning(self.project, self.content))


if __name__ == '__main__':
    unittest.main()
