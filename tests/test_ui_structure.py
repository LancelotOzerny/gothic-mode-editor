"""UI reorganization checks using synthetic data, never the working property JSON."""
import importlib
from pathlib import Path
import pkgutil
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

from gothic_editor.core.properties_schema import PropertiesSchema, PropertyField, PropertySection
from gothic_editor.ui.panels.properties import PropertiesPanel
from gothic_editor.ui.widgets.choice_field import ExpressionChoiceField
from gothic_editor.ui.widgets.icons import IconImages


class StructureTests(unittest.TestCase):
    def test_all_ui_modules_import_and_icons_keep_the_asset_directory(self):
        import gothic_editor.ui
        for module in pkgutil.walk_packages(gothic_editor.ui.__path__,gothic_editor.ui.__name__+'.'):
            importlib.import_module(module.name)
        self.assertEqual(IconImages(None).directory,Path(__file__).resolve().parents[1]/'assets/icons')

    def test_schema_loader_uses_only_properties_without_reading_any_schema(self):
        from gothic_editor.core.properties_schema import schema_for
        sentinel=object()
        with patch('gothic_editor.core.properties_schema.Path.is_file',return_value=True), \
                patch.object(PropertiesSchema,'load',return_value=sentinel) as read:
            self.assertIs(schema_for('potions'),sentinel)
        self.assertEqual(read.call_args.args[0].parts[-3:],('assets','properties','potion.json'))


class GenericFormTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.geometry('800x600')
        self.root.update()

    def test_fixed_scheme_source_replaces_extra_schema_options(self):
        from gothic_editor.core.item_options import item_options
        field=PropertyField('scemeName','Scheme',field_type='enum',widget='combobox',
                            options=(('Other','"FOOD"'),),options_source='item_schemes')
        form=PropertiesPanel(self.root,lambda *_:None,options_provider=lambda source:item_options(None,source))
        form.editable=True
        form.render_field(form.inner,field,'"POTIONFAST"')
        choice=form.inputs['scemeName']
        self.assertEqual(choice.options,[('Выпить','"POTION"'),('Выпить быстро','"POTIONFAST"')])
        self.assertEqual(choice.current(),1)

    def test_settings_window_builds_and_saves_without_opening_an_item(self):
        from gothic_editor.core.settings import EditorSettings
        from gothic_editor.ui.windows.settings import SettingsWindow
        self.root.repo=SimpleNamespace(root=None)
        saved=[]
        window=SettingsWindow(self.root,EditorSettings(),{},saved.append)
        self.root.update()
        self.assertTrue(window.values)
        window.save()
        self.assertEqual(len(saved),1)
        self.assertIn('interface.general.window_size',saved[0])
        self.assertFalse(window.winfo_exists())

    def test_form_controller_and_choice_window_with_synthetic_schema(self):
        schema=PropertiesSchema((PropertySection('general','General',(
            PropertyField('caption','Caption',field_type='string'),
            PropertyField('mode','Mode',field_type='enum',widget='combobox',options=(('First','MODE_A'),('Second','MODE_B'))),
        )),))
        item=SimpleNamespace(instance='DEMO',origin='project',fields={'caption':'"Before"','mode':'MODE_A'},editor_metadata={})
        saves=[]

        def save(current,values,**options):
            saves.append(dict(values))
            current.fields.update(values)
            return current

        with patch('gothic_editor.ui.panels.properties.schema_for',return_value=schema), \
                patch('gothic_editor.ui.panels.properties.classify',return_value='demo'), \
                patch('gothic_editor.ui.panels.properties.EDITABLE_CATEGORIES',frozenset({'demo'})):
            form=PropertiesPanel(self.root,save)
            form.pack(fill='both',expand=True)
            form.show(item)
        self.root.update()
        entry=form.inputs['caption']
        entry.delete(0,'end')
        entry.insert(0,'After')
        entry.event_generate('<FocusOut>')
        self.assertEqual(saves[-1],{'caption':'"After"'})
        self.assertIs(form.inputs['caption'],entry)
        choice=form.inputs['mode']
        self.assertIsInstance(choice,ExpressionChoiceField)
        choice.open_choices()
        self.root.update()
        window=choice.selection_window
        self.assertEqual((window.winfo_width(),window.winfo_height()),(480,320))
        window.focus_option(1)
        self.assertTrue(window.option_buttons[1].selected)
        window.choose_button.invoke()
        self.root.update()
        self.assertIsNone(choice.selection_window)
        self.assertEqual(choice.get(),'MODE_B')
        choice.event_generate('<FocusOut>')
        self.assertEqual(item.fields['mode'],'MODE_B')
        choice.open_choices()
        self.root.update()
        choice.selection_window.focus_option(0)
        choice.close_choices()
        self.assertEqual(choice.get(),'MODE_B')
        self.assertIsNone(self.root.grab_current())
