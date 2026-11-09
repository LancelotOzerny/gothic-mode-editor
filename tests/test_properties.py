import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.properties_schema import PropertiesSchema, schema_for
from gothic_editor.core.property_blocks import load_property_data
from gothic_editor.core.settings import SettingsStore
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.scripts import parse_items
from gothic_editor.ui.widgets.choice_field import ExpressionChoiceField


class PropertiesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with patch('gothic_editor.app.SettingsStore', return_value=SettingsStore(self.root/'settings.json')):
            self.app = EditorApp()
        self.addCleanup(self.close_app)
        self.app.withdraw()
        self.repo = self.app.repo
        self.repo.create(self.root/'project', 'Test')
        self.item = self.repo.create_item('potions')
        self.app.show_project()
        self.app.select(self.item)

    def close_app(self):
        self.app.properties.show(None)
        self.app.destroy()

    def change(self, key, value):
        entry = self.app.properties.inputs[key]
        entry.delete(0, 'end')
        entry.insert(0, value)

    def test_form_matches_schema_sections_and_missing_values_are_not_written(self):
        schema = schema_for('potions')
        form = self.app.properties
        self.assertEqual(list(form.inputs), [field.key for section in schema.sections for field in section.fields])
        self.assertEqual(list(form.sections), ['general', 'parameters', 'appearance', 'actions', 'inventory'])
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
        self.assertEqual(item.fields['text[5]'], 'NAME_Value')
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
            self.assertFalse(form.editable)
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
        self.assertFalse(self.app.properties.save())
        self.assertIn('instance',self.app.properties.error_labels)
        self.assertEqual(len(self.repo.project_items), 2)
        self.change('instance', '')
        self.assertFalse(self.app.properties.save())
        self.assertIn('instance',self.app.properties.error_labels)

    def test_schema_extension_changes_form_without_python_field_list(self):
        data = load_property_data(Path('assets/properties/categories/potions.json'))
        data['sections'].append({'id': 'custom', 'title': 'Extra section', 'fields': [
            {'key': 'extra_code', 'label': 'Extra label', 'type': 'expression', 'source': 'property'}]})
        path = self.root/'custom.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch('gothic_editor.ui.panels.properties.schema_for', return_value=PropertiesSchema.load(path)):
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
        with patch('gothic_editor.ui.panels.properties.schema_for', side_effect=ValueError('bad schema')):
            self.app.select(self.item)
        self.assertFalse(self.app.properties.editable)
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
        self.assertIsInstance(combo,ExpressionChoiceField)
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
        data=load_property_data(Path('assets/properties/categories/potions.json'))
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
        data=load_property_data(Path('assets/properties/categories/potions.json'))
        data['sections'][0]['fields'][0]['options_ref']='Missing'
        path=self.root/'invalid-options.json'
        path.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'unknown option list'):
            PropertiesSchema.load(path)

    def test_inventory_add_limit_delete_and_responsive_layout(self):
        widget = self.app.properties.inputs['inventory_rows']
        for _ in range(6):widget.add_button.invoke()
        self.assertEqual(len(widget.rows), 5)
        self.assertEqual(str(widget.add_button['state']), 'disabled')
        index, frame, cells = widget.rows[0]
        cells[0][1].insert(0, 'Бонус')
        cells[1][1].insert(0, 'BONUS + 10')
        self.app.update_idletasks()
        frame.event_generate('<Configure>', width=500)
        self.assertEqual(cells[1][1].surface.master.grid_info()['row'], 0)
        frame.event_generate('<Configure>', width=200)
        self.assertEqual(cells[1][1].surface.master.grid_info()['row'], 1)
        self.app._rebuild_translated_ui()
        widget = self.app.properties.inputs['inventory_rows']
        self.assertEqual(widget.get()[0], (index, ('"Бонус"', 'BONUS + 10')))
        self.app.properties.save()
        self.assertEqual(self.app.current.fields['text[0]'], '"Бонус"')
        self.assertEqual(self.app.current.fields['count[5]'], 'value')
        widget = self.app.properties.inputs['inventory_rows']
        widget.remove_row(index)
        self.app.properties.save()
        self.assertNotIn('text[0]', self.app.current.fields)

    def test_effect_none_and_animation_save_as_expressions(self):
        self.app.properties.inputs['effect'].current(0)
        combo = self.app.properties.inputs['scemeName']
        combo.current(next(index for index, (_, expression) in enumerate(combo.options) if expression == '"POTION"'))
        self.app.properties.save()
        self.assertEqual(self.app.current.fields['effect'], '""')
        self.assertEqual(self.app.current.fields['scemename'], '"POTION"')

    def test_inventory_text_in_count_does_not_save_any_pending_changes(self):
        widget = self.app.properties.inputs['inventory_rows']
        widget.add_row()
        cells = widget.rows[0][2]
        cells[0][1].insert(0, 'Время')
        cells[1][1].insert(0, '2 минуты')
        self.change('name', 'Изменённое имя')
        before = self.item.path.read_bytes()
        self.assertFalse(self.app.properties.save())
        self.assertIn('count[0]',self.app.properties.error_labels['inventory_rows'].cget('text'))
        self.assertEqual(self.item.path.read_bytes(), before)
        cells[1][1].delete(0, 'end')
        cells[1][1].insert(0, '2')
        self.app.properties.save()
        self.assertEqual(self.app.current.fields['count[0]'], '2')

    def test_autosave_batches_pending_fields_and_preserves_widgets(self):
        self.app.deiconify()
        self.app.update()
        form=self.app.properties
        self.change('name','Незавершённое имя')
        self.change('value','235')
        entry=form.inputs['value']
        with patch.object(self.repo,'edit',wraps=self.repo.edit) as edit:
            entry.event_generate('<FocusOut>')
            self.app.properties.save(automatic=True)
            self.assertEqual(edit.call_count,1)
            self.assertEqual(self.app.current.fields['value'],'235')
            self.assertEqual(self.app.current.fields['name'],'"Незавершённое имя"')
            self.assertIs(form.inputs['value'],entry)
            self.assertEqual(form.inputs['name'].get(),'Незавершённое имя')
            entry.event_generate('<FocusOut>')
            self.app.properties.save(automatic=True)
            self.assertEqual(edit.call_count,1)
        self.assertEqual(form.info.cget('text'),self.app.current.instance)
        self.assertFalse(hasattr(form,'save_btn'))

    def test_combobox_and_enter_wait_for_autosave_before_saving(self):
        self.app.deiconify()
        self.app.update()
        combo=self.app.properties.inputs['effect']
        combo.current(0)
        combo.event_generate('<<ComboboxSelected>>')
        self.assertNotIn('effect',self.app.current.fields)
        combo.event_generate('<FocusOut>')
        self.app.properties.save(automatic=True)
        self.assertEqual(self.app.current.fields['effect'],'""')
        self.change('instance','AutosavedPotion')
        entry=self.app.properties.inputs['instance']
        entry.focus_force()
        self.app.update()
        entry.event_generate('<Return>')
        self.assertEqual(self.app.current.instance,self.item.instance)
        entry.event_generate('<FocusOut>')
        self.app.properties.save(automatic=True)
        self.assertEqual(self.app.current.instance,'ItPo_AutosavedPotion')
        self.assertTrue(self.app.current.path.is_file())
        self.change('name','После переименования')
        self.app.properties.inputs['name'].event_generate('<FocusOut>')
        self.app.properties.save(automatic=True)
        self.assertEqual(self.repo.project_items[0].fields['name'],'"После переименования"')

    def test_inventory_autosave_preserves_constants_and_removes_assignments(self):
        item=self.repo.edit(self.item,{'text[0]':'NAME_Bonus','count[0]':'BASE'})
        self.app.select(item)
        self.app.deiconify()
        self.app.update()
        widget=self.app.properties.inputs['inventory_rows']
        cells=widget.rows[0][2]
        count=cells[1][1]
        count.delete(0,'end')
        count.insert(0,'BASE + 2')
        count.event_generate('<FocusOut>')
        self.app.properties.save(automatic=True)
        self.assertEqual(self.app.current.fields['text[0]'],'NAME_Bonus')
        self.assertEqual(self.app.current.fields['count[0]'],'BASE + 2')
        before=self.app.current.path.read_bytes()
        count.event_generate('<FocusOut>')
        self.app.properties.save(automatic=True)
        self.assertEqual(self.app.current.path.read_bytes(),before)
        widget.remove_row(0)
        self.app.properties.save(automatic=True)
        self.assertNotIn('text[0]',self.app.current.fields)
        self.assertNotIn('count[0]',self.app.current.fields)
        self.assertEqual(self.app.current.fields['text[5]'],'NAME_Value')

    def test_autosave_rejects_invalid_inventory_and_can_be_corrected(self):
        self.app.deiconify()
        self.app.update()
        widget=self.app.properties.inputs['inventory_rows']
        widget.add_row()
        self.app.update_idletasks()
        cells=widget.rows[0][2]
        cells[0][1].insert(0,'Время')
        cells[1][1].insert(0,'2 минуты')
        before=self.app.current.path.read_bytes()
        self.assertFalse(self.app.properties.save(automatic=True))
        self.assertIn('inventory_rows',self.app.properties.error_labels)
        self.assertEqual(self.app.current.path.read_bytes(),before)
        cells[1][1].delete(0,'end')
        cells[1][1].insert(0,'2')
        cells[1][1].event_generate('<FocusOut>')
        self.app.properties.save(automatic=True)
        self.assertEqual(self.app.current.fields['count[0]'],'2')

    def test_switching_items_flushes_drafts_and_rejects_invalid_required_value(self):
        other=self.repo.create_item('potions')
        self.change('value','321')
        self.app.select(other)
        stored=next(item for item in self.repo.project_items if item.instance==self.item.instance)
        self.assertEqual(stored.fields['value'],'321')
        self.assertEqual(self.app.current.instance,other.instance)
        self.change('instance','')
        self.app.select(stored)
        self.assertIn('instance',self.app.properties.error_labels)
        self.assertEqual(self.app.current.instance,other.instance)

    def test_build_flushes_focused_field_before_starting_tools(self):
        self.change('value','543')
        with patch('gothic_editor.app.ProjectTools') as factory:
            factory.return_value.compile.return_value=None
            with patch.object(self.app._tool_runner,'start') as start:
                self.app.run_project_tool('compile')
                self.assertEqual(self.app.current.fields['value'],'543')
                start.assert_called_once()

    def test_dropdown_selection_autosaves_and_escape_keeps_current_value(self):
        self.app.deiconify()
        self.app.update()
        combo=self.app.properties.inputs['flags']
        combo.event_generate('<ButtonPress-1>',x=10,y=8)
        self.app.update()
        self.assertIsNone(combo.selection_window)
        combo.event_generate('<ButtonRelease-1>',x=10,y=8)
        self.app.update()
        self.assertIsNotNone(combo.selection_window)
        self.assertFalse(combo.selection_window.overrideredirect())
        self.assertEqual((combo.selection_window.winfo_width(),combo.selection_window.winfo_height()),(480,320))
        self.assertAlmostEqual(combo.selection_window.winfo_x(),self.app.winfo_rootx()+(self.app.winfo_width()-480)//2,delta=3)
        self.assertAlmostEqual(combo.selection_window.winfo_y(),self.app.winfo_rooty()+(self.app.winfo_height()-320)//2,delta=3)
        self.assertTrue(all(button.winfo_height()==40 for button in combo.selection_window.option_buttons))
        self.assertTrue(combo.selection_window.option_buttons[combo.current()].selected)
        combo.selection_window.option_buttons[2].event_generate('<ButtonRelease-1>',x=10,y=20)
        self.app.update()
        combo.selection_window.option_buttons[2].event_generate('<Leave>')
        self.assertTrue(combo.selection_window.option_buttons[2].selected)
        self.assertEqual(sum(button.selected for button in combo.selection_window.option_buttons),1)
        self.assertIsNotNone(combo.selection_window)
        combo.selection_window.choose_button.invoke()
        self.app.update()
        self.assertIsNone(combo.selection_window)
        self.assertEqual(self.app.current.fields['flags'],'ITEM_MULTI')
        combo.event_generate('<FocusOut>')
        self.app.properties.save(automatic=True)
        self.assertEqual(self.app.current.fields['flags'],'ITEM_MISSION')
        combo.open_choices()
        self.app.update()
        combo.selection_window.focus_option(0)
        combo.selection_window.event_generate('<Escape>')
        self.app.update()
        self.assertIsNone(combo.selection_window)
        self.assertEqual(self.app.current.fields['flags'],'ITEM_MISSION')

    def test_inventory_headers_are_shared_and_create_icon_stays_visible(self):
        self.app.deiconify()
        self.app.update()
        widget=self.app.properties.inputs['inventory_rows']
        for _ in range(3):widget.add_row()
        self.app.update()
        self.assertEqual(len(widget.column_labels),2)
        for _,frame,cells in widget.rows:
            for _,entry,_,_ in cells:
                holder=entry.surface.master
                self.assertFalse(any(isinstance(child,tk.Label) for child in holder.winfo_children()))
        picture=widget.add_button.image
        self.assertIsNotNone(picture)
        brightest=max(sum(picture.get(x,y)) for y in range(picture.height()) for x in range(picture.width()))
        self.assertGreater(brightest,600)

    def test_dropdown_disabled_and_long_lists_can_be_scrolled_and_closed(self):
        self.app.deiconify()
        self.app.update()
        combo=self.app.properties.inputs['effect']
        combo.options=tuple((str(i),f'"FX_{i}"') for i in range(20))
        combo.open_choices()
        self.app.update()
        combo.selection_window.focus_option(19)
        self.app.update()
        self.assertGreater(combo.selection_window.option_buttons[-1].master.master.yview()[0],0)
        combo.selection_window.apply(19)
        combo.event_generate('<FocusOut>')
        self.app.properties.save(automatic=True)
        self.assertEqual(self.app.current.fields['effect'],'"FX_19"')
        combo.config(state='disabled')
        combo.open_choices()
        self.assertIsNone(combo.selection_window)

    def test_clicking_field_padding_focuses_native_entry_and_accepts_typing(self):
        self.app.deiconify()
        self.app.update()
        self.app.focus_force()
        entry=self.app.properties.inputs['name']
        entry.surface.event_generate('<ButtonPress-1>',x=5,y=20)
        entry.surface.event_generate('<ButtonRelease-1>',x=5,y=20)
        self.app.update()
        self.assertIs(self.app.focus_get(),entry)
        before=entry.get()
        entry.event_generate('<KeyPress>',keysym='space')
        self.app.update()
        self.assertEqual(len(entry.get()),len(before)+1)
        entry.event_generate('<FocusOut>')
        self.app.properties.save(automatic=True)
        self.assertIn(entry.get(),self.app.current.fields['name'])

    def test_dropdown_opens_from_text_padding_and_arrow(self):
        self.app.deiconify()
        self.app.update()
        combo=self.app.properties.inputs['flags']
        for target in (combo,combo.surface,combo.arrow):
            with self.subTest(target=str(target)):
                target.event_generate('<ButtonPress-1>',x=3,y=3)
                target.event_generate('<ButtonRelease-1>',x=3,y=3)
                self.app.update()
                self.assertIsNotNone(combo.selection_window)
                self.assertTrue(combo.selection_window.winfo_viewable())
                combo.close_choices()
                self.app.update()

    def test_repeated_selection_does_not_grab_mouse_or_block_text_input(self):
        self.app.deiconify()
        self.app.update()
        combo=self.app.properties.inputs['flags']
        entry=self.app.properties.inputs['name']
        for option in (2,1,2):
            combo.open_choices()
            self.app.update()
            self.assertIsNone(self.app.grab_current())
            combo.selection_window.apply(option)
            self.app.update()
            self.assertIsNone(self.app.grab_current())
            entry.surface.event_generate('<ButtonPress-1>',x=5,y=20)
            entry.surface.event_generate('<ButtonRelease-1>',x=5,y=20)
            self.app.update()
            self.assertIs(self.app.focus_get(),entry)
            before=entry.get()
            entry.event_generate('<KeyPress>',keysym='space')
            self.app.update()
            self.assertEqual(len(entry.get()),len(before)+1)
            self.assertIsNone(combo.selection_window)

    def test_selection_window_does_not_block_other_fields(self):
        self.app.deiconify()
        self.app.update()
        combo=self.app.properties.inputs['flags']
        entry=self.app.properties.inputs['value']
        combo.open_choices()
        self.app.update()
        entry.surface.event_generate('<ButtonPress-1>',x=5,y=20)
        entry.surface.event_generate('<ButtonRelease-1>',x=5,y=20)
        self.app.update()
        self.assertIsNotNone(combo.selection_window)
        self.assertIsNone(self.app.grab_current())
        self.assertIs(self.app.focus_get(),entry)
