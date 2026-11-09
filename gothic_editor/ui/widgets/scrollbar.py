import tkinter as tk
from .theme import MUTED, BORDER

class RoundedScrollbar(tk.Canvas):
    """Narrow rounded thumb with normal yscrollcommand and dragging support."""
    def __init__(self, parent, command):
        super().__init__(parent, width=8, bg=parent.cget('bg'), highlightthickness=0, bd=0)
        self.command = command
        self.first, self.last = 0., 1.
        self.drag = None
        self.hovered = False
        self.bind('<Configure>', lambda _:self.draw())
        self.bind('<Button-1>', self.press)
        self.bind('<B1-Motion>', self.move)
        self.bind('<ButtonRelease-1>', lambda _:setattr(self,'drag',None))
        self.bind('<Enter>', lambda _:self.highlight(True))
        self.bind('<Leave>', lambda _:self.highlight(False))

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.draw()

    def bounds(self):
        height = max(1,self.winfo_height())
        size = min(height,max(24,(self.last-self.first)*height))
        top = (height-size)*self.first/max(.0001,1-(self.last-self.first))
        return top,size

    def draw(self):
        self.delete('all')
        if self.last-self.first >= .999:return
        top,size = self.bounds()
        self.create_line(4,top+3,4,top+size-3,width=6,capstyle='round',
                         fill=MUTED if self.hovered else BORDER)

    def highlight(self, value):
        self.hovered = value
        self.draw()

    def press(self, event):
        top,size = self.bounds()
        if top <= event.y <= top+size:self.drag = event.y-top
        else:
            self.drag = size/2
            self.move(event)

    def move(self, event):
        if self.drag is None:return
        height = max(1,self.winfo_height())
        self.command('moveto', max(0,min(1,event.y/height-self.drag/height)))
