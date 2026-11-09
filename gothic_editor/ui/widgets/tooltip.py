import tkinter as tk
from .theme import PANEL, TXT

class Tooltip:
    def __init__(self,widget,text):
        self.widget=widget
        self.text=text
        self.pending=None
        self.window=None
        widget.bind('<Enter>',self.schedule,add='+')
        widget.bind('<Leave>',self.hide,add='+')
        widget.bind('<ButtonPress>',self.hide,add='+')
        widget.bind('<Destroy>',self.hide,add='+')

    def schedule(self,_=None):
        self.pending=self.widget.after(450,self.show)

    def show(self):
        self.pending=None
        self.window=tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.geometry(f'+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty()+self.widget.winfo_height()+5}')
        tk.Label(self.window,text=self.text,bg=PANEL,fg=TXT,padx=8,pady=4).pack()

    def hide(self,_=None):
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending=None
        if self.window is not None:
            self.window.destroy()
            self.window=None
