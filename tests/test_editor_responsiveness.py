"""Editing/rendering regressions using temporary items and synthetic property schemas only."""
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from gothic_editor.app import EditorApp
from gothic_editor.core.mesh import PreviewMesh
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.properties_schema import PropertiesSchema, PropertyField, PropertySection
from gothic_editor.core.scripts import Item
from gothic_editor.core.settings import SettingsStore
from gothic_editor.ui.controllers.preview_renderer import PreviewRenderer
from gothic_editor.ui.panels.properties import PropertiesPanel


def schema():
    return PropertiesSchema((PropertySection('general','General',(
        PropertyField('instance','ID',source='instance_id',field_type='identifier',required=True,prefix='ItPo_'),
        PropertyField('name','Name',required=True),
        PropertyField('value','Value',field_type='expression'),
        PropertyField('mode','Mode',field_type='enum',widget='combobox',options=(('One','FIRST'),('Two','SECOND'))),
        PropertyField('rows','Inventory',field_type='key_value_list',max_rows=6,
            columns=(PropertyField('text','Text'),PropertyField('count','Count',field_type='expression')),
            reserved=(('text','NAME_Value'),)),
    )),))


def temporary_item(repo, name='ItPo_Test'):
    code=f'INSTANCE {name}(C_Item) {{ name="Before"; value=1; mainflag=ITEM_KAT_POTIONS; custom=BASE+2; }};'
    source=Item(name,repo.root/'synthetic.d','project',code,{},0,len(code))
    repo.components.import_item(source)
    repo.refresh()
    return next(i for i in repo.project_items if i.instance==name)


class DraftAutosaveTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.geometry('800x650')
        self.addCleanup(self.root.destroy)
        self.saved=[]
        self.item=Item('ItPo_Test',Path('synthetic.json'),'project','',{'name':'"Before"','value':'1','mode':'FIRST'},0,0)
        def save(current, values, **options):
            self.saved.append((dict(values),options))
            return replace(current,fields={**current.fields,**values},instance=options.get('instance',current.instance))
        with patch('gothic_editor.ui.panels.properties.schema_for',return_value=schema()):
            self.form=PropertiesPanel(self.root,save)
            self.form.pack(fill='both',expand=True)
            self.form.show(self.item)
        self.form.editor.AUTOSAVE_DELAY=60
        self.root.update()

    def tick(self, milliseconds=100):
        done=tk.BooleanVar(self.root,value=False)
        self.root.after(milliseconds,lambda:done.set(True))
        self.root.wait_variable(done)

    def change(self, key, value):
        entry=self.form.inputs[key]
        entry.delete(0,'end')
        entry.insert(0,value)
        return entry

    def test_typing_batches_saves_without_losing_focus_or_rebuilding_fields(self):
        entry=self.change('name','After')
        entry.focus_force()
        self.assertFalse(self.saved)
        self.assertEqual(self.form.editor.draft['name'],'After')
        self.assertIn('name',self.form.editor.dirty)
        self.tick()
        self.assertEqual(len(self.saved),1)
        self.assertEqual(self.saved[0][0],{'name':'"After"'})
        self.assertIs(self.root.focus_get(),entry)
        self.assertIs(self.form.inputs['name'],entry)
        self.assertFalse(self.form.editor.dirty)
        self.form.inputs['mode'].current(1)
        self.tick()
        self.assertEqual(self.saved[-1][0],{'mode':'SECOND'})

    def test_explicit_save_cancels_timer_and_reverting_draft_does_not_write(self):
        self.change('name','After')
        self.assertTrue(self.form.save())
        self.assertIsNone(self.form.editor._after)
        self.tick()
        self.assertEqual(len(self.saved),1)
        self.change('name','Temporary')
        self.change('name','After')
        self.tick()
        self.assertEqual(len(self.saved),1)

    def test_inventory_single_character_changes_save_and_invalid_values_stay_inline(self):
        rows=self.form.inputs['rows']
        rows.add_row()
        cells=rows.rows[0][2]
        cells[0][1].insert(0,'A')
        cells[1][1].insert(0,'2 minutes')
        self.tick()
        self.assertFalse(self.saved)
        self.assertEqual(cells[1][1].get(),'2 minutes')
        self.assertTrue(self.form.error_labels['rows'].winfo_ismapped())
        cells[1][1].delete(0,'end')
        cells[1][1].insert(0,'2')
        self.tick()
        self.assertEqual(self.saved[-1][0],{'text[0]':'"A"','count[0]':'2'})
        rows.remove_row(0)
        self.tick()
        self.assertEqual(self.saved[-1][0],{'text[0]':'','count[0]':''})

    def test_invalid_required_value_and_io_failure_keep_drafts_for_retry(self):
        self.change('name','')
        self.tick()
        self.assertFalse(self.saved)
        self.assertIn('name',self.form.editor.dirty)
        self.assertTrue(self.form.error_labels['name'].winfo_ismapped())
        self.change('name','Retry')
        with patch.object(self.form,'on_save',side_effect=OSError('Disk unavailable')):
            self.tick()
        self.assertEqual(self.form.inputs['name'].get(),'Retry')
        self.assertIn('name',self.form.editor.dirty)
        self.assertTrue(self.form.save())
        self.assertEqual(self.saved[-1][0],{'name':'"Retry"'})

    def test_switching_form_cancels_stale_timer_and_traces(self):
        self.change('name','Pending')
        with patch('gothic_editor.ui.panels.properties.schema_for',return_value=schema()):
            self.form.show(replace(self.item,instance='ItPo_Other'))
        self.tick()
        self.assertFalse(self.saved)


class IncrementalPersistenceTests(unittest.TestCase):
    def test_component_edit_and_rename_do_not_rescan_game_or_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=ProjectRepository()
            repo.create(Path(temporary)/'project','Test')
            item=temporary_item(repo)
            model=item.path.parent/'assets/model.3ds'
            model.parent.mkdir()
            model.write_bytes(b'synthetic model')
            repo.refresh()
            with patch.object(repo,'refresh',side_effect=AssertionError('Full scan')):
                updated=repo.edit(item,{'value':'PRICE+2'})
                updated=repo.edit(updated,{},instance='ItPo_Renamed')
            self.assertEqual(updated.fields['custom'],'BASE+2')
            self.assertEqual(updated.fields['value'],'PRICE+2')
            self.assertIn('model_itpo_renamed.3ds',repo.mesh_index)
            self.assertNotIn('model_itpo_test.3ds',repo.mesh_index)
            self.assertEqual(repo.project_items,[updated])
            self.assertEqual(repo.items,[updated])

    def test_copy_game_item_does_not_rescan_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=ProjectRepository()
            repo.create(Path(temporary)/'project','Test')
            repo.game=Path(temporary)/'game'
            source=Item('ItFo_Game',repo.game/'Items/source.d','game',
                        'INSTANCE ItFo_Game(C_Item) { name="Game"; mainflag=ITEM_KAT_FOOD; }',
                        {'name':'"Game"','mainflag':'ITEM_KAT_FOOD'},0,0)
            repo.game_items=[source]
            repo.items=[source]
            with patch.object(repo,'refresh',side_effect=AssertionError('Full scan')):
                copied=repo.copy_to_project(source)
            self.assertEqual(copied.instance,'ItFo_Game')
            self.assertEqual(copied.origin,'project')
            self.assertIn(copied,repo.project_items)

    def test_script_edit_reparses_only_its_file_and_preserves_neighbor_instances(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=ProjectRepository()
            repo.create(Path(temporary)/'project','Test')
            item=repo._write_new('ItSc_Test','INSTANCE ItSc_Test(C_Item) { mainflag=ITEM_KAT_RUNE; name="Scroll"; };\n'
                                'INSTANCE Other(C_Item) { name="Other"; };')
            with patch.object(repo,'refresh',side_effect=AssertionError('Full scan')):
                updated=repo.edit(item,{'value':'PRICE+2'})
            self.assertEqual(updated.fields['value'],'PRICE+2')
            self.assertEqual({i.instance for i in repo.project_items},{'ItSc_Test','Other'})


class ApplicationDraftTests(unittest.TestCase):
    def test_ctrl_s_switch_and_close_flush_drafts_and_reuse_hierarchy_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(root/'settings.json')):
                app=EditorApp()
            try:
                app.repo.create(root/'project','Test')
                item=temporary_item(app.repo)
                second=temporary_item(app.repo,'ItPo_Second')
                app.show_project()
                with patch('gothic_editor.ui.panels.properties.schema_for',return_value=schema()):
                    app.hierarchy.choose(item)
                    app.select(item)
                    app.update()
                    section=app.hierarchy.sections['project']
                    row=section.item_rows[app.hierarchy.item_key(item)]
                    name=app.properties.inputs['name']
                    name.delete(0,'end')
                    name.insert(0,'Saved in focus')
                    app.select(app.current)
                    self.assertIs(app.properties.inputs['name'],name)
                    self.assertTrue(app.properties.editor.dirty)
                    name.focus_force()
                    app.update()
                    with patch.object(app.repo,'refresh',side_effect=AssertionError('Full scan')):
                        name.event_generate('<Control-KeyPress>',keycode=83)
                        self.assertEqual(app.current.fields['name'],'"Saved in focus"')
                        self.assertIs(section.item_rows[app.hierarchy.item_key(item)],row)
                        self.assertEqual(row.item.fields['name'],'"Saved in focus"')
                        self.assertIs(app.properties.inputs['name'],name)
                    name.insert('end',' again')
                    app.select(second)
                    self.assertEqual(next(i for i in app.repo.project_items if i.instance==item.instance).fields['name'],
                                     '"Saved in focus again"')
                    other_root=root/'other'
                    ProjectRepository().create(other_root,'Other')
                    original_root=app.repo.root
                    pending=app.properties.inputs['name']
                    pending.delete(0,'end')
                    app.open_project_path(other_root)
                    self.assertEqual(app.repo.root,original_root)
                    pending.insert(0,'Saved before project switch')
                    app.open_project_path(other_root)
                    self.assertEqual(app.repo.root,other_root)
                    data=json.loads(second.path.read_text('utf-8'))
                    self.assertEqual(data['fields']['name'],'"Saved before project switch"')
                    app.open_project_path(original_root)
                    app.select(next(i for i in app.repo.project_items if i.instance==second.instance))
                    current=app.properties.inputs['name']
                    current.delete(0,'end')
                    app.destroy()
                    self.assertTrue(app.winfo_exists())
                    current.insert(0,'Saved on close')
                    app.destroy()
                    app=None
            finally:
                if app is not None:
                    app.properties.show(None)
                    app.destroy()


class RenderSchedulingTests(unittest.TestCase):
    def test_only_latest_camera_is_queued_and_scene_is_sent_once(self):
        owner=SimpleNamespace(after=Mock(return_value='poll'),after_cancel=Mock())
        frames,errors=Mock(),Mock()
        executor=Mock()
        futures=[]
        def submit(*args):
            future=Future()
            futures.append(future)
            return future
        executor.submit.side_effect=submit
        renderer=PreviewRenderer(owner,frames,errors)
        mesh=PreviewMesh([],[])
        with patch('gothic_editor.ui.controllers.preview_renderer.ProcessPoolExecutor',return_value=executor):
            renderer.request((1,0),mesh,{},(1,1,0,0,1,False))
            for camera in range(1,10):renderer.request((1,camera),mesh,{},(1,1,0,camera,1,False))
            self.assertEqual(executor.submit.call_count,1)
            futures[0].set_result(b'first')
            renderer._poll()
            self.assertEqual(executor.submit.call_count,2)
            self.assertIsNone(executor.submit.call_args.args[1])
            self.assertEqual(executor.submit.call_args.args[2][3],9)
            futures[1].set_result(b'latest')
            renderer._poll()
            frames.assert_any_call((1,9),b'latest')
            renderer.close()
        errors.assert_not_called()


if __name__=='__main__':unittest.main()
