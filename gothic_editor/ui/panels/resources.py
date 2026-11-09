"""Files belonging to the selected item's category directory."""
import tkinter as tk
from tkinter import messagebox, ttk

from gothic_editor.core.localization import tr
from gothic_editor.core.resources import item_resource_files, open_in_editor, open_in_folder
from gothic_editor.ui.widgets import BG, PANEL, MUTED, label
from gothic_editor.ui.widgets.panel import Panel, attach_scrollbar


class ResourcesPanel(Panel):
    def __init__(self, parent, get_editor, on_hide):
        super().__init__(parent, bg=BG)
        self.project = None
        self.item = None
        self.paths = {}
        self.get_editor = get_editor
        self.menu = None
        header = tk.Frame(self, bg=PANEL)
        header.pack(fill='x')
        self.location = label(header, tr('resources.select_item'), fg=MUTED, anchor='w')
        self.location.pack(side='left', fill='x', expand=True, padx=10)
        self.add_button('×',on_hide,parent=header).pack(side='right')
        self.add_button(tr('resources.refresh'),self.refresh,parent=header).pack(side='right',padx=6)
        self.tree = ttk.Treeview(self, columns=('type', 'size'), show='tree headings',
                                 selectmode='browse', height=1)
        self.scrollbar=attach_scrollbar(self,self.tree)
        self.tree.heading('#0', text=tr('resources.file'))
        self.tree.heading('type', text=tr('resources.type'))
        self.tree.heading('size', text=tr('resources.size'))
        self.tree.column('#0', width=450, minwidth=120)
        self.tree.column('type', width=90, stretch=False)
        self.tree.column('size', width=100, stretch=False, anchor='e')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-Button-1>', self.double_click)
        self.tree.bind('<Return>', lambda _: self.open_selected())
        self.tree.bind('<Button-3>', self.context)

    def set_item(self, project, item):
        self.project, self.item = project, item
        self.refresh()

    def refresh(self):
        selected = self.selected_file()
        self.tree.delete(*self.tree.get_children())
        self.paths = {}
        if self.project is None or self.item is None:
            self.location.config(text=tr('resources.select_item'))
            return
        try:
            folder, files = item_resource_files(self.project, self.item.instance)
            self.location.config(text=str(folder) if files else tr('resources.empty', path=str(folder)))
            for index, path in enumerate(files):
                row = str(index)
                self.paths[row] = path
                self.tree.insert('', 'end', iid=row, text=path.relative_to(folder).as_posix(),
                                 values=(path.suffix.lstrip('.').upper(), path.stat().st_size))
                if path == selected:
                    self.tree.selection_set(row)
        except (OSError, ValueError) as exc:
            self.location.config(text=str(exc))

    def selected_file(self):
        selection = self.tree.selection()
        return self.paths.get(selection[0]) if selection else None

    def double_click(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.open_selected()
        return 'break'

    def open_selected(self):
        path = self.selected_file()
        if path is not None:
            try:
                open_in_editor(path, self.get_editor(), self.project)
            except (OSError, ValueError) as exc:
                messagebox.showerror(tr('resources.title'), str(exc), parent=self.winfo_toplevel())

    def reveal_selected(self):
        path = self.selected_file()
        if path is not None:
            try:
                open_in_folder(path)
            except OSError as exc:
                messagebox.showerror(tr('resources.title'), str(exc), parent=self.winfo_toplevel())

    def context(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        if self.menu is not None:
            self.menu.destroy()
        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label=tr('resources.open'), command=self.open_selected)
        self.menu.add_command(label=tr('resources.reveal'), command=self.reveal_selected)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
