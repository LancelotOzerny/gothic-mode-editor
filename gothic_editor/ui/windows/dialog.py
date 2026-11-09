"""Common dialog appearance and positioning, with explicit modality per window."""
import tkinter as tk
from gothic_editor.ui.widgets.theme import BG
from gothic_editor.ui.widgets.buttons import PropertyButton


class EditorDialog(tk.Toplevel):
    def __init__(self, parent, **kwargs):
        kwargs.setdefault('bg', BG)
        super().__init__(parent, **kwargs)
        self.withdraw()
        self.owner = parent.winfo_toplevel()
        self.transient(self.owner)

    def add_button(self, parent, text, command, **kwargs):
        return PropertyButton(parent, command, text=text, **kwargs)

    def center(self):
        self.update_idletasks()
        self.owner.update_idletasks()
        x = self.owner.winfo_rootx() + (self.owner.winfo_width()-self.winfo_width())//2
        y = self.owner.winfo_rooty() + (self.owner.winfo_height()-self.winfo_height())//2
        self.geometry(f'+{max(0,x)}+{max(0,y)}')

    def show_centered(self, modal=False, focus=None):
        self.center()
        self.deiconify()
        self.update_idletasks()
        if modal:self.grab_set()
        if focus is not None:focus.focus_set()
