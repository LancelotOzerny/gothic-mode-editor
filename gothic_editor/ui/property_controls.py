"""Dark property controls with shared sizing, padding and hover colours."""
import tkinter as tk

from .icons import IconImages
from .widgets import INPUT, PANEL, TXT, MUTED, BORDER, ACCENT, entry_menu, Tooltip

FIELD_HEIGHT = 40
FIELD_FONT = 'TkDefaultFont'
OPTION_BG = '#293444'
HOVER_BG = '#354257'


def rounded_box(canvas, width, height, fill, border=BORDER):
    """Two-pixel corners; the native entry lives inside the painted surface."""
    canvas.delete('surface')
    for inset, color in ((0, border), (1, fill)):
        x, y, right, bottom = inset, inset, width-inset, height-inset
        radius = max(1, 2-inset)
        canvas.create_polygon(x+radius,y,right-radius,y,right,y,right,y+radius,
            right,bottom-radius,right,bottom,right-radius,bottom,x+radius,bottom,
            x,bottom,x,bottom-radius,x,y+radius,x,y, smooth=True, splinesteps=12,
            fill=color, outline='', tags='surface')
    canvas.tag_lower('surface')


class PropertyEntry(tk.Entry):
    """A native entry (selection, clipboard, focus) inside a padded dark surface."""
    def __init__(self, parent, right_padding=10, **kwargs):
        self.surface = tk.Canvas(parent, bg=PANEL, height=FIELD_HEIGHT, width=1,
                                 highlightthickness=0, bd=0)
        self.right_padding = right_padding
        self.hovered = False
        super().__init__(self.surface, bg=INPUT, readonlybackground=INPUT, disabledbackground=INPUT, fg=TXT,
                         disabledforeground=MUTED, insertbackground=TXT, font=FIELD_FONT,
                         relief='flat', bd=0, highlightthickness=0, **kwargs)
        self._entry_window=self.surface.create_window(10,FIELD_HEIGHT/2,window=self,anchor='w')
        entry_menu(self)
        self.bind('<Button-1>',lambda _:self.focus_set(),add='+')
        self.surface.bind('<Configure>', lambda _:self.paint())
        for widget in (self, self.surface):
            widget.bind('<Enter>', lambda _:self.highlight(True), add='+')
            widget.bind('<Leave>', lambda _:self.highlight(False), add='+')
        self.bind('<FocusIn>', lambda _:self.paint(), add='+')
        self.bind('<FocusOut>', lambda _:self.paint(), add='+')
        self.surface.bind('<Button-1>', lambda _:self.focus_set())

    def pack(self, **kwargs):
        kwargs.pop('ipady', None)
        return self.surface.pack(**kwargs)

    def highlight(self, hovered):
        self.hovered = hovered
        self.paint()

    def paint(self):
        focused = self.focus_get() is self
        border = ACCENT if focused else MUTED if self.hovered else BORDER
        width=self.surface.winfo_width()
        self.surface.itemconfigure(self._entry_window,width=max(1,width-10-self.right_padding))
        if hasattr(self,'_arrow_window'):
            self.surface.coords(self._arrow_window,width-10,FIELD_HEIGHT/2)
        rounded_box(self.surface, width, FIELD_HEIGHT, INPUT, border)


class PropertyButton(tk.Canvas):
    """Matching text/icon buttons, including lighter dropdown option rows."""
    def __init__(self, parent, command, text='', filename=None, caption='',
                 icons=None, background=INPUT, align='center'):
        super().__init__(parent, bg=PANEL, height=FIELD_HEIGHT, width=FIELD_HEIGHT,
                         bd=0, highlightthickness=0, takefocus=True, cursor='hand2')
        self.command, self.text, self.filename = command, text, filename
        self.icons = icons or IconImages(self)
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
        width = max(FIELD_HEIGHT, self.winfo_width())
        rounded_box(self, width, FIELD_HEIGHT, fill, ACCENT if self.selected and not disabled else BORDER)
        self.image = None
        if self.filename and (self.icons.directory/self.filename).is_file():
            try:self.image = self.icons.frames(self.filename,20,foreground,fill,
                                               normalize_alpha=self.filename=='create.png')[0]
            except (tk.TclError, OSError):pass
        if self.image:self.create_image(width/2,FIELD_HEIGHT/2,image=self.image)
        else:self.create_text(10 if self.align=='left' else width/2,FIELD_HEIGHT/2,
                              text=self.text, fill=foreground, font=FIELD_FONT,
                              anchor='w' if self.align=='left' else 'center')
