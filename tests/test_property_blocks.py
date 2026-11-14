"""Composed schemas and editable scrolls share the existing form and script paths."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from time import monotonic
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.categories import EDITABLE_CATEGORIES, classify
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.properties_schema import PropertiesSchema, schema_for
from gothic_editor.core.scripts import parse_items
from gothic_editor.core.settings import SettingsStore
from gothic_editor.core.model_export import geometry_3ds


ASSETS = Path(__file__).resolve().parents[1] / 'assets/properties'


class PropertyBlocksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_categories_contain_only_block_references_and_share_sections(self):
        self.assertTrue({'potions', 'scrolls', 'runes'} <= EDITABLE_CATEGORIES)
        for category in ('potions', 'scrolls'):
            data = json.loads((ASSETS / 'categories' / (category + '.json')).read_text('utf-8'))
            self.assertEqual(set(data), {'blocks'})
            self.assertTrue(all((ASSETS / 'blocks' / name).is_file() for name in data['blocks']))
        potions, scrolls = schema_for('potions'), schema_for('scrolls')
        self.assertEqual([s.key for s in scrolls.sections], ['general', 'parameters', 'actions', 'appearance', 'inventory'])
        self.assertIn('actions', [s.key for s in potions.sections])
        self.assertEqual(next(s for s in potions.sections if s.key == 'appearance'),
                         next(s for s in scrolls.sections if s.key == 'appearance'))
        self.assertEqual(potions.generated_defaults['material'], 'MAT_GLAS')
        self.assertNotIn('material', scrolls.generated_defaults)
        self.assertNotIn('scemeName', scrolls.generated_defaults)

    def test_shared_block_change_reaches_both_categories_and_profiles_remain_independent(self):
        shutil.copytree(ASSETS, self.root / 'properties')
        main = self.root / 'properties/blocks/general/main.json'
        data = json.loads(main.read_text('utf-8'))
        data['sections'][0]['fields'][1]['label'] = 'Shared caption'
        main.write_text(json.dumps(data), encoding='utf-8')
        for category, prefix in (('potions', 'ItPo_'), ('scrolls', 'ItSc_')):
            schema = PropertiesSchema.load(self.root / f'properties/categories/{category}.json')
            self.assertEqual(schema.sections[0].fields[1].label, 'Shared caption')
            self.assertEqual(schema.sections[0].fields[0].prefix, prefix)
        self.assertFalse((ASSETS / 'potion.json').exists())

    def test_invalid_block_paths_missing_files_duplicates_and_unknown_overrides(self):
        categories, blocks = self.root / 'categories', self.root / 'blocks'
        categories.mkdir()
        blocks.mkdir()
        category = categories / 'test.json'
        block = blocks / 'base.json'
        block.write_text(json.dumps({'sections': [{'id': 'base', 'title': 'Base', 'fields': [
            {'key': 'name', 'label': 'Name', 'type': 'string'}]}]}), encoding='utf-8')
        for references, error in ((['../outside.json'], ValueError), (['missing.json'], OSError),
                                  (['base.json', 'base.json'], ValueError)):
            category.write_text(json.dumps({'blocks': references}), encoding='utf-8')
            with self.assertRaises(error):PropertiesSchema.load(category)
        category.write_text(json.dumps({'blocks': ['base.json', 'override.json']}), encoding='utf-8')
        override = blocks / 'override.json'
        override.write_text(json.dumps({'field_overrides': {'missing': {'default': '1'}}}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'override'):PropertiesSchema.load(category)
        override.write_text(block.read_text('utf-8'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate section'):PropertiesSchema.load(category)

    def test_scroll_create_edit_reopen_duplicate_and_delete(self):
        repo = ProjectRepository()
        repo.create(self.root / 'project', 'Test')
        item = repo.create_item('scrolls', 'Свиток')
        self.assertEqual(item.instance, 'ItSc_Scroll1')
        self.assertEqual(classify(item), 'scrolls')
        self.assertEqual(item.fields['description'], '"Свиток"')
        self.assertEqual(item.fields['text[5]'], 'NAME_Value')
        self.assertNotIn('scemename', item.fields)
        self.assertNotIn('material', item.fields)
        item = repo.edit(item, {'effect': '"FX"', 'visual': '"Scroll.3ds"',
                                'text[0]': '"Описание"', 'count[0]': 'BONUS + 3'}, instance='ItSc_Test')
        repo.open(repo.root)
        item = next(i for i in repo.items if i.instance == 'ItSc_Test')
        self.assertEqual(item.fields['count[0]'], 'BONUS + 3')
        self.assertEqual(classify(item), 'scrolls')
        other = repo.duplicate(item)
        self.assertEqual(classify(other), 'scrolls')
        self.assertEqual(other.fields, item.fields)
        repo.delete(other)
        self.assertEqual(len(repo.items), 1)

    def test_imported_scroll_preserves_source_helpers_unknown_expressions_and_build(self):
        repo = ProjectRepository()
        repo.create(self.root / 'project', 'Test')
        content = self.root / 'game/_work/Data/Scripts/Content'
        (content / 'Items').mkdir(parents=True)
        source = content / 'Items/IT_Scrolls.d'
        original = ('INSTANCE ItSc_Fireball(C_Item) { mainflag=ITEM_KAT_RUNE; name="Fire"; '
                    'custom=BASE + 3; on_state[0]=CastScroll; };\n'
                    'INSTANCE OTHER(C_Item) { mainflag=ITEM_KAT_NONE; };\n'
                    'func void CastScroll() {};\n').encode('cp1251')
        source.write_bytes(original)
        (content / 'Gothic.src').write_bytes(b'Items\\IT_*.d\n')
        repo.set_game_path(str(self.root / 'game'))
        item = next(i for i in repo.game_items if i.instance == 'ItSc_Fireball')
        self.assertEqual(classify(item), 'scrolls')
        item = repo.copy_to_project(item)
        item = repo.edit(item, {'value': 'PRICE + 2'})
        self.assertEqual(item.fields['custom'], 'BASE + 3')
        self.assertEqual(item.fields['on_state[0]'], 'CastScroll')
        self.assertNotIn('description', item.fields)
        new = repo.create_item('scrolls')
        (self.root / 'stage').mkdir()
        staged, _, _ = ProjectTools(repo.root, repo.game)._prepare(self.root / 'stage', lambda _: None)
        built = {i.instance: i for path in staged.rglob('*.d') for i in parse_items(path, 'build')}
        self.assertEqual(built[item.instance].fields['value'], 'PRICE + 2')
        self.assertIn('OTHER', built)
        self.assertIn(new.instance, built)
        self.assertIn('func void CastScroll()', (staged / 'Items/IT_Scrolls.d').read_text('cp1251'))
        self.assertEqual(source.read_bytes(), original)


class ScrollFormTests(unittest.TestCase):
    def test_shared_fields_autosave_resource_quoting_and_single_appearance_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('gothic_editor.app.SettingsStore', return_value=SettingsStore(root / 'settings.json')):
                app = EditorApp()
            try:
                app.withdraw()
                app.repo.create(root / 'project', 'Test')
                item = app.repo.create_item('scrolls')
                app.show_project()
                app.select(item)
                app.update()
                form = app.properties
                self.assertTrue(form.editable)
                self.assertNotIn('scemeName', form.inputs)
                self.assertEqual(set(form.inputs), {'instance', 'name', 'description', 'flags', 'value', 'visual', 'effect', 'inventory_rows', 'item_actions'})
                self.assertEqual(len(form.sections), 5)
                self.assertIsNotNone(form.appearance_holder)
                model = app.repo.root / 'Assets/Models/Scroll.3ds'
                model.write_bytes(geometry_3ds([(0.,0.,0.), (1.,0.,0.), (0.,1.,0.)], [(0,1,2)]))
                app.repo.mesh_index['scroll.3ds'] = model
                visual_entry = form.inputs['visual']
                for key, value in (('visual', 'Scroll.3ds'), ('instance', 'Renamed')):
                    entry = form.inputs[key]
                    entry.delete(0, 'end')
                    entry.insert(0, value)
                    entry.event_generate('<FocusOut>')
                form.save()
                deadline = monotonic() + 5
                while app._model_future is not None and monotonic() < deadline:app.update()
                self.assertEqual(app.viewer.faces, [(0,1,2)])
                self.assertIs(form.inputs['visual'], visual_entry)
                self.assertEqual(app.current.instance, 'ItSc_Renamed')
                self.assertEqual(app.current.fields['visual'], '"Scroll.3ds"')
                app.repo.open(app.repo.root)
                self.assertEqual(app.repo.project_items[0].fields['visual'], '"Scroll.3ds"')
                potion = app.repo.create_item('potions')
                app.select(potion)
                self.assertEqual(len(app.properties.sections), 5)
                self.assertEqual([field.key for section in schema_for('potions').sections
                                  if section.key=='appearance' for field in section.fields], ['visual', 'effect'])
                def create_scroll(dialog):
                    self.assertTrue(dialog.editable)
                    dialog.name.set('Новый тестовый свиток')
                    dialog.create()
                with patch.object(app, 'wait_window', side_effect=create_scroll):
                    app.create_item('scrolls')
                self.assertEqual(classify(app.current), 'scrolls')
                self.assertEqual(app.current.title, 'Новый тестовый свиток')
            finally:
                app.destroy()


if __name__ == '__main__':
    unittest.main()
