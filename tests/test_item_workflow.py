"""Fast item workflows and terminal tests, using only temporary/synthetic assets."""
from dataclasses import replace
from pathlib import Path
from queue import Empty,Queue
from time import monotonic
from types import SimpleNamespace
import shutil
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch,Mock

from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.model_preview import ModelPreviewCache
from gothic_editor.core.model_export import export_texture
from gothic_editor.core.properties_schema import schema_for,_SCHEMA_CACHE
from gothic_editor.core.powershell import PowerShellSession
from gothic_editor.core.textures import read_tga,Texture
from gothic_editor.ui.panels.properties import PropertiesPanel
from gothic_editor.ui.panels.hierarchy import HierarchyPanel,CategoryRow
from gothic_editor.ui.panels.resources import ResourcesPanel
from gothic_editor.ui.panels.terminal import TerminalPanel
from gothic_editor.app import EditorApp
from gothic_editor.core.settings import SettingsStore
from test_editor_responsiveness import temporary_item,schema
from test_model_preview import textured_3ds,tga


class FastRepositoryTests(unittest.TestCase):
    def test_schema_cache_observes_only_dependency_stamps(self):
        with tempfile.TemporaryDirectory() as temporary:
            dependency=Path(temporary)/'synthetic.json'
            dependency.write_text('{}')
            first=replace(schema(),dependencies=(dependency,))
            second=replace(schema(),dependencies=(dependency,))
            _SCHEMA_CACHE.clear()
            self.addCleanup(_SCHEMA_CACHE.clear)
            with patch('gothic_editor.core.properties_schema.Path.is_file',return_value=True), \
                    patch('gothic_editor.core.properties_schema.PropertiesSchema.load',side_effect=[first,second]) as load:
                self.assertIs(schema_for('potions'),first)
                self.assertIs(schema_for('potions'),first)
                dependency.write_text('{"changed":true}')
                self.assertIs(schema_for('potions'),second)
                self.assertEqual(load.call_count,2)

    def test_duplicate_keeps_unknown_fields_without_creating_item_folders(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=ProjectRepository()
            repo.create(Path(temporary)/'project','Test')
            item=temporary_item(repo)
            with patch.object(repo,'refresh',side_effect=AssertionError('Unexpected full scan')):
                copied=repo.duplicate(item)
                edited=repo.edit(copied,{'name':'"Changed"'})
                other=repo._write_new('ItSc_Test','INSTANCE ItSc_Test(C_Item) {mainflag=ITEM_KAT_RUNE;};')
            self.assertEqual(edited.fields['custom'],'BASE+2')
            self.assertEqual(copied.path.parent,item.path.parent)
            self.assertEqual(set(path.name for path in item.path.parent.iterdir()),
                             {item.path.name,copied.path.name})
            self.assertEqual(item.fields['name'],'"Before"')
            self.assertIn(other,repo.items)
            self.assertEqual(len(repo.project_items),3)

    def test_geometry_cache_skips_texture_scan_and_invalidates_model_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/'model.3ds'
            source.write_bytes(textured_3ds())
            cache=ModelPreviewCache(2)
            key=cache.key(source,1,False)
            with patch('gothic_editor.core.model_preview.os.walk',side_effect=AssertionError('Texture scan')):
                preview=cache.load(key,source,root,with_textures=False)
            self.assertFalse(preview.textures_loaded)
            self.assertIs(cache.get(key),preview)
            self.assertEqual(key,cache.key(source,1,False,root/'other'))
            source.write_bytes(textured_3ds()+b'changed')
            self.assertNotEqual(key,cache.key(source,1,False))

    def test_export_decoded_texture_round_trips_alpha_and_original_tga(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            texture=Texture(2,1,bytes((5,10,20,128,30,40,50,255)))
            export_texture(texture,None,root/'export.tga')
            self.assertEqual(read_tga((root/'export.tga').read_bytes()),texture)
            source=root/'original.tga'
            source.write_bytes(tga())
            export_texture(read_tga(tga()),source,root/'copy.tga')
            self.assertEqual((root/'copy.tga').read_bytes(),source.read_bytes())


class WorkflowWidgetsTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.geometry('800x650')
        self.addCleanup(self.root.destroy)

    def test_switch_reuses_form_with_correct_choices_and_no_dirty_draft(self):
        item=SimpleNamespace(instance='ItPo_First',origin='project',fields={'mainflag':'ITEM_KAT_POTIONS',
            'name':'"First"','value':'1','mode':'FIRST'},editor_metadata={})
        other=SimpleNamespace(**{**vars(item),'instance':'ItPo_Second','fields':{**item.fields,'name':'"Second"','mode':'SECOND'}})
        with patch('gothic_editor.ui.panels.properties.schema_for',return_value=schema()):
            form=PropertiesPanel(self.root,lambda *_:None)
            form.pack(fill='both',expand=True)
            form.show(item)
            entry=form.inputs['name']
            choice=form.inputs['mode']
            form.show(other)
            self.assertIs(form.inputs['name'],entry)
            self.assertIs(form.inputs['mode'],choice)
            self.assertEqual(entry.get(),'Second')
            self.assertEqual(choice.get(),'SECOND')
            self.assertEqual(choice.current(),1)
            self.assertFalse(form.editor.dirty)
            entry.value_variable.set('Draft')
            self.assertEqual(form.editor.dirty,{'name'})

    def test_hierarchy_filters_empty_branches_and_keyboard_ignores_entries(self):
        calls=[]
        item=SimpleNamespace(instance='ItPo_Test',title='Bottle',origin='project',fields={'mainflag':'ITEM_KAT_POTIONS'})
        hierarchy=HierarchyPanel(self.root,lambda _:None,lambda _:None,
            lambda value:calls.append(('copy',value)),lambda value:calls.append(('delete',value)),lambda *_:None)
        hierarchy.pack(fill='both',expand=True)
        hierarchy.set_items([item])
        hierarchy.search.set('bottle')
        section=hierarchy.sections['project']
        categories=[child for child in section.inner.winfo_children() if isinstance(child,CategoryRow)]
        self.assertEqual([child.category.key for child in categories],['potions'])
        hierarchy.selected=hierarchy.item_key(item)
        self.root.update()
        hierarchy.focus_force()
        hierarchy.shortcut(SimpleNamespace(keysym='d',keycode=68))
        hierarchy.shortcut(SimpleNamespace(keysym='Delete',keycode=46))
        self.assertEqual([call[0] for call in calls],['copy','delete'])
        entry=tk.Entry(hierarchy)
        entry.pack()
        self.root.update()
        entry.focus_force()
        hierarchy.shortcut(SimpleNamespace(keysym='Delete',keycode=46))
        self.assertEqual(len(calls),2)
        hierarchy.search.set('missing')
        self.assertFalse(any(isinstance(child,CategoryRow) for child in section.inner.winfo_children()))
        self.assertTrue(any(child.cget('text')=='Ничего не найдено' for child in section.inner.winfo_children()))

    def test_resource_tiles_resize_and_preserve_selection_on_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            folder=root/'Items/Potions/ItPo_Test'
            folder.mkdir(parents=True)
            for name in ('item.json','params.json','functions.d'):(folder/name).write_text('{}')
            item=SimpleNamespace(instance='ItPo_Test',path=folder/'item.json')
            panel=ResourcesPanel(self.root,lambda:'',lambda:None)
            panel.pack(fill='both',expand=True)
            panel.set_item(root,item)
            self.root.update()
            self.assertEqual(len(panel.tiles),3)
            self.assertGreater(panel.columns,1)
            panel.select_file(item.path)
            panel.refresh()
            self.assertEqual(panel.selected_file(),item.path)
            self.root.geometry('200x500')
            self.root.update()
            self.assertEqual(panel.columns,1)
            self.assertNotEqual(panel.scroll_area.canvas.cget('bg'),'white')

    def test_inserting_item_keeps_rows_and_download_menu_targets_clicked_item(self):
        calls=[]
        item=SimpleNamespace(instance='ItPo_First',title='A',origin='project',fields={'mainflag':'ITEM_KAT_POTIONS'})
        copied=SimpleNamespace(instance='ItPo_Copy',title='B',origin='project',fields=item.fields)
        hierarchy=HierarchyPanel(self.root,lambda _:None,lambda _:None,lambda _:None,lambda _:None,lambda *_:None,
            on_export_model=lambda value:calls.append(('model',value)),
            on_export_texture=lambda value:calls.append(('texture',value)))
        hierarchy.pack(fill='both',expand=True)
        hierarchy.set_items([item])
        hierarchy.choose(item)
        section=hierarchy.sections['project']
        before=section.item_rows[hierarchy.item_key(item)]
        with patch.object(section,'rebuild',side_effect=AssertionError('Unexpected rebuild')):
            hierarchy.insert_item(copied,[item,copied])
            hierarchy.choose(copied)
        self.assertIs(section.item_rows[hierarchy.item_key(item)],before)
        self.assertEqual(section.count(section.category_rows['potions'].category),2)
        with patch('tkinter.Menu.tk_popup'):
            hierarchy.context(SimpleNamespace(x_root=0,y_root=0),copied)
        menu=hierarchy._context_menu
        self.assertEqual(menu.entrycget(0,'accelerator'),'Ctrl+D')
        self.assertEqual(menu.entrycget(1,'accelerator'),'Delete')
        submenu=menu.nametowidget(menu.entrycget(2,'menu'))
        submenu.invoke(0)
        submenu.invoke(1)
        self.assertEqual(calls,[('model',copied),('texture',copied)])

    def test_terminal_input_history_output_and_session_survive_panel_replacement(self):
        session=SimpleNamespace(cwd=Path.cwd(),events=Queue(),running=False,close=Mock())
        def execute(command):
            session.running=True
            session.events.put(('output','result: '+command))
            session.events.put(('done',str(session.cwd)))
        session.execute=Mock(side_effect=execute)
        panel=TerminalPanel(self.root,lambda:None)
        panel.pack(fill='both',expand=True)
        panel.command.insert(0,'dir')
        with patch('gothic_editor.ui.panels.terminal.PowerShellSession',return_value=session):panel.execute()
        panel.after_cancel(panel._poll_id)
        panel.poll()
        self.assertIn('result: dir',panel.log.get('1.0','end'))
        self.assertFalse(session.running)
        panel.navigate_history(-1)
        self.assertEqual(panel.command.get(),'dir')
        panel.command.selection_range(0,'end')
        panel.copy_or_stop()
        self.assertEqual(self.root.clipboard_get(),'dir')
        state=panel.detach()
        panel.destroy()
        session.close.assert_not_called()
        replacement=TerminalPanel(self.root,lambda:None)
        replacement.adopt(state)
        self.assertIs(replacement.session,session)
        self.assertEqual(replacement.command.get(),'dir')
        replacement.stop()
        session.close.assert_called_once()


class WorkflowApplicationTests(unittest.TestCase):
    def test_duplicate_flushes_focused_draft_and_reuses_existing_form_and_row(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        with patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(root/'settings.json')):
            app=EditorApp()
        self.addCleanup(app.destroy)
        app.withdraw()
        app.repo.create(root/'project','Test')
        item=temporary_item(app.repo)
        app.show_project()
        with patch('gothic_editor.ui.panels.properties.schema_for',return_value=schema()):
            app.hierarchy.choose(item)
            app.select(item)
            field=app.properties.inputs['name']
            row=app.hierarchy.sections['project'].item_rows[app.hierarchy.item_key(item)]
            field.delete(0,'end')
            field.insert(0,'Focused draft')
            with patch.object(app.repo,'refresh',side_effect=AssertionError('Unexpected scan')):
                app.duplicate(item)
            self.assertEqual(len(app.repo.project_items),2)
            self.assertEqual(app.current.fields['name'],'"Focused draft"')
            self.assertNotEqual(app.current.instance,item.instance)
            self.assertIs(app.properties.inputs['name'],field)
            self.assertIs(app.hierarchy.sections['project'].item_rows[app.hierarchy.item_key(item)],row)
            self.assertFalse(app.properties.editor.dirty)


@unittest.skipUnless(shutil.which('powershell') or shutil.which('pwsh'),'PowerShell required')
class PowerShellTests(unittest.TestCase):
    def run_command(self,session,command):
        session.execute(command)
        deadline=monotonic()+15
        output=[]
        while monotonic()<deadline:
            try:kind,value=session.events.get(timeout=.1)
            except Empty:continue
            if kind=='output':output.append(value)
            elif kind=='done':
                session.running=False
                session.cwd=Path(value)
                return '\n'.join(output)
            elif kind=='exit':self.fail(f'PowerShell exited: {value}; output: {output}')
        self.fail(f'Command timed out: {output}')

    def test_commands_persist_location_variables_unicode_and_recover_after_error(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        (root/'child').mkdir()
        (root/'example.txt').write_text('example')
        session=PowerShellSession(root)
        self.addCleanup(lambda:session.close().join(5))
        self.assertIn('example.txt',self.run_command(session,'dir -Name'))
        self.run_command(session,"$testValue = 'Привет'; Set-Location child")
        self.assertEqual(session.cwd,root/'child')
        self.assertIn('Привет',self.run_command(session,'Write-Output $testValue'))
        self.assertIn('Start-Process',self.run_command(session,'(Get-Command start).Definition'))
        self.run_command(session,'bad-command-not-found')
        self.assertIn('after error',self.run_command(session,"'after error'"))
        self.assertIn('if (',self.run_command(session,'if ('))
        self.assertIn('still alive',self.run_command(session,"'still alive'"))
        session.close().join(5)
        self.assertIsNotNone(session.process.poll())
