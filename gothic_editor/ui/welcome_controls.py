"""Canvas controls scoped to the borderless welcome window."""
import tkinter as tk

from .widgets import BG, PANEL, TXT, MUTED, BORDER, Tooltip


def blend(start, end, amount):
    a = [int(start[i:i+2], 16) for i in (1,3,5)]
    b = [int(end[i:i+2], 16) for i in (1,3,5)]
    return '#%02x%02x%02x' % tuple(round(x+(y-x)*amount) for x,y in zip(a,b))


class RoundedIconButton(tk.Canvas):
    """Sized hit target with configurable padding around the icon."""
    def __init__(self, parent, icons, filename, text, caption, command, background=PANEL, hover=True, size=40, padding=10):
        super().__init__(parent, width=size, height=size, bg=background,
                         highlightthickness=0, bd=0, takefocus=True, cursor='hand2')
        self.size = size
        self.padding = padding
        self.icons, self.filename, self.text = icons, filename, text
        self.command, self.base = command, background
        self.hover_enabled = hover
        self.hovered = False
        self.opacity = 1
        self.image = None
        self.bind('<Enter>', lambda _:self.highlight(True))
        self.bind('<Leave>', lambda _:self.highlight(False))
        self.bind('<ButtonRelease-1>', self.click)
        self.bind('<Return>', lambda _:self.invoke())
        self.bind('<space>', lambda _:self.invoke())
        self.tooltip = Tooltip(self, caption)
        self.paint()

    def highlight(self, hovered):
        if self.hover_enabled:
            self.hovered = hovered
            self.paint()

    def click(self, event):
        if 0 <= event.x < self.size and 0 <= event.y < self.size:self.invoke()

    def invoke(self):
        if self.opacity > 0:self.command()

    def paint(self, background=None, opacity=None):
        if background is not None:self.base = background
        if opacity is not None:self.opacity = opacity
        self.configure(bg=self.base)
        self.delete('all')
        if self.opacity <= 0:return
        fill = blend(self.base, BORDER, .55 if self.hovered else .15)
        foreground = blend(fill, TXT, self.opacity)
        # Smooth polygon keeps the corners in the parent colour.
        size, radius = self.size, min(10,self.size/4)
        self.create_polygon(radius,0,size-radius,0,size,0,size,radius,size,size-radius,
                            size,size,size-radius,size,radius,size,0,size,0,size-radius,
                            0,radius,0,0, smooth=True, splinesteps=24,
                            fill=blend(self.base, fill, self.opacity), outline='')
        fill = blend(self.base, fill, self.opacity)
        self.image = None
        if (self.icons.directory/self.filename).is_file():
            try:self.image = self.icons.frames(self.filename,self.size-2*self.padding,foreground,fill)[0]
            except (tk.TclError, OSError):pass
        if self.image:self.create_image(size/2,size/2,image=self.image)
        else:self.create_text(size/2,size/2,text=self.text,fill=foreground,font=('Arial',14))


class WelcomeScrollbar(tk.Canvas):
    """Narrow rounded thumb with normal yscrollcommand and dragging support."""
    def __init__(self, parent, command):
        super().__init__(parent, width=8, bg=BG, highlightthickness=0, bd=0)
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
