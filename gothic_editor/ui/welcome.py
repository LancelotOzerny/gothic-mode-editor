"""Startup project picker with a persistent recent-project list."""
import tkinter as tk
from tkinter import ttk

from ..core.localization import tr
from .widgets import BG, PANEL, MUTED, label


class WelcomeScreen(tk.Frame):
    def __init__(self, parent, history, on_create, on_browse, on_open):
        super().__init__(parent, bg=BG)
        self.entries = list(history.entries[:10])
        self.on_open = on_open
        self.on_browse = on_browse
        self.columnconfigure(0, weight=1)
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        content = tk.Frame(self, bg=PANEL, padx=24, pady=24, bd=1, relief='solid')
        content.grid(row=1, column=1, padx=24, pady=24)
        label(content, 'Gothic Editor', font=('Arial', 22, 'bold')).pack(anchor='w', pady=(0, 20))
        table = tk.Frame(content, bg=PANEL)
        table.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(table)
        scroll.pack(side='right', fill='y')
        self.projects = ttk.Treeview(table, columns=('project',), show='',
                                     selectmode='browse', height=10, yscrollcommand=scroll.set)
        self.projects.column('project', width=680, minwidth=260)
        self.projects.pack(fill='both', expand=True)
        scroll.config(command=self.projects.yview)
        for index, entry in enumerate(self.entries):
            self.projects.insert('', 'end', iid=str(index), values=(f'{entry.name} ({entry.path})',))
        if self.entries:
            self.projects.selection_set('0')
            self.projects.focus('0')
        else:
            label(content, tr('welcome.empty'), fg=MUTED).pack(anchor='w', pady=8)
        actions = tk.Frame(content, bg=PANEL)
        actions.pack(fill='x', pady=(18, 0))
        ttk.Button(actions, text=tr('welcome.create_button'), command=on_create).pack(side='right')
        ttk.Button(actions, text=tr('welcome.open_button'), command=self.open_selected).pack(side='right', padx=8)
        self.projects.bind('<Return>', lambda _: self.open_selected())
        self.projects.bind('<Double-Button-1>', self.double_click)

    def open_selected(self):
        selection = self.projects.selection()
        if selection:
            self.on_open(self.entries[int(selection[0])].path)
        else:
            self.on_browse()

    def double_click(self, event):
        row = self.projects.identify_row(event.y)
        if row:
            self.projects.selection_set(row)
            self.open_selected()
        return 'break'
