"""Startup project picker with a persistent recent-project list."""
import tkinter as tk
from tkinter import ttk

from ..core.localization import tr
from .widgets import BG, PANEL, TXT, MUTED, label


class WelcomeScreen(tk.Frame):
    def __init__(self, parent, history, on_create, on_browse, on_open):
        super().__init__(parent, bg=BG)
        self.entries = list(history.entries[:10])
        self.on_open = on_open
        content = tk.Frame(self, bg=BG)
        content.pack(fill='both', expand=True, padx=50, pady=28)
        label(content, 'Gothic Editor', bg=BG, font=('Arial', 24, 'bold')).pack(anchor='w')
        label(content, tr('welcome.title'), bg=BG, fg=MUTED, font=('Arial', 12)).pack(anchor='w', pady=(4, 16))
        actions = tk.Frame(content, bg=BG)
        actions.pack(fill='x')
        ttk.Button(actions, text=tr('welcome.create'), command=on_create).pack(side='left')
        ttk.Button(actions, text=tr('app.open_project'), command=on_browse).pack(side='left', padx=10)
        parent_directory = history.parent_directory()
        hint = tr('welcome.create_near', path=str(parent_directory)) if parent_directory else tr('welcome.choose_folder')
        label(content, hint, bg=BG, fg=MUTED, anchor='w', wraplength=1000).pack(fill='x', pady=(10, 18))
        label(content, tr('welcome.recent'), bg=BG, font=('Arial', 12, 'bold')).pack(anchor='w', pady=(0, 8))
        table = tk.Frame(content, bg=BG)
        table.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(table)
        scroll.pack(side='right', fill='y')
        self.projects = ttk.Treeview(table, columns=('name', 'path'), show='headings',
                                     selectmode='browse', height=10, yscrollcommand=scroll.set)
        self.projects.heading('name', text=tr('welcome.name'))
        self.projects.heading('path', text=tr('welcome.path'))
        self.projects.column('name', width=240, minwidth=160)
        self.projects.column('path', width=600, minwidth=200)
        self.projects.pack(fill='both', expand=True)
        scroll.config(command=self.projects.yview)
        for index, entry in enumerate(self.entries):
            self.projects.insert('', 'end', iid=str(index), values=(entry.name, str(entry.path)))
        if self.entries:
            self.projects.selection_set('0')
            self.projects.focus('0')
        else:
            label(content, tr('welcome.empty'), bg=BG, fg=MUTED).pack(anchor='w', pady=8)
        ttk.Button(content, text=tr('welcome.open_selected'), command=self.open_selected,
                   state='normal' if self.entries else 'disabled').pack(anchor='e', pady=(12, 0))
        self.projects.bind('<Return>', lambda _: self.open_selected())
        self.projects.bind('<Double-Button-1>', self.double_click)

    def open_selected(self):
        selection = self.projects.selection()
        if selection:
            self.on_open(self.entries[int(selection[0])].path)

    def double_click(self, event):
        row = self.projects.identify_row(event.y)
        if row:
            self.projects.selection_set(row)
            self.open_selected()
        return 'break'
