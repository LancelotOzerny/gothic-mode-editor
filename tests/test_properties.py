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
from gothic_editor.ui.property_widgets import ExpressionCombobox


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
        self.assertEqual(list(form.sections), ['general', 'parameters'])
        self.assertEqual(form.inputs['instance'].get(), 'Potion1')
        self.assertEqual(form.inputs['name'].get(), 'Новое зелье')
        self.assertEqual(form.inputs['description'].get(), 'Новое зелье')
        self.assertEqual(form.inputs['flags'].get(), 'ITEM_MULTI')
        self.assertEqual(form.inputs['value'].get(), '100')
        before = self.item.path.read_bytes()
        form.save()
        self.assertEqual(self.item.path.read_bytes(), before)

    def test_arrays_case_and_expressions_round_trip_without_losing_unknown_fields(self):
        item = self.repo.edit(self.item, {'custom_bonus': 'BASE + 2', 'TEXT[0]': 'NAME_Value'})
        self.app.select(item)
        self.assertNotIn('TEXT[0]', self.app.properties.inputs)
        self.assertNotIn('custom_bonus', self.app.properties.inputs)
        self.change('value', 'value * 2')
        self.app.properties.save()
        item = self.app.current
        self.assertEqual(item.fields['value'], 'value * 2')
        self.assertEqual(item.fields['text[0]'], 'NAME_Value')
        self.assertEqual(item.fields['custom_bonus'], 'BASE + 2')
        self.assertNotIn('text[5]', item.fields)
        self.assertNotIn('effect', item.fields)

    def test_plain_strings_round_trip_and_description_is_independent(self):
        self.change('name', 'Зелье "силы" \\ тест')
        self.change('description', 'Отдельное описание')
        self.app.properties.save()
        self.repo.open(self.repo.root)
        item=self.repo.project_items[0]
        self.assertEqual(item.fields['name'], '"Зелье \\"силы\\" \\\\ тест"')
        self.assertEqual(item.fields['description'], '"Отдельное описание"')
        self.app.select(item)
        self.assertEqual(self.app.properties.inputs['name'].get(), 'Зелье "силы" \\ тест')
        self.assertEqual(self.app.properties.inputs['description'].get(), 'Отдельное описание')
        before=item.path.read_bytes()
        self.app.properties.save()
        self.assertEqual(item.path.read_bytes(),before)

    def test_metadata_is_persistent_and_never_exported_to_daedalus(self):
        self.repo.edit(self.item, {}, metadata={'description_raw': 'Editor note: preserve this'})
        self.repo.open(self.repo.root)
        item = self.repo.project_items[0]
        data = json.loads(item.path.read_text('utf-8'))
        self.assertEqual(data['editor_metadata']['description_raw'], 'Editor note: preserve this')
        self.assertNotIn('description_raw', data['fields'])
        self.assertNotIn('Editor note', item.text)
        self.assertNotIn('description_raw', '\n'.join(self.repo.components.generated()[1]))
        self.app.select(item)
        self.assertNotIn('description_raw', self.app.properties.inputs)

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
        self.change('instance', 'RenamedPotion')
        self.app.properties.save()
        self.assertEqual(self.app.current.instance, 'ItPo_RenamedPotion')
        self.assertEqual(self.app.current.path.parent.name, 'ItPo_RenamedPotion')
        self.assertFalse(old_folder.exists())
        self.assertIn('INSTANCE ItPo_RenamedPotion', self.app.current.text)
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
        data = json.loads(Path('assets/schemas/potions.json').read_text('utf-8'))
        data['sections'].append({'id': 'custom', 'title': 'Extra section', 'fields': [
            {'key': 'extra_code', 'label': 'Extra label', 'type': 'expression', 'source': 'property'}]})
        path = self.root/'custom.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch('gothic_editor.ui.properties.schema_for', return_value=PropertiesSchema.load(path)):
            self.app.select(self.item)
        self.change('extra_code', 'BONUS + 1')
        self.app.properties.save()
        self.assertEqual(self.app.current.fields['extra_code'], 'BONUS + 1')

    def test_clearing_property_removes_assignment_instead_of_emitting_invalid_code(self):
        self.change('description', '')
        self.app.properties.save()
        self.assertNotIn('description', self.app.current.fields)
        self.assertNotIn('description = ;', self.app.current.text)

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
        self.change('instance', 'CustomPotion')
        self.app.properties.save()
        data = json.loads(self.app.current.path.read_text('utf-8'))
        self.assertIsNone(data['source_instance'])
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            staged, _, _ = ProjectTools(self.repo.root, self.repo.game)._prepare(Path(temporary), lambda _: None)
            self.assertEqual((staged/'Items/IT_Potions.d').read_bytes(), raw)
            generated = staged/'Items/GE_ComponentPotions.d'
            self.assertEqual({item.instance for item in parse_items(generated,'build')},
                             {'ItPo_CustomPotion',self.item.instance})
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

    def test_combobox_displays_names_but_saves_daedalus_values(self):
        combo=self.app.properties.inputs['flags']
        self.assertIsInstance(combo,ExpressionCombobox)
        self.assertEqual(str(combo['state']),'readonly')
        self.assertEqual(combo.value_variable.get(),'Складываемое')
        self.assertEqual(combo.get(),'ITEM_MULTI')
        combo.current(2)  # Квестовый предмет
        self.app.properties.save()
        self.assertEqual(self.app.current.fields['flags'],'ITEM_MISSION')
        self.assertNotIn('Квестовый предмет',self.app.current.text)
        self.assertEqual(self.app.properties.inputs['flags'].value_variable.get(),'Квестовый предмет')

    def test_custom_flags_expressions_resources_and_function_identifiers_stay_raw(self):
        item=self.repo.edit(self.item,{'flags':'ITEM_MULTI | CUSTOM_FLAG'})
        self.app.select(item)
        values={'flags':'ITEM_MULTI | CUSTOM_FLAG', 'value':'Value_HpMaxElixier + 7',
                'name':'"Custom type"'}
        for key,value in values.items():
            if key!='flags':self.change(key,value)
        self.app.properties.save()
        for key,value in values.items():
            self.assertEqual(self.app.current.fields[key.casefold()],value)
        self.assertEqual(self.app.current.fields['description'],'"Новое зелье"')

    def test_original_missing_fields_do_not_receive_defaults_or_placeholders(self):
        source=self.root/'Original.d'
        source.write_bytes(b'INSTANCE ItPo_Test(C_Item) { name=NAME_Trank; };')
        original=parse_items(source,'game')[0]
        self.repo.components.import_item(original)
        self.repo.refresh()
        item=next(item for item in self.repo.project_items if item.instance=='ItPo_Test')
        self.app.select(item)
        before=item.path.read_bytes()
        for key in ('description','flags','value'):
            self.assertEqual(self.app.properties.inputs[key].get(),'')
        hint=self.app.properties.inputs['value'].placeholder
        self.assertEqual(hint['text'],'100')
        self.app.properties.save()
        self.assertEqual(item.path.read_bytes(),before)

    def test_new_item_defaults_are_taken_from_schema_only_at_creation(self):
        data=json.loads(Path('assets/schemas/potions.json').read_text('utf-8'))
        data['generated_defaults']['visual']='"OtherPotion.3ds"'
        data['generated_defaults']['inv_animate']='1'
        for section in data['sections']:
            for field in section['fields']:
                if field['key']=='visual':field['default']='"OtherPotion.3ds"'
                if field['key']=='value':field['default']='BASE_PRICE + 17'
                if field['key']=='inv_animate':field['default']='1'
        path=self.root/'defaults.json'
        path.write_text(json.dumps(data),encoding='utf-8')
        with patch('gothic_editor.core.project.schema_for',return_value=PropertiesSchema.load(path)):
            item=self.repo.create_item('potions','Custom title')
        self.assertEqual(item.fields['visual'],'"OtherPotion.3ds"')
        self.assertEqual(item.fields['value'],'BASE_PRICE + 17')
        self.assertEqual(item.fields['inv_animate'],'1')
        self.assertEqual(item.fields['description'],'"Custom title"')
        self.assertNotIn('wear',item.fields)
        self.assertNotIn('on_state[1]',item.fields)
        self.assertNotIn('inv_animate',self.item.fields)

    def test_sections_collapse_without_losing_drafts_and_survive_rebuild(self):
        self.change('value','42 + BONUS')
        section=self.app.properties.sections['parameters']
        section.header.invoke()
        self.assertTrue(section.closed)
        self.assertEqual(section.body.winfo_manager(),'')
        self.app._rebuild_translated_ui()
        self.assertTrue(self.app.properties.sections['parameters'].closed)
        self.assertEqual(self.app.properties.inputs['value'].get(),'42 + BONUS')
        self.assertEqual(self.app.properties.inputs['flags'].value_variable.get(),'Складываемое')
        self.app.properties.sections['parameters'].header.invoke()
        self.assertEqual(self.app.properties.sections['parameters'].body.winfo_manager(),'pack')

    def test_invalid_option_references_are_rejected(self):
        data=json.loads(Path('assets/properties/potion.json').read_text('utf-8'))
        data['sections'][0]['fields'][0]['options_ref']='Missing'
        path=self.root/'invalid-options.json'
        path.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'unknown option list'):
            PropertiesSchema.load(path)
