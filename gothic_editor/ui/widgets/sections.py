import tkinter as tk
from .theme import PANEL, TXT, BORDER

class PropertySectionFrame(tk.Frame):
    def __init__(self, parent, title, closed=False, on_toggle=lambda _: None):
        super().__init__(parent, bg=PANEL)
        self.closed = closed
        self.on_toggle = on_toggle
        self.title = title
        heading=tk.Frame(self,bg=PANEL)
        heading.pack(fill='x',padx=10,pady=10)
        heading.columnconfigure(0,weight=1)
        heading.columnconfigure(2,weight=1)
        tk.Frame(heading,bg=BORDER,height=1).grid(row=0,column=0,sticky='ew',padx=(0,10))
        self.header = tk.Button(heading, bg=PANEL, fg=TXT, relief='flat', anchor='center',
                                cursor='hand2', command=self.toggle)
        self.header.grid(row=0,column=1)
        tk.Frame(heading,bg=BORDER,height=1).grid(row=0,column=2,sticky='ew',padx=(10,0))
        self.body = tk.Frame(self, bg=PANEL)
        self.update_state()

    def update_state(self):
        self.header.config(text=('▸ ' if self.closed else '▾ ') + self.title)
        if self.closed:
            self.body.pack_forget()
        else:
            self.body.pack(fill='x')

    def toggle(self):
        self.closed = not self.closed
        self.update_state()
        self.on_toggle(self.closed)
