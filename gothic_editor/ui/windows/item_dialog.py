"""Create a named item or choose an original from the selected category."""
import tkinter as tk
from tkinter import ttk

from gothic_editor.core.categories import classify, get_category, walk_categories, EDITABLE_CATEGORIES
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import BG, MUTED, label, make_entry


class AddItemDialog(tk.Toplevel):
    def __init__(self, parent, category_key, originals):
        super().__init__(parent, bg=BG)
        self.withdraw()
        self.result = None
        self.editable=category_key in EDITABLE_CATEGORIES
        self.title(tr('items.add_title', category=tr('categories.' + category_key)))
        self.transient(parent)
        self.geometry('720x490')
        self.minsize(520, 400)
        categories = {category.key for category in walk_categories([get_category(category_key)])}
        self.originals = sorted((item for item in originals if classify(item) in categories),
                                key=lambda item: (item.title.casefold(), item.instance.casefold()))
        self.name = tk.StringVar(self)
        self.search = tk.StringVar(self)
        content = tk.Frame(self, bg=BG, padx=20, pady=16)
        content.pack(fill='both', expand=True)
        label(content, tr('items.new_name'), bg=BG).pack(anchor='w')
        row = tk.Frame(content, bg=BG)
        row.pack(fill='x', pady=(6, 18))
        self.name_entry = make_entry(row, textvariable=self.name)
        self.name_entry.pack(side='left', fill='x', expand=True)
        self.create_button = ttk.Button(row, text=tr('welcome.create'), command=self.create, state='disabled')
        self.create_button.pack(side='left', padx=(10, 0))
        label(content, tr('items.originals'), bg=BG).pack(anchor='w')
        self.search_entry = make_entry(content, textvariable=self.search)
        self.search_entry.pack(fill='x', pady=6)
        self.projects = ttk.Treeview(content, columns=('item',), show='', selectmode='browse', height=10)
        self.projects.column('item', width=600)
        self.projects.pack(fill='both', expand=True)
        self.status = tk.StringVar(self)
        label(content, textvariable=self.status, bg=BG, fg=MUTED).pack(anchor='w', pady=6)
        actions = tk.Frame(content, bg=BG)
        actions.pack(fill='x', pady=(8, 0))
        ttk.Button(actions, text=tr('settings.cancel'), command=self.destroy).pack(side='right')
        self.copy_button = ttk.Button(actions, text=tr('hierarchy.copy_to_project'), command=self.copy, state='disabled')
        self.copy_button.pack(side='right', padx=8)
        self.search.trace_add('write', self.refresh)
        self.name.trace_add('write', lambda *_: self.create_button.config(
            state='normal' if self.editable and self.name.get().strip() else 'disabled'))
        self.projects.bind('<<TreeviewSelect>>', lambda _: self.copy_button.config(
            state='normal' if self.editable and self.projects.selection() else 'disabled'))
        self.projects.bind('<Double-Button-1>', self.double_click)
        self.projects.bind('<Return>', lambda _: self.copy())
        self.name_entry.bind('<Return>', lambda _: self.create())
        self.bind('<Escape>', lambda _: self.destroy())
        self.refresh()
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.deiconify()
        self.grab_set()
        self.name_entry.focus_set()

    def refresh(self, *_):
        self.projects.delete(*self.projects.get_children())
        query = self.search.get().strip().casefold()
        matches = [item for item in self.originals
                   if query in item.title.casefold() or query in item.instance.casefold()]
        self.matches = matches[:10]
        for index, item in enumerate(self.matches):
            self.projects.insert('', 'end', iid=str(index), values=(f'{item.title} ({item.instance})',))
        self.status.set(tr('items.matches', shown=len(self.matches), total=len(matches)))
        self.copy_button.config(state='disabled')

    def create(self):
        name = self.name.get().strip()
        if self.editable and name:
            self.result = ('create', name)
            self.destroy()

    def copy(self):
        selection = self.projects.selection()
        if self.editable and selection:
            self.result = ('copy', self.matches[int(selection[0])])
            self.destroy()

    def double_click(self, event):
        row = self.projects.identify_row(event.y)
        if row:
            self.projects.selection_set(row)
            self.copy()
        return 'break'
