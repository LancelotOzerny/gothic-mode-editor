"""Two-pane settings dialog rendered from the settings catalog."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from gothic_editor.core.localization import tr
from gothic_editor.core.settings import field_key, validate_value
from gothic_editor.core.settings_schema import FieldType, all_fields, categories
from gothic_editor.ui.widgets import BG, PANEL, TXT, MUTED, ACCENT, label


from gothic_editor.ui.controllers.settings_form import SettingsFormRenderer

class SettingsWindow(tk.Toplevel):
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
        ttk.Button(footer, text=tr('settings.cancel'), command=self.destroy).pack(side='right')
        ttk.Button(footer, text=tr('settings.save'), command=self.save).pack(side='right', padx=8)
        navigation = tk.Frame(self, bg=PANEL, width=190)
        navigation.pack(side='left', fill='y', padx=(12, 0), pady=(12, 0))
        navigation.pack_propagate(False)
        label(navigation, tr('settings.categories'), fg=ACCENT).pack(anchor='w', padx=12, pady=12)
        self.navigation = tk.Listbox(navigation, bg=PANEL, fg=TXT, selectbackground='#3a4d66',
                                     relief='flat', highlightthickness=0, exportselection=False)
        self.navigation.pack(fill='both', expand=True, padx=6)
        self.categories = categories()
        for category in self.categories:
            self.navigation.insert('end', tr(category.title_key))
        self.navigation.bind('<<ListboxSelect>>', self.show_category)
        right = tk.Frame(self, bg=BG)
        right.pack(side='left', fill='both', expand=True, padx=16, pady=(12, 0))
        self.canvas = tk.Canvas(right, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(right, orient='vertical', command=self.canvas.yview)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.config(yscrollcommand=scroll.set)
        self.content = tk.Frame(self.canvas, bg=BG)
        item = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self.content.bind('<Configure>', lambda _: self.canvas.config(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(item, width=event.width))
        self.bind('<MouseWheel>', self.scroll)
        if self.categories:
            self.navigation.selection_set(0)
            self.show_category()
        self.bind('<Escape>', lambda _: self.destroy())
        self.update_idletasks()
        parent.update_idletasks()
        x=parent.winfo_rootx()+(parent.winfo_width()-self.winfo_width())//2
        y=parent.winfo_rooty()+(parent.winfo_height()-self.winfo_height())//2
        self.geometry(f'+{max(0,x)}+{max(0,y)}')
        self.grab_set()

    def scroll(self, event):
        if self.canvas.winfo_rootx() <= event.x_root < self.canvas.winfo_rootx() + self.canvas.winfo_width():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')

    def show_category(self, _event=None):
        selection = self.navigation.curselection()
        if not selection:
            return
        category = self.categories[selection[0]]
        for child in self.content.winfo_children():
            child.destroy()
        label(self.content, tr(category.title_key), bg=BG, font=('Arial', 13, 'bold')).pack(anchor='w', pady=(0, 12))
        if not self.renderer.project_open and any(field.scope == 'project' for group in category.groups for field in group.fields):
            label(self.content, tr('settings.project_required'), bg=BG, fg=MUTED, wraplength=430).pack(anchor='w', pady=8)
        for group in category.groups:
            frame = tk.LabelFrame(self.content, text=tr(group.title_key), bg=PANEL, fg=TXT, padx=12, pady=8)
            frame.pack(fill='x', pady=(0, 12))
            for field in group.fields:
                self.renderer.render(frame, field)
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
