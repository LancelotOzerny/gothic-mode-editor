"""Two-step category recipe creation or searchable Gothic template selection."""
import tkinter as tk
from tkinter import ttk, messagebox
from .dialog import EditorDialog
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import make_entry, label, MUTED
from gothic_editor.ui.widgets.panel import attach_scrollbar


class AddRecipeDialog(EditorDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.result = None
        self.title(tr('recipes.add_recipe'))
        self.geometry('380x180')
        for value, key in (('game','from_gothic'), ('new','create')):
            self.add_button(self, tr('recipes.'+key), lambda v=value: self.accept(v)).pack(fill='x', padx=20, pady=12)
        self.bind('<Escape>', lambda _:self.destroy())

    def accept(self, value):
        self.result = value
        self.destroy()


class GameRecipeDialog(EditorDialog):
    def __init__(self, owner, recipes, skipped=()):
        super().__init__(owner)
        self.result = None
        self.recipes = recipes
        self.title(tr('recipes.from_gothic'))
        self.geometry('640x480')
        self.query = tk.StringVar(self)
        make_entry(self, textvariable=self.query).pack(fill='x', padx=12, pady=12)
        notice = tr('recipes.template_note', count=len(skipped))
        label(self, notice, fg=MUTED, wraplength=600).pack(fill='x', padx=12)
        if skipped:
            self.add_button(self, 'Почему некоторые рецепты пропущены?',
                lambda: messagebox.showinfo('Диагностика импорта Gothic',
                    '\n'.join(skipped),parent=self)).pack(fill='x', padx=12, pady=4)
        footer = tk.Frame(self, bg=self.cget('bg'))
        footer.pack(side='bottom', fill='x', padx=12, pady=12)
        self.add_button(footer, tr('settings.cancel'), self.destroy).pack(side='right')
        self.choose = self.add_button(footer, tr('settings.choose'), self.accept)
        self.choose.pack(side='right', padx=8)
        body = tk.Frame(self, bg=self.cget('bg'))
        body.pack(fill='both', expand=True, padx=12)
        self.tree = ttk.Treeview(body, columns=('name',), show='', selectmode='browse')
        self.tree.column('name', width=580)
        attach_scrollbar(body, self.tree)
        self.tree.pack(fill='both', expand=True)
        self.query.trace_add('write', lambda *_:self.populate())
        self.tree.bind('<<TreeviewSelect>>', lambda _:self.choose.config(state='normal' if self.tree.selection() else 'disabled'))
        self.tree.bind('<Double-Button-1>', lambda _:self.accept())
        self.bind('<Return>', lambda _:self.accept())
        self.bind('<Escape>', lambda _:self.destroy())
        self.populate()

    def populate(self):
        self.tree.delete(*self.tree.get_children())
        query = self.query.get().strip().casefold()
        self.matches = [r for r in self.recipes if query in (r['id']+' '+r['name']+' '+r['result']).casefold()]
        for index, row in enumerate(self.matches):
            self.tree.insert('', 'end', iid=str(index), values=(row['name']+' / '+row['result'],))
        self.choose.config(state='disabled')

    def accept(self):
        selection = self.tree.selection()
        if selection:
            self.result = self.matches[int(selection[0])]
            self.destroy()
