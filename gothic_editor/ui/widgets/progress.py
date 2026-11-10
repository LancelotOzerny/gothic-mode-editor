"""Dark progress indicator matching the editor's controls."""
import tkinter as tk
from .theme import INPUT,ACCENT


class ProgressBar(tk.Canvas):
    def __init__(self,parent):
        super().__init__(parent,height=10,bg=INPUT,bd=0,highlightthickness=0)
        self.value=0
        self.bind('<Configure>',lambda _:self.paint())

    def set(self,value):
        self.value=max(0,min(1,value))
        self.paint()

    def paint(self):
        self.delete('all')
        self.create_rectangle(0,0,self.winfo_width()*self.value,10,fill=ACCENT,outline='')
