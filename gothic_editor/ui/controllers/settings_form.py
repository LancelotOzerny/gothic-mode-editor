"""Two-pane settings dialog rendered from the settings catalog."""
from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, filedialog, ttk

from gothic_editor.core.localization import localization, tr
from gothic_editor.core.settings import field_key
from gothic_editor.core.settings_schema import FieldType
from gothic_editor.ui.widgets import PANEL, MUTED, label, make_entry


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
        elif kind in (FieldType.LANGUAGE, FieldType.ENUM):
            options = (localization.available_languages() if kind is FieldType.LANGUAGE
                       else {code:tr(name) for code,name in field.options})
            codes = list(options)
            combo = ttk.Combobox(controls, values=list(options.values()), state='readonly' if enabled else 'disabled')
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
