import tkinter as tk
from gothic_editor.core.localization import tr
from .theme import INPUT, PANEL, TXT, MUTED, BORDER, ACCENT, FIELD_HEIGHT, FIELD_FONT, rounded_box

def entry_menu(widget):
    menu=tk.Menu(widget,tearoff=False)
    for title,sequence in [(tr('widgets.cut'),'<<Cut>>'),(tr('widgets.copy'),'<<Copy>>'),(tr('widgets.paste'),'<<Paste>>'),(tr('widgets.select_all'),None)]:
        if sequence:menu.add_command(label=title,command=lambda s=sequence:widget.event_generate(s))
        else:menu.add_command(label=title,command=lambda:widget.select_range(0,'end') if isinstance(widget,tk.Entry) else widget.selection_range(0,'end'))
    def show(e):widget.focus_set();menu.tk_popup(e.x_root,e.y_root)
    widget.bind('<Button-3>',show,add='+')
    widget.bind('<Control-a>',lambda e:(widget.select_range(0,'end'),widget.icursor('end'),'break')[-1],add='+')
    return widget

def make_entry(parent,**kw):
    e=tk.Entry(parent,bg=INPUT,fg=TXT,insertbackground=TXT,relief='flat',highlightthickness=1,highlightbackground=BORDER,highlightcolor=ACCENT,**kw)
    entry_menu(e)
    return e

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
