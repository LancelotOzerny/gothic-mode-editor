import tkinter as tk
from .dialog import EditorDialog
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import BG, MUTED, label

class ProjectConfirmationDialog(EditorDialog):
    def __init__(self, parent, entry, action):
        super().__init__(parent, bg=BG)
        self.withdraw()
        self.result = False
        self.title(tr('welcome.'+action+'_title'))
        owner = parent.winfo_toplevel()
        self.transient(owner)
        content = tk.Frame(self, bg=BG, padx=24, pady=20)
        content.pack(fill='both', expand=True)
        label(content, tr('welcome.'+action+'_question', name=entry.name), bg=BG,
              font=('Arial',12,'bold'), wraplength=420, justify='left').pack(fill='x')
        label(content, str(entry.path), bg=BG, fg=MUTED, wraplength=420,
              justify='left').pack(fill='x', pady=12)
        if action=='remove':
            label(content, tr('welcome.files_kept'), bg=BG, wraplength=420, justify='left').pack(fill='x')
        actions = tk.Frame(content, bg=BG)
        actions.pack(fill='x', pady=(20,0))
        cancel = self.add_button(actions,tr('settings.cancel'),self.destroy)
        cancel.pack(side='right')
        self.add_button(actions,tr('welcome.'+action),self.confirm).pack(side='right',padx=8)
        self.bind('<Escape>', lambda _:self.destroy())
        self.show_centered(modal=True,focus=cancel)

    def confirm(self):
        self.result = True
        self.destroy()
