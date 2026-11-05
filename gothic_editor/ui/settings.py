"""Two-pane settings dialog rendered from the settings catalog."""
from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from ..core.localization import localization, tr
from ..core.settings import field_key, validate_value
from ..core.settings_schema import FieldType, all_fields, categories
from .widgets import BG, PANEL, TXT, MUTED, ACCENT, label, make_entry


class SettingsFormRenderer:
    def __init__(self, values, project_open):
        self.values = values
        self.project_open = project_open

    def render(self, parent, field):
        variables = self.values[field_key(field)]
        enabled = field.scope != 'project' or self.project_open
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill='x', pady=(8, 2))
        label(row, tr(field.label_key)).pack(anchor='w')
        controls = tk.Frame(row, bg=PANEL)
        controls.pack(fill='x', pady=6)
        kind = field.field_type
        if kind is FieldType.BOOLEAN:
            ttk.Checkbutton(controls, variable=variables[0], state='normal' if enabled else 'disabled').pack(anchor='w')
        elif kind is FieldType.LANGUAGE:
            languages = localization.available_languages()
            codes = list(languages)
            combo = ttk.Combobox(controls, values=list(languages.values()), state='readonly')
            if codes:
                combo.current(codes.index(variables[0].get()) if variables[0].get() in codes else 0)
            else:
                combo.config(state='disabled')
            combo.bind('<<ComboboxSelected>>', lambda _: variables[0].set(codes[combo.current()]))
            combo.pack(anchor='w')
        elif kind in (FieldType.NUMBER, FieldType.SIZE):
            for index, variable in enumerate(variables):
                if index:
                    label(controls, ' × ').pack(side='left')
                ttk.Spinbox(controls, from_=field.minimum if field.minimum is not None else -2147483648,
                            to=field.maximum if field.maximum is not None else 2147483647,
                            textvariable=variable, width=9, state='normal' if enabled else 'disabled').pack(side='left')
        else:
            entry = make_entry(controls, textvariable=variables[0])
            entry.pack(side='left', fill='x', expand=True, ipady=4)
            if not enabled:
                entry.config(state='disabled')
            if kind in (FieldType.DIRECTORY, FieldType.FILE, FieldType.COLOR):
                def choose():
                    if kind is FieldType.DIRECTORY:
                        value = filedialog.askdirectory(parent=parent.winfo_toplevel(), title=tr(field.label_key),
                                                        initialdir=variables[0].get() or None)
                    elif kind is FieldType.FILE:
                        value = filedialog.askopenfilename(parent=parent.winfo_toplevel(), title=tr(field.label_key),
                                                           filetypes=[(tr('settings.executables'), '*.exe *.dll'),
                                                                      (tr('settings.all_files'), '*.*')])
                    else:
                        value = colorchooser.askcolor(parent=parent.winfo_toplevel(), color=variables[0].get())[1]
                    if value:
                        variables[0].set(value)
                ttk.Button(controls, text=tr('settings.choose'), command=choose,
                           state='normal' if enabled else 'disabled').pack(side='left', padx=(8, 0))
            if kind in (FieldType.DIRECTORY, FieldType.FILE):
                ttk.Button(row, text=tr('settings.clear'), command=lambda: variables[0].set(''),
                           state='normal' if enabled else 'disabled').pack(anchor='e')
        label(row, tr(field.title_key), fg=MUTED, wraplength=430, justify='left').pack(anchor='w', pady=(4, 8))


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
