"""Small non-modal label following a hierarchy drag without covering its target."""
import tkinter as tk
from .theme import INPUT, TXT, ACCENT, ERROR, label


class DragPreview(tk.Toplevel):
    def __init__(self, owner, names):
        super().__init__(owner, bg=ACCENT)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        body = tk.Frame(self,bg=INPUT,padx=10,pady=7)
        body.pack(padx=1,pady=1)
        label(body,'Перенос: '+str(len(names)),bg=INPUT,fg=TXT,
              font=('Arial',10,'bold'),anchor='w').pack(fill='x')
        caption = '\n'.join(name[:60] for name in names[:3])
        if len(names)>3:caption += '\n… ещё '+str(len(names)-3)
        label(body,caption,bg=INPUT,fg=TXT,justify='left',anchor='w').pack(fill='x')
        self.status = label(body,'',bg=INPUT,anchor='w')
        self.status.pack(fill='x',pady=(4,0))

    def move(self,x,y,target,allowed):
        color = ACCENT if allowed else ERROR
        self.configure(bg=color)
        self.status.configure(text=('→ '+target) if allowed else 'Перенос недоступен',fg=color)
        self.geometry(f'+{max(0,x+18)}+{max(0,y+18)}')
        self.deiconify()
