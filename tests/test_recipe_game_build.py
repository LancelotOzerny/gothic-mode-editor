"""Opt-in compilation against an installed Gothic; never writes into that game."""
import os
import tempfile
import unittest
from pathlib import Path

from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.recipes import RecipeStore
from gothic_editor.core.scripts import parse_items
from gothic_editor.core.mod_archive import read_mod
from gothic_editor.core.mod_package import DAT_PATH


@unittest.skipUnless(os.environ.get('GOTHIC_TEST_GAME') and os.environ.get('GOTHIC_TEST_COMPILER'),
                     'Set GOTHIC_TEST_GAME and GOTHIC_TEST_COMPILER for a real MOD build')
class RecipeGameBuildTests(unittest.TestCase):
    def test_real_game_always_and_global_variable_mod(self):
        game = Path(os.environ['GOTHIC_TEST_GAME'])
        content = game/'_work/Data/Scripts/Content'
        items = parse_items(content/'Items/IT_Potions.d', 'game')
        plants = parse_items(content/'Items/IT_Plants.d', 'game')
        originals = {p: p.read_bytes() for p in content.rglob('*') if p.is_file()}
        with tempfile.TemporaryDirectory(prefix='recipe-game-test-') as temporary:
            project = Path(temporary)
            (project/'project.json').write_text('{"name":"RecipeTest"}', 'utf-8')
            store = RecipeStore(project)
            from gothic_editor.core.recipe_categories import RecipeCategories
            categories = RecipeCategories(project)
            rows = categories.load()
            rows[0]['name'] = 'Здоровье (тест)'
            categories.save(rows + [{'id': 'experience', 'name': 'Зелья опыта'}])
            for code, availability in [('TEST_ALWAYS', {'type': 'always'}),
                                       ('TEST_KNOWLEDGE', {'type': 'global_variable', 'variable': 'GE_Test_KnowsRecipe'})]:
                store.save(dict(schema_version=1, id=code, category='health' if code=='TEST_ALWAYS' else 'experience', name='Тестовый рецепт', result=items[0].instance,
                                result_count=1, ingredients=[{'instance': plants[0].instance, 'count': 2}],
                                availability=availability))
            tools = ProjectTools(project, game, os.environ['GOTHIC_TEST_COMPILER'])
            try:
                result = tools.compile()
            except Exception as exc:
                self.fail(str(exc) + '\n' + (project/'logs/compile.log').read_text('utf-8')[-6000:])
            packed = read_mod(result.archive)
            self.assertIn(DAT_PATH, packed)
            self.assertFalse(any('recipes/' in name.casefold() for name in packed))
            self.assertGreater(len(packed[DAT_PATH]), 1000)
        for path, before in originals.items():
            self.assertEqual(path.read_bytes(), before, str(path))
