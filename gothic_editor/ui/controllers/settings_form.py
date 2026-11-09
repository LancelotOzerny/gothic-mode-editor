"""Two-pane settings dialog rendered from the settings catalog."""
from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, filedialog

from gothic_editor.core.localization import localization, tr
from gothic_editor.core.settings import field_key
from gothic_editor.core.settings_schema import FieldType
from gothic_editor.ui.widgets import PANEL, MUTED, label
from gothic_editor.ui.widgets.form import create_field
from gothic_editor.ui.widgets.field_label import FieldLabel
from gothic_editor.ui.widgets.buttons import PropertyButton


class SettingsFormRenderer:
    def __init__(self, values, project_open):
        self.values = values
        self.project_open = project_open
        self.inputs = {}

    def render(self, parent, field):
        variables = self.values[field_key(field)]
        enabled = field.scope != 'project' or self.project_open
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill='x', padx=8, pady=(8, 2))
        FieldLabel(row, tr(field.label_key)).pack(fill='x')
        controls = tk.Frame(row, bg=PANEL)
        controls.pack(fill='x', pady=6)
        kind = field.field_type
        if kind is FieldType.BOOLEAN:
            checkbox=create_field(controls,'boolean',variable=variables[0],enabled=enabled)
            checkbox.pack(anchor='w')
            self.inputs[field_key(field)]=[checkbox]
        elif kind in (FieldType.LANGUAGE, FieldType.ENUM):
            options = (localization.available_languages() if kind is FieldType.LANGUAGE
                       else {code:tr(name) for code,name in field.options})
            combo=create_field(controls,'choice',variable=variables[0],
                options=tuple((name,code) for code,name in options.items()),
                caption=tr(field.label_key),enabled=enabled and bool(options))
            combo.pack(fill='x')
            self.inputs[field_key(field)]=[combo]
        elif kind in (FieldType.NUMBER, FieldType.SIZE):
            entries=[]
            for index, variable in enumerate(variables):
                if index:
                    label(controls, ' × ').pack(side='left')
                entry=create_field(controls,'number',variable=variable,minimum=field.minimum,
                    maximum=field.maximum,enabled=enabled)
                entry.pack(side='left',fill='x',expand=True)
                entries.append(entry)
            self.inputs[field_key(field)]=entries
        else:
            entry = create_field(controls,variable=variables[0],enabled=enabled)
            entry.pack(side='left', fill='x', expand=True, ipady=4)
            self.inputs[field_key(field)]=[entry]
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
                button=PropertyButton(controls,choose,text=tr('settings.choose'))
                button.config(state='normal' if enabled else 'disabled')
                button.pack(side='left',padx=(8,0))
            if kind in (FieldType.DIRECTORY, FieldType.FILE):
                button=PropertyButton(row,lambda:variables[0].set(''),text=tr('settings.clear'))
                button.config(state='normal' if enabled else 'disabled')
                button.pack(anchor='e')
        label(row, tr(field.title_key), fg=MUTED, wraplength=430, justify='left').pack(anchor='w', pady=(4, 8))
