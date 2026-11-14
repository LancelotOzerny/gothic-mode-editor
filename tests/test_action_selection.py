"""Generic grouped choices, function discovery and metadata compatibility."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from gothic_editor.core.item_options import item_options
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.properties_schema import PropertyField, PropertySection, PropertiesSchema
from gothic_editor.core.item_spreadsheet import export_items, ItemSpreadsheetService
from gothic_editor.ui.widgets.choice_list import ChoiceList
from gothic_editor.ui.panels.properties import PropertiesPanel
from test_editor_responsiveness import temporary_item


FIELD=PropertyField('item_actions','Actions',source='editor_metadata',export=False,
                    field_type='choice_list',max_rows=5,options_source='item_actions')
SCHEMA=PropertiesSchema((PropertySection('actions','Actions',(FIELD,)),))
GROUPS=[('Project',[('Content/Use.d','project:Assets/Scripts/Content/Use.d')]),
        ('Gothic',[('Content/Use.d','game:Content/Use.d')])]


class ScriptChoiceTests(unittest.TestCase):
    def test_discovery_is_grouped_cached_and_never_modifies_scripts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            repo=ProjectRepository()
            repo.create(root/'project','Test')
            user=repo.root/'Assets/Scripts/Actions/User.d'
            user.parent.mkdir()
            user.write_bytes(b'func void UserAction() {};')
            game=root/'game/_work/data/Scripts/Content'
            (game/'Items').mkdir(parents=True)
            standard=game/'Items/Original.D'
            standard.write_bytes(b'func void OriginalAction() {};')
            repo.game=root/'game'
            groups=item_options(repo,'item_actions')
            self.assertIn('project:Assets/Scripts/Actions/User.d#UserAction',[value for _,value in groups[0][1]])
            self.assertIn('game:Content/Items/Original.D#OriginalAction',[value for _,value in groups[1][1]])
            with patch.object(Path,'rglob',side_effect=AssertionError('Repeated scan')):
                self.assertEqual(item_options(repo,'item_actions'),groups)
            self.assertEqual(user.read_bytes(),b'func void UserAction() {};')
            self.assertEqual(standard.read_bytes(),b'func void OriginalAction() {};')

    def test_metadata_survives_reopen_duplicate_xlsx_and_does_not_generate_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=ProjectRepository()
            repo.create(Path(temporary)/'project','Test')
            item=temporary_item(repo)
            value=json.dumps(['project:Assets/Scripts/Use.d','game:Content/Use.d',''])
            item=repo.edit(item,{},metadata={'item_actions':value})
            self.assertEqual(repo.duplicate(item).editor_metadata['item_actions'],value)
            repo.open(repo.root)
            current=next(i for i in repo.items if i.instance==item.instance)
            self.assertEqual(current.editor_metadata['item_actions'],value)
            _,additions,helpers=repo.components.generated()
            self.assertFalse(helpers)
            self.assertNotIn('item_actions',''.join(additions))
            self.assertNotIn('on_state',''.join(additions))
            sheet=Path(temporary)/'items.xlsx'
            export_items([current],sheet)
            with patch('gothic_editor.core.item_spreadsheet.schema_for',return_value=SCHEMA):
                ItemSpreadsheetService(repo).import_file(sheet,'replace')
            self.assertEqual(next(i for i in repo.items if i.instance==item.instance).editor_metadata['item_actions'],value)


class ChoiceListTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.addCleanup(self.root.destroy)
        self.widget=ChoiceList(self.root,FIELD,'',lambda:GROUPS)
        self.widget.pack(fill='both',expand=True)
        self.root.update_idletasks()

    def test_default_limit_remove_and_empty_list(self):
        self.assertEqual(json.loads(self.widget.get()),[''])
        self.assertEqual(self.widget.rows[0][1].variable.get(),'Нет')
        for _ in range(10):self.widget.add_row()
        self.assertEqual(len(self.widget.rows),5)
        self.assertEqual(self.widget.add_button.cget('state'),'disabled')
        for frame,_ in list(self.widget.rows):self.widget.remove_row(frame)
        self.assertEqual(json.loads(self.widget.get()),[])
        self.assertEqual(self.widget.add_button.cget('state'),'normal')

    def test_invalid_saved_list_does_not_replace_visible_choices(self):
        for value in ('{}','[1]','["", "", "", "", "", ""]'):
            with self.assertRaises(ValueError):self.widget.set_expression(value)
        self.assertEqual(json.loads(self.widget.get()),[''])

    def test_picker_groups_search_and_distinct_choices_with_same_filename(self):
        entry=self.widget.rows[0][1]
        entry.open_choices()
        picker=entry.selection_window
        roots=picker.tree.get_children()
        self.assertEqual([picker.tree.item(node,'text') for node in roots],['Нет','Project','Gothic'])
        game=picker.tree.get_children(roots[2])[0]
        picker.tree.selection_set(game)
        picker.selected()
        picker.apply()
        self.assertEqual(json.loads(self.widget.get()),['game:Content/Use.d'])
        self.assertIn('Gothic',entry.variable.get())
        entry.open_choices()
        picker=entry.selection_window
        self.assertEqual(picker.values[picker.tree.selection()[0]],'game:Content/Use.d')
        picker.query.set('not found')
        self.assertEqual(len(picker.values),1)
        picker.on_cancel()
        self.assertEqual(json.loads(self.widget.get()),['game:Content/Use.d'])

    def test_readonly_blocks_edits_and_missing_choice_is_preserved(self):
        self.widget.destroy()
        self.widget=ChoiceList(self.root,FIELD,'["game:Missing.d"]',lambda:GROUPS,editable=False)
        self.widget.add_row()
        self.widget.remove_row(self.widget.rows[0][0])
        entry=self.widget.rows[0][1]
        entry.open_choices()
        self.assertIsNone(entry.selection_window)
        self.assertEqual(json.loads(self.widget.get()),['game:Missing.d'])

    def test_form_autosave_and_reuse_do_not_mix_item_selections(self):
        from dataclasses import replace
        from gothic_editor.core.scripts import Item
        saved=[]
        item=Item('ItPo_Test',Path('synthetic.json'),'project','',{'mainflag':'ITEM_KAT_POTIONS'},0,0)
        def save(current,values,**options):
            saved.append((values,options))
            return replace(current,editor_metadata={**current.editor_metadata,**options.get('metadata',{})})
        with patch('gothic_editor.ui.panels.properties.schema_for',return_value=SCHEMA):
            form=PropertiesPanel(self.root,save,options_provider=lambda _:GROUPS)
            form.show(item)
            entry=form.inputs['item_actions']
            entry.rows[0][1].set_expression('game:Content/Use.d')
            self.assertTrue(form.save())
            self.assertEqual(saved[-1][0],{})
            self.assertEqual(json.loads(saved[-1][1]['metadata']['item_actions']),['game:Content/Use.d'])
            other=replace(item,instance='ItPo_Other')
            form.show(other)
            self.assertIs(form.inputs['item_actions'],entry)
            self.assertEqual(json.loads(entry.get()),[''])
            self.assertFalse(form.editor.dirty)
            form.show(replace(item,editor_metadata={'item_actions':'["game:Content/Use.d"]'}))
            self.assertEqual(json.loads(entry.get()),['game:Content/Use.d'])
