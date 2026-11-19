"""Small non-modal label following a hierarchy drag without covering its target."""
import tkinter as tk
from .theme import INPUT, ACCENT, ERROR, label


class DragPreview(tk.Toplevel):
    def __init__(self, owner):
        super().__init__(owner, bg=ACCENT)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        body = tk.Frame(self,bg=INPUT,padx=10,pady=7)
        body.pack(padx=1,pady=1)
        self.status = label(body,'',bg=INPUT,anchor='w')
        self.status.pack(fill='x')

    def move(self,x,y,target,allowed):
        color = ACCENT if allowed else ERROR
        self.configure(bg=color)
        self.status.configure(text=target if allowed else 'Перенос недоступен',fg=color)
        self.geometry(f'+{max(0,x+18)}+{max(0,y+18)}')
        self.deiconify()
