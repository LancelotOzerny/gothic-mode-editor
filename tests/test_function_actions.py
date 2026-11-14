"""Function metadata, dynamic arguments and staged Daedalus callbacks."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from gothic_editor.core.item_actions import ActionCatalog,read_functions,argument_literal
from gothic_editor.core.item_options import item_options
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.properties_schema import PropertyField,PropertySection,PropertiesSchema
from gothic_editor.core.scripts import parse_items
from gothic_editor.ui.panels.properties import PropertiesPanel
from test_editor_responsiveness import temporary_item


SOURCE='''// @INFO NAME=Добавить опыт
// @PARAM VALUE=exp NAME="Кол-во опыта"
func void AddExperience(var int exp) { TotalExp = TotalExp + exp; };
// @INFO NAME="Смешанные параметры"
// @PARAM VALUE=caption NAME="Текст"
func void Mixed(var string caption, var float scale) {};
func int NotAnAction() { return 1; };
'''
FIELD=PropertyField('item_actions','Actions',source='editor_metadata',export=False,
                    field_type='action_list',max_rows=4,options_source='item_actions')
SCHEMA=PropertiesSchema((PropertySection('parameters','Parameters',()),PropertySection('actions','Actions',(FIELD,))))


class ActionFixture:
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='function actions ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.repo=ProjectRepository()
        self.repo.create(self.root/'project','Test')
        self.item=temporary_item(self.repo)
        self.source=self.repo.root/'Assets/Scripts/Actions/Experience.d'
        self.source.parent.mkdir()
        self.source.write_text(SOURCE,encoding='utf-8')
        self.identifier='project:Assets/Scripts/Actions/Experience.d#AddExperience'
        self.game=self.root/'game'
        self.content=self.game/'_work/Data/Scripts/Content'
        (self.content/'Items').mkdir(parents=True)
        (self.content/'Gothic.src').write_text('Items\\*.d\n')
        (self.content/'Items/Base.d').write_text('''
const int ITEM_KAT_POTIONS = 1;
const int BASE = 1;
var int TotalExp;
class C_Item { var string name; var int value; var int mainflag; var int custom; var func on_state[4]; };
func void Previous() {};
''')
        self.repo.game=self.game

    def assign(self,item,amount,identifier=None):
        raw=json.dumps([{'id':identifier or self.identifier,'values':{'exp':str(amount)}}])
        return self.repo.edit(item,{},metadata={'item_actions':raw})

    def prepare(self):
        staging=self.root/('staging'+str(len(list(self.root.glob('staging*')))))
        staging.mkdir()
        return ProjectTools(self.repo.root,self.game)._prepare(staging,lambda _:None)


class FunctionMetadataTests(ActionFixture,unittest.TestCase):
    def test_annotations_match_function_parameters_and_legacy_file_selection(self):
        values=read_functions(self.source,'project:Assets/Scripts/Actions/Experience.d')
        self.assertEqual([value.name for value in values],['AddExperience','Mixed'])
        function=values[0]
        self.assertEqual(function.label,'Добавить опыт')
        self.assertEqual(function.parameters[0].label,'Кол-во опыта')
        self.assertEqual(function.parameters[0].kind,'int')
        catalog=ActionCatalog(self.repo.root,self.content)
        self.assertEqual(catalog.resolve(self.identifier),function)
        with self.assertRaisesRegex(ValueError,'конкретную функцию'):
            catalog.resolve('project:Assets/Scripts/Actions/Experience.d')
        bad=SOURCE.replace('VALUE=exp','VALUE=unknown')
        with self.assertRaisesRegex(ValueError,'не соответствует'):read_functions(self.source,'test',bad)

    def test_short_param_annotation_uses_the_argument_name_as_key(self):
        source='''// @INFO NAME="Добавить опыт"
// @PARAM VALUE="Кол-во опыта"
func void AddExperience(var int VALUE) { TotalExp = TotalExp + VALUE; };
'''
        function=read_functions(self.source,'test',source)[0]
        self.assertEqual(function.parameters[0].name,'VALUE')
        self.assertEqual(function.parameters[0].label,'Кол-во опыта')

    def test_three_items_share_function_and_preserve_previous_handler(self):
        first=self.repo.edit(self.item,{'on_state[0]':'Previous'})
        items=[first,self.repo.duplicate(first),self.repo.duplicate(first)]
        for item,amount in zip(items,[100,500,1000]):self.assign(item,amount)
        before=self.item.path.read_bytes()
        content,manifest,files=self.prepare()
        text=(content/'Items/GE_ComponentPotions.d').read_text('cp1251')
        for item,amount in zip(items,[100,500,1000]):
            handler='GE_ItemActions_'+item.instance
            self.assertIn(handler,text)
            self.assertIn(f'AddExperience({amount});',text)
        self.assertEqual(text.count('Previous();'),3)
        self.assertNotIn('func void AddExperience',text)
        scripts=list((content/'GE_ActionScripts').glob('*.d'))
        self.assertEqual(len(scripts),1)
        self.assertIn('GE_ActionScripts',manifest.read_text())
        self.assertEqual(self.item.path.read_bytes(),before)
        self.assertEqual(self.source.read_text('utf-8'),SOURCE)
        self.assertEqual(len(parse_items(content/'Items/GE_ComponentPotions.d','project')),3)

    def test_no_assignments_preserve_manual_callback_and_invalid_values_fail(self):
        item=self.repo.edit(self.item,{'on_state[0]':'Previous'})
        content,_,_=self.prepare()
        parsed=parse_items(content/'Items/GE_ComponentPotions.d','project')[0]
        self.assertEqual(parsed.fields['on_state[0]'],'Previous')
        self.assign(item,'100; Evil()')
        with self.assertRaisesRegex(ValueError,'целое число'):self.prepare()

    def test_standard_function_and_mixed_scalar_arguments(self):
        standard=self.content/'Items/Standard.d'
        standard.write_text('func void StandardAction(var int count) {};')
        raw=json.dumps([{'id':'game:Content/Items/Standard.d#StandardAction','values':{'count':'5'}},
                        {'id':'project:Assets/Scripts/Actions/Experience.d#Mixed',
                         'values':{'caption':'Текст "опыт"','scale':'1.25'}}])
        self.repo.edit(self.item,{},metadata={'item_actions':raw})
        content,manifest,_=self.prepare()
        text=(content/'Items/GE_ComponentPotions.d').read_text('cp1251')
        self.assertIn('StandardAction(5);',text)
        self.assertIn('Mixed("Текст \\"опыт\\"", 1.25);',text)

    def test_conflicts_missing_functions_and_signature_changes_are_reported(self):
        self.assign(self.item,100)
        self.source.write_text(SOURCE.replace('AddExperience','Renamed'),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'AddExperience'):self.prepare()
        self.source.write_text(SOURCE,encoding='utf-8')
        (self.content/'Items/Conflict.d').write_text('func void AddExperience(var int exp) {};')
        with self.assertRaisesRegex(ValueError,'конфликт'):self.prepare()

    @unittest.skipUnless(os.environ.get('GOTHIC_TEST_COMPILER'),'Optional real GDC')
    def test_real_compiler_accepts_callbacks_and_shared_function(self):
        from gothic_editor.core.compiler_runner import run_compiler
        first=self.assign(self.repo.edit(self.item,{'on_state[0]':'Previous'}),100)
        for amount in (500,1000):self.assign(self.repo.duplicate(first),amount)
        rows=json.loads(first.editor_metadata['item_actions'])
        rows.append({'id':'project:Assets/Scripts/Actions/Experience.d#Mixed',
                     'values':{'caption':'Опыт','scale':'1.25'}})
        self.repo.edit(first,{},metadata={'item_actions':json.dumps(rows)})
        content,manifest,_=self.prepare()
        output=content.parent/'Gothic.dat'
        result=run_compiler([os.environ['GOTHIC_TEST_COMPILER'],str(manifest),'--output-dat',str(output)],
                            content.parent,content.parent/'compiler.log')
        self.assertEqual(result.returncode,0,(content.parent/'compiler.log').read_text('utf-8'))
        self.assertTrue(output.stat().st_size)

    def test_parameters_survive_xlsx_and_duplication(self):
        from gothic_editor.core.item_spreadsheet import export_items,ItemSpreadsheetService
        item=self.assign(self.item,500)
        duplicate=self.repo.duplicate(item)
        self.assertEqual(duplicate.editor_metadata,item.editor_metadata)
        sheet=self.root/'actions.xlsx'
        export_items([item],sheet)
        with patch('gothic_editor.core.item_spreadsheet.schema_for',return_value=SCHEMA):
            ItemSpreadsheetService(self.repo).import_file(sheet,'replace')
        updated=next(value for value in self.repo.items if value.instance==item.instance)
        self.assertEqual(json.loads(updated.editor_metadata['item_actions'])[0]['values'],{'exp':'500'})


class FunctionParameterUITests(ActionFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.window=tk.Tk()
        self.addCleanup(self.window.destroy)
        patcher=patch('gothic_editor.ui.panels.properties.schema_for',return_value=SCHEMA)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.form=PropertiesPanel(self.window,self.save,options_provider=lambda source:item_options(self.repo,source))
        self.form.pack(fill='both',expand=True)
        self.form.show(self.item)
        self.window.update_idletasks()

    def save(self,item,values,**options):
        return self.repo.edit(item,values,metadata=options.get('metadata'))

    def test_parameter_label_input_save_reuse_and_per_row_values(self):
        from gothic_editor.ui.widgets.inputs import PropertyEntry
        widget=self.form.inputs['item_actions']
        widget.rows[0][1].set_expression(self.identifier)
        self.window.update_idletasks()
        holder=widget.parameter_holder
        def descendants(parent):
            for child in parent.winfo_children():
                yield child
                yield from descendants(child)
        labels=[child.cget('text') for child in descendants(holder) if isinstance(child,tk.Label)]
        self.assertIn('[Добавить опыт] Кол-во опыта',labels)
        entry=next(child for child in descendants(holder) if isinstance(child,PropertyEntry))
        entry.delete(0,'end')
        entry.insert(0,'100')
        entry.focus_force()
        self.window.update()
        self.assertTrue(self.form.save())
        self.assertIs(self.window.focus_get(),entry)
        stored=self.repo.components.read_item(self.item.path)
        self.assertEqual(json.loads(stored.editor_metadata['item_actions'])[0]['values'],{'exp':'100'})
        other=temporary_item(self.repo,'ItPo_Other')
        self.form.show(other)
        self.assertFalse(widget.parameter_holder.winfo_children())
        self.form.show(stored)
        self.assertEqual(json.loads(widget.get())[0]['values'],{'exp':'100'})
        self.assertFalse(self.form.editor.dirty)
        widget.add_row()
        widget.rows[1][1].set_expression(self.identifier)
        self.assertEqual(json.loads(widget.get())[1]['values'],{'exp':'0'})
        widget.remove_row(widget.rows[0][0])
        self.assertEqual(json.loads(widget.get())[0]['values'],{'exp':'0'})

    def test_invalid_argument_is_not_saved(self):
        widget=self.form.inputs['item_actions']
        widget.rows[0][1].set_expression(self.identifier)
        frame,_=widget.rows[0]
        widget.arguments[frame]['exp']='bad text'
        widget._sync()
        self.assertFalse(self.form.save())
        self.assertNotIn('item_actions',self.repo.components.read_item(self.item.path).editor_metadata)

    def test_scroll_shows_the_same_action_and_parameter_controls(self):
        scroll=self.repo._write_new('ItSc_Example','INSTANCE ItSc_Example(C_Item) {mainflag=ITEM_KAT_RUNE;};')
        self.form.show(scroll)
        widget=self.form.inputs['item_actions']
        widget.rows[0][1].set_expression(self.identifier)
        frame,_=widget.rows[0]
        widget.arguments[frame]['exp']='250'
        widget._sync()
        self.assertTrue(self.form.save())
        saved=parse_items(scroll.path,'project')[0]
        self.assertEqual(json.loads(saved.editor_metadata['item_actions'])[0]['values'],{'exp':'250'})

    def test_four_row_limit_preserves_legacy_five_row_assignments(self):
        widget=self.form.inputs['item_actions']
        for _ in range(8):widget.add_row()
        self.assertEqual(len(widget.rows),4)
        self.assertEqual(widget.add_button.cget('state'),'disabled')
        legacy=[{'id':self.identifier,'values':{'exp':str(amount)}} for amount in range(5)]
        widget.set_expression(json.dumps(legacy))
        self.assertEqual(json.loads(widget.get()),legacy)
        widget.add_row()
        self.assertEqual(len(widget.rows),5)
        widget.remove_row(widget.rows[0][0])
        self.assertEqual(len(widget.rows),4)
        self.assertEqual(widget.add_button.cget('state'),'disabled')
