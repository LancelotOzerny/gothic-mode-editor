import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from gothic_editor.core.item_options import item_options
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.properties_schema import PropertiesSchema, schema_for
from gothic_editor.core.property_lists import PropertyList, display_value, expression_value


class PropertyListTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = ProjectRepository()
        self.repo.create(self.root/'project', 'Test')
        self.item = self.repo.create_item('potions')
        self.field = next(field for section in schema_for('potions').sections
                          for field in section.fields if field.field_type == 'key_value_list')

    def test_limits_reserved_cost_and_delete_round_trip(self):
        model = PropertyList(self.field, self.item.fields)
        rows = []
        for _ in range(5):
            index = model.available_index(rows)
            rows.append((index, ('"Bonus"', 'BASE + 2')))
        self.assertIsNone(model.available_index(rows))
        item = self.repo.edit(self.item, model.updates(rows))
        self.repo.open(self.repo.root)
        item = self.repo.project_items[0]
        self.assertEqual(item.fields['text[5]'], 'NAME_Value')
        self.assertEqual(item.fields['count[5]'], 'value')
        model = PropertyList(self.field, item.fields)
        item = self.repo.edit(item, model.updates(rows[1:]))
        self.assertNotIn('text[0]', item.fields)
        self.assertNotIn('count[0]', item.fields)
        self.assertEqual(item.fields['count[1]'], 'BASE + 2')
        generated = self.repo.components.generated()[1][0]
        self.assertIn('count[5] = value;', generated)
        self.assertNotIn('inventory_rows', generated)
        with self.assertRaises(ValueError):model.updates(rows + [(5, ('"Conflict"', '1'))])

    def test_sparse_imports_keep_expressions_and_cost_at_original_index(self):
        fields = {'TEXT [1]': 'NAME_Value', 'count[1]': 'PRICE',
                  'text[4]': 'NAME_Bonus', 'count[4]': 'BONUS * 2', 'text[9]': 'CUSTOM'}
        model = PropertyList(self.field, fields)
        self.assertEqual(model.rows, [(4, ('NAME_Bonus', 'BONUS * 2'))])
        self.assertEqual(model.updates(model.rows), {})
        self.assertEqual(model.available_index(model.rows), 0)
        updates = model.updates([])
        self.assertEqual(updates, {'text[4]': '', 'count[4]': ''})

    def test_generic_names_types_and_nonzero_start(self):
        columns = tuple(replace(column, key=key) for column, key in zip(self.field.columns, ('caption', 'amount')))
        field = replace(self.field, max_rows=2, start_index=3, columns=columns, reserved=())
        model = PropertyList(field, {})
        self.assertEqual(model.available_index([]), 3)
        self.assertEqual(model.updates([(3, ('"Hi"', '7'))]), {'caption[3]': '"Hi"', 'amount[3]': '7'})
        self.assertIsNone(model.available_index([(3, ('', '')), (4, ('', ''))]))

    def test_plain_text_count_is_rejected_without_affecting_expressions(self):
        model = PropertyList(self.field, self.item.fields)
        for value in ('2 минуты', '2 minutes', '"2 минуты"', '2; OTHER = 3', '2 /* minutes */ minutes'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, r'count\[1\]'):
                model.updates([(1, ('"Time"', value))])
        for value in ('2', 'BONUS + 2', '(BASE_PRICE * 2) / 3', '0x10', '-2', 'value /* keep */ + 1'):
            with self.subTest(value=value):
                self.assertEqual(model.updates([(1, ('"Time"', value))])['count[1]'], value)

    def test_strings_and_schema_validation(self):
        text = 'Potion "strong" \\ test'
        self.assertEqual(display_value(expression_value(text, 'string'), 'string'), text)
        self.assertEqual(expression_value('BASE + 1', 'expression'), 'BASE + 1')
        data = json.loads(Path('assets/properties/potion.json').read_text('utf-8'))
        data['sections'][-1]['fields'][0]['max_rows'] = -1
        path = self.root/'bad.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'key_value_list'):PropertiesSchema.load(path)

    def test_effect_choices_and_new_properties_round_trip(self):
        source = self.root/'game/_work/Data/Scripts/System/VisualFX/VisualFX.d'
        source.parent.mkdir(parents=True)
        source.write_text('INSTANCE CUSTOM_FX(CFX_BASE) {}; // INSTANCE FAKE(CFX_BASE) {}', encoding='cp1251')
        self.repo.game = self.root/'game'
        self.assertIn(('CUSTOM_FX', '"CUSTOM_FX"'), item_options(self.repo, 'visual_effects'))
        self.assertNotIn(('FAKE', '"FAKE"'), item_options(self.repo, 'visual_effects'))
        self.repo.edit(self.item, {'effect': '"CUSTOM_FX"', 'scemeName': '"CUSTOM_USE"'})
        self.repo.open(self.repo.root)
        item = self.repo.project_items[0]
        self.assertEqual(item.fields['effect'], '"CUSTOM_FX"')
        self.assertEqual(item.fields['scemename'], '"CUSTOM_USE"')
        self.assertNotIn(('CUSTOM_USE', '"CUSTOM_USE"'), item_options(self.repo, 'item_schemes'))
        self.assertNotIn('on_state[0]', item.fields)
