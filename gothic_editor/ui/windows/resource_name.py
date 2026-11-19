"""Name prompt using the common editor dialog and input widgets."""
import tkinter as tk
from .dialog import EditorDialog
from gothic_editor.ui.widgets import BG, label, make_entry
from gothic_editor.core.localization import tr


class ResourceNameDialog(EditorDialog):
    def __init__(self, parent, script=False, *, resource=None):
        super().__init__(parent)
        self.result = None
        title = 'rename' if resource is not None else 'empty_script' if script else 'create_directory'
        self.title(tr('resources.' + title))
        self.resizable(False, False)
        content = tk.Frame(self, bg=BG, padx=20, pady=20)
        content.pack(fill='both', expand=True)
        caption = 'resource_name' if resource is not None else 'script_name' if script else 'directory_name'
        label(content, tr('resources.' + caption), bg=BG).pack(anchor='w')
        self.entry = make_entry(content)
        self.entry.pack(fill='x', pady=12)
        name = resource.name if resource is not None else 'NewScript.d' if script else 'NewFolder'
        self.entry.insert(0, name)
        end = len(resource.stem) if resource is not None and resource.is_file() else 'end'
        self.entry.selection_range(0, end)
        buttons = tk.Frame(content, bg=BG)
        buttons.pack(fill='x')
        self.add_button(buttons, tr('settings.cancel'), self.destroy).pack(side='right')
        self.add_button(buttons, tr('resources.rename' if resource is not None else 'resources.create'),
                        self.confirm).pack(side='right', padx=8)
        self.bind('<Return>', lambda _:self.confirm())
        self.bind('<Escape>', lambda _:self.destroy())
        self.show_centered(modal=True, focus=self.entry)

    def confirm(self):
        self.result = self.entry.get()
        self.destroy()
