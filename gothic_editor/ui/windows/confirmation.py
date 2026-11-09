import tkinter as tk
from tkinter import ttk
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import BG, MUTED, label

class ProjectConfirmationDialog(tk.Toplevel):
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
        cancel = ttk.Button(actions, text=tr('settings.cancel'), command=self.destroy)
        cancel.pack(side='right')
        ttk.Button(actions, text=tr('welcome.'+action), command=self.confirm).pack(side='right', padx=8)
        self.bind('<Escape>', lambda _:self.destroy())
        self.update_idletasks()
        x = owner.winfo_rootx() + (owner.winfo_width()-self.winfo_reqwidth())//2
        y = owner.winfo_rooty() + (owner.winfo_height()-self.winfo_reqheight())//2
        self.geometry(f'+{max(0,x)}+{max(0,y)}')
        self.deiconify()
        self.grab_set()
        cancel.focus_set()

    def confirm(self):
        self.result = True
        self.destroy()
