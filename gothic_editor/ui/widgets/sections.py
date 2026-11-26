import tkinter as tk
from .icons import IconImages
from .theme import PANEL, TXT, BORDER, MUTED

class PropertySectionFrame(tk.Frame):
    def __init__(self, parent, title, closed=False, on_toggle=lambda _: None, *, compact=False):
        super().__init__(parent, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1 if compact else 0)
        self.closed = closed
        self.on_toggle = on_toggle
        self.title = title
        self.compact = compact
        self.arrows = IconImages.shared(self).disclosure(MUTED, PANEL)
        heading=tk.Frame(self,bg=PANEL)
        heading.pack(fill='x',padx=10,pady=2 if compact else 10)
        heading.columnconfigure(0,weight=1)
        heading.columnconfigure(2,weight=1)
        tk.Frame(heading,bg=BORDER,height=1).grid(row=0,column=0,sticky='ew',padx=(0,10))
        self.header = tk.Button(heading, bg=PANEL, fg=TXT, activebackground=PANEL, relief='flat', anchor='center',
                                bd=0, pady=0, compound='left', text=self.title,
                                cursor='hand2', command=self.toggle)
        self.header.grid(row=0,column=1)
        tk.Frame(heading,bg=BORDER,height=1).grid(row=0,column=2,sticky='ew',padx=(10,0))
        if compact:
            heading.configure(bg=BORDER)
            heading.pack_configure(padx=0, pady=0)
            for child in heading.winfo_children():
                if child is not self.header:child.destroy()
            heading.columnconfigure(0,weight=1)
            heading.columnconfigure(2,weight=0)
            self.header.configure(anchor='w', padx=8, pady=4, bg=BORDER,
                                  activebackground=BORDER, font=('Arial',9,'bold'))
            self.header.grid(row=0,column=0,sticky='ew')
        self.body = tk.Frame(self, bg=PANEL)
        self.update_state()

    def update_state(self):
        self.header.config(image=self.arrows[0 if self.closed else -1])
        if self.closed:
            self.body.pack_forget()
        else:
            self.body.pack(fill='x', pady=(4,6) if self.compact else 0)

    def toggle(self):
        self.closed = not self.closed
        self.update_state()
        self.on_toggle(self.closed)
