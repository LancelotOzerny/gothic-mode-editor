import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.core.recipes import RecipeStore, validate_recipe, batch_requirements, MAX_INT
from gothic_editor.core.recipe_build import apply_recipes
from gothic_editor.core.build_assets import BuildAssetService


def recipe():
    return dict(schema_version=1, id='TEST', name='Зелье', result='POTION', result_count=1,
                ingredients=[{'instance': 'WATER', 'count': 1}, {'instance': 'FLASK', 'count': 1},
                             {'instance': 'PLANT', 'count': 2}], availability={'type': 'always'})


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.store = RecipeStore(self.project)
        self.content = self.root / 'Content'
        self.content.mkdir()
        self.manifest = self.content / 'Gothic.src'
        self.manifest.write_text('base.d\n', 'utf-8')
        self.base = self.content / 'base.d'
        self.original = '''instance POTION(C_Item) {};
instance WATER(C_Item) {}; instance FLASK(C_Item) {}; instance PLANT(C_Item) {};
func void POTIONALCHEMY_S1() {};
func void PC_PotionAlchemy_End_Info() { CreateInvItems(self, FLASK, 1); B_ENDPRODUCTIONDIALOG(); };
func int PC_PotionAlchemy_End_Condition() { if (PLAYER_MOBSI_PRODUCTION == MOBSI_POTIONALCHEMY) { return TRUE; }; };
func void B_ENDPRODUCTIONDIALOG() {};
'''
        self.base.write_text(self.original, 'utf-8')

    def generate(self):
        result = apply_recipes(self.project, self.content, self.manifest)
        return (self.content / result[0]).read_text('cp1251')

    def test_storage_duplicate_delete_and_atomic_failure(self):
        data = recipe()
        self.store.save(data)
        self.assertEqual(self.store.load(), [data])
        copy = self.store.duplicate(data)
        self.assertNotEqual(copy['id'], data['id'])
        copy['name'] = 'Другое'
        self.store.save(copy, copy['id'])
        self.assertEqual(self.store.load()[0]['name'], 'Зелье')
        before = self.store.path('TEST').read_bytes()
        with patch('gothic_editor.core.recipes.os.fsync', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.store.save(dict(data, name='Новое'), 'TEST')
        self.assertEqual(before, self.store.path('TEST').read_bytes())
        self.store.delete(copy['id'])
        self.assertEqual(len(self.store.load()), 1)

    def test_corrupt_json_blocks_build(self):
        self.store.root.mkdir(parents=True)
        (self.store.root / 'broken.json').write_text('{', 'utf-8')
        with self.assertRaisesRegex(ValueError, 'broken.json'):
            self.generate()

    def test_invalid_fields(self):
        for key, value in [('id', '../escape'), ('id', 'CON'), ('schema_version', True),
                           ('schema_version', 2), ('name', '😀'), ('name', ''),
                           ('result_count', 0), ('result_count', True), ('result_count', MAX_INT+1),
                           ('ingredients', []), ('availability', {'type': 'python'})]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.store.save(dict(recipe(), **{key: value}))
        data = recipe()
        data['ingredients'].append({'instance': 'water', 'count': 1})
        with self.assertRaisesRegex(ValueError, 'объедините'):
            validate_recipe(data)

    def test_case_insensitive_ids_and_paths(self):
        self.store.save(recipe())
        with self.assertRaises(ValueError):
            self.store.save(dict(recipe(), id='test'))
        with self.assertRaises(ValueError):
            self.store.checked(self.root / 'outside.json')
        (self.store.root / 'other.json').write_text(json.dumps(recipe()), 'utf-8')
        with self.assertRaises(ValueError):
            self.store.load()

    def test_batch_and_overflow(self):
        needed, count = batch_requirements(recipe(), 5)
        self.assertEqual(needed, {'WATER': 5, 'FLASK': 5, 'PLANT': 10})
        self.assertEqual(count, 5)
        for portions in (0, -1, True, MAX_INT):
            with self.assertRaises(ValueError):
                batch_requirements(recipe(), portions)

    def test_generation_checks_before_removal_and_keeps_sources(self):
        self.store.save(recipe())
        text = self.generate()
        self.assertLess(text.index('Npc_HasItems(self, PLANT)'), text.index('Npc_RemoveInvItems'))
        self.assertIn('portions > 1073741823', text)
        self.assertIn('GE_Recipe_TEST_Craft(1)', text)
        self.assertIn('PC_PotionAlchemy_End_Condition()', text)
        self.assertEqual(self.base.read_text('utf-8'), self.original)
        self.assertTrue(self.manifest.read_text('utf-8').endswith('GE_Recipes\\Alchemy.d\n'))
        self.assertEqual(BuildAssetService(self.project).collect(), {})

    def test_original_recipe_replaces_existing_gothic_dialog_in_staging(self):
        self.base.write_text(self.original + '''
func int PC_Test_Condition() { return TRUE; };
func void PC_Test_Info() {};
instance PC_Test(C_Info)
{
    condition = PC_Test_Condition;
    information = PC_Test_Info;
    description = "Оригинальное зелье";
};''', 'utf-8')
        original=self.base.read_bytes()
        self.store.save(dict(recipe(), id='PC_TEST', source_info='PC_TEST',
                             name='Изменённый рецепт'))
        code=self.generate()
        self.assertNotIn('instance GE_Recipe_PC_TEST(C_Info)', code)
        self.assertIn('GE_Recipe_PC_TEST_Craft',code)
        staged=self.base.read_text('utf-8')
        self.assertIn('condition = GE_Recipe_PC_TEST_Condition;',staged)
        self.assertIn('information = GE_Recipe_PC_TEST_Info;',staged)
        self.assertIn('description = "Изменённый рецепт";',staged)
        self.assertNotEqual(staged.encode('utf-8'),original)

    def test_global_variable_created_once(self):
        data = recipe()
        data['availability'] = {'type': 'global_variable', 'variable': 'Knows_Test'}
        self.store.save(data)
        self.store.save(dict(data, id='SECOND'))
        text = self.generate()
        self.assertEqual(text.count('var int Knows_Test;'), 1)
        self.assertIn('(Knows_Test != 0)', text)

    def test_stock_knowledge_uses_existing_gothic_talent(self):
        self.base.write_text(self.original +
            '\nconst int POTION_Health_01 = 1;'
            '\nvar int PLAYER_TALENT_ALCHEMY[100];'
            '\nfunc int PC_Health_Stop_Condition() { return TRUE; };', 'utf-8')
        data = dict(recipe(), category='health',
                    availability={'type': 'stock_talent',
                                  'talent': 'POTION_Health_01'})
        self.store.save(data)
        text = self.generate()
        self.assertIn('PLAYER_TALENT_ALCHEMY[POTION_Health_01] == TRUE', text)
        self.assertIn('PC_Health_Stop_Condition()', text)
        self.assertNotIn('var int POTION_Health_01', text)

    def test_stock_knowledge_requires_an_existing_gothic_talent(self):
        data = dict(recipe(), availability={'type': 'stock_talent',
                                            'talent': 'MISSING_TALENT'})
        self.store.save(data)
        with self.assertRaisesRegex(ValueError, 'MISSING_TALENT'):
            self.generate()

    def test_existing_variable_not_redeclared(self):
        self.base.write_text(self.original + '\nvar int Knows_Test;', 'utf-8')
        data = recipe()
        data['availability'] = {'type': 'global_variable', 'variable': 'knows_test'}
        self.store.save(data)
        self.assertNotIn('var int knows_test', self.generate())

    def test_missing_ingredients_each_guard_returns_before_all_mutations(self):
        self.store.save(recipe())
        text = self.generate()
        craft = text.split('func int GE_Recipe_TEST_Craft', 1)[1].split('func int GE_Recipe_TEST_Condition', 1)[0]
        guards, mutations = craft.split('Npc_RemoveInvItems', 1)
        for instance, count in [('WATER', 1), ('FLASK', 1), ('PLANT', 2)]:
            self.assertIn(f'if (Npc_HasItems(self, {instance}) < ({count} * portions)) {{ return FALSE; }};', guards)
        self.assertNotIn('CreateInvItems', guards)
        self.assertIn('CreateInvItems(self, POTION, 1 * portions)', mutations)

    def test_item_not_in_manifest_is_rejected(self):
        self.store.save(dict(recipe(), result='UNINCLUDED'))
        (self.content/'unused.d').write_text('instance UNINCLUDED(C_Item) {};', 'utf-8')
        with self.assertRaisesRegex(ValueError, 'UNINCLUDED'):
            self.generate()

    def test_type_item_and_generated_conflicts(self):
        for extra, field in [('var string Knows_Test;', 'variable'),
                             ('const int Knows_Test=1;', 'variable'),
                             ('var int Knows_Test[2];', 'variable'),
                             ('var int GE_Recipe_TEST_Craft;', 'generated'),
                             ('', 'missing')]:
            with self.subTest(field=field):
                data = recipe()
                if field == 'variable':
                    data['availability'] = {'type': 'global_variable', 'variable': 'Knows_Test'}
                if field == 'missing':
                    data['result'] = 'MISSING'
                self.base.write_text(self.original + extra, 'utf-8')
                self.store.save(data, 'TEST' if self.store.path('TEST').exists() else None)
                with self.assertRaises(ValueError):
                    self.generate()

    def test_no_recipes_does_not_require_game_hooks(self):
        self.base.write_text('const int TEST=1;', 'utf-8')
        self.assertEqual(apply_recipes(self.project, self.content, self.manifest), [])

    def test_nested_categories_under_stock_special_menu(self):
        from gothic_editor.core.recipe_categories import RecipeCategories
        categories = RecipeCategories(self.project)
        categories.save(categories.load() + [
            {'id': 'experience', 'name': 'Зелья опыта', 'parent': 'special'},
            {'id': 'advanced_exp', 'name': 'Усиленные', 'parent': 'experience'},
        ])
        self.store.save(dict(recipe(), id='EXP_1', name='Эссенция опыта',
                             category='experience'))
        self.store.save(dict(recipe(), id='EXP_2', name='Эликсир опыта',
                             category='advanced_exp'))
        self.base.write_text(self.original +
            'func int PC_Special_Stop_Condition() { return TRUE; };',
            'utf-8')
        text = self.generate()
        self.assertIn('func int GE_RecipeCategory_experience_Condition()', text)
        self.assertIn('PC_Special_Stop_Condition()', text)
        self.assertIn('description = "Зелья опыта"', text)
        self.assertIn('Info_AddChoice(GE_RecipeCategory_experience, "Усиленные", '
                      'GE_RecipeCategory_advanced_exp_Info)', text)
        self.assertIn('Info_AddChoice(GE_RecipeCategory_experience, "Эссенция опыта", '
                      'GE_Recipe_EXP_1_Info)', text)
        self.assertIn('Info_AddChoice(GE_RecipeCategory_experience, "Эликсир опыта", '
                      'GE_Recipe_EXP_2_Info)', text)
        self.assertIn('GE_RecipeCategory_experience_Info();', text)
        self.assertNotIn('instance GE_RecipeCategory_advanced_exp(C_Info)', text)
        self.assertIn('Info_ClearChoices(GE_RecipeCategory_experience)', text)

    def test_category_tree_prevents_cycles_and_missing_parents(self):
        from gothic_editor.core.recipe_categories import RecipeCategories
        categories = RecipeCategories(self.project)
        initial = categories.load()
        with self.assertRaisesRegex(ValueError, 'родительская категория'):
            categories.save(initial + [{'id': 'nested', 'name': 'Вложенная', 'parent': 'unknown'}])
        with self.assertRaisesRegex(ValueError, 'цикл'):
            categories.save(initial + [
                {'id': 'first', 'name': 'Первая', 'parent': 'second'},
                {'id': 'second', 'name': 'Вторая', 'parent': 'first'},
            ])
        with self.assertRaisesRegex(ValueError, 'Штатная категория'):
            categories.save([dict(initial[0], parent='special')] + initial[1:])
        self.assertEqual(categories.load(), initial)

    def test_category_change_preserves_nested_links(self):
        from gothic_editor.core.recipe_categories import RecipeCategories
        categories = RecipeCategories(self.project)
        categories.change(None, {'id': 'experience', 'name': 'Зелья опыта', 'parent': 'special'})
        categories.change(None, {'id': 'advanced', 'name': 'Усиленные', 'parent': 'experience'})
        data = dict(recipe(), category='advanced')
        self.store.save(data)
        categories.change('experience', {'id': 'experience_2', 'name': 'Опыт',
                                         'parent': 'special'})
        self.assertEqual(next(row for row in categories.load() if row['id'] == 'advanced')['parent'],
                         'experience_2')
        categories.change('advanced', None)
        self.assertEqual(self.store.load()[0]['category'], 'experience_2')

    def test_custom_category_choices_and_unknown_category(self):
        from gothic_editor.core.recipe_categories import RecipeCategories
        categories = RecipeCategories(self.project)
        rows = categories.load()
        categories.save(rows + [{'id': 'experience', 'name': 'Опыт'}])
        self.store.save(dict(recipe(), category='experience'))
        text = self.generate()
        self.assertIn('Info_AddChoice(GE_RecipeCategory_experience, "Зелье", GE_Recipe_TEST_Info)', text)
        self.assertIn('Info_AddChoice(GE_RecipeCategory_experience, DIALOG_BACK', text)
        self.assertIn('Info_ClearChoices(GE_RecipeCategory_experience)', text)
        with self.assertRaises(ValueError):self.store.save(dict(recipe(), category='missing'), 'TEST')
        with self.assertRaises(ValueError):categories.save(rows + [{'id': 'HEALTH', 'name': 'Дубль'}])
        categories.save([row for row in rows if row['id'] != 'health'])
        self.assertNotIn('health', [r['id'] for r in categories.load()])


if __name__ == '__main__':
    unittest.main()
