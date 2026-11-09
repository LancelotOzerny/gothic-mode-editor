"""Two-pane settings dialog rendered from the settings catalog."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from gothic_editor.core.localization import tr
from gothic_editor.core.settings import field_key, validate_value
from gothic_editor.core.settings_schema import FieldType, all_fields, categories
from gothic_editor.ui.widgets import BG, PANEL, TXT, MUTED, ACCENT, label
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea, attach_scrollbar
from .dialog import EditorDialog


from gothic_editor.ui.controllers.settings_form import SettingsFormRenderer

class SettingsWindow(EditorDialog):
    def __init__(self, parent, settings, project_values, on_save):
        super().__init__(parent, bg=BG)
        self.title(tr('settings.title'))
        self.geometry('800x520')
        self.minsize(680, 400)
        self.transient(parent)
        self.on_save = on_save
        self.values = {}
        for field in all_fields():
            value = project_values.get(field_key(field), field.default) if field.scope == 'project' else settings.get(field)
            parts = value if field.field_type is FieldType.SIZE else [value]
            variable_type = tk.BooleanVar if field.field_type is FieldType.BOOLEAN else tk.StringVar
            self.values[field_key(field)] = [variable_type(self, value=part) for part in parts]
        self.renderer = SettingsFormRenderer(self.values, parent.repo.root is not None)
        footer = tk.Frame(self, bg=BG)
        footer.pack(side='bottom', fill='x', padx=16, pady=12)
        self.add_button(footer,tr('settings.cancel'),self.destroy).pack(side='right')
        self.add_button(footer,tr('settings.save'),self.save).pack(side='right',padx=8)
        navigation = tk.Frame(self, bg=PANEL, width=190)
        navigation.pack(side='left', fill='y', padx=(12, 0), pady=(12, 0))
        navigation.pack_propagate(False)
        label(navigation, tr('settings.categories'), fg=ACCENT).pack(anchor='w', padx=12, pady=12)
        self.navigation = tk.Listbox(navigation, bg=PANEL, fg=TXT, selectbackground='#3a4d66',
                                     relief='flat', highlightthickness=0, exportselection=False)
        self.navigation_scrollbar=attach_scrollbar(navigation,self.navigation)
        self.navigation.pack(fill='both', expand=True, padx=6)
        self.categories = categories()
        for category in self.categories:
            self.navigation.insert('end', tr(category.title_key))
        self.navigation.bind('<<ListboxSelect>>', self.show_category)
        right = Panel(self)
        self.form = right
        right.pack(side='left', fill='both', expand=True, padx=16, pady=(12, 0))
        self.scroll_area=ScrollableArea(right)
        self.scroll_area.pack(fill='both',expand=True)
        self.canvas,self.content=self.scroll_area.canvas,self.scroll_area.content
        if self.categories:
            self.navigation.selection_set(0)
            self.show_category()
        self.bind('<Escape>', lambda _: self.destroy())
        self.show_centered(modal=True)

    def scroll(self, event):
        return self.scroll_area.wheel(event)

    def show_category(self, _event=None):
        selection = self.navigation.curselection()
        if not selection:
            return
        category = self.categories[selection[0]]
        for child in self.content.winfo_children():
            child.destroy()
        self.renderer.inputs.clear()
        label(self.content, tr(category.title_key), font=('Arial', 13, 'bold')).pack(anchor='w', pady=(0, 12))
        if not self.renderer.project_open and any(field.scope == 'project' for group in category.groups for field in group.fields):
            label(self.content, tr('settings.project_required'), fg=MUTED, wraplength=430).pack(anchor='w', pady=8)
        for group in category.groups:
            frame = self.form.add_group(tr(group.title_key),parent=self.content)
            for field in group.fields:
                self.renderer.render(frame.body, field)
        self.canvas.yview_moveto(0)

    def save(self):
        values = {}
        try:
            for field in all_fields():
                parts = [variable.get() for variable in self.values[field_key(field)]]
                if field.field_type in (FieldType.NUMBER, FieldType.SIZE):
                    try:
                        parts = [int(part) for part in parts]
                    except ValueError:
                        raise ValueError(tr('settings.invalid', name=tr(field.label_key))) from None
                value = parts if field.field_type is FieldType.SIZE else parts[0]
                values[field_key(field)] = validate_value(field, value)
            self.on_save(values)
        except (ValueError, OSError, tk.TclError) as exc:
            messagebox.showerror(tr('settings.error'), str(exc), parent=self)
            return
        self.destroy()
