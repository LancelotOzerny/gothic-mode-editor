"""Name prompt using the common editor dialog and input widgets."""
import tkinter as tk
from .dialog import EditorDialog
from gothic_editor.ui.widgets import BG, label, make_entry
from gothic_editor.core.localization import tr


class ResourceNameDialog(EditorDialog):
    def __init__(self, parent, script=False):
        super().__init__(parent)
        self.result = None
        self.title(tr('resources.empty_script' if script else 'resources.create_directory'))
        self.resizable(False, False)
        content = tk.Frame(self, bg=BG, padx=20, pady=20)
        content.pack(fill='both', expand=True)
        label(content, tr('resources.script_name' if script else 'resources.directory_name'), bg=BG).pack(anchor='w')
        self.entry = make_entry(content)
        self.entry.pack(fill='x', pady=12)
        self.entry.insert(0, 'NewScript.d' if script else 'NewFolder')
        self.entry.selection_range(0, 'end')
        buttons = tk.Frame(content, bg=BG)
        buttons.pack(fill='x')
        self.add_button(buttons, tr('settings.cancel'), self.destroy).pack(side='right')
        self.add_button(buttons, tr('resources.create'), self.confirm).pack(side='right', padx=8)
        self.bind('<Return>', lambda _:self.confirm())
        self.bind('<Escape>', lambda _:self.destroy())
        self.show_centered(modal=True, focus=self.entry)

    def confirm(self):
        self.result = self.entry.get()
        self.destroy()
