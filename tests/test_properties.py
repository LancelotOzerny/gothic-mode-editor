import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.properties_schema import PropertiesSchema, schema_for
from gothic_editor.core.settings import SettingsStore
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.scripts import parse_items


class PropertiesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with patch('gothic_editor.app.SettingsStore', return_value=SettingsStore(self.root/'settings.json')):
            self.app = EditorApp()
        self.addCleanup(self.app.destroy)
        self.app.withdraw()
        self.repo = self.app.repo
        self.repo.create(self.root/'project', 'Test')
        self.item = self.repo.create_item('potions')
        self.app.show_project()
        self.app.select(self.item)

    def change(self, key, value):
        entry = self.app.properties.inputs[key]
        entry.delete(0, 'end')
        entry.insert(0, value)

    def test_form_matches_schema_sections_and_missing_values_are_not_written(self):
        schema = schema_for('potions')
        form = self.app.properties
        self.assertEqual(list(form.inputs), [field.key for section in schema.sections for field in section.fields])
        titles = [child.cget('text') for child in form.inner.winfo_children() if isinstance(child, tk.LabelFrame)]
        self.assertEqual(titles, [section.title for section in schema.sections])
        self.assertEqual(form.inputs['instance'].get(), self.item.instance)
        self.assertEqual(form.inputs['scemeName'].get(), '"POTIONFAST"')
        self.assertEqual(form.inputs['TEXT[0]'].get(), '')
        before = self.item.path.read_bytes()
        form.save()
        self.assertEqual(self.item.path.read_bytes(), before)

    def test_arrays_case_and_expressions_round_trip_without_losing_unknown_fields(self):
        item = self.repo.edit(self.item, {'custom_bonus': 'BASE + 2', 'TEXT[0]': 'NAME_Value'})
        self.app.select(item)
        self.assertEqual(self.app.properties.inputs['TEXT[0]'].get(), 'NAME_Value')
        self.assertEqual(self.app.properties.inputs['custom_bonus'].get(), 'BASE + 2')
        self.change('COUNT[0]', 'value * 2')
        self.change('scemeName', '"POTIONSLOW"')
        self.app.properties.save()
        item = self.app.current
        self.assertEqual(item.fields['count[0]'], 'value * 2')
        self.assertEqual(item.fields['scemename'], '"POTIONSLOW"')
        self.assertEqual(item.fields['custom_bonus'], 'BASE + 2')
        self.assertNotIn('text[5]', item.fields)
        self.assertNotIn('effect', item.fields)

    def test_metadata_is_persistent_and_never_exported_to_daedalus(self):
        self.change('description_raw', 'Editor note: preserve this')
        self.app.properties.save()
        self.repo.open(self.repo.root)
        item = self.repo.project_items[0]
        data = json.loads(item.path.read_text('utf-8'))
        self.assertEqual(data['editor_metadata']['description_raw'], 'Editor note: preserve this')
        self.assertNotIn('description_raw', data['fields'])
        self.assertNotIn('Editor note', item.text)
        self.assertNotIn('description_raw', '\n'.join(self.repo.components.generated()[1]))
        self.app.select(item)
        self.assertEqual(self.app.properties.inputs['description_raw'].get(), 'Editor note: preserve this')

    def test_other_categories_and_ctrl_save_are_readonly(self):
        for category in ('onehand', 'armor', 'runes', 'food', 'rings', 'documents', 'ammo', 'misc'):
            item = self.repo.create_item(category)
            self.app.select(item)
            form = self.app.properties
            self.assertEqual(form.save_btn['state'], 'disabled')
            self.assertTrue(all(entry['state'] == 'readonly' for entry in form.inputs.values()))
            before = item.path.read_bytes()
            with patch.object(self.repo, 'edit') as edit:
                form.save()
                self.app.save_fields(item, {'name': '"Bypassed"'})
                self.app.rename(item, 'Bypassed')
            edit.assert_not_called()
            self.assertEqual(item.path.read_bytes(), before)

    def test_instance_rename_updates_folder_and_rejects_collisions(self):
        old_folder = self.item.path.parent
        self.change('instance', 'GE_RenamedPotion')
        self.app.properties.save()
        self.assertEqual(self.app.current.instance, 'GE_RenamedPotion')
        self.assertEqual(self.app.current.path.parent.name, 'GE_RenamedPotion')
        self.assertFalse(old_folder.exists())
        self.assertIn('INSTANCE GE_RenamedPotion', self.app.current.text)
        other = self.repo.create_item('potions')
        self.change('instance', other.instance)
        with patch('gothic_editor.app.messagebox.showerror') as error:
            self.app.properties.save()
        error.assert_called_once()
        self.assertEqual(len(self.repo.project_items), 2)
        self.change('instance', '')
        with patch('gothic_editor.ui.properties.messagebox.showerror') as error:
            self.app.properties.save()
        error.assert_called_once()

    def test_schema_extension_changes_form_without_python_field_list(self):
        data = json.loads(Path('assets/properties/potion.json').read_text('utf-8'))
        data['sections'].append({'id': 'custom', 'title': 'Extra section', 'fields': [
            {'key': 'extra_code', 'label': 'Extra label', 'type': 'string', 'source': 'property'}]})
        path = self.root/'custom.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch('gothic_editor.ui.properties.schema_for', return_value=PropertiesSchema.load(path)):
            self.app.select(self.item)
        self.change('extra_code', 'BONUS + 1')
        self.app.properties.save()
        self.assertEqual(self.app.current.fields['extra_code'], 'BONUS + 1')

    def test_clearing_property_removes_assignment_instead_of_emitting_invalid_code(self):
        self.change('visual', '')
        self.app.properties.save()
        self.assertNotIn('visual', self.app.current.fields)
        self.assertNotIn('visual = ;', self.app.current.text)

    def test_invalid_schema_disables_save_with_an_explanation(self):
        with patch('gothic_editor.ui.properties.schema_for', side_effect=ValueError('bad schema')):
            self.app.select(self.item)
        self.assertEqual(self.app.properties.save_btn['state'], 'disabled')
        self.assertIn('bad schema', self.app.properties.info['text'])

    def test_renaming_copied_instance_keeps_original_and_builds_as_new_item(self):
        content = self.root/'game/_work/Data/Scripts/Content'
        (content/'Items').mkdir(parents=True)
        source = content/'Items/IT_Potions.d'
        raw = b'INSTANCE ItPo_Original(C_Item) { name="Original"; mainflag=ITEM_KAT_POTIONS; };\r\nfunc void Helper() {};'
        source.write_bytes(raw)
        (content/'Gothic.src').write_bytes(b'Items\\IT_*.d\r\n')
        self.repo.set_game_path(str(self.root/'game'))
        copied = self.repo.copy_to_project(self.repo.game_items[0])
        self.app.select(copied)
        self.change('instance', 'GE_CustomPotion')
        self.change('description_raw', 'Private note')
        self.app.properties.save()
        data = json.loads(self.app.current.path.read_text('utf-8'))
        self.assertIsNone(data['source_instance'])
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            staged, _, _ = ProjectTools(self.repo.root, self.repo.game)._prepare(Path(temporary), lambda _: None)
            self.assertEqual((staged/'Items/IT_Potions.d').read_bytes(), raw)
            generated = staged/'Items/GE_ComponentPotions.d'
            self.assertEqual({item.instance for item in parse_items(generated,'build')},
                             {'GE_CustomPotion',self.item.instance})
            self.assertNotIn('Private note',generated.read_text('cp1251'))
        self.assertEqual(source.read_bytes(),raw)

    def test_case_only_rename_preserves_original_override_link(self):
        content = self.root/'game/_work/Data/Scripts/Content/Items'
        content.mkdir(parents=True)
        (content/'IT_Potions.d').write_bytes(b'INSTANCE ItPo_Original(C_Item) { name="Original"; };')
        self.repo.set_game_path(str(self.root/'game'))
        copied = self.repo.copy_to_project(self.repo.game_items[0])
        changed = self.repo.edit(copied, {}, instance='ITPO_ORIGINAL')
        self.assertEqual(changed.path.parent.name,'ITPO_ORIGINAL')
        data = json.loads(changed.path.read_text('utf-8'))
        self.assertEqual(data['source_instance'],'ItPo_Original')
        self.assertIn('itpo_original',self.repo.components.generated()[0])
