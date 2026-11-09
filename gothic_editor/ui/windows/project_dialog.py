"""Project creation form: choose a name and a parent directory."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import BG, label, make_entry


class NewProjectDialog(tk.Toplevel):
    def __init__(self, parent, initial_directory=None):
        super().__init__(parent, bg=BG)
        self.withdraw()
        self.result = None
        self.title(tr('app.new_project'))
        self.transient(parent)
        self.resizable(False, False)
        self.name = tk.StringVar(self, tr('welcome.default_name'))
        self.directory = tk.StringVar(self, str(initial_directory or Path.home()))
        content = tk.Frame(self, bg=BG, padx=24, pady=20)
        content.pack(fill='both', expand=True)
        label(content, tr('app.project_name'), bg=BG).pack(anchor='w')
        self.name_entry = make_entry(content, textvariable=self.name)
        self.name_entry.pack(fill='x', pady=(6, 16))
        label(content, tr('welcome.location'), bg=BG).pack(anchor='w')
        row = tk.Frame(content, bg=BG)
        row.pack(fill='x', pady=6)
        make_entry(row, textvariable=self.directory, width=55).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text=tr('settings.choose'), command=self.browse).pack(side='left', padx=(8, 0))
        self.destination = tk.StringVar(self)
        label(content, textvariable=self.destination, bg=BG, wraplength=520).pack(anchor='w', pady=8)
        for variable in (self.name, self.directory):
            variable.trace_add('write', self.update_destination)
        self.update_destination()
        actions = tk.Frame(content, bg=BG)
        actions.pack(fill='x', pady=(12, 0))
        ttk.Button(actions, text=tr('settings.cancel'), command=self.destroy).pack(side='right')
        ttk.Button(actions, text=tr('welcome.create'), command=self.submit).pack(side='right', padx=8)
        self.bind('<Return>', lambda _: self.submit())
        self.bind('<Escape>', lambda _: self.destroy())
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 2
        self.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.deiconify()
        self.grab_set()
        self.name_entry.focus_set()
        self.name_entry.selection_range(0, 'end')

    def browse(self):
        path = filedialog.askdirectory(parent=self, initialdir=self.directory.get() or None,
                                       title=tr('welcome.location'))
        if path:
            self.directory.set(path)

    def update_destination(self, *_):
        self.destination.set(str(Path(self.directory.get()).expanduser() / self.name.get().strip()))

    def submit(self):
        name = self.name.get().strip()
        try:
            if (not name or name in ('.', '..') or name.endswith(('.', ' '))
                    or any(char in name for char in '<>:"/\\|?*')
                    or any(ord(char) < 32 for char in name)):
                raise ValueError(tr('welcome.invalid_name'))
            directory = Path(self.directory.get().strip()).expanduser()
            if not self.directory.get().strip() or not directory.is_absolute() or not directory.is_dir():
                raise ValueError(tr('welcome.invalid_directory'))
            destination = directory.resolve() / name
            if destination.exists():
                raise ValueError(tr('welcome.folder_exists', path=str(destination)))
        except (ValueError, OSError) as exc:
            messagebox.showerror(tr('app.create_error'), str(exc), parent=self)
            return
        self.result = (destination, name)
        self.destroy()
