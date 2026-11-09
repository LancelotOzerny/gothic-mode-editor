"""Shared UI behavior: native editing, scoped scrolling, resize and dialog policy."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.settings import SettingsStore
from gothic_editor.core.scripts import Item
from gothic_editor.ui.controllers.item_appearance import ItemAppearanceController
from gothic_editor.ui.widgets.choice_field import ExpressionChoiceField
from gothic_editor.ui.widgets.buttons import PropertyButton
from gothic_editor.ui.widgets.inputs import PropertyEntry, NumberField, make_entry
from gothic_editor.ui.widgets.form import create_field, FormGroup
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets.scrollbar import RoundedScrollbar
from gothic_editor.ui.windows.dialog import EditorDialog


class SharedWidgetTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry('700x500+30+30')
        self.root.update()
        try:self.original_clipboard = self.root.clipboard_get()
        except tk.TclError:self.original_clipboard = None
        self.addCleanup(self.close)

    def close(self):
        if self.original_clipboard is not None:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.original_clipboard)
        self.root.destroy()

    def key(self, entry, key):
        entry.focus_force()
        self.root.update()
        if self.root.tk.call('tk','windowingsystem') == 'win32':
            codes={'a':65,'c':67,'v':86,'x':88,'Cyrillic_ef':65,'Cyrillic_es':67,
                   'Cyrillic_em':86,'Cyrillic_che':88}
            entry.event_generate('<Control-KeyPress>',keycode=codes[key])
        else:
            entry.event_generate('<Control-KeyPress>', keysym=key)
        self.root.update()

    def test_native_clipboard_shortcuts_for_text_and_number_including_cyrillic_keys(self):
        for factory in (PropertyEntry, NumberField, make_entry):
            with self.subTest(factory=factory):
                entry = factory(self.root)
                entry.pack(fill='x')
                entry.insert(0,'123456')
                self.key(entry,'a')
                self.assertEqual((entry.index('sel.first'),entry.index('sel.last')),(0,6))
                self.key(entry,'c')
                self.assertEqual(self.root.clipboard_get(),'123456')
                self.key(entry,'x')
                self.assertEqual(entry.get(),'')
                self.key(entry,'v')
                self.assertEqual(entry.get(),'123456')
                self.key(entry,'Cyrillic_ef')
                self.root.clipboard_clear()
                self.root.clipboard_append('-42')
                self.key(entry,'Cyrillic_em')
                self.assertEqual(entry.get(),'-42')
                self.key(entry,'Cyrillic_ef')
                self.key(entry,'Cyrillic_es')
                self.assertEqual(self.root.clipboard_get(),'-42')
                self.key(entry,'Cyrillic_che')
                self.assertEqual(entry.get(),'')
                entry.surface.destroy()

    def test_readonly_copy_and_disabled_number_stepping_do_not_change_values(self):
        entry = create_field(self.root,value='Read only',readonly=True)
        entry.pack(fill='x')
        self.key(entry,'a')
        self.key(entry,'c')
        self.assertEqual(self.root.clipboard_get(),'Read only')
        self.key(entry,'x')
        self.key(entry,'v')
        self.assertEqual(entry.get(),'Read only')
        number=create_field(self.root,'number',value='3',minimum=2,maximum=4)
        number.step(10)
        self.assertEqual(number.get(),'4')
        number.step(-10)
        self.assertEqual(number.get(),'2')
        number.config(state='disabled')
        number.step(1)
        self.assertEqual(number.get(),'2')

    def test_panel_builder_and_choice_values_use_the_same_widgets(self):
        panel=Panel(self.root)
        panel.pack(fill='both',expand=True)
        group=panel.add_group('Group')
        self.assertIsInstance(group,FormGroup)
        text=group.add_field('Name',value='Initial')
        self.assertIsInstance(text,PropertyEntry)
        flag=tk.BooleanVar(self.root,value=False)
        toggle=group.add_field('Enabled',kind='boolean',variable=flag)
        toggle.invoke()
        self.assertTrue(flag.get())
        value=tk.StringVar(self.root,value='first')
        choice=group.add_field('Choice',kind='choice',variable=value,options=(('One','first'),('Two','second')))
        choice.current(1)
        self.assertEqual(value.get(),'second')
        value.set('first')
        self.assertEqual(choice.get(),'first')
        command=unittest.mock.Mock()
        group.add_button('Run',command).invoke()
        command.assert_called_once()
        group.destroy()
        value.set('second')  # Destroyed fields must not leave traces behind.
        flag.set(False)

    def test_scroll_over_children_is_scoped_and_destroy_removes_bindings(self):
        before=self.root.bind('<MouseWheel>') or ''
        left,right=ScrollableArea(self.root),ScrollableArea(self.root)
        for area in (left,right):
            area.pack(side='left',fill='both',expand=True)
            for index in range(40):
                tk.Label(area.content,text=str(index),height=2).pack(fill='x')
        self.root.update()
        self.assertIsInstance(left.scrollbar,RoundedScrollbar)
        child=left.content.winfo_children()[0]
        child.event_generate('<MouseWheel>',delta=-120,x=1,y=1)
        self.root.update()
        self.assertGreater(left.canvas.yview()[0],0)
        self.assertEqual(right.canvas.yview()[0],0)
        left.destroy()
        right.destroy()
        self.assertEqual(self.root.bind('<MouseWheel>') or '',before)

    def test_common_dialog_keeps_modal_policy_explicit(self):
        dialog=EditorDialog(self.root)
        dialog.geometry('480x320')
        dialog.show_centered()
        self.assertIsNone(self.root.grab_current())
        dialog.show_centered(modal=True)
        self.assertIs(self.root.grab_current(),dialog)
        dialog.destroy()
        self.assertIsNone(self.root.grab_current())


    def test_model_picker_uses_shared_fields_and_keeps_its_selection(self):
        self.root.repo=SimpleNamespace(project_items=[],mesh_index={
            'a.3ds':Path('A.3ds'),'b.3ds':Path('B.3ds')},
            archive_models=SimpleNamespace(entries={}),components=SimpleNamespace(owns=lambda _:False))
        self.root.save_fields=unittest.mock.Mock()
        item=Item('ItSc_Test',Path('test.d'),'project','',{'mainflag':'ITEM_KAT_RUNE'},0,0)
        ItemAppearanceController(self.root).choose(item)
        window=next(w for w in self.root.winfo_children() if isinstance(w,EditorDialog))
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        widgets=list(descendants(window))
        search=next(w for w in widgets if isinstance(w,PropertyEntry) and not isinstance(w,ExpressionChoiceField))
        choice=next(w for w in widgets if isinstance(w,ExpressionChoiceField))
        search.insert(0,'B.')
        self.assertEqual(choice.get(),'B.3ds')
        choice.open_choices()
        self.root.update()
        self.assertIs(self.root.grab_current(),window)
        choice.selection_window.apply(0)
        next(w for w in window.winfo_children() if isinstance(w,PropertyButton)).invoke()
        self.root.save_fields.assert_called_once_with(item,{'visual':'"B.3ds"'})


class SharedPanelLayoutTests(unittest.TestCase):
    def test_workspace_panels_keep_sashes_and_expand_with_the_editor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with patch('gothic_editor.app.SettingsStore',return_value=SettingsStore(root/'settings.json')):
                app=EditorApp()
            try:
                app.repo.create(root/'project','Test')
                app.show_project()
                app.geometry('1200x850')
                app.update()
                panes=app.hierarchy.master
                before=app.hierarchy.winfo_width()
                panes.sash_place(0,250,0)
                app.update()
                self.assertNotEqual(app.hierarchy.winfo_width(),before)
                before=app.properties.winfo_width()
                panes.sash_place(1,760,0)
                app.update()
                self.assertNotEqual(app.properties.winfo_width(),before)
                app.workspace.sash_place(0,0,400)
                app.update()
                for panel in (app.terminal,app.resources):
                    self.assertIsInstance(panel,Panel)
                    app.bottom_dock.select(panel)
                    app.update()
                    self.assertGreater(panel.winfo_width(),500)
                    self.assertGreater(panel.winfo_height(),100)
                    self.assertIsInstance(panel.scrollbar,RoundedScrollbar)
                self.assertIsInstance(app.properties.scroll_area,ScrollableArea)
                self.assertTrue(all(isinstance(s.scroll_area,ScrollableArea) for s in app.hierarchy.sections.values()))
            finally:app.destroy()


if __name__ == '__main__':unittest.main()
