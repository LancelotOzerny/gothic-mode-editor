import tkinter as tk
from tkinter import font as tkfont
from .theme import PANEL, INPUT, TXT, MUTED, BORDER, ACCENT, FIELD_HEIGHT, FIELD_FONT, HOVER_BG, rounded_box, blend
from .icons import IconImages
from .tooltip import Tooltip

class PropertyButton(tk.Canvas):
    """Matching text/icon buttons, including lighter dropdown option rows."""
    def __init__(self, parent, command, text='', filename=None, caption='',
                 icons=None, background=INPUT, align='center', height=FIELD_HEIGHT):
        self.height = height
        width = height if filename else max(height,tkfont.Font(root=parent,font=FIELD_FONT).measure(text)+20)
        super().__init__(parent, bg=parent.cget('bg'), height=height, width=width,
                         bd=0, highlightthickness=0, takefocus=True, cursor='hand2')
        self.command, self.text, self.filename = command, text, filename
        self.icons = icons or IconImages.shared(self)
        self.background, self.align = background, align
        self.hovered = False
        self.image = None
        self.selected = False
        self.bind('<Configure>', lambda _:self.paint())
        self.bind('<Enter>', lambda _:self.highlight(True))
        self.bind('<Leave>', lambda _:self.highlight(False))
        self.bind('<ButtonRelease-1>', self.click)
        self.bind('<Return>', lambda _:self.invoke())
        self.bind('<space>', lambda _:self.invoke())
        if caption:Tooltip(self, caption)
        self.paint()

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        if 'state' in kwargs and hasattr(self, 'background'):self.paint()
        return result

    config = configure

    def click(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():self.invoke()

    def invoke(self):
        if self.cget('state') != 'disabled':self.command()

    def highlight(self, hovered):
        self.hovered = hovered
        self.paint()

    def set_selected(self, selected):
        self.selected = selected
        self.paint()

    def paint(self):
        disabled = self.cget('state') == 'disabled'
        fill = HOVER_BG if self.hovered and not disabled else self.background
        if self.selected and not disabled:fill='#3a5675' if self.hovered else '#304a65'
        foreground = MUTED if disabled else TXT
        self.delete('all')
        width = self.winfo_width()
        if width == 1:
            width = self.winfo_reqwidth()
        rounded_box(self, width, self.height, fill, ACCENT if self.selected and not disabled else BORDER)
        self.image = None
        if self.filename and (self.icons.directory/self.filename).is_file():
            size = min(20, self.height - 4)
            if self.filename == 'remove_recent.png':
                size = round(0.8 * min(width, self.height))
            try:self.image = self.icons.frames(self.filename,max(1,size),foreground,fill,
                                               normalize_alpha=self.filename=='create.png')[0]
            except (tk.TclError, OSError):pass
        if self.image:self.create_image(width/2,self.height/2,image=self.image)
        else:self.create_text(10 if self.align=='left' else width/2,self.height/2,
                              text=self.text, fill=foreground, font=FIELD_FONT,
                              anchor='w' if self.align=='left' else 'center')


class PropertyToggle(PropertyButton):
    def __init__(self, parent, variable):
        self.variable = variable
        super().__init__(parent,self.toggle)
        self.configure(width=FIELD_HEIGHT)
        self._trace = variable.trace_add('write',lambda *_:self.refresh())
        self.bind('<Destroy>',self._dispose,add='+')
        self.refresh()

    def toggle(self):self.variable.set(not self.variable.get())

    def refresh(self):
        self.text = '✓' if self.variable.get() else ''
        self.set_selected(bool(self.variable.get()))

    def _dispose(self, event):
        if event.widget is self:self.variable.trace_remove('write',self._trace)

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
